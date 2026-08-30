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


def make_query(path: str, result):
    query = Query(path, result)
    query.available = True
    return query


class QueryBuilder:
    def where(self, *conditions):
        del conditions
        return self


class Column:
    def __eq__(self, other):
        del other
        return self


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


@pytest.mark.asyncio
@pytest.mark.parametrize("loaded_plugin", ["perm_manager"], indirect=True)
async def test_permission_list_rejects_cross_group_target_in_group(
    loaded_plugin,
) -> None:
    loaded_plugin.permission_checker = PermissionChecker(
        registry=PermissionRegistry(master_id="20001")
    )
    loaded_plugin._tables = lambda: (
        SimpleNamespace(),
        SimpleNamespace(),
        SimpleNamespace(),
    )
    loaded_plugin._database = lambda: SimpleNamespace(fetch_all=AsyncMock())

    result = await loaded_plugin.get_perm_list.callable_target(
        make_session("20001", "member"), make_query("group.group_id", 40002)
    )

    assert str(result) == "群内只能查询当前群"


@pytest.mark.asyncio
@pytest.mark.parametrize("loaded_plugin", ["perm_manager"], indirect=True)
async def test_master_private_permission_list_can_query_requested_group(
    loaded_plugin,
) -> None:
    member_perm = SimpleNamespace(qq=Column(), perm=Column(), group_id=Column())
    group_perm = SimpleNamespace()
    group_setting = SimpleNamespace()
    database = SimpleNamespace(fetch_all=AsyncMock(return_value=[("30001", 32)]))
    loaded_plugin.permission_checker = PermissionChecker(
        registry=PermissionRegistry(master_id="90001")
    )
    loaded_plugin._tables = lambda: (group_perm, group_setting, member_perm)
    loaded_plugin._select = lambda: (lambda *columns: QueryBuilder())
    loaded_plugin._database = lambda: database

    result = await loaded_plugin.get_perm_list.callable_target(
        make_private_session("90001"), make_query("group.group_id", 40002)
    )

    output = str(result)
    assert "群40002权限等级: 1" in output
    assert "30001: 32" in output
    database.fetch_all.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("loaded_plugin", ["perm_manager"], indirect=True)
async def test_non_master_private_permission_list_is_denied(loaded_plugin) -> None:
    loaded_plugin.permission_checker = PermissionChecker(registry=PermissionRegistry())
    loaded_plugin._tables = lambda: (_ for _ in ()).throw(
        AssertionError("database should not be read")
    )

    result = await loaded_plugin.get_perm_list.callable_target(
        make_private_session("20001"), make_query("group.group_id", 40002)
    )

    assert str(result) == "权限不足"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("handler_name", "data_name", "expected"),
    [
        ("get_vg_list", "vip", "VIP群列表"),
        ("get_global_black_list", "black", "全局黑名单"),
        ("get_bot_admins_list", "admins", "BOT管理列表"),
    ],
)
@pytest.mark.parametrize("loaded_plugin", ["perm_manager"], indirect=True)
async def test_sensitive_permission_lists_are_master_private_only(
    loaded_plugin, handler_name: str, data_name: str, expected: str
) -> None:
    loaded_plugin.permission_checker = PermissionChecker(
        registry=PermissionRegistry(master_id="90001")
    )
    if data_name == "vip":
        group_perm = SimpleNamespace(
            group_id=Column(), group_name=Column(), perm=Column()
        )
        loaded_plugin._tables = lambda: (
            group_perm,
            SimpleNamespace(),
            SimpleNamespace(),
        )
        loaded_plugin._select = lambda: (lambda *columns: QueryBuilder())
        loaded_plugin._database = lambda: SimpleNamespace(
            fetch_all=AsyncMock(return_value=[("40002", "其他群")])
        )
    elif data_name == "black":
        loaded_plugin._global_black_ids = AsyncMock(return_value={"20002"})
    else:
        loaded_plugin._bot_admin_ids = AsyncMock(return_value={"20003"})

    handler = getattr(loaded_plugin, handler_name)
    group_result = await handler.callable_target(make_session("90001", "member"))
    assert str(group_result) == "该指令仅支持 Master 私聊执行"

    private_result = await handler.callable_target(make_private_session("90001"))
    assert expected in str(private_result)

    loaded_plugin.permission_checker = PermissionChecker(registry=PermissionRegistry())
    denied = await handler.callable_target(make_private_session("20001"))
    assert str(denied) == "权限不足"
