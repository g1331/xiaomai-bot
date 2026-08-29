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
from satori.model import Event, Member

from tenko.host.perm import Permission, PermissionChecker, PermissionRegistry


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
@pytest.mark.parametrize("loaded_plugin", ["perm_manager"], indirect=True)
async def test_native_permission_command_writes_parsed_target(loaded_plugin) -> None:
    loaded_plugin.permission_checker = PermissionChecker(registry=PermissionRegistry())
    loaded_plugin._member_permission = AsyncMock(return_value=Permission.User)
    loaded_plugin._write_member_permission = AsyncMock()

    result = await loaded_plugin.change_user_perm.callable_target(
        make_session("20001", "owner"),
        Match(32, True),
        Match(("30001",), True),
        Query("group.group_id"),
    )

    assert "1个执行成功" in str(result)
    loaded_plugin._write_member_permission.assert_awaited_once_with(
        "40001", "30001", 32
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("loaded_plugin", ["perm_manager"], indirect=True)
async def test_permission_command_returns_denial_for_insufficient_member(
    loaded_plugin,
) -> None:
    loaded_plugin.permission_checker = PermissionChecker(registry=PermissionRegistry())
    loaded_plugin._member_permission = AsyncMock()

    result = await loaded_plugin.change_user_perm.callable_target(
        make_session("20001", "member"),
        Match(32, True),
        Match(("30001",), True),
        Query("group.group_id"),
    )

    assert str(result) == "权限不足"
    loaded_plugin._member_permission.assert_not_awaited()
