from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from arclet.entari.command import Match, Query
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
from satori.element import At, Author, Quote
from satori.model import Event, Member

from tenko.host.actions import ActionService
from tenko.host.accounts import AccountRegistry
from tenko.host.perm import PermissionChecker, PermissionRegistry


def make_session(user_id: str, role: str, elements=None):
    event = Event(
        type=EventType.MESSAGE_CREATED,
        timestamp=datetime.now(),
        login=Login(platform="onebot", user=User("10001")),
        channel=Channel("40001", ChannelType.TEXT),
        guild=Guild("40001", "Tenko"),
        member=Member(user=User(user_id), roles=[Role(role)]),
        user=User(user_id),
        message=MessageObject.from_elements("50001", elements or []),
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
@pytest.mark.parametrize("loaded_plugin", ["group_manager"], indirect=True)
async def test_group_setting_trigger_is_read_only(loaded_plugin) -> None:
    loaded_plugin.permission_checker = PermissionChecker(registry=PermissionRegistry())
    loaded_plugin.read_group_settings = AsyncMock(
        return_value={
            "frequency_limitation": True,
            "response_type": "random",
            "permission_type": "admin",
            "permission": 2,
            "active": True,
        }
    )

    result = await loaded_plugin.group_setting.callable_target(
        make_session("20001", "admin"), Query("group.group_id", None)
    )

    assert "权限类型: admin" in str(result)
    loaded_plugin.read_group_settings.assert_awaited_once_with("40001")


@pytest.mark.asyncio
@pytest.mark.parametrize("loaded_plugin", ["group_manager"], indirect=True)
async def test_group_setting_permission_filter_blocks_normal_member(
    loaded_plugin,
) -> None:
    loaded_plugin.permission_checker = PermissionChecker(registry=PermissionRegistry())
    loaded_plugin.read_group_settings = AsyncMock()

    result = await loaded_plugin.group_setting.callable_target(
        make_session("20001", "member"), Query("group.group_id", None)
    )

    assert str(result) == "权限不足"
    loaded_plugin.read_group_settings.assert_not_awaited()


class FakeProtocol:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []

    async def guild_member_mute(self, *args):
        self.calls.append(("guild_member_mute", args, {}))

    async def channel_mute(self, *args):
        self.calls.append(("channel_mute", args, {}))

    async def message_delete(self, *args):
        self.calls.append(("message_delete", args, {}))

    async def guild_member_kick(self, *args, **kwargs):
        self.calls.append(("guild_member_kick", args, kwargs))


class FakeAccount:
    self_id = "10001"

    def __init__(self, protocol: FakeProtocol) -> None:
        self.protocol = protocol


def install_action_service(loaded_plugin):
    protocol = FakeProtocol()
    account = FakeAccount(protocol)
    accounts = AccountRegistry()
    accounts.register(account, groups=["40001"])
    permissions = PermissionRegistry()
    checker = PermissionChecker(registry=permissions)
    loaded_plugin.permission_checker = checker
    loaded_plugin.action_service = ActionService(accounts, checker)
    return protocol


@pytest.mark.asyncio
@pytest.mark.parametrize("loaded_plugin", ["group_manager"], indirect=True)
async def test_management_commands_call_action_service(loaded_plugin) -> None:
    protocol = install_action_service(loaded_plugin)
    session = make_session("20001", "admin")

    mute_result = await loaded_plugin.mute.callable_target(
        session,
        Match((At("20002"), "5"), True),
        Match(None, False),
    )
    unmute_result = await loaded_plugin.unmute.callable_target(
        session,
        Match((At("20002"),), True),
    )
    whole_mute_result = await loaded_plugin.mute_all.callable_target(session)
    whole_unmute_result = await loaded_plugin.unmute_all.callable_target(session)
    kick_result = await loaded_plugin.kick.callable_target(
        session,
        Match(("20002",), True),
    )

    assert str(mute_result) == "已设置【20002】5分钟的禁言!"
    assert str(unmute_result) == "已解禁20002!"
    assert str(whole_mute_result) == "开启全体禁言成功!"
    assert str(whole_unmute_result) == "关闭全体禁言成功!"
    assert str(kick_result) == "已将20002踢出群聊!"
    assert protocol.calls == [
        ("guild_member_mute", ("40001", "20002", 300.0), {}),
        ("guild_member_mute", ("40001", "20002", 0.0), {}),
        ("channel_mute", ("40001", 60.0), {}),
        ("channel_mute", ("40001", 0.0), {}),
        ("guild_member_kick", ("40001", "20002"), {"permanent": False}),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("loaded_plugin", ["group_manager"], indirect=True)
async def test_recall_uses_the_satori_quote_message_id(loaded_plugin) -> None:
    protocol = install_action_service(loaded_plugin)
    session = make_session(
        "20001",
        "admin",
        [Quote("60001", content=[Author("20002")])],
    )

    result = await loaded_plugin.recall.callable_target(session)

    assert result is None
    assert protocol.calls == [("message_delete", ("40001", "60001"), {})]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("command_name", "arguments"),
    [
        ("mute", (Match(("20002", "5"), True), Match(None, False))),
        ("unmute", (Match(("20002",), True),)),
        ("mute_all", ()),
        ("unmute_all", ()),
        ("recall", ()),
        ("kick", (Match(("20002",), True),)),
    ],
)
@pytest.mark.parametrize("loaded_plugin", ["group_manager"], indirect=True)
async def test_every_management_command_blocks_members(
    loaded_plugin, command_name, arguments
) -> None:
    loaded_plugin.permission_checker = PermissionChecker(registry=PermissionRegistry())
    loaded_plugin.action_service = ActionService(
        AccountRegistry(), loaded_plugin.permission_checker
    )
    result = await getattr(loaded_plugin, command_name).callable_target(
        make_session("20001", "member"), *arguments
    )

    assert str(result) == "权限不足"


@pytest.mark.asyncio
@pytest.mark.parametrize("minutes", [0, 30 * 24 * 60 + 1])
@pytest.mark.parametrize("loaded_plugin", ["group_manager"], indirect=True)
async def test_mute_rejects_legacy_minute_boundaries(loaded_plugin, minutes) -> None:
    protocol = install_action_service(loaded_plugin)
    result = await loaded_plugin.mute.callable_target(
        make_session("20001", "admin"),
        Match((At("20002"), str(minutes)), True),
        Match(None, False),
    )

    assert str(result) == "时间非法!范围(分钟): `0 &lt; time &lt;= 43200`"
    assert protocol.calls == []
