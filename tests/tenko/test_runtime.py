from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest
from arclet.entari import Entari
from arclet.entari.config import EntariConfig
from graia.amnesia.builtins.aiohttp import AiohttpClientService
from launart import Launart
from satori import LoginStatus

from tenko import runtime as runtime_module
from tenko.config import TenkoConfig
from tenko.connection import OneBotConnection
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
    monkeypatch.setattr(runtime_module, "Launart", Mock(return_value=manager))
    monkeypatch.setattr(
        runtime_module, "PluginRuntime", Mock(return_value=plugin_runtime)
    )

    async def run_app(*args, **kwargs):
        lifecycle.append("app")

    app.run_async.side_effect = run_app

    await runtime.run_async()

    app.ensure_manager.assert_not_called()
    connection.install.assert_called_once_with(manager)
    plugin_runtime.load_all.assert_awaited_once_with()
    assert runtime.plugin_runtime is plugin_runtime
    app.run_async.assert_awaited_once_with(
        manager,
        stop_signal=(runtime_module.signal.SIGINT, runtime_module.signal.SIGTERM),
    )
    assert lifecycle == ["connection", "plugins", "app"]
    assert app.required == {"tenko.ready"}


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


@pytest.mark.asyncio
async def test_build_app_reapplies_prefix_after_entari_initialization(
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
            EntariConfig.instance.basic.prefix = ["!"]
            EntariConfig.instance.basic.nickname = "Tenko"
            self.event_callbacks = [self.handle_event]
            self.registered_message_handler = None

        async def handle_event(self, account, event):
            return None

        def register_on(self, event_type):
            def register(callback):
                self.registered_message_handler = callback
                return callback

            return register

        def lifecycle(self, callback):
            self.lifecycle_callback = callback

    monkeypatch.setattr(runtime_module, "Entari", FakeEntari)
    config = TenkoConfig.from_mapping(
        {
            "runtime": {
                "command_prefix": "!",
                "superusers": {"onebot": [12345, "67890"]},
            },
            "debug": {"enabled": True, "masters": [20001]},
        }
    )
    runtime = TenkoRuntime(config)
    original_superusers = (
        dict(EntariConfig.instance.basic.superusers) if EntariConfig._inited else None
    )

    try:
        app = runtime.build_app()

        assert EntariConfig.instance.basic.prefix == []
        assert EntariConfig.instance.basic.nickname == ""
        assert EntariConfig.instance.basic.superusers == {"onebot": ["12345", "67890"]}
        assert app.registered_message_handler.__self__ is runtime.message_handler
        assert (
            app.registered_message_handler.__func__
            is runtime.message_handler.handle.__func__
        )
        assert runtime.message_handler.debug_config is config.debug
    finally:
        runtime_module.configure_command_prefix("/")
        EntariConfig.instance.basic.superusers = original_superusers or {}
