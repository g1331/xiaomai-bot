from __future__ import annotations

import asyncio
import signal
import sys
from collections.abc import Mapping
from pathlib import Path

from arclet.entari import Entari
from arclet.entari.config import EntariConfig
from arclet.letoderea.utils import set_event_loop
from launart import Launart
from loguru import logger
from satori import EventType, LoginStatus
from satori.client import Account

from .config import TenkoConfig
from .commands import configure_command_prefix
from .connection import OneBotConnection
from .db.bootstrap import load_database_plugin
from .db.errors import DatabaseUnavailableError
from .events import MessageEventHandler, configure_message_metrics
from .host.accounts import account_registry
from .host.actions import action_service
from .host.features import CommandPolicy, configure_feature_service
from .host.plugins import PluginRuntime
from .host.ratelimit import configure_rate_limiter
from .host.updater import UpgradeManager, configure_updater


def _configure_entari_superusers(
    superusers: Mapping[str, tuple[str, ...]],
) -> None:
    """把 Tenko 的平台用户映射写入 Entari 原生 basic 配置。"""

    EntariConfig.instance.basic.superusers = {
        platform: list(user_ids) for platform, user_ids in superusers.items()
    }


class TenkoRuntime:
    """Tenko 第一阶段运行时的服务编排。"""

    def __init__(self, config: TenkoConfig) -> None:
        self.config = config
        configure_command_prefix(config.runtime.command_prefix)
        self.accounts = account_registry
        self.accounts.configure_persistence(config.accounts.state_path)
        self.actions = action_service
        self.actions.configure_capability_overrides(config.onebot.capability_overrides)
        self.feature_service = configure_feature_service(
            config.features.state_path,
            default_enabled=config.features.default_enabled,
        )
        self.rate_limiter = configure_rate_limiter(
            config.ratelimit.state_path,
            enabled=config.ratelimit.enabled,
            window_seconds=config.ratelimit.window_seconds,
            max_weight=config.ratelimit.max_weight,
            default_weight=config.ratelimit.default_weight,
            cooldown_seconds=config.ratelimit.cooldown_seconds,
            blacklist_seconds=config.ratelimit.blacklist_seconds,
        )
        self.updater = UpgradeManager.from_config(
            config.upgrade, project_root=Path.cwd()
        )
        configure_updater(
            self.updater,
            superuser_ids=config.upgrade.superuser_ids,
        )
        self.connection = OneBotConnection(config.onebot)
        self.message_metrics = configure_message_metrics(
            config.exception.message_buffer_size
        )
        self.message_handler = MessageEventHandler(
            send_replies=config.runtime.send_replies,
            reply_text=config.runtime.reply_text,
            account_registry=self.accounts,
            debug_config=config.debug,
            command_prefix=config.runtime.command_prefix,
            metrics=self.message_metrics,
            action_service=self.actions,
        )
        self.app: Entari | None = None
        self.manager: Launart | None = None
        self.plugin_runtime: PluginRuntime | None = None
        self.database_service = None

    def build_app(self) -> Entari:
        if self.app is not None:
            return self.app

        set_event_loop(asyncio.get_running_loop())
        app = Entari(
            self.connection.client_config,
            log_level=self.config.runtime.log_level,
            ignore_self_message=True,
        )
        _configure_entari_superusers(self.config.entari.superusers)
        configure_command_prefix(self.config.runtime.command_prefix)
        native_handler = app.handle_event
        for index, callback in enumerate(app.event_callbacks):
            if callback == native_handler:
                app.event_callbacks[index] = self.message_handler.guard(callback)
                break
        else:  # pragma: no cover - Entari registers this callback in __init__
            raise RuntimeError("Entari native event handler is not registered")
        # OneBot 11 的 group_decrease.leave/kick 在当前适配器中都先转换为
        # GUILD_MEMBER_REMOVED；kick_me 转换为 GUILD_REMOVED。先注册退群
        # 事件，再注册消息事件，保留原有消息回调作为最后一个可观察入口。
        app.register_on(EventType.GUILD_MEMBER_REMOVED)(
            self.message_handler.handle_member_removed
        )
        app.register_on(EventType.GUILD_REMOVED)(
            self.message_handler.handle_member_removed
        )
        # OneBot 11 的适配器在退群事件补充信息的 action 失败时，会把原始
        # notice 保留在 EventType.INTERNAL；处理器按已核实的 _type/_data
        # 再识别一次，避免 kick_me 因“已被踢后无法查成员信息”丢失解绑。
        app.register_on(EventType.INTERNAL)(self.message_handler.handle_member_removed)
        app.register_on(EventType.MESSAGE_CREATED)(self.message_handler.handle)
        app.lifecycle(self._on_lifecycle)
        self.app = app
        return app

    async def _on_lifecycle(self, account: Account, state: LoginStatus) -> None:
        if state in (LoginStatus.ONLINE, LoginStatus.CONNECT, LoginStatus.RECONNECT):
            self.accounts.register(account, available=state == LoginStatus.ONLINE)
            if state == LoginStatus.ONLINE:
                try:
                    group_ids = await self.actions.get_group_list(account)
                except Exception as error:
                    logger.warning(
                        "Could not discover groups for OneBot account {}: {}",
                        account.self_id,
                        error,
                    )
                else:
                    for group_id in group_ids:
                        self.accounts.bind_group(group_id, account)
                    logger.info(
                        "Discovered {} groups for OneBot account {}",
                        len(group_ids),
                        account.self_id,
                    )
        elif state in (LoginStatus.DISCONNECT, LoginStatus.OFFLINE):
            if self.accounts.get(account.self_id) is not None:
                self.accounts.set_available(account, False)

        if state == LoginStatus.ONLINE:
            logger.info("OneBot account {} is online", account.self_id)
        elif state in (LoginStatus.CONNECT, LoginStatus.RECONNECT):
            logger.info("OneBot account {} is connecting/reconnecting", account.self_id)
        elif state in (LoginStatus.DISCONNECT, LoginStatus.OFFLINE):
            logger.warning(
                "OneBot account {} disconnected; waiting for reverse WebSocket "
                "reconnection",
                account.self_id,
            )
        else:
            logger.warning(
                "OneBot account {} changed to unknown state {}",
                account.self_id,
                state,
            )

    async def run_async(self) -> None:
        manager = Launart()
        self.manager = manager
        self.connection.install(manager)

        logger.info(
            "Tenko starting; NapCat reverse WebSocket endpoint: {}",
            self.config.onebot.reverse_ws_url,
        )
        logger.info(
            "Fixed replies are {}",
            "enabled" if self.config.runtime.send_replies else "disabled",
        )
        app = self.build_app()
        try:
            self.database_service = load_database_plugin(self.config.database)
        except DatabaseUnavailableError as error:
            # PermissionChecker and the database-backed plugins have explicit
            # fallback/error paths. Keep the host alive so a temporary database
            # failure does not prevent messages from reaching Entari.
            self.database_service = None
            logger.error("Tenko database is unavailable: {}", error)
        # PluginRuntime.load_all() only imports Tenko plugins through Entari's
        # load_plugin API, so it does not need a Launart component registration.
        # Keep it after database model registration and before run_async: the
        # official database service is then added by Entari's plugin manager.
        self.plugin_runtime = PluginRuntime()
        await self.plugin_runtime.load_all()
        exception_catcher = sys.modules.get("tenko.plugins.exception_catcher")
        if exception_catcher is not None:
            configure_evidence_directory = getattr(
                exception_catcher, "configure_evidence_directory", None
            )
            if callable(configure_evidence_directory):
                configure_evidence_directory(self.config.exception.evidence_dir)
        self.message_handler.command_policy = CommandPolicy(
            self.feature_service,
            self.rate_limiter,
            plugin_runtime=self.plugin_runtime,
            command_prefix=self.config.runtime.command_prefix,
            rate_limit_override_permission=self.config.ratelimit.override_permission,
        )
        # The Satori client must start after the server socket is accepting
        # connections. Otherwise its first connection attempt can race Uvicorn
        # and events arriving in that window would not be replayed to a client.
        app.required = {*app.required, self.connection.ready_service.id}
        for connection in app.connections:
            connection.required = {
                *connection.required,
                self.connection.ready_service.id,
            }
        await app.run_async(
            manager,
            stop_signal=(signal.SIGINT, signal.SIGTERM),
        )


def run(config: TenkoConfig) -> None:
    asyncio.run(TenkoRuntime(config).run_async())
