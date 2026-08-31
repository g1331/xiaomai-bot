from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

from arclet.alconna import Alconna, Args, CommandMeta, Field, MultiVar, Option
from arclet.entari import MessageChain, Session, command, plugin
from arclet.entari.command import Match, Query
from arclet.entari.event.base import (
    GuildMemberAddedEvent,
    GuildMemberRemovedEvent,
    GuildMemberUpdatedEvent,
    InternalEvent,
)
from arclet.entari.config import EntariConfig
from arclet.entari.plugin import PluginRole
from loguru import logger
from satori import Image

from tenko.db.errors import DatabaseUnavailableError
from tenko.host.actions import ActionServiceError, action_service
from tenko.host.perm import Permission, PermissionChecker
from tenko.plugins._common import (
    context_from_session,
    normalize_targets,
    send_private_message,
    text_message,
)
from tenko.render import RenderService
from tenko.render import render_or_none


plugin.metadata(
    "权限管理",
    PluginRole.NORMAL,
    author=["13"],
    version="0.1.0",
    description="管理 Tenko 的成员权限、群权限和权限同步。",
    classifier=["required"],
)
# Entari 0.18.6 的构造函数没有 default_switch 字段。将兼容性标记保留在原生
# metadata 上，供 host/plugins.py 和 inspectors 使用。
plugin.get_plugin().metadata.default_switch = True


permission_checker = PermissionChecker()
_MASTER_PRIVATE_ONLY = "该指令仅支持 Master 私聊执行"
_notify_group_id: str | None = None


def configure_notify_group(group_id: str | int | None) -> None:
    """设置通知群保护的目标；空值表示不启用该保护。"""

    global _notify_group_id
    _notify_group_id = (
        None if group_id is None or str(group_id) == "" else str(group_id)
    )


def _is_notify_group(group_id: str) -> bool:
    return _notify_group_id is not None and group_id == _notify_group_id


def _member_repository():
    from tenko.db.repositories import member_perm_repository

    return member_perm_repository


def _group_repository():
    from tenko.db.repositories import group_perm_repository

    return group_perm_repository


def _setting_repository():
    from tenko.db.repositories import group_setting_repository

    return group_setting_repository


async def _member_permission(group_id: str | int, user_id: str | int) -> int:
    result = await _member_repository().get_permission(group_id, user_id)
    return Permission.User if result is None else int(result)


async def _bot_admin_ids() -> set[str]:
    return {str(value) for value in await _member_repository().list_bot_admins()}


async def _global_black_ids() -> set[str]:
    return {str(value) for value in await _member_repository().list_global_blacklist()}


async def _permission_type(group_id: str | int) -> str:
    result = await _setting_repository().get(group_id)
    return (
        "default"
        if result is None or result.permission_type is None
        else str(result.permission_type)
    )


async def _write_member_permission(
    group_id: str | int, user_id: str | int, permission: int
) -> None:
    await _member_repository().set_permission(group_id, user_id, int(permission))


async def _delete_member_permission(group_id: str | int, user_id: str | int) -> None:
    await _member_repository().delete_permission(group_id, user_id)


async def _vip_groups():
    return await _group_repository().list_vip()


async def _group_member_permissions(group_id: str | int):
    return await _member_repository().list_group_permissions(group_id)


async def _target_member(
    session: Session, group_id: str, user_id: str
) -> object | None:
    account = getattr(session, "account", None)
    if account is None:
        raise ActionServiceError("当前会话没有可用账号，无法确认群成员身份")
    return await action_service.get_group_member(account, group_id, user_id)


async def _target_members(session: Session, group_id: str) -> tuple[object, ...]:
    account = getattr(session, "account", None)
    if account is None:
        raise ActionServiceError("当前会话没有可用账号，无法读取群成员列表")
    return await action_service.list_group_members(account, group_id)


