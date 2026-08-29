from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest

from tenko.config import TenkoConfig
from tenko import runtime as runtime_module
from tenko.runtime import TenkoRuntime


@pytest.mark.asyncio
async def test_run_async_installs_entari_manager_before_loading_plugins(
    monkeypatch,
) -> None:
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
    runtime.connection.install = Mock()

    plugin_runtime = Mock()
    plugin_runtime.load_all = AsyncMock(return_value={})
    monkeypatch.setattr(runtime_module, "Launart", Mock(return_value=manager))
    monkeypatch.setattr(
        runtime_module, "PluginRuntime", Mock(return_value=plugin_runtime)
    )

    await runtime.run_async()

    app.ensure_manager.assert_called_once_with(manager)
    connection.install.assert_called_once_with(manager)
    plugin_runtime.load_all.assert_awaited_once_with()
    assert runtime.plugin_runtime is plugin_runtime
    app.run_async.assert_awaited_once_with(
        manager,
        stop_signal=(runtime_module.signal.SIGINT, runtime_module.signal.SIGTERM),
    )
