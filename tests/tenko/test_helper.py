from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from arclet.entari.command import Query
from satori import (
    Channel,
    ChannelType,
    EventType,
    Guild,
    Login,
    MessageObject,
    Role,
    User,
)
from satori.model import Event, Member

from tenko.host.perm import PermissionChecker, PermissionRegistry


def make_session(user_id: str, role: str):
    event = Event(
        type=EventType.MESSAGE_CREATED,
        timestamp=datetime.now(),
        login=Login(platform="onebot", user=User("10001")),
        channel=Channel("40001", ChannelType.TEXT),
        guild=Guild("40001", "Tenko"),
        member=Member(user=User(user_id), roles=[Role(role)]),
        user=User(user_id),
        message=MessageObject.from_elements("50001", []),
    )
    return SimpleNamespace(
        event=SimpleNamespace(
            _origin=event,
            channel=event.channel,
            guild=event.guild,
            user=event.user,
        )
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("loaded_plugin", ["helper"], indirect=True)
async def test_helper_trigger_uses_native_command_registry(loaded_plugin) -> None:
    loaded_plugin.permission_checker = PermissionChecker(registry=PermissionRegistry())

    result = await loaded_plugin.helper.callable_target(
        make_session("20001", "member"),
        Query("index", None),
        render_service=loaded_plugin.RenderService(),
    )

    assert "Tenko 已注册命令" in str(result)
    assert "内置插件：" in str(result)
    assert "运行插件：" in str(result)
    assert "维护插件：" in str(result)
    assert loaded_plugin.help_command.parse("/帮助").matched
    assert loaded_plugin.help_command.parse("/-help 1").matched
    assert loaded_plugin.help_command.parse("/-帮助 1").matched
    assert not loaded_plugin.help_command.parse("帮助").matched


@pytest.mark.asyncio
@pytest.mark.parametrize("loaded_plugin", ["helper"], indirect=True)
async def test_helper_permission_filter_blocks_global_blacklisted_user(
    loaded_plugin,
) -> None:
    registry = PermissionRegistry()
    registry.set_user_level(None, "20001", -1)
    loaded_plugin.permission_checker = PermissionChecker(registry=registry)

    result = await loaded_plugin.helper.callable_target(
        make_session("20001", "member"),
        Query("index", None),
        render_service=loaded_plugin.RenderService(),
    )

    assert str(result) == "权限不足"


@pytest.mark.parametrize("loaded_plugin", ["helper"], indirect=True)
def test_help_data_partitions_required_available_and_maintenance(
    monkeypatch, loaded_plugin
):
    infos = tuple(
        loaded_plugin.PluginInfo(
            name=name,
            path=Path(name),
            is_package=True,
            qualified_name=f"tenko.plugins.{name}",
        )
        for name in ("required", "available", "disabled", "maintenance")
    )
    native_plugins = tuple(
        SimpleNamespace(
            id=f"tenko.plugins.{name}",
            metadata=SimpleNamespace(
                name=f"{name} plugin",
                description=f"{name} description",
                classifier=("required",) if name == "required" else (),
            ),
        )
        for name in ("required", "available", "disabled", "maintenance")
    )

    class FakeFeatureService:
        @staticmethod
        def is_maintenance(plugin_name):
            return plugin_name == "maintenance"

        @staticmethod
        def is_enabled(plugin_name, group_id):
            return plugin_name != "disabled"

    monkeypatch.setattr(loaded_plugin.plugin_runtime, "discover", lambda: infos)
    monkeypatch.setattr(
        loaded_plugin, "get_plugins", lambda *, subplugged: native_plugins
    )
    monkeypatch.setattr(loaded_plugin, "feature_service", FakeFeatureService())

    data = loaded_plugin.build_help_data("40001")

    assert [item["name"] for item in data["required"]] == ["required plugin"]
    assert [item["name"] for item in data["available"]] == [
        "available plugin",
        "disabled plugin",
    ]
    assert [item["name"] for item in data["unavailable"]] == ["maintenance plugin"]
    assert data["available"][0]["state_label"] == "运行中"
    assert data["available"][1]["state_label"] == "已关闭"
    assert data["unavailable"][0]["state_label"] == "维护中"
    assert data["total"] == 4
    assert data["enabled_count"] == 2

    text = loaded_plugin.format_help_text(data)
    assert (
        text.index("内置插件：") < text.index("运行插件：") < text.index("维护插件：")
    )