def _member_id(member: object) -> str:
    if isinstance(member, Mapping):
        value = member.get("user_id", member.get("id"))
    else:
        value = getattr(member, "user_id", None)
        if value is None:
            user = getattr(member, "user", None)
            value = getattr(user, "id", None)
        if value is None:
            value = getattr(member, "id", None)
    if value is None or not str(value):
        raise ValueError("群成员列表缺少用户 ID")
    return str(value)


def _member_permission_from_platform(member: object) -> int:
    level = action_service._management_level(member)
    if level is None or level < Permission.GroupAdmin:
        return Permission.User
    return (
        Permission.GroupOwner
        if level >= Permission.GroupOwner
        else Permission.GroupAdmin
    )


def _superuser_ids(account: object) -> tuple[str, ...]:
    if not EntariConfig._inited:
        return ()
    configured = getattr(
        getattr(EntariConfig.instance, "basic", None), "superusers", {}
    )
    platform = getattr(account, "platform", "onebot")
    return tuple(str(value) for value in configured.get(platform, ()))


def _permission_demotion_notice(event: GuildMemberUpdatedEvent) -> str:
    group_id = getattr(getattr(event, "guild", None), "id", "未知群")
    user = getattr(event, "user", None)
    user_id = getattr(user, "id", "未知成员")
    name = getattr(user, "name", None) or user_id
    return (
        "检测到群管理权限变动\n"
        f"{name}({user_id})->16\n"
        "Tenko 权限暂不自动修改，请人工确认；如需修改请使用指令 "
        f"/修改权限 16 {user_id}（群 {group_id}）"
    )


async def _notify_permission_demotion(event: GuildMemberUpdatedEvent) -> None:
    notice = _permission_demotion_notice(event)
    if event.channel:
        try:
            await Session(event.account, event).send(text_message(notice))
        except Exception:
            logger.exception(
                "管理员降级提示发送失败: group={} user={}",
                getattr(getattr(event, "guild", None), "id", None),
                getattr(getattr(event, "user", None), "id", None),
            )
        return

    session = Session(event.account, event)
    for reviewer_id in _superuser_ids(event.account):
        await send_private_message(session, reviewer_id, notice)


def _database_error_message(error: BaseException, *, action: str) -> object:
    logger.warning("权限数据库不可用，{}未执行: {}", action, error)
    return text_message(f"数据库暂不可用，{action}未执行")


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
    """返回目标群 ID，以及它是否不同于当前群。"""

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


def _list_data(
    title: str,
    subtitle: str,
    badge: str,
    summary: str,
    items: tuple[dict[str, object], ...],
    empty_text: str,
) -> dict[str, object]:
    return {
        "title": title,
        "subtitle": subtitle,
        "badge": badge,
        "summary": summary,
        "items": items,
        "item_count": len(items),
        "empty_text": empty_text,
    }


async def _render_list(
    render_service: RenderService, data: dict[str, object]
) -> MessageChain | None:
    image = await render_or_none(
        render_service,
        "render_template",
        "list.html",
        data,
    )
    if image is None:
        return None
    return MessageChain(Image.of(raw=image, mime="image/jpeg"))


def build_vip_groups_data(rows) -> dict[str, object]:
    items = tuple(
        {
            "number": index,
            "name": f"{row.group_id}({row.group_name})",
            "meta": "VIP 群",
            "detail": f"群号：{row.group_id}",
            "badge": "VIP",
        }
        for index, row in enumerate(rows, 1)
    )
    return _list_data(
        "VIP 群列表",
        "Master 私聊 · 已授权的群组",
        "VIP",
        f"共 {len(items)} 个 VIP 群",
        items,
        "当前没有VIP群~",
    )


