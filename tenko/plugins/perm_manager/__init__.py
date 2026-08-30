from __future__ import annotations

from dataclasses import replace
from typing import Any

from arclet.alconna import Alconna, Args, CommandMeta, Field, MultiVar, Option
from arclet.entari import Session, command, plugin
from arclet.entari.command import Match, Query
from arclet.entari.event.base import (
    GuildMemberAddedEvent,
    GuildMemberRemovedEvent,
    GuildMemberUpdatedEvent,
    InternalEvent,
)
from arclet.entari.plugin import PluginRole
from loguru import logger

from tenko.host.perm import Permission, PermissionChecker
from tenko.plugins._common import (
    context_from_session,
    normalize_targets,
    text_message,
)


plugin.metadata(
    "权限管理",
    PluginRole.NORMAL,
    author=["13"],
    version="0.1.0",
    description="管理 Tenko 的成员权限、群权限和权限同步。",
    classifier=["required"],
)
# Entari 0.18.6 has no constructor field for default_switch.  Keep the
# compatibility marker on native metadata for host/plugins.py and inspectors.
plugin.get_plugin().metadata.default_switch = True


permission_checker = PermissionChecker()
_MASTER_PRIVATE_ONLY = "该指令仅支持 Master 私聊执行"


def _database() -> Any:
    from core.orm import orm

    return orm


def _tables():
    from core.orm.tables import GroupPerm, GroupSetting, MemberPerm

    return GroupPerm, GroupSetting, MemberPerm


def _select():
    """Load the legacy query builder only when a database operation is used."""

    from sqlalchemy import select

    return select


def _database_id(value: str | int) -> str | int:
    value = str(value)
    return int(value) if value.isdecimal() else value


def _row_value(row: object) -> object | None:
    if row is None:
        return None
    try:
        return row[0]  # type: ignore[index]
    except (IndexError, KeyError, TypeError):
        return None


async def _member_permission(group_id: str | int, user_id: str | int) -> int:
    _, _, member_perm = _tables()
    select = _select()
    result = await _database().fetch_one(
        select(member_perm.perm).where(
            member_perm.group_id == _database_id(group_id),
            member_perm.qq == _database_id(user_id),
        )
    )
    value = _row_value(result)
    return Permission.User if value is None else int(value)


async def _bot_admin_ids() -> set[str]:
    _, _, member_perm = _tables()
    select = _select()
    rows = await _database().fetch_all(
        select(member_perm.qq).where(member_perm.perm == Permission.BotAdmin)
    )
    return {str(value) for row in rows if (value := _row_value(row)) is not None}


async def _global_black_ids() -> set[str]:
    _, _, member_perm = _tables()
    select = _select()
    rows = await _database().fetch_all(
        select(member_perm.qq).where(
            member_perm.group_id == 0,
            member_perm.perm == Permission.GlobalBlack,
        )
    )
    return {str(value) for row in rows if (value := _row_value(row)) is not None}


async def _permission_type(group_id: str | int) -> str:
    _, group_setting, _ = _tables()
    select = _select()
    result = await _database().fetch_one(
        select(group_setting.permission_type).where(
            group_setting.group_id == _database_id(group_id)
        )
    )
    value = _row_value(result)
    return "default" if value is None else str(value)


async def _write_member_permission(
    group_id: str | int, user_id: str | int, permission: int
) -> None:
    _, _, member_perm = _tables()
    group_id = _database_id(group_id)
    user_id = _database_id(user_id)
    await _database().insert_or_update(
        member_perm,
        {"group_id": group_id, "qq": user_id, "perm": int(permission)},
        [member_perm.group_id == group_id, member_perm.qq == user_id],
    )


async def _delete_member_permission(group_id: str | int, user_id: str | int) -> None:
    _, _, member_perm = _tables()
    await _database().delete(
        member_perm,
        [
            member_perm.group_id == _database_id(group_id),
            member_perm.qq == _database_id(user_id),
        ],
    )


async def _authorized(session: Session, required: int) -> bool:
    context = context_from_session(session)
    return (
        context.chat_type == "group"
        and await permission_checker.require_group_perm(context, Permission.ActiveGroup)
        and await permission_checker.require_perm(context, required)
    )


def _current_group(session: Session, group: Query[int]) -> str | None:
    if group.available:
        return str(group.result)
    event_group = getattr(session.event, "guild", None)
    return event_group.id if event_group else None


async def _target_group(session: Session, group: Query[int]) -> tuple[str | None, bool]:
    """Return target group ID and whether it differs from the current group."""

    context = context_from_session(session)
    target = _current_group(session, group)
    if target is None:
        return None, False
    is_cross_group = target != context.channel_id
    if is_cross_group and not await permission_checker.require_perm(
        context, Permission.BotAdmin
    ):
        return None, True
    return target, is_cross_group


