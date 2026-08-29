from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import AsyncMock, Mock

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

    runtime = PluginRuntime(plugin_dir, legacy_state_path=None)

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

    runtime = PluginRuntime(plugin_dir, legacy_state_path=None)

    assert await runtime.load("file_plugin") is loaded
    assert load_plugin.call_args.args == ("tenko.plugins.file_plugin",)
    assert runtime.unload("file_plugin")
    assert unload_plugin.call_args.args == ("tenko.plugins.file_plugin",)
    assert await runtime.enable("file_plugin")
    assert await runtime.disable("file_plugin")
    enable_plugin.assert_awaited_once_with("tenko.plugins.file_plugin")
    disable_plugin.assert_awaited_once_with("tenko.plugins.file_plugin")


@pytest.mark.asyncio
async def test_reload_uses_native_unload_and_load(monkeypatch, tmp_path: Path) -> None:
    plugin_dir = make_plugin_dir(tmp_path)
    first = FakePlugin("tenko.plugins.file_plugin")
    second = FakePlugin("tenko.plugins.file_plugin")
    load_plugin = Mock(side_effect=[first, second])
    unload_plugin = Mock(return_value=True)
    monkeypatch.setattr(plugin_host, "load_plugin", load_plugin)
    monkeypatch.setattr(plugin_host, "unload_plugin", unload_plugin)

    runtime = PluginRuntime(plugin_dir, legacy_state_path=None)

    assert await runtime.load("file_plugin") is first
    assert await runtime.reload("file_plugin") is second
    assert unload_plugin.call_args.args == ("tenko.plugins.file_plugin",)
    assert load_plugin.call_args_list[-1].args == ("tenko.plugins.file_plugin",)


@pytest.mark.asyncio
async def test_legacy_state_maps_global_switches_and_is_read_only(
    monkeypatch,
    tmp_path: Path,
) -> None:
    plugin_dir = make_plugin_dir(tmp_path)
    state_path = tmp_path / "modules_data.json"
    state = {
        "modules": {
            "modules.self_contained.file_plugin": {"available": False},
            "modules.required.package_plugin": {"available": True},
        },
        "groups": {},
    }
    state_path.write_text(json.dumps(state), encoding="utf-8")
    before = state_path.read_bytes()
    native_plugins = {
        "file_plugin": FakePlugin("native.file_plugin"),
        "package_plugin": FakePlugin("native.package_plugin"),
    }
    load_plugin = Mock(side_effect=lambda name: native_plugins[name.rsplit(".", 1)[-1]])
    enable_plugin = AsyncMock(return_value=True)
    disable_plugin = AsyncMock(return_value=True)
    monkeypatch.setattr(plugin_host, "load_plugin", load_plugin)
    monkeypatch.setattr(plugin_host, "enable_plugin", enable_plugin)
    monkeypatch.setattr(plugin_host, "disable_plugin", disable_plugin)

    runtime = PluginRuntime(plugin_dir, legacy_state_path=state_path)

    assert await runtime.load("file_plugin") is native_plugins["file_plugin"]
    assert (
        await runtime.load("modules.required.package_plugin")
        is native_plugins["package_plugin"]
    )
    disable_plugin.assert_awaited_once_with("native.file_plugin")
    enable_plugin.assert_awaited_once_with("native.package_plugin")
    assert state_path.read_bytes() == before


def test_legacy_group_switch_uses_compatible_name_without_global_toggle(
    tmp_path: Path,
) -> None:
    plugin_dir = make_plugin_dir(tmp_path)
    state_path = tmp_path / "modules_data.json"
    state_path.write_text(
        json.dumps(
            {
                "modules": {
                    "modules.self_contained.file_plugin": {
                        "groups": {"100": {"switch": False}}
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    runtime = PluginRuntime(plugin_dir, legacy_state_path=state_path)

    assert not runtime.is_enabled("file_plugin", make_group_context("100"))
    assert runtime.is_enabled("file_plugin", make_group_context("101"))
