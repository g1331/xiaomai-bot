from __future__ import annotations

from datetime import datetime
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
@pytest.mark.parametrize("loaded_plugin", ["status"], indirect=True)
async def test_status_command_reports_native_runtime_context(loaded_plugin) -> None:
    loaded_plugin.permission_checker = PermissionChecker(registry=PermissionRegistry())

    result = await loaded_plugin.status.callable_target(
        make_session("20001", "member"), Query("text.value", False)
    )

    assert "Tenko 状态" in str(result)
    assert "账号: 10001" in str(result)
    assert loaded_plugin.status_command.parse("-bot -t").matched


@pytest.mark.asyncio
@pytest.mark.parametrize("loaded_plugin", ["status"], indirect=True)
async def test_status_permission_filter_blocks_global_blacklisted_user(
    loaded_plugin,
) -> None:
    registry = PermissionRegistry()
    registry.set_user_level(None, "20001", Permission.GlobalBlack)
    loaded_plugin.permission_checker = PermissionChecker(registry=registry)

    result = await loaded_plugin.status.callable_target(
        make_session("20001", "member"), Query("text.value", False)
    )

    assert str(result) == "权限不足"
