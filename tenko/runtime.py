from __future__ import annotations

import asyncio
import signal
import sys
from pathlib import Path

from arclet.entari import Entari
from arclet.letoderea.utils import set_event_loop
from creart import it
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
from .render import RenderService


class TenkoRuntime:
    """Tenko 第一阶段运行时的服务编排。"""

    def __init__(self, config: TenkoConfig) -> None:
        self.config = config
        configure_command_prefix(
            config.command_prefixes,
            use_entari_prefix=True,
        )
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
        stable_root = Path.cwd().resolve()
        self.updater = UpgradeManager.from_config(
            config.upgrade, project_root=stable_root
        )
        configure_updater(
            self.updater,
            superuser_ids=config.upgrade.superuser_ids,
            shutdown_callback=self.request_graceful_shutdown,
        )
        self.connection = OneBotConnection(config.onebot)
        self.message_metrics = configure_message_metrics(
            config.exception.message_buffer_size
        )
        self.message_handler = MessageEventHandler(
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

    def request_graceful_shutdown(self) -> bool:
        """沿 Launart 的 SIGINT 生命周期路径请求当前运行时退出。"""

        manager = self.manager
        if manager is None:
            logger.warning("无法请求 Tenko 优雅退出：Launart manager 尚未就绪")
            return False

        # Launart 0.8.2 的 SIGINT 处理器通过同一组状态转换唤醒 cleanup；
        # 这里不取消当前命令任务，确保回复已经交给 Entari 的发送链路。
        manager.status.exiting = True
        task_group = manager.task_group
        if task_group is None:
            logger.warning("无法请求 Tenko 优雅退出：Launart task group 尚未就绪")
            return False
        task_group.stop = True
        if task_group.blocking_task is not None:
            task_group.blocking_task.cancel()
        return True

    def build_app(self) -> Entari:
        if self.app is not None:
            return self.app

        set_event_loop(asyncio.get_running_loop())
        basic = self.config.basic
        app = Entari(
            self.connection.client_config,
            log_level=basic.log.level,
            ignore_self_message=basic.ignore_self_message,
            skip_req_missing=basic.skip_req_missing,
            external_dirs=basic.external_dirs,
            rich_error=basic.log.rich_error,
            gen_schema=basic.schema,
        )
        native_handler = app.handle_event
        for index, callback in enumerate(app.event_callbacks):
            if callback == native_handler:
                app.event_callbacks[index] = self.message_handler.guard(callback)
                break
        else:  # pragma: no cover - Entari 在 __init__ 中注册此回调
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
        # Entari 的 service provider 通过 creart 的 Launart 实例解析组件；这里
        # 使用与 App.run_async 接收的同一个 manager。
        manager = it(Launart)
        self.manager = manager
        self.connection.install(manager)

        logger.info(
            "Tenko starting; OneBot 11 reverse WebSocket endpoint: {}",
            self.config.onebot.reverse_ws_url,
        )
        app = self.build_app()
        try:
            self.database_service = load_database_plugin(self.config.database)
        except DatabaseUnavailableError as error:
            # PermissionChecker 和依赖数据库的插件都有明确的回退/错误路径。
            # 保持宿主存活，使临时数据库故障不会阻止消息到达 Entari。
            self.database_service = None
            logger.error("Tenko database is unavailable: {}", error)
        manager.add_component(
            RenderService(
                timeout=self.config.render.timeout,
                width=self.config.render.width,
                quality=self.config.render.quality,
                device_scale_factor=self.config.render.device_scale_factor,
            )
        )

        # PluginRuntime.load_all() 只通过 Entari 的 load_plugin API 导入 Tenko
        # 插件，因此不需要注册 Launart 组件。将其放在数据库模型和
        # RenderService 注册之后、run_async 之前。
        self.plugin_runtime = PluginRuntime()
        await self.plugin_runtime.load_all()
        permission_manager = sys.modules.get("tenko.plugins.perm_manager")
        configure_test_group = getattr(permission_manager, "configure_test_group", None)
        if callable(configure_test_group):
            configure_test_group(self.config.test_group)
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
        # Satori client 必须在 server socket 开始接受连接后启动。否则其第一次
        # 连接尝试可能与 Uvicorn 发生竞争，该时间窗口内到达的事件也不会被
        # replay 给 client。
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
