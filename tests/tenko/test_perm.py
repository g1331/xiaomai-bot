from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal
from unittest.mock import Mock

import pytest
from arclet.entari.config import EntariConfig

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

    @staticmethod
    def _database_id(value: int | str) -> int | str:
        normalized = str(value)
        return int(normalized) if normalized.isdecimal() else normalized

    async def get_member_permission(
        self, group_id: int | str, user_id: int | str
    ) -> int | None:
        self.queries.append(("member_perm", group_id, user_id))
        return self.member_levels.get(
            (self._database_id(group_id), self._database_id(user_id))
        )

    async def get_group_permission(self, group_id: int | str) -> int | None:
        self.queries.append(("group_perm", group_id))
        return self.group_levels.get(self._database_id(group_id))

    async def get_bot_admin_ids(self) -> tuple[int, ...]:
        self.queries.append(("bot_admins",))
        return self.bot_admin_ids


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
    assert all(
        query[0] in {"member_perm", "group_perm", "bot_admins"}
        for query in database.queries
    )


@pytest.mark.asyncio
async def test_permission_checker_reads_real_repository(tenko_database) -> None:
    del tenko_database
    from tenko.db.repositories import (
        group_perm_repository,
        member_perm_repository,
    )

    await member_perm_repository.set_permission("10001", "20001", Permission.GroupBlack)
    await group_perm_repository.set("10001", GroupPermission.VipGroup)

    checker = PermissionChecker()
    context = make_context("20001", member_role="owner")

    assert await checker.get_user_perm(context) == Permission.GroupBlack
    assert await checker.get_group_perm(context) == GroupPermission.VipGroup


@pytest.mark.asyncio
async def test_missing_sqlalchemy_uses_default_group_permission_and_warns_once(
    monkeypatch,
) -> None:
    warning = Mock()
    monkeypatch.setattr(perm_module.logger, "warning", warning)

    checker = PermissionChecker()
    context = make_context()

    async def missing_sqlalchemy(*_args):
        raise ModuleNotFoundError("No module named 'sqlalchemy'", name="sqlalchemy")

    monkeypatch.setattr(checker, "_call_database", missing_sqlalchemy)

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

    async def fail_database_call(*_args):
        raise ModuleNotFoundError(
            "No module named 'unrelated_dependency'",
            name="unrelated_dependency",
        )

    monkeypatch.setattr(checker, "_call_database", fail_database_call)

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


@pytest.mark.asyncio
async def test_entari_native_superuser_has_master_permission(monkeypatch) -> None:
    if not EntariConfig._inited:
        EntariConfig(Path("/tmp/tenko-native-superuser-test.yml"))
    original = EntariConfig.instance.basic.superusers
    monkeypatch.setattr(
        EntariConfig.instance.basic,
        "superusers",
        {"onebot": ["native-master"]},
    )
    try:
        checker = PermissionChecker(registry=PermissionRegistry())
        assert await checker.get_user_perm(make_context("native-master")) == (
            Permission.Master
        )
        assert await checker.require_perm(
            make_context("native-master"), Permission.Master
        )
    finally:
        EntariConfig.instance.basic.superusers = original