def build_permission_list_data(
    target_group: str, group_level: int, rows
) -> dict[str, object]:
    entries = tuple(row for row in rows if row.perm != Permission.User)
    items = tuple(
        {
            "number": index,
            "name": str(row.qq),
            "meta": f"权限等级：{row.perm}",
            "detail": f"群{target_group}成员权限",
            "badge": str(row.perm),
        }
        for index, row in enumerate(entries, 1)
    )
    return _list_data(
        "权限列表",
        f"群{target_group} · 成员权限",
        f"群 {target_group}",
        f"群{target_group}权限等级: {group_level}",
        items,
        "暂无额外权限成员",
    )


def build_global_blacklist_data(values) -> dict[str, object]:
    items = tuple(
        {
            "number": index,
            "name": str(value),
            "meta": "全局黑名单成员",
            "detail": "该成员在所有群组中受限",
            "badge": "黑名单",
        }
        for index, value in enumerate(values, 1)
    )
    return _list_data(
        "全局黑名单",
        "Master 私聊 · 全局权限限制",
        "BLACK",
        f"共 {len(items)} 名成员",
        items,
        "全局黑名单为空哦~",
    )


def build_bot_admins_data(values) -> dict[str, object]:
    items = tuple(
        {
            "number": index,
            "name": str(value),
            "meta": "BOT 管理员",
            "detail": "可执行受授权的机器人管理操作",
            "badge": "ADMIN",
        }
        for index, value in enumerate(values, 1)
    )
    return _list_data(
        "BOT 管理列表",
        "Master 私聊 · Tenko 管理权限",
        "ADMIN",
        f"共 {len(items)} 名 BOT 管理员",
        items,
        "当前还没有BOT管理哦~",
    )


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
        try:
            current_permission = await _member_permission(target_group, target)
            if actor_permission < current_permission:
                failures.append((target, f"无法降级{target}({current_permission})"))
            elif current_permission >= Permission.BotAdmin:
                failures.append((target, "无法直接通过该指令修改BOT管理权限"))
            elif await _target_member(session, target_group, target) is None:
                failures.append((target, f"没有在群{target_group}找到群成员"))
            else:
                await _write_member_permission(target_group, target, perm.result)
        except DatabaseUnavailableError as error:
            logger.warning("成员 {} 的权限修改未执行，数据库不可用: {}", target, error)
            failures.append((target, "数据库暂不可用，未写入权限"))
        except ActionServiceError as error:
            logger.warning("成员 {} 的群成员身份确认失败: {}", target, error)
            failures.append((target, f"无法确认{target}是否在群内"))
        except ValueError as error:
            failures.append((target, str(error)))
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
    if _is_notify_group(target_group):
        return text_message(f"无法通过该指令修改通知群({target_group})权限!")
    try:
        await _group_repository().set(
            target_group,
            perm.result,
            group_name=target_group,
            active=True,
        )
    except DatabaseUnavailableError as error:
        return _database_error_message(error, action="修改群权限")
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
    if _is_notify_group(target_group):
        return text_message(f"无法通过该指令修改通知群({target_group})权限!")
    try:
        members = await _target_members(session, target_group)
        await _setting_repository().set_permission_type(
            target_group, permission_type.result
        )
        for member in members:
            member_id = _member_id(member)
            current_permission = await _member_permission(target_group, member_id)
            if permission_type.result == "admin":
                if current_permission < Permission.GroupAdmin:
                    await _write_member_permission(
                        target_group, member_id, Permission.GroupAdmin
                    )
                continue
            if current_permission >= Permission.GroupOwner:
                continue
            target_permission = _member_permission_from_platform(member)
            if current_permission != target_permission:
                await _write_member_permission(
                    target_group, member_id, target_permission
                )
    except DatabaseUnavailableError as error:
        return _database_error_message(error, action="修改群权限类型")
    except ActionServiceError as error:
        logger.warning("群 {} 的成员权限同步未完成: {}", target_group, error)
        return text_message(f"无法读取群{target_group}成员，未完成权限同步")
    except ValueError as error:
        return text_message(f"群{target_group}成员数据无效，未完成权限同步: {error}")
    return text_message(f"已修改群{target_group}权限类型为{permission_type.result}")