def _failure_summary(targets: tuple[str, ...], failures: list[tuple[str, str]]) -> str:
    succeeded = len(targets) - len(failures)
    result = (
        f"共解析{len(targets)}个目标\n其中{succeeded}个执行成功,{len(failures)}个失败"
    )
    if failures:
        result += "\n\n失败目标:" + "".join(
            f"\n{target}-{reason}" for target, reason in failures
        )
    return result


modify_user_command = Alconna(
    "修改权限",
    Args["perm", int],
    Args[
        "member_id",
        MultiVar(str),
        Field(missing_tips=lambda: "至少需要一个成员 ID"),
    ],
    Option(
        "--group",
        Args["group_id", int],
        alias=["-g", "群"],
        help_text="修改指定群的权限（跨群需要 BotAdmin）",
    ),
    meta=CommandMeta(
        "修改群成员权限",
        usage="修改权限 <0|16|32|64> <成员ID...> [--group <群号>]",
        example="修改权限 32 123456",
        compact=True,
    ),
)


@command.on(modify_user_command)
async def change_user_perm(
    session: Session,
    perm: Match[int],
    member_id: Match[tuple[str, ...]],
    group: Query[int] = Query("group.group_id", None),
):
    if perm.result not in {
        Permission.GroupOwner,
        Permission.GroupAdmin,
        Permission.User,
        Permission.GroupBlack,
    }:
        return text_message("请检查输入的权限(64/32/16/0)")
    context = context_from_session(session)
    if context.chat_type != "group":
        return text_message("该指令只能在群聊中使用")
    target_group, is_cross_group = await _target_group(session, group)
    if target_group is None:
        return text_message("权限不足或没有找到目标群")
    required = Permission.BotAdmin if is_cross_group else Permission.GroupOwner
    if not await _authorized(session, required):
        return text_message("权限不足")

    targets = normalize_targets(member_id.result)
    actor_permission = await permission_checker.get_user_perm(context)
    failures: list[tuple[str, str]] = []
    for target in targets:
        current_permission = await _member_permission(target_group, target)
        if actor_permission < current_permission:
            failures.append((target, f"无法降级{target}({current_permission})"))
        elif current_permission >= Permission.BotAdmin:
            failures.append((target, "无法直接通过该指令修改BOT管理权限"))
        else:
            await _write_member_permission(target_group, target, perm.result)
    return text_message(_failure_summary(targets, failures))


modify_group_command = Alconna(
    "修改群权限",
    Args["perm", int],
    Option("--group", Args["group_id", int], alias=["-g", "群"]),
    meta=CommandMeta(
        "修改群权限等级",
        usage="修改群权限 <0|1|2|3> [--group <群号>]",
        compact=True,
    ),
)


@command.on(modify_group_command)
async def change_group_perm(
    session: Session,
    perm: Match[int],
    group: Query[int] = Query("group.group_id", None),
):
    if not await _authorized(session, Permission.BotAdmin):
        return text_message("权限不足")
    target_group, _ = await _target_group(session, group)
    if target_group is None:
        return text_message("没有找到目标群")
    if perm.result not in {
        Permission.InactiveGroup,
        Permission.ActiveGroup,
        Permission.VipGroup,
        Permission.TestGroup,
    }:
        return text_message("请检查输入的群权限(3/2/1/0)")
    group_perm, _, _ = _tables()
    await _database().insert_or_update(
        group_perm,
        {
            "group_id": _database_id(target_group),
            "group_name": target_group,
            "active": True,
            "perm": perm.result,
        },
        [group_perm.group_id == _database_id(target_group)],
    )
    return text_message(f"已修改群{target_group}权限为{perm.result}")


modify_group_type_command = Alconna(
    "修改群权限类型",
    Args["permission_type", "admin|default"],
    Option("--group", Args["group_id", int], alias=["-g", "群"]),
    meta=CommandMeta(
        "修改群成员权限同步策略",
        usage="修改群权限类型 <admin|default> [--group <群号>]",
        compact=True,
    ),
)


@command.on(modify_group_type_command)
async def change_group_perm_type(
    session: Session,
    permission_type: Match[str],
    group: Query[int] = Query("group.group_id", None),
):
    if not await _authorized(session, Permission.BotAdmin):
        return text_message("权限不足")
    target_group, _ = await _target_group(session, group)
    if target_group is None:
        return text_message("没有找到目标群")
    _, group_setting, _ = _tables()
    await _database().insert_or_update(
        group_setting,
        {
            "group_id": _database_id(target_group),
            "permission_type": permission_type.result,
        },
        [group_setting.group_id == _database_id(target_group)],
    )
    return text_message(f"已修改群{target_group}权限类型为{permission_type.result}")


