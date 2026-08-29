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
        make_session("20001", "member"), Query("index", None)
    )

    assert "Tenko 已注册命令" in str(result)
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
        make_session("20001", "member"), Query("index", None)
    )

    assert str(result) == "权限不足"
