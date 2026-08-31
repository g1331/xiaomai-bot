from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest
import arclet.entari.core as entari_core
from arclet.entari import Entari
from arclet.entari.config import EntariConfig
from graia.amnesia.builtins.aiohttp import AiohttpClientService
from launart import Launart
from satori import EventType, LoginStatus

from tenko import runtime as runtime_module
from tenko.config import TenkoConfig
from tenko.connection import OneBotConnection
from tenko.render import RenderService
from tenko.runtime import TenkoRuntime


@pytest.mark.asyncio
async def test_run_async_loads_plugins_before_starting_entari(
    monkeypatch,
) -> None:
    lifecycle: list[str] = []
    connection = Mock()
    connection.ready_service.id = "tenko.ready"
    monkeypatch.setattr(
        runtime_module, "OneBotConnection", Mock(return_value=connection)
    )
    runtime = TenkoRuntime(TenkoConfig())
    manager = Mock()
    app = Mock()
    app.required = set()
    app.connections = []
    app.ensure_manager = Mock()
    app.run_async = AsyncMock()
    runtime.build_app = Mock(return_value=app)
    runtime.connection.install = Mock(
        side_effect=lambda _: lifecycle.append("connection")
    )

    plugin_runtime = Mock()

    async def load_all():
        lifecycle.append("plugins")
        return {}

    plugin_runtime.load_all = AsyncMock(side_effect=load_all)
    manager_provider = Mock(return_value=manager)
    monkeypatch.setattr(runtime_module, "it", manager_provider)
    monkeypatch.setattr(
        runtime_module, "PluginRuntime", Mock(return_value=plugin_runtime)
    )
    database_loader = Mock(return_value=object())
    monkeypatch.setattr(runtime_module, "load_database_plugin", database_loader)

    async def run_app(*args, **kwargs):
        lifecycle.append("app")

    app.run_async.side_effect = run_app

    await runtime.run_async()

    app.ensure_manager.assert_not_called()
    manager_provider.assert_called_once_with(runtime_module.Launart)
    connection.install.assert_called_once_with(manager)
    manager.add_component.assert_called_once()
    registered = manager.add_component.call_args.args[0]
    assert registered.id == "tenko.render"
    plugin_runtime.load_all.assert_awaited_once_with()
    assert runtime.plugin_runtime is plugin_runtime
    database_loader.assert_called_once_with(runtime.config.database)
    assert runtime.database_service is database_loader.return_value
    app.run_async.assert_awaited_once_with(
        manager,
        stop_signal=(runtime_module.signal.SIGINT, runtime_module.signal.SIGTERM),
    )
    assert lifecycle == ["connection", "plugins", "app"]
    assert app.required == {"tenko.ready"}


@pytest.mark.asyncio
async def test_run_async_registers_enabled_render_service(
    monkeypatch,
) -> None:
    connection = Mock()
    connection.ready_service.id = "tenko.ready"
    monkeypatch.setattr(
        runtime_module, "OneBotConnection", Mock(return_value=connection)
    )
    config = TenkoConfig.from_mapping(
        {
            "render": {
                "enabled": True,
                "timeout": 4.5,
                "width": 1024,
                "quality": 91,
                "device_scale_factor": 3,
            }
        }
    )
    runtime = TenkoRuntime(config)
    manager = Mock()
    app = Mock()
    app.required = set()
    app.connections = []
    app.run_async = AsyncMock()
    runtime.build_app = Mock(return_value=app)
    runtime.connection.install = Mock()
    plugin_runtime = Mock()
    plugin_runtime.load_all = AsyncMock(return_value={})
    monkeypatch.setattr(runtime_module, "it", Mock(return_value=manager))
    monkeypatch.setattr(
        runtime_module, "PluginRuntime", Mock(return_value=plugin_runtime)
    )
    monkeypatch.setattr(runtime_module, "load_database_plugin", Mock(return_value=None))

    await runtime.run_async()

    manager.add_component.assert_called_once()
    service = manager.add_component.call_args.args[0]
    assert isinstance(service, RenderService)
    assert service.enabled is True
    assert service.timeout == 4.5
    assert service.width == 1024
    assert service.quality == 91
    assert service.device_scale_factor == 3
    plugin_runtime.load_all.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_online_lifecycle_discovers_groups_through_action_service() -> None:
    runtime = TenkoRuntime(TenkoConfig())
    accounts = Mock()
    actions = Mock()
    actions.get_group_list = AsyncMock(return_value=("40001", "40002"))
    runtime.accounts = accounts
    runtime.actions = actions
    account = Mock()
    account.self_id = "10001"

    await runtime._on_lifecycle(account, LoginStatus.ONLINE)

    accounts.register.assert_called_once_with(account, available=True)
    assert accounts.bind_group.call_args_list == [
        (("40001", account), {}),
        (("40002", account), {}),
    ]
    actions.get_group_list.assert_awaited_once_with(account)


@pytest.mark.asyncio
async def test_online_lifecycle_tolerates_group_discovery_failure(monkeypatch) -> None:
    runtime = TenkoRuntime(TenkoConfig())
    runtime.accounts = Mock()
    runtime.actions = Mock()
    runtime.actions.get_group_list = AsyncMock(side_effect=RuntimeError("offline"))
    warning = Mock()
    monkeypatch.setattr(runtime_module.logger, "warning", warning)
    account = Mock()
    account.self_id = "10001"

    await runtime._on_lifecycle(account, LoginStatus.ONLINE)

    runtime.accounts.register.assert_called_once_with(account, available=True)
    runtime.accounts.bind_group.assert_not_called()
    assert "discover groups" in warning.call_args.args[0]