@command.on(
    Alconna(
        "VIP群列表",
        meta=CommandMeta("查询 VIP 群列表", compact=True),
    )
)
async def get_vg_list(session: Session, *, render_service: RenderService):
    context = context_from_session(session)
    if context.chat_type != "private":
        return text_message(_MASTER_PRIVATE_ONLY)
    if not await permission_checker.require_perm(context, Permission.Master):
        return text_message("权限不足")
    try:
        rows = await _vip_groups()
    except DatabaseUnavailableError as error:
        return _database_error_message(error, action="查询 VIP 群列表")
    groups = [f"{row.group_id}({row.group_name})" for row in rows]
    result = "当前没有VIP群~" if not groups else "VIP群列表:\n" + "\n".join(groups)
    if not groups:
        return text_message(result)
    image = await _render_list(render_service, build_vip_groups_data(rows))
    return image if image is not None else text_message(result)


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
    *,
    render_service: RenderService,
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
    try:
        rows = await _group_member_permissions(target_group)
    except DatabaseUnavailableError as error:
        return _database_error_message(error, action="查询成员权限")
    entries = [f"{row.qq}: {row.perm}" for row in rows if row.perm != Permission.User]
    group_level = await permission_checker.get_group_perm(target_context)
    result = f"群{target_group}权限等级: {group_level}"
    if entries:
        result += "\n" + "\n".join(entries)
    image = await _render_list(
        render_service,
        build_permission_list_data(target_group, group_level, rows),
    )
    return image if image is not None else text_message(result)


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
    try:
        black_list = await _global_black_ids()
        admin_ids = await _bot_admin_ids()
    except DatabaseUnavailableError as error:
        return _database_error_message(error, action="修改全局黑名单")
    failures: list[tuple[str, str]] = []
    master_id = permission_checker.registry.master_id
    for target in targets:
        if action.result == "添加":
            if target in admin_ids or target == master_id:
                failures.append((target, "无法修改BOT管理/Master的权限哦~"))
            elif target in black_list:
                failures.append((target, f"{target}已经在全局黑名单内!"))
            else:
                try:
                    await _write_member_permission(0, target, Permission.GlobalBlack)
                except DatabaseUnavailableError as error:
                    logger.warning("全局黑名单写入失败: {}", error)
                    failures.append((target, "数据库暂不可用，未写入权限"))
        elif target not in black_list:
            failures.append((target, f"{target}不在全局黑名单内!"))
        else:
            try:
                await _delete_member_permission(0, target)
            except DatabaseUnavailableError as error:
                logger.warning("全局黑名单删除失败: {}", error)
                failures.append((target, "数据库暂不可用，未删除权限"))
    return text_message(_failure_summary(targets, failures))


@command.on(Alconna("全局黑名单列表", meta=CommandMeta("查询全局黑名单", compact=True)))
async def get_global_black_list(session: Session, *, render_service: RenderService):
    context = context_from_session(session)
    if context.chat_type != "private":
        return text_message(_MASTER_PRIVATE_ONLY)
    if not await permission_checker.require_perm(context, Permission.Master):
        return text_message("权限不足")
    try:
        values = sorted(await _global_black_ids())
    except DatabaseUnavailableError as error:
        return _database_error_message(error, action="查询全局黑名单")
    result = "全局黑名单为空哦~" if not values else "全局黑名单:\n" + "\n".join(values)
    if not values:
        return text_message(result)
    image = await _render_list(render_service, build_global_blacklist_data(values))
    return image if image is not None else text_message(result)


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
    try:
        admin_ids = await _bot_admin_ids()
    except DatabaseUnavailableError as error:
        return _database_error_message(error, action="修改 BOT 管理员")
    failures: list[tuple[str, str]] = []
    for target in targets:
        if action.result == "添加":
            if target in admin_ids:
                failures.append((target, f"{target}已经是BOT管理啦!"))
            else:
                try:
                    await _write_member_permission(0, target, Permission.BotAdmin)
                except DatabaseUnavailableError as error:
                    logger.warning("BOT 管理员写入失败: {}", error)
                    failures.append((target, "数据库暂不可用，未写入权限"))
        elif target not in admin_ids:
            failures.append((target, f"{target}还不是BOT管理哦!"))
        else:
            try:
                await _delete_member_permission(0, target)
            except DatabaseUnavailableError as error:
                logger.warning("BOT 管理员删除失败: {}", error)
                failures.append((target, "数据库暂不可用，未删除权限"))
    return text_message(_failure_summary(targets, failures))


