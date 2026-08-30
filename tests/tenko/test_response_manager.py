from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from arclet.entari.command import Query
from satori import (
    Channel,
    ChannelType,
    EventType,
    Guild,
    Image,
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


def make_private_session(user_id: str):
    event = Event(
        type=EventType.MESSAGE_CREATED,
        timestamp=datetime.now(),
        login=Login(platform="onebot", user=User("10001")),
        channel=Channel(f"private:{user_id}", ChannelType.DIRECT),
        guild=None,
        member=None,
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


@pytest.mark.parametrize("loaded_plugin", ["response_manager"], indirect=True)
def test_query_format_only_includes_aggregate_counts(loaded_plugin) -> None:
    registry = make_registry()
    group_text = loaded_plugin.format_group_bots(registry, 40001)
    online_text = loaded_plugin.format_online_bots(registry)

    assert "群40001BOT数: 2；可用数: 0" in group_text
    assert "禁言至" not in group_text
    assert "在线BOT列表:1/2" in online_text
    assert "10001" not in online_text
    assert "10002" not in online_text


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
        if command is loaded_plugin.bot_group_list_command:
            assert command.parse(second).matched
        else:
            assert not command.parse(second).matched
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
        make_session(), render_service=loaded_plugin.RenderService()
    )

    assert "群40001BOT数: 2；可用数: 0" in str(result)
    assert "禁言至" not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("loaded_plugin", ["response_manager"], indirect=True)
async def test_online_bot_uses_only_current_group_counts(loaded_plugin) -> None:
    registry = make_registry()
    loaded_plugin.account_registry = registry
    permissions = PermissionRegistry()
    loaded_plugin.permission_checker = PermissionChecker(registry=permissions)

    result = await loaded_plugin.online_bot.callable_target(
        make_session(), render_service=loaded_plugin.RenderService()
    )

    assert str(result) == "群40001在线BOT: 0/2"


@pytest.mark.asyncio
@pytest.mark.parametrize("loaded_plugin", ["response_manager"], indirect=True)
async def test_bot_group_list_is_master_private_only(loaded_plugin) -> None:
    registry = make_registry()
    second = FakeAccount("10003")
    registry.register(second, groups=[40002])
    loaded_plugin.account_registry = registry

    loaded_plugin.permission_checker = PermissionChecker(
        registry=PermissionRegistry(master_id="90001")
    )
    group_result = await loaded_plugin.bot_group_list.callable_target(
        make_session(),
        Query("account_id", None),
        render_service=loaded_plugin.RenderService(),
    )
    assert str(group_result) == "该指令仅支持 Master 私聊执行"

    private_result = await loaded_plugin.bot_group_list.callable_target(
        make_private_session("90001"),
        Query("account_id", None),
        render_service=loaded_plugin.RenderService(),
    )
    assert "群40001" in str(private_result)
    assert "群40002" in str(private_result)

    loaded_plugin.permission_checker = PermissionChecker(registry=PermissionRegistry())
    denied = await loaded_plugin.bot_group_list.callable_target(
        make_private_session("20001"),
        Query("account_id", None),
        render_service=loaded_plugin.RenderService(),
    )
    assert str(denied) == "权限不足"


@pytest.mark.asyncio
@pytest.mark.parametrize("loaded_plugin", ["response_manager"], indirect=True)
async def test_response_list_wraps_successful_render_as_image(
    loaded_plugin, monkeypatch
) -> None:
    registry = make_registry()
    loaded_plugin.account_registry = registry
    permissions = PermissionRegistry()
    permissions.set_user_level(None, "20001", Permission.BotAdmin)
    loaded_plugin.permission_checker = PermissionChecker(registry=permissions)
    renderer = AsyncMock(return_value=b"jpeg-bytes")
    monkeypatch.setattr(loaded_plugin, "render_or_none", renderer)
    render_service = loaded_plugin.RenderService()

    result = await loaded_plugin.bot_list.callable_target(
        make_session(), render_service=render_service
    )

    assert isinstance(result[0], Image)
    renderer.assert_awaited_once()
    assert renderer.await_args.args[:3] == (
        render_service,
        "render_template",
        "list.html",
    )
    data = renderer.await_args.args[3]
    assert data["summary"] == "群40001BOT数: 2；可用数: 0"
    assert data["items"][0]["name"] == "群40001"