def test_entari_run_async_registration_keeps_connection_components(
    entari_plugin_host,
) -> None:
    app = entari_plugin_host
    assert isinstance(app, Entari)
    connection = OneBotConnection(TenkoConfig().onebot)
    manager = Launart()

    connection.install(manager)
    manager.add_component(AiohttpClientService())
    manager.add_component(app)

    assert manager.get_component(Entari) is app
    assert manager.get_component(AiohttpClientService).id == "http.client/aiohttp"
    assert manager.get_component("satori-python.server") is connection.server
    assert (
        manager.get_component(connection.ready_service.id) is connection.ready_service
    )


def test_runtime_configures_account_response_state_path(tmp_path, monkeypatch) -> None:
    accounts = Mock()
    monkeypatch.setattr(runtime_module, "account_registry", accounts)
    state_path = tmp_path / "accounts.json"
    config = TenkoConfig.from_mapping({"accounts": {"state_path": str(state_path)}})

    runtime = TenkoRuntime(config)

    assert runtime.accounts is accounts
    accounts.configure_persistence.assert_called_once_with(str(state_path))


@pytest.mark.asyncio
async def test_build_app_uses_basic_without_rewriting_entari_config(
    monkeypatch,
) -> None:
    connection = Mock()
    monkeypatch.setattr(
        runtime_module, "OneBotConnection", Mock(return_value=connection)
    )
    monkeypatch.setattr(runtime_module, "set_event_loop", Mock())

    class FakeEntari:
        def __init__(self, *configs, **kwargs) -> None:
            if not EntariConfig._inited:
                EntariConfig(Path("/tmp/tenko-runtime-test.yml"))
            self.configs = configs
            self.kwargs = kwargs
            EntariConfig.instance.basic.prefix = ["native"]
            EntariConfig.instance.basic.nickname = "Native"
            self.event_callbacks = [self.handle_event]
            self.registered_message_handler = None
            self.registered_handlers = {}

        async def handle_event(self, account, event):
            return None

        def register_on(self, event_type):
            def register(callback):
                self.registered_message_handler = callback
                self.registered_handlers[event_type] = callback
                return callback

            return register

        def lifecycle(self, callback):
            self.lifecycle_callback = callback

    monkeypatch.setattr(runtime_module, "Entari", FakeEntari)
    config = TenkoConfig.from_mapping(
        {
            "basic": {
                "prefix": ["!"],
                "ignore_self_message": False,
                "skip_req_missing": True,
                "network": [{"type": "ws", "host": "127.0.0.1", "port": 5140}],
                "external_dirs": ["plugins"],
                "schema": True,
                "log": {"level": "DEBUG", "rich_error": True},
            },
            "debug": {"enabled": True, "masters": [20001]},
        }
    )
    runtime = TenkoRuntime(config)
    original_prefix = list(EntariConfig.instance.basic.prefix)
    original_nickname = EntariConfig.instance.basic.nickname
    original_superusers = (
        dict(EntariConfig.instance.basic.superusers) if EntariConfig._inited else None
    )

    try:
        app = runtime.build_app()

        assert app.configs == (connection.client_config,)
        assert app.kwargs == {
            "log_level": "DEBUG",
            "ignore_self_message": False,
            "skip_req_missing": True,
            "external_dirs": ["plugins"],
            "rich_error": True,
            "gen_schema": True,
        }
        assert EntariConfig.instance.basic.prefix == ["native"]
        assert EntariConfig.instance.basic.nickname == "Native"
        assert EntariConfig.instance.basic.superusers == original_superusers
        assert app.registered_message_handler.__self__ is runtime.message_handler
        assert (
            app.registered_message_handler.__func__
            is runtime.message_handler.handle.__func__
        )
        assert runtime.message_handler.debug_config is config.debug
        assert (
            app.registered_handlers[EventType.GUILD_MEMBER_REMOVED].__func__
            is runtime.message_handler.handle_member_removed.__func__
        )
        assert (
            app.registered_handlers[EventType.GUILD_REMOVED].__func__
            is runtime.message_handler.handle_member_removed.__func__
        )
        assert (
            app.registered_handlers[EventType.INTERNAL].__func__
            is runtime.message_handler.handle_member_removed.__func__
        )
    finally:
        runtime_module.configure_command_prefix("/")
        EntariConfig.instance.basic.prefix = original_prefix
        EntariConfig.instance.basic.nickname = original_nickname
        EntariConfig.instance.basic.superusers = original_superusers or {}


def test_entari_consumes_official_log_save_configuration(tmp_path, monkeypatch) -> None:
    path = tmp_path / "tenko.toml"
    path.write_text(
        """
[basic.log]
level = "INFO"
save = { rotation = "00:00", compression = "gz", colorize = false }
""",
        encoding="utf-8",
    )
    original_config = EntariConfig.instance
    EntariConfig.load(path)
    apply_log_save = Mock(return_value=Mock())
    monkeypatch.setattr(entari_core, "apply_log_save", apply_log_save)

    def fake_app_init(self, *configs, **kwargs) -> None:
        self.accounts = {}
        self.connections = []
        self.event_callbacks = []
        self.lifecycle_callbacks = []

    try:
        monkeypatch.setattr(entari_core.App, "__init__", fake_app_init)
        app = Entari()

        apply_log_save.assert_called_once_with(
            log_dir=entari_core.local_data._get_base_log_dir(),
            rotation="00:00",
            compression="gz",
            colorize=False,
        )
        app._log_save_dispose()
    finally:
        EntariConfig.instance = original_config
        EntariConfig._inited = True