@command.on(Alconna("BOT管理列表", meta=CommandMeta("查询 BOT 管理员", compact=True)))
async def get_bot_admins_list(session: Session, *, render_service: RenderService):
    context = context_from_session(session)
    if context.chat_type != "private":
        return text_message(_MASTER_PRIVATE_ONLY)
    if not await permission_checker.require_perm(context, Permission.Master):
        return text_message("权限不足")
    try:
        values = sorted(await _bot_admin_ids())
    except DatabaseUnavailableError as error:
        return _database_error_message(error, action="查询 BOT 管理员")
    result = (
        "当前还没有BOT管理哦~" if not values else "BOT管理列表:\n" + "\n".join(values)
    )
    if not values:
        return text_message(result)
    image = await _render_list(render_service, build_bot_admins_data(values))
    return image if image is not None else text_message(result)


@plugin.listen(GuildMemberRemovedEvent)
async def auto_delete_member_permission(event: GuildMemberRemovedEvent):
    if not event.guild or not event.user:
        return
    try:
        previous = await _member_permission(event.guild.id, event.user.id)
        await _delete_member_permission(event.guild.id, event.user.id)
    except DatabaseUnavailableError as error:
        logger.warning("退群成员 {} 的权限清理失败: {}", event.user.id, error)
        return
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
    try:
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
    except DatabaseUnavailableError as error:
        logger.warning("新成员 {} 的权限同步失败: {}", event.user.id, error)


@plugin.listen(GuildMemberUpdatedEvent)
async def auto_change_member_permission(event: GuildMemberUpdatedEvent):
    if not event.guild or not event.user:
        return
    if event.user.id == permission_checker.registry.master_id:
        return
    try:
        if event.user.id in await _bot_admin_ids():
            return
        if await _permission_type(event.guild.id) == "admin":
            return

        previous_permission = await _member_permission(event.guild.id, event.user.id)

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
    except DatabaseUnavailableError as error:
        logger.warning("成员 {} 的权限变更同步失败: {}", event.user.id, error)
        return

    if permission == Permission.User and previous_permission >= Permission.GroupAdmin:
        logger.info(
            "成员 {} 在群 {} 的平台管理权限已降为普通成员；待人工确认 Tenko 权限",
            event.user.id,
            event.guild.id,
        )
        await _notify_permission_demotion(event)
        return

    try:
        await _write_member_permission(event.guild.id, event.user.id, permission)
    except DatabaseUnavailableError as error:
        logger.warning("成员 {} 的权限变更同步失败: {}", event.user.id, error)
        return

    if permission != Permission.User and event.channel:
        await Session(event.account, event).send(
            text_message(
                f"检测到群管理权限变动\n已自动修改{event.user.name or event.user.id}"
                f"({event.user.id})权限为{permission}"
            )
        )


@plugin.listen(InternalEvent)
async def log_unmapped_membership_capability(event: InternalEvent):
    # OneBot 适配器对于某些成员管理能力没有对应的 Satori 事件。
    # 在 NapCat 能力映射得到确认前保留显式日志；不要静默丢弃收到的内部事件。
    logger.warning(
        "收到未映射的成员管理能力事件，待 NapCat capability 确认: {}",
        getattr(event._origin, "_type", None),
    )
