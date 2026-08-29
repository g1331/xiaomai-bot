from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

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
