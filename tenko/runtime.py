from __future__ import annotations

import asyncio
import inspect
import signal
import sys
from collections.abc import Mapping
from pathlib import Path

from arclet.entari import Entari
from arclet.letoderea.utils import set_event_loop
from creart import it
from launart import Launart
from loguru import logger
from satori import EventType, LoginStatus
from satori.client import Account

from . import _process_start_monotonic
from .config import TenkoConfig
from .commands import configure_command_prefix
from .connection import OneBotConnection
from .db.bootstrap import load_database_plugin
from .db.errors import DatabaseUnavailableError
from .db.runtime import RuntimeStateService
from .events import MessageEventHandler, configure_message_metrics
from .host.accounts import account_registry
from .host.account_management import AccountManagement
from .host.actions import action_service
from .host.features import CommandPolicy, configure_feature_service
from .host.plugins import PluginRuntime
from .host.ratelimit import configure_rate_limiter
from .host.startup import StartupHistory
from .host.updater import UpgradeManager, configure_updater
from .render import RenderService
from .webui import WebUIService


class TenkoRuntime:
    """Tenko 第一阶段运行时的服务编排。"""

    def __init__(self, config: TenkoConfig) -> None:
        self.config = config
        configure_command_prefix(
            config.command_prefixes,
            use_entari_prefix=True,
        )
        self.accounts = account_registry
        self.accounts.configure(None)
        self.actions = action_service
        self.actions.configure_capability_overrides(config.onebot.capability_overrides)
        self.feature_service = configure_feature_service(
            default_enabled=config.features.default_enabled,
        )
        self.rate_limiter = configure_rate_limiter(
            enabled=config.ratelimit.enabled,
            window_seconds=config.ratelimit.window_seconds,
            max_weight=config.ratelimit.max_weight,
            default_weight=config.ratelimit.default_weight,
            cooldown_seconds=config.ratelimit.cooldown_seconds,
            blacklist_seconds=config.ratelimit.blacklist_seconds,
        )
        self.startup_history = StartupHistory()
        stable_root = Path.cwd().resolve()
        self.updater = UpgradeManager.from_config(
            config.upgrade,
            project_root=stable_root,
            database_url=config.database.url,
        )
        configure_updater(
            self.updater,
            superuser_ids=config.upgrade.superuser_ids,
            shutdown_callback=self.request_graceful_shutdown,
        )
        self.account_management = AccountManagement(self.accounts, self.actions)
        self.connection = OneBotConnection(config.onebot)
        self.connection.adapter.admission = self.account_management.can_connect
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
        self._startup_notify_module: object | None = None
        self.database_service = None
        self.webui_service: WebUIService | None = None
        self.runtime_state_service = RuntimeStateService(
            self._initialize_runtime_state,
            self._flush_runtime_state,
        )

    def _configure_database_repositories(self) -> None:
        """将官方 database service 接入六类运行期状态。"""

        from .db.repositories import (
            account_state_repository,
            ManagementRepository,
            feature_state_repository,
            rate_limit_repository,
            startup_time_repository,
        )

        self.account_management.repository = ManagementRepository()
        self.accounts.configure(account_state_repository)
        self.feature_service.configure(
            feature_state_repository,
            default_enabled=self.config.features.default_enabled,
        )
        self.rate_limiter.configure(rate_limit_repository)
        self.startup_history = StartupHistory(startup_time_repository)

    def _mark_runtime_state_unavailable(self) -> None:
        """数据库 bootstrap 失败时让运行期状态统一进入保守状态。"""

        self.accounts.mark_unavailable()
        self.feature_service.mark_unavailable()
        self.rate_limiter.mark_unavailable()
        self.startup_history.mark_unavailable()

    async def _initialize_runtime_state(self) -> None:
        """在数据库服务就绪后加载快照；单类失败不阻止宿主启动。"""

        state_loaders = (
            ("account routes", self.accounts.initialize),
            (
                "account preferences",
                lambda: self.account_management.initialize(
                    self.config.onebot.capability_overrides
                ),
            ),
            ("feature switches", self.feature_service.initialize),
            ("rate limit", self.rate_limiter.initialize),
            ("startup duration history", self.startup_history.load),
        )
        for label, loader in state_loaders:
            try:
                await loader()
            except Exception as error:
                logger.error("Could not load Tenko {} state: {}", label, error)

        if self.account_management.ready:
            self.account_management.ready = False
            try:
                await self.account_management.restore_settings(
                    self.feature_service, self.plugin_runtime
                )
            except Exception as error:
                logger.error(
                    "Could not restore management settings: {}", type(error).__name__
                )
            else:
                self.account_management.ready = True

    async def _flush_runtime_state(self) -> None:
        """在数据库连接销毁前等待同步事件安排的状态写入。"""

        try:
            await self.accounts.flush_persistence()
        except Exception as error:
            logger.error("Could not flush Tenko account route state: {}", error)

    @staticmethod
    def _plugin_module(loaded_plugins: object, name: str) -> object | None:
        """从 Entari loader 的结果取模块，兼容旧的 sys.modules 查找。"""

        loaded = (
            loaded_plugins.get(name) if isinstance(loaded_plugins, Mapping) else None
        )
        if loaded is not None:
            module = getattr(loaded, "module", None)
            return loaded if module is None else module
        return sys.modules.get(f"tenko.plugins.{name}")

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
            if self.accounts.get(account) is not None:
                self.accounts.set_available(account, False)

        if state == LoginStatus.ONLINE:
            logger.info("OneBot account {} is online", account.self_id)
            startup_notify = self._startup_notify_module
            if startup_notify is None:
                # 保留对测试替身和直接导入插件的兼容；正常的 Entari 插件
                # 由自定义 loader 管理，不一定留在 sys.modules 中。
                startup_notify = sys.modules.get("tenko.plugins.startup_notify")
            on_account_online = getattr(startup_notify, "on_account_online", None)
            if callable(on_account_online):
                try:
                    result = on_account_online(account)
                    if inspect.isawaitable(result):
                        await result
                except Exception:
                    # 启动通知是就绪后的附加动作，不能影响账号已上线的主流程。
                    logger.exception("Could not dispatch Tenko startup notification")
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
            self.database_service = load_database_plugin(
                self.config.database,
                runtime_state_service=self.runtime_state_service,
            )
            self._configure_database_repositories()
        except DatabaseUnavailableError as error:
            self.database_service = None
            self._mark_runtime_state_unavailable()
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
        loaded_plugins = await self.plugin_runtime.load_all()
        self._startup_notify_module = self._plugin_module(
            loaded_plugins, "startup_notify"
        )
        group_manager = self._plugin_module(loaded_plugins, "group_manager")
        configure_notify_group = getattr(group_manager, "configure_notify_group", None)
        if callable(configure_notify_group):
            configure_notify_group(self.config.notify_group)
        startup_notify = self._startup_notify_module
        if startup_notify is None:
            startup_notify = self._plugin_module(loaded_plugins, "startup_notify")
        configure_startup_notification = getattr(
            startup_notify, "configure_startup_notification", None
        )
        if callable(configure_startup_notification):
            recovery_notice_path = getattr(
                self.updater.layout, "recovery_notice_file", None
            )
            notification_kwargs = {
                "started_at": _process_start_monotonic,
                "history": self.startup_history,
            }
            if recovery_notice_path is not None and recovery_notice_path.is_file():
                notification_kwargs["recovery_notice_path"] = recovery_notice_path
            configure_startup_notification(
                self.config.notify_group, **notification_kwargs
            )
        permission_manager = self._plugin_module(loaded_plugins, "perm_manager")
        configure_notify_group = getattr(
            permission_manager, "configure_notify_group", None
        )
        if callable(configure_notify_group):
            configure_notify_group(self.config.notify_group)
        exception_catcher = self._plugin_module(loaded_plugins, "exception_catcher")
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
        if self.config.webui.enabled:
            feature_repository = None
            if self.database_service is not None:
                from .db.repositories import feature_state_repository

                feature_repository = feature_state_repository

            self.webui_service = WebUIService(
                self.connection.server,
                self.config.webui,
                accounts=self.accounts,
                metrics=self.message_metrics,
                feature_service=self.feature_service,
                feature_repository=feature_repository,
                plugin_runtime=self.plugin_runtime,
                management=self.account_management,
                connection=self.connection,
                tenko_config=self.config,
            )
            manager.add_component(self.webui_service)
        # Satori client 必须在 server socket 开始接受连接后启动。否则其第一次
        # 连接尝试可能与 Uvicorn 发生竞争，该时间窗口内到达的事件也不会被
        # replay 给 client。
        app.required = {*app.required, self.connection.ready_service.id}
        # 注意（pre8 生产事故根因）：RuntimeStateService 与官方
        # SqlalchemyService 都经插件机制注册，由 PluginManagerService 在其
        # launch 阶段统一 resolve_requirements 后装载。两者都不可加入
        # app.required，也不可在此提前 add_component——Launart 顶层解析发生在
        # 插件服务装载之前，任何一者提前进入组件表都会让解析因依赖缺失而
        # 整体崩溃（RequirementResolveFailed）。启动时序由 RuntimeStateService
        # 自身的 required={"database/sqlalchemy"} 与 wait_for_required 保证。
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
