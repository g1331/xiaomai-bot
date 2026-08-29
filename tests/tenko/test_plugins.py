from __future__ import annotations

import json
from pathlib import Path

import pytest

from tenko.context import MessageContext
from tenko.host.plugins import PluginInterfaceError, PluginRuntime


def write_plugin(
    plugin_dir: Path,
    name: str,
    source: str,
    *,
    metadata: dict | None = None,
) -> None:
    path = plugin_dir / name
    path.mkdir(parents=True, exist_ok=True)
    (path / "__init__.py").write_text(source, encoding="utf-8")
    if metadata is not None:
        (path / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")


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


def test_discover_packages_and_python_modules(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "plugins"
    plugin_dir.mkdir()
    write_plugin(plugin_dir, "package_plugin", "def register(app, ctx): pass\n")
    (plugin_dir / "file_plugin.py").write_text(
        "def register(app, ctx): pass\n", encoding="utf-8"
    )
    (plugin_dir / "not_a_plugin").mkdir()
    (plugin_dir / "_private.py").write_text("", encoding="utf-8")

    runtime = PluginRuntime(plugin_dir, legacy_state_path=None)

    assert [info.name for info in runtime.discover()] == [
        "file_plugin",
        "package_plugin",
    ]


def test_load_and_unload_call_plugin_lifecycle(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "plugins"
    plugin_dir.mkdir()
    write_plugin(
        plugin_dir,
        "lifecycle",
        """
def register(app, ctx):
    app.append(("register", ctx))

def unregister(app, ctx):
    app.append(("unregister", ctx))
""",
    )
    calls: list[tuple[str, object]] = []
    context = object()
    runtime = PluginRuntime(
        plugin_dir,
        app=calls,
        context=context,
        legacy_state_path=None,
    )

    module = runtime.load("lifecycle")

    assert module is not None
    assert calls == [("register", context)]
    assert runtime.is_loaded("lifecycle")
    assert runtime.unload("lifecycle")
    assert calls == [("register", context), ("unregister", context)]
    assert not runtime.is_loaded("lifecycle")
    assert runtime.unload("lifecycle") is False


def test_legacy_switches_filter_loading_and_are_read_only(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "plugins"
    plugin_dir.mkdir()
    write_plugin(
        plugin_dir,
        "alpha",
        'def register(app, ctx): app.append("alpha")\n',
        metadata={"default_switch": True},
    )
    write_plugin(
        plugin_dir,
        "beta",
        'def register(app, ctx): app.append("beta")\n',
        metadata={"default_switch": True},
    )
    state_path = tmp_path / "modules_data.json"
    state = {
        "modules": {
            "alpha": {"available": True, "100": {"switch": False}},
            "beta": {"available": False},
        },
        "groups": {},
    }
    state_path.write_text(json.dumps(state), encoding="utf-8")
    before = state_path.read_bytes()
    calls: list[str] = []
    runtime = PluginRuntime(
        plugin_dir,
        app=calls,
        legacy_state_path=state_path,
    )

    assert not runtime.is_enabled("alpha", make_group_context("100"))
    assert runtime.is_enabled("alpha", make_group_context("101"))
    assert runtime.load("alpha", group_id="100") is None
    assert runtime.load("alpha", group_id="101") is not None
    assert runtime.load("beta") is None
    runtime.set_enabled("beta", True)
    assert runtime.is_enabled("beta")
    assert runtime.load("beta") is not None
    assert state_path.read_bytes() == before
    assert calls == ["alpha", "beta"]


def test_reload_reads_changed_source_and_rejects_missing_register(
    tmp_path: Path,
) -> None:
    plugin_dir = tmp_path / "plugins"
    plugin_dir.mkdir()
    plugin_path = plugin_dir / "reloadable"
    write_plugin(
        plugin_dir,
        "reloadable",
        "VERSION = 'one'\ndef register(app, ctx): app.append(VERSION)\n",
    )
    calls: list[str] = []
    runtime = PluginRuntime(plugin_dir, app=calls, legacy_state_path=None)
    first = runtime.load("reloadable")
    assert first is not None
    assert calls == ["one"]

    (plugin_path / "__init__.py").write_text(
        "VERSION = 'two'\ndef register(app, ctx): app.append(VERSION)\n",
        encoding="utf-8",
    )
    second = runtime.reload("reloadable")

    assert second is not None
    assert second.VERSION == "two"
    assert calls == ["one", "two"]

    write_plugin(plugin_dir, "invalid", "VALUE = 1\n")
    with pytest.raises(PluginInterfaceError, match="register"):
        runtime.discover()
        runtime.load("invalid")
