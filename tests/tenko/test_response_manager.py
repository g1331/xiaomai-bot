from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
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

from tenko.host.accounts import AccountRegistry
from tenko.host.perm import Permission, PermissionChecker, PermissionRegistry


@dataclass
class FakeAccount:
    self_id: str


def make_registry() -> AccountRegistry:
    registry = AccountRegistry()
    first = FakeAccount("10001")
    second = FakeAccount("10002")
    registry.register(first, groups=[40001])
    registry.register(second, available=False, groups=[40001])
    registry.set_response_type(40001, "deterministic")
    registry.set_deterministic_account(40001, first)
    registry.set_muted(
        first,
        40001,
        True,
        until=datetime.now(timezone.utc) + timedelta(minutes=5),
    )
    return registry


def make_session():
    event = Event(
        type=EventType.MESSAGE_CREATED,
        timestamp=datetime.now(),
        login=Login(platform="onebot", user=User("10001")),
        channel=Channel("40001", ChannelType.TEXT),
        guild=Guild("40001", "Tenko"),
        member=Member(user=User("20001"), roles=[Role("member")]),
        user=User("20001"),
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


@pytest.mark.parametrize("loaded_plugin", ["response_manager"], indirect=True)
def test_query_format_includes_route_availability_and_mute_state(loaded_plugin) -> None:
    registry = make_registry()
    group_text = loaded_plugin.format_group_bots(registry, 40001)
    online_text = loaded_plugin.format_online_bots(registry)

    assert "群40001响应账号" in group_text
    assert "响应类型: 指定(10001)" in group_text
    assert "10001: 在线，禁言至" in group_text
    assert "10002: 离线，可用" in group_text
    assert "在线BOT列表:1/2" in online_text
    assert "10001: 在线" in online_text
    assert "10002: 离线" in online_text


@pytest.mark.parametrize("loaded_plugin", ["response_manager"], indirect=True)
def test_query_commands_use_prefix_and_reject_bare_words(loaded_plugin) -> None:
    commands = (
        (loaded_plugin.bot_list_command, "/BOT列表", "/BOT列表 40001"),
        (loaded_plugin.bot_group_list_command, "/BOT群列表", "/BOT群列表 10001"),
        (loaded_plugin.online_bot_command, "/在线BOT", "/在线BOT 40001"),
    )
    for command, first, second in commands:
        assert command.prefixes == ["/"]
        assert command.parse(first).matched
        assert command.parse(second).matched
        assert not command.parse(first.removeprefix("/")).matched
        assert not command.parse(f"{first}x").matched
        assert not command.parse(f"/ {first.removeprefix('/')}").matched


@pytest.mark.asyncio
@pytest.mark.parametrize("loaded_plugin", ["response_manager"], indirect=True)
async def test_query_handler_reads_the_shared_account_registry(loaded_plugin) -> None:
    registry = make_registry()
    loaded_plugin.account_registry = registry
    permissions = PermissionRegistry()
    permissions.set_user_level(None, "20001", Permission.BotAdmin)
    loaded_plugin.permission_checker = PermissionChecker(registry=permissions)

    result = await loaded_plugin.bot_list.callable_target(
        make_session(), Query("group_id", None)
    )

    assert "群40001响应账号" in str(result)
    assert "禁言至" in str(result)
