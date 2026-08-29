from __future__ import annotations

import builtins
from dataclasses import dataclass, field
from typing import Literal
from unittest.mock import Mock

import pytest

import tenko.host.perm as perm_module
from tenko.context import MessageContext
from tenko.host.perm import (
    GroupPermission,
    Permission,
    PermissionChecker,
    PermissionRegistry,
)


@dataclass
class FakeDatabase:
    member_levels: dict[tuple[int | str, int | str], int] = field(default_factory=dict)
    group_levels: dict[int | str, int] = field(default_factory=dict)
    bot_admin_ids: tuple[int, ...] = ()
    queries: list[tuple] = field(default_factory=list)

    async def fetch_one(self, query: tuple) -> tuple[int] | None:
        self.queries.append(query)
        if query[0] == "member_perm":
            level = self.member_levels.get((query[1], query[2]))
        elif query[0] == "group_perm":
            level = self.group_levels.get(query[1])
        else:
            raise AssertionError(f"unexpected fetch_one query: {query}")
        return None if level is None else (level,)

    async def fetch_all(self, query: tuple) -> list[tuple[int]]:
        self.queries.append(query)
        assert query == ("bot_admins",)
        return [(user_id,) for user_id in self.bot_admin_ids]


def make_context(
    user_id: str = "20001",
    *,
    group_id: str = "10001",
    member_role: str | None = "member",
    chat_type: Literal["private", "group", "other"] = "group",
) -> MessageContext:
    return MessageContext(
        account_id="30001",
        event_type="message-created",
        protocol_event_type="message.group.normal",
        chat_type=chat_type,
        channel_id=group_id,
        user_id=user_id,
        message_id="40001",
        text="hello",
        image_urls=(),
        member_role=member_role,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("user_id", "role", "expected"),
    [
        ("master", "member", Permission.Master),
        ("admin", "member", Permission.BotAdmin),
        ("owner", "owner", Permission.GroupOwner),
        ("group-admin", "admin", Permission.GroupAdmin),
        ("member", "member", Permission.User),
    ],
)
async def test_permission_matrix_without_database(
    user_id: str, role: str, expected: Permission
) -> None:
    registry = PermissionRegistry(master_id="master", bot_admin_ids=["admin"])
    checker = PermissionChecker(registry=registry)

    context = make_context(user_id, member_role=role)

    assert await checker.get_user_perm(context) == expected
    assert await checker.require_perm(context, expected)
    assert await checker.require_perm(context, int(expected) + 1) is False


@pytest.mark.asyncio
async def test_database_levels_override_context_defaults_and_are_read_only() -> None:
    database = FakeDatabase(
        member_levels={
            (0, 20001): Permission.GlobalBlack,
            (10001, 20002): Permission.GroupBlack,
        },
        group_levels={10001: GroupPermission.VipGroup},
        bot_admin_ids=(20003,),
    )
    checker = PermissionChecker(database=database)

    global_black = make_context("20001")
    group_black = make_context("20002", member_role="owner")
    bot_admin = make_context("20003")
    normal = make_context("20004", member_role="owner")

    assert await checker.get_user_perm(global_black) == Permission.GlobalBlack
    assert not await checker.require_perm(global_black, Permission.User)
    assert await checker.get_user_perm(group_black) == Permission.GroupBlack
    assert await checker.get_user_perm(bot_admin) == Permission.BotAdmin
    assert await checker.get_user_perm(normal) == Permission.GroupOwner
    assert await checker.get_group_perm(normal) == GroupPermission.VipGroup
    assert await checker.require_group_perm(normal, GroupPermission.VipGroup)
    assert not await checker.require_group_perm(normal, GroupPermission.TestGroup)
    assert not any(
        query[0] in {"add", "update", "delete"} for query in database.queries
    )


@pytest.mark.asyncio
async def test_missing_sqlalchemy_uses_default_group_permission_and_warns_once(
    monkeypatch,
) -> None:
    real_import = builtins.__import__

    def missing_sqlalchemy(name, *args, **kwargs):
        if name == "sqlalchemy":
            raise ModuleNotFoundError("No module named 'sqlalchemy'", name="sqlalchemy")
        return real_import(name, *args, **kwargs)

    warning = Mock()
    monkeypatch.setattr(builtins, "__import__", missing_sqlalchemy)
    monkeypatch.setattr(perm_module.logger, "warning", warning)

    checker = PermissionChecker()
    context = make_context()

    assert await checker.require_group_perm(context, GroupPermission.ActiveGroup)
    assert not await checker.require_group_perm(context, GroupPermission.VipGroup)
    assert await checker.get_group_perm(context) == GroupPermission.ActiveGroup

    warning.assert_called_once()
    message = warning.call_args.args[0]
    assert "10001" in message
    assert "sqlalchemy" in message


@pytest.mark.asyncio
async def test_non_database_import_errors_are_not_swallowed(monkeypatch) -> None:
    checker = PermissionChecker(database=object())

    def fail_statement(*_args):
        raise ModuleNotFoundError(
            "No module named 'unrelated_dependency'",
            name="unrelated_dependency",
        )

    monkeypatch.setattr(checker, "_statement", fail_statement)

    with pytest.raises(ModuleNotFoundError, match="unrelated_dependency"):
        await checker.get_group_perm(make_context())


@pytest.mark.asyncio
async def test_private_context_skips_group_requirement_but_checks_user_permission() -> (
    None
):
    checker = PermissionChecker(registry=PermissionRegistry())
    context = make_context("20001", chat_type="private", member_role=None)

    assert await checker.require_group_perm(context, GroupPermission.TestGroup)
    assert await checker.require_perm(context, Permission.User)


@pytest.mark.asyncio
async def test_inactive_group_level_is_not_replaced_by_default() -> None:
    registry = PermissionRegistry()
    registry.set_group_level("10001", GroupPermission.InactiveGroup)
    checker = PermissionChecker(registry=registry)

    context = make_context()

    assert await checker.get_group_perm(context) == GroupPermission.InactiveGroup
    assert not await checker.require_group_perm(context, GroupPermission.ActiveGroup)


@pytest.mark.asyncio
async def test_runtime_global_blacklist_applies_to_group_context() -> None:
    registry = PermissionRegistry()
    registry.set_user_level(None, "20001", Permission.GlobalBlack)
    checker = PermissionChecker(registry=registry)

    assert await checker.get_user_perm(make_context("20001", member_role="owner")) == (
        Permission.GlobalBlack
    )