@command.on(
    Alconna(
        "VIP群列表",
        meta=CommandMeta("查询 VIP 群列表", compact=True),
    )
)
async def get_vg_list(session: Session):
    context = context_from_session(session)
    if context.chat_type != "private":
        return text_message(_MASTER_PRIVATE_ONLY)
    if not await permission_checker.require_perm(context, Permission.Master):
        return text_message("权限不足")
    group_perm, _, _ = _tables()
    select = _select()
    rows = await _database().fetch_all(
        select(group_perm.group_id, group_perm.group_name).where(
            group_perm.perm == Permission.VipGroup
        )
    )
    groups = [
        f"{_row_value(row)}({row[1]})"  # type: ignore[index]
        for row in rows
    ]
    return text_message(
        "当前没有VIP群~" if not groups else "VIP群列表:\n" + "\n".join(groups)
    )


permission_list_command = Alconna(
    "权限列表",
    Option("--group", Args["group_id", int], alias=["-g", "群"]),
    meta=CommandMeta("查询群成员权限", compact=True),
)
permission_list_command.shortcut(
    "perm list",
    {"command": "权限列表", "fuzzy": True, "prefix": False},
)


@command.on(permission_list_command)
async def get_perm_list(
    session: Session,
    group: Query[int] = Query("group.group_id", None),
):
    context = context_from_session(session)
    if context.chat_type == "group":
        target_group = str(group.result) if group.available else context.channel_id
        if target_group != context.channel_id:
            return text_message("群内只能查询当前群")
        if not await permission_checker.require_group_perm(
            context, Permission.ActiveGroup
        ) or not await permission_checker.require_perm(context, Permission.GroupAdmin):
            return text_message("权限不足")
        target_context = context
    elif context.chat_type == "private":
        if not await permission_checker.require_perm(context, Permission.Master):
            return text_message("权限不足")
        if not group.available:
            return text_message("Master 私聊查询请提供 --group <群号>")
        target_group = str(group.result)
        target_context = replace(
            context,
            chat_type="group",
            channel_id=target_group,
        )
    else:
        return text_message("该指令仅支持群聊或 Master 私聊执行")
    _, _, member_perm = _tables()
    select = _select()
    rows = await _database().fetch_all(
        select(member_perm.qq, member_perm.perm).where(
            member_perm.group_id == _database_id(target_group),
            member_perm.perm != Permission.User,
        )
    )
    entries = [f"{row[0]}: {row[1]}" for row in rows]
    group_level = await permission_checker.get_group_perm(target_context)
    result = f"群{target_group}权限等级: {group_level}"
    if entries:
        result += "\n" + "\n".join(entries)
    return text_message(result)


global_black_command = Alconna(
    "全局黑",
    Args["action", "添加|删除"],
    Args["member_id", MultiVar(str)],
    meta=CommandMeta("增删全局黑名单", compact=True),
)


@command.on(global_black_command)
async def change_global_black(
    session: Session,
    action: Match[str],
    member_id: Match[tuple[str, ...]],
):
    if not await _authorized(session, Permission.BotAdmin):
        return text_message("权限不足")
    targets = normalize_targets(member_id.result)
    black_list = await _global_black_ids()
    failures: list[tuple[str, str]] = []
    admin_ids = await _bot_admin_ids()
    master_id = permission_checker.registry.master_id
    for target in targets:
        if action.result == "添加":
            if target in admin_ids or target == master_id:
                failures.append((target, "无法修改BOT管理/Master的权限哦~"))
            elif target in black_list:
                failures.append((target, f"{target}已经在全局黑名单内!"))
            else:
                await _write_member_permission(0, target, Permission.GlobalBlack)
        elif target not in black_list:
            failures.append((target, f"{target}不在全局黑名单内!"))
        else:
            await _delete_member_permission(0, target)
    return text_message(_failure_summary(targets, failures))


@command.on(Alconna("全局黑名单列表", meta=CommandMeta("查询全局黑名单", compact=True)))
async def get_global_black_list(session: Session):
    context = context_from_session(session)
    if context.chat_type != "private":
        return text_message(_MASTER_PRIVATE_ONLY)
    if not await permission_checker.require_perm(context, Permission.Master):
        return text_message("权限不足")
    values = sorted(await _global_black_ids())
    return text_message(
        "全局黑名单为空哦~" if not values else "全局黑名单:\n" + "\n".join(values)
    )


