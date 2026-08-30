from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock

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


@pytest.mark.asyncio
@pytest.mark.parametrize("loaded_plugin", ["perm_manager"], indirect=True)
async def test_native_permission_command_writes_parsed_target(loaded_plugin) -> None:
    loaded_plugin.permission_checker = PermissionChecker(registry=PermissionRegistry())
    loaded_plugin._member_permission = AsyncMock(return_value=Permission.User)
    loaded_plugin._write_member_permission = AsyncMock()
    loaded_plugin._target_member = AsyncMock(return_value=object())

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
    result = await loaded_plugin.get_perm_list.callable_target(
        make_session("20001", "member"), make_query("group.group_id", 40002)
    )

    assert str(result) == "群内只能查询当前群"


@pytest.mark.asyncio
@pytest.mark.parametrize("loaded_plugin", ["perm_manager"], indirect=True)
async def test_master_private_permission_list_can_query_requested_group(
    loaded_plugin,
) -> None:
    loaded_plugin.permission_checker = PermissionChecker(
        registry=PermissionRegistry(master_id="90001")
    )
    loaded_plugin._group_member_permissions = AsyncMock(
        return_value=[SimpleNamespace(qq=30001, perm=32)]
    )

    result = await loaded_plugin.get_perm_list.callable_target(
        make_private_session("90001"), make_query("group.group_id", 40002)
    )

    output = str(result)
    assert "群40002权限等级: 1" in output
    assert "30001: 32" in output
    loaded_plugin._group_member_permissions.assert_awaited_once_with("40002")


@pytest.mark.asyncio
@pytest.mark.parametrize("loaded_plugin", ["perm_manager"], indirect=True)
async def test_non_master_private_permission_list_is_denied(loaded_plugin) -> None:
    loaded_plugin.permission_checker = PermissionChecker(registry=PermissionRegistry())
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
        loaded_plugin._vip_groups = AsyncMock(
            return_value=[SimpleNamespace(group_id=40002, group_name="其他群")]
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


@pytest.mark.asyncio
@pytest.mark.parametrize("loaded_plugin", ["perm_manager"], indirect=True)
async def test_permission_command_reads_and_writes_real_repository(
    loaded_plugin, tenko_database
) -> None:
    del tenko_database
    from tenko.db.repositories import member_perm_repository

    loaded_plugin.permission_checker = PermissionChecker(registry=PermissionRegistry())
    loaded_plugin._target_member = AsyncMock(return_value=object())

    result = await loaded_plugin.change_user_perm.callable_target(
        make_session("20001", "owner"),
        Match(32, True),
        Match(("30001",), True),
        Query("group.group_id"),
    )

    assert "1个执行成功" in str(result)
    assert await member_perm_repository.get_permission("40001", "30001") == 32
    loaded_plugin._target_member.assert_awaited_once_with(ANY, "40001", "30001")


@pytest.mark.asyncio
@pytest.mark.parametrize("loaded_plugin", ["perm_manager"], indirect=True)
async def test_group_permission_commands_sync_real_repository(
    loaded_plugin, tenko_database
) -> None:
    del tenko_database
    from tenko.db.repositories import (
        group_perm_repository,
        group_setting_repository,
        member_perm_repository,
    )

    loaded_plugin.permission_checker = PermissionChecker(
        registry=PermissionRegistry(bot_admin_ids=["20001"])
    )
    session = make_session("20001", "member")
    loaded_plugin._target_members = AsyncMock(
        return_value=(
            {"user_id": "30001", "permission": "admin"},
            {"user_id": "30002", "permission": "member"},
            {"user_id": "30003", "permission": "member"},
        )
    )
    await member_perm_repository.set_permission("40001", "30002", Permission.GroupOwner)
    await member_perm_repository.set_permission("40001", "30003", Permission.User)

    group_result = await loaded_plugin.change_group_perm.callable_target(
        session, Match(2, True), Query("group.group_id")
    )
    type_result = await loaded_plugin.change_group_perm_type.callable_target(
        session, Match("admin", True), Query("group.group_id")
    )

    assert str(group_result) == "已修改群40001权限为2"
    assert str(type_result) == "已修改群40001权限类型为admin"
    group_row = await group_perm_repository.get("40001")
    setting_row = await group_setting_repository.get("40001")
    assert group_row is not None and (group_row.perm, group_row.active) == (2, True)
    assert setting_row is not None and setting_row.permission_type == "admin"
    assert await member_perm_repository.get_permission("40001", "30001") == 32
    assert await member_perm_repository.get_permission("40001", "30002") == 64
    assert await member_perm_repository.get_permission("40001", "30003") == 32

    loaded_plugin._target_members = AsyncMock(
        return_value=(
            {"user_id": "30001", "permission": "member"},
            {"user_id": "30002", "permission": "member"},
            {"user_id": "30003", "permission": "member"},
        )
    )
    default_result = await loaded_plugin.change_group_perm_type.callable_target(
        session, Match("default", True), Query("group.group_id")
    )

    assert str(default_result) == "已修改群40001权限类型为default"
    assert await group_setting_repository.get("40001")
    assert await member_perm_repository.get_permission("40001", "30001") == 16
    assert await member_perm_repository.get_permission("40001", "30002") == 64
    assert await member_perm_repository.get_permission("40001", "30003") == 16


@pytest.mark.asyncio
@pytest.mark.parametrize("loaded_plugin", ["perm_manager"], indirect=True)
async def test_permission_command_rejects_non_member_without_writing(
    loaded_plugin, tenko_database
) -> None:
    del tenko_database
    from tenko.db.repositories import member_perm_repository

    loaded_plugin.permission_checker = PermissionChecker(registry=PermissionRegistry())
    loaded_plugin._target_member = AsyncMock(return_value=None)

    result = await loaded_plugin.change_user_perm.callable_target(
        make_session("20001", "owner"),
        Match(32, True),
        Match(("30001",), True),
        Query("group.group_id"),
    )

    assert "没有在群40001找到群成员" in str(result)
    assert await member_perm_repository.get_permission("40001", "30001") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("loaded_plugin", ["perm_manager"], indirect=True)
async def test_test_group_protection_blocks_both_permission_commands(
    loaded_plugin, tenko_database
) -> None:
    del tenko_database
    loaded_plugin.permission_checker = PermissionChecker(
        registry=PermissionRegistry(bot_admin_ids=["20001"])
    )
    loaded_plugin.configure_test_group("40001")
    try:
        session = make_session("20001", "member")
        group_result = await loaded_plugin.change_group_perm.callable_target(
            session, Match(2, True), Query("group.group_id")
        )
        type_result = await loaded_plugin.change_group_perm_type.callable_target(
            session, Match("admin", True), Query("group.group_id")
        )
    finally:
        loaded_plugin.configure_test_group(None)

    assert str(group_result) == "无法通过该指令修改测试群(40001)权限!"
    assert str(type_result) == "无法通过该指令修改测试群(40001)权限!"


@pytest.mark.asyncio
@pytest.mark.parametrize("loaded_plugin", ["perm_manager"], indirect=True)
async def test_permission_write_reports_database_unavailable(
    loaded_plugin, tenko_database
) -> None:
    from tenko.db.repositories import configure_session_factory

    loaded_plugin.permission_checker = PermissionChecker(
        registry=PermissionRegistry(bot_admin_ids=["20001"])
    )
    configure_session_factory(None)
    result = await loaded_plugin.change_group_perm.callable_target(
        make_session("20001", "member"), Match(2, True), Query("group.group_id")
    )

    assert str(result) == "数据库暂不可用，修改群权限未执行"
