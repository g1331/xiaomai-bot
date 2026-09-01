from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from unittest.mock import AsyncMock, Mock, call

import pytest

from tenko.context import MessageContext
from tenko.host import plugins as plugin_host
from tenko.host.plugins import PluginRuntime


@dataclass
class FakePlugin:
    id: str
    is_available: bool = True


def make_plugin_dir(tmp_path: Path) -> Path:
    plugin_dir = tmp_path / "plugins"
    plugin_dir.mkdir()
    (plugin_dir / "package_plugin").mkdir()
    (plugin_dir / "package_plugin" / "__init__.py").write_text("", encoding="utf-8")
    (plugin_dir / "file_plugin.py").write_text("", encoding="utf-8")
    return plugin_dir


def make_group_context(group_id: str) -> MessageContext:
    return MessageContext(
        account_id="10001",
        event_type="message-created",
        protocol_event_type="message.group.normal",
        chat_type="group",
        channel_id=group_id,
        user_id="20001",
        message_id="30001",
        text="hello",
        image_urls=(),
    )


def test_discover_plugin_shapes_without_reading_plugin_metadata(
    tmp_path: Path,
) -> None:
    plugin_dir = make_plugin_dir(tmp_path)
    (plugin_dir / "package_plugin" / "metadata.json").write_text(
        "{not valid json", encoding="utf-8"
    )
    (plugin_dir / "not_a_plugin").mkdir()
    (plugin_dir / "_private.py").write_text("", encoding="utf-8")

    runtime = PluginRuntime(plugin_dir)

    infos = runtime.discover()

    assert [info.name for info in infos] == ["file_plugin", "package_plugin"]
    assert infos[0].qualified_name == "tenko.plugins.file_plugin"
    assert "modules.self_contained.file_plugin" in infos[0].lookup_names


@pytest.mark.asyncio
async def test_lifecycle_delegates_to_entari(monkeypatch, tmp_path: Path) -> None:
    plugin_dir = make_plugin_dir(tmp_path)
    loaded = FakePlugin("tenko.plugins.file_plugin")
    load_plugin = Mock(return_value=loaded)
    unload_plugin = Mock(return_value=True)
    enable_plugin = AsyncMock(return_value=True)
    disable_plugin = AsyncMock(return_value=True)
    monkeypatch.setattr(plugin_host, "load_plugin", load_plugin)
    monkeypatch.setattr(plugin_host, "unload_plugin", unload_plugin)
    monkeypatch.setattr(plugin_host, "enable_plugin", enable_plugin)
    monkeypatch.setattr(plugin_host, "disable_plugin", disable_plugin)

    runtime = PluginRuntime(plugin_dir)

    assert await runtime.load("file_plugin") is loaded
    assert load_plugin.call_args.args == ("tenko.plugins.file_plugin",)
    assert runtime.unload("file_plugin")
    assert unload_plugin.call_args.args == ("tenko.plugins.file_plugin",)
    assert await runtime.enable("file_plugin")
    assert await runtime.disable("file_plugin")
    enable_plugin.assert_awaited_once_with("tenko.plugins.file_plugin")
    disable_plugin.assert_awaited_once_with("tenko.plugins.file_plugin")


@pytest.mark.asyncio
async def test_load_all_forwards_explicit_plugin_configs(
    monkeypatch, tmp_path: Path
) -> None:
    plugin_dir = make_plugin_dir(tmp_path)
    native_plugins = {
        "file_plugin": FakePlugin("tenko.plugins.file_plugin"),
        "package_plugin": FakePlugin("tenko.plugins.package_plugin"),
    }

    def load_plugin(name: str, *args):
        return native_plugins[name.rsplit(".", 1)[-1]]

    load_plugin_mock = Mock(side_effect=load_plugin)
    monkeypatch.setattr(plugin_host, "load_plugin", load_plugin_mock)
    monkeypatch.setattr(
        plugin_host,
        "get_plugins",
        lambda subplugged=False: list(native_plugins.values()),
    )

    runtime = PluginRuntime(plugin_dir)

    await runtime.load_all({"file_plugin": {"enabled": True}})

    assert load_plugin_mock.call_args_list == [
        call("tenko.plugins.file_plugin", {"enabled": True}),
        call("tenko.plugins.package_plugin"),
    ]


@pytest.mark.asyncio
async def test_load_all_loads_explicit_configs_before_default_plugins(
    monkeypatch, tmp_path: Path
) -> None:
    plugin_dir = make_plugin_dir(tmp_path)
    native_plugins = {
        "file_plugin": FakePlugin("tenko.plugins.file_plugin"),
        "package_plugin": FakePlugin("tenko.plugins.package_plugin"),
    }
    load_plugin_mock = Mock(
        side_effect=lambda name, *args: native_plugins[name.rsplit(".", 1)[-1]]
    )
    monkeypatch.setattr(plugin_host, "load_plugin", load_plugin_mock)
    monkeypatch.setattr(
        plugin_host,
        "get_plugins",
        lambda subplugged=False: list(native_plugins.values()),
    )

    runtime = PluginRuntime(plugin_dir)
    await runtime.load_all({"package_plugin": {"enabled": True}})

    assert load_plugin_mock.call_args_list == [
        call("tenko.plugins.package_plugin", {"enabled": True}),
        call("tenko.plugins.file_plugin"),
    ]


@pytest.mark.asyncio
async def test_reload_uses_native_unload_and_load(monkeypatch, tmp_path: Path) -> None:
    plugin_dir = make_plugin_dir(tmp_path)
    first = FakePlugin("tenko.plugins.file_plugin")
    second = FakePlugin("tenko.plugins.file_plugin")
    load_plugin = Mock(side_effect=[first, second])
    unload_plugin = Mock(return_value=True)
    monkeypatch.setattr(plugin_host, "load_plugin", load_plugin)
    monkeypatch.setattr(plugin_host, "unload_plugin", unload_plugin)

    runtime = PluginRuntime(plugin_dir)

    assert await runtime.load("file_plugin") is first
    assert await runtime.reload("file_plugin") is second
    assert unload_plugin.call_args.args == ("tenko.plugins.file_plugin",)
    assert load_plugin.call_args_list[-1].args == ("tenko.plugins.file_plugin",)