bot_admin_command = Alconna(
    "BOT管理",
    Args["action", "添加|删除"],
    Args["member_id", MultiVar(str)],
    meta=CommandMeta("增删 BOT 管理员", compact=True),
)


@command.on(bot_admin_command)
async def change_bot_admin(
    session: Session,
    action: Match[str],
    member_id: Match[tuple[str, ...]],
):
    if not await _authorized(session, Permission.Master):
        return text_message("权限不足")
    targets = normalize_targets(member_id.result)
    admin_ids = await _bot_admin_ids()
    failures: list[tuple[str, str]] = []
    for target in targets:
        if action.result == "添加":
            if target in admin_ids:
                failures.append((target, f"{target}已经是BOT管理啦!"))
            else:
                await _write_member_permission(0, target, Permission.BotAdmin)
        elif target not in admin_ids:
            failures.append((target, f"{target}还不是BOT管理哦!"))
        else:
            await _delete_member_permission(0, target)
    return text_message(_failure_summary(targets, failures))


@command.on(Alconna("BOT管理列表", meta=CommandMeta("查询 BOT 管理员", compact=True)))
async def get_bot_admins_list(session: Session):
    context = context_from_session(session)
    if context.chat_type != "private":
        return text_message(_MASTER_PRIVATE_ONLY)
    if not await permission_checker.require_perm(context, Permission.Master):
        return text_message("权限不足")
    values = sorted(await _bot_admin_ids())
    return text_message(
        "当前还没有BOT管理哦~" if not values else "BOT管理列表:\n" + "\n".join(values)
    )


@plugin.listen(GuildMemberRemovedEvent)
async def auto_delete_member_permission(event: GuildMemberRemovedEvent):
    if not event.guild or not event.user:
        return
    previous = await _member_permission(event.guild.id, event.user.id)
    await _delete_member_permission(event.guild.id, event.user.id)
    if previous < Permission.GroupAdmin or not event.channel:
        return
    session = Session(event.account, event)
    await session.send(
        text_message(
            f"已自动删除退群成员{event.user.name or event.user.id}({event.user.id})的权限"
        )
    )


@plugin.listen(GuildMemberAddedEvent)
async def auto_add_member_permission(event: GuildMemberAddedEvent):
    if not event.guild or not event.user:
        return
    group_id = event.guild.id
    permission_type = await _permission_type(group_id)
    permission: int | None = None
    if permission_type == "admin":
        permission = Permission.GroupAdmin
    elif permission_checker.registry.master_id == event.user.id:
        permission = Permission.Master
    elif event.user.id in await _bot_admin_ids():
        permission = Permission.BotAdmin
    if permission is not None:
        await _write_member_permission(group_id, event.user.id, permission)
        if event.channel and permission == Permission.GroupAdmin:
            await Session(event.account, event).send(
                text_message(
                    f"已自动修改成员{event.user.name or event.user.id}({event.user.id})的权限为32"
                )
            )


@plugin.listen(GuildMemberUpdatedEvent)
async def auto_change_member_permission(event: GuildMemberUpdatedEvent):
    if not event.guild or not event.user:
        return
    if event.user.id == permission_checker.registry.master_id:
        return
    if event.user.id in await _bot_admin_ids():
        return
    if await _permission_type(event.guild.id) == "admin":
        return

    roles = {
        str(role.id).lower()
        for role in getattr(event.member, "roles", ())
        if getattr(role, "id", None)
    }
    if "owner" in roles or "群主" in roles:
        permission = Permission.GroupOwner
    elif roles.intersection({"admin", "administrator", "管理员"}):
        permission = Permission.GroupAdmin
    else:
        permission = Permission.User
    await _write_member_permission(event.guild.id, event.user.id, permission)
    if permission == Permission.User:
        logger.info(
            "成员 {} 在群 {} 的平台管理权限已降为普通成员；待人工确认 Tenko 权限",
            event.user.id,
            event.guild.id,
        )
    elif event.channel:
        await Session(event.account, event).send(
            text_message(
                f"检测到群管理权限变动\n已自动修改{event.user.name or event.user.id}"
                f"({event.user.id})权限为{permission}"
            )
        )


@plugin.listen(InternalEvent)
async def log_unmapped_membership_capability(event: InternalEvent):
    # The OneBot adapter has no Satori event for some membership capabilities.
    # Keep an explicit log until the NapCat capability mapping is confirmed;
    # do not silently discard the incoming internal event.
    logger.warning(
        "收到未映射的成员管理能力事件，待 NapCat capability 确认: {}",
        getattr(event._origin, "_type", None),
    )
