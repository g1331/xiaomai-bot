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
    assert not loaded_plugin.help_command.parse("/-help 1").matched
    assert not loaded_plugin.help_command.parse("/-帮助 1").matched
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


@pytest.mark.parametrize("loaded_plugin", ["helper"], indirect=True)
def test_help_number_uses_plugin_commands_for_card_positions(
    monkeypatch, loaded_plugin
):
    plugin_names = (
        "announcement",
        "exception_catcher",
        "feature_manager",
        "group_manager",
        "helper",
        "perm_manager",
        "render",
        "response_manager",
        "status",
        "updater",
    )
    commands_by_plugin = {
        "group_manager": (
            "同意邀请",
            "拒绝邀请",
            "待审邀请",
            "重置能力",
            "群设置",
            "禁言",
            "解禁",
            "解禁自己",
            "全体禁言",
            "全体解禁",
            "撤回",
            "踢出",
        ),
        "updater": ("检查更新", "升级", "回滚"),
    }
    infos = tuple(
        loaded_plugin.PluginInfo(
            name=name,
            path=Path(name),
            is_package=True,
            qualified_name=f"tenko.plugins.{name}",
        )
        for name in plugin_names
    )

    def make_native_plugin(name):
        return SimpleNamespace(
            id=f"tenko.plugins.{name}",
            metadata=SimpleNamespace(
                name=f"{name} plugin",
                description=f"{name} description",
                classifier=("required",),
            ),
            _extra={
                "commands": [
                    (["/"], command_name)
                    for command_name in commands_by_plugin.get(name, ())
                ]
            },
        )

    native_plugins = tuple(make_native_plugin(name) for name in plugin_names)
    command_help = {
        command_name: SimpleNamespace(
            get_help=lambda command_name=command_name: f"help<{command_name}>"
        )
        for commands in commands_by_plugin.values()
        for command_name in commands
    }
    lookups = []

    def get_command(command_name):
        lookups.append(command_name)
        return command_help[command_name]

    monkeypatch.setattr(loaded_plugin.plugin_runtime, "discover", lambda: infos)
    monkeypatch.setattr(
        loaded_plugin, "get_plugins", lambda *, subplugged: native_plugins
    )
    monkeypatch.setattr(loaded_plugin.command_manager, "get_command", get_command)

    data = loaded_plugin.build_help_data()
    items = {
        item["plugin"]: item
        for section in data["sections"]
        for item in section["items"]
    }

    assert items["group_manager"]["number"] == 4
    assert items["updater"]["number"] == 10
    assert loaded_plugin.build_help(4) == "\n\n".join(
        f"help<{command_name}>" for command_name in commands_by_plugin["group_manager"]
    )
    assert loaded_plugin.build_help(10) == "\n\n".join(
        f"help<{command_name}>" for command_name in commands_by_plugin["updater"]
    )
    assert loaded_plugin.build_help(2) == "该插件未注册命令"
    assert loaded_plugin.build_help(11) == "编号不在范围内~"
    assert lookups == [
        *commands_by_plugin["group_manager"],
        *commands_by_plugin["updater"],
    ]
