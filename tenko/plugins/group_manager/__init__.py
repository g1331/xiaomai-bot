from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass, replace
from typing import Any

from arclet.alconna import Alconna, Args, CommandMeta, MultiVar, Option
from arclet.entari import Session, command, plugin
from arclet.entari.command import Match, Query
from arclet.entari.config import EntariConfig
from arclet.entari.event.base import GuildRequestEvent
from arclet.entari.plugin import PluginRole, collect_disposes
from loguru import logger
from satori import Text
from satori.element import At, Author, Element, Quote

from tenko.host.actions import (
    ActionPermissionDenied,
    ActionServiceError,
    action_service,
)
from tenko.context import MessageContext
from tenko.host.perm import Permission, PermissionChecker
from tenko.plugins._common import (
    action_error_message,
    context_from_session,
    report_action_error,
    text_message,
)


plugin.metadata(
    "群管理",
    PluginRole.NORMAL,
    author=["13"],
    version="0.1.0",
    description="查询群设置并通过宿主动作服务执行群管理操作。",
    classifier=["required"],
)
# Entari 0.18.6 has no constructor field for default_switch.  Keep the
# compatibility marker on native metadata for host/plugins.py and inspectors.
plugin.get_plugin().metadata.default_switch = True


permission_checker = PermissionChecker()
_database_warning_groups: set[str] = set()


INVITE_TIMEOUT_SECONDS = 60 * 60


@dataclass(slots=True)
class PendingInvite:
    """当前进程中等待管理员决定的 Satori 群邀请。"""

    request_id: str
    account: Any
    group_id: str
    group_name: str
    inviter_id: str
    inviter_name: str
    comment: str
    created_at: float
    notification_id: str | None = None
    notification_channel_id: str | None = None


pending_invites: dict[str, PendingInvite] = {}
invite_expiry_tasks: dict[str, asyncio.Task[None]] = {}


def _dispose_invite_state() -> None:
    for task in tuple(invite_expiry_tasks.values()):
        task.cancel()
    invite_expiry_tasks.clear()
    pending_invites.clear()


collect_disposes(_dispose_invite_state)


def _request_context(event: GuildRequestEvent):
    try:
        return MessageContext.from_event(event._origin)
    except (AttributeError, TypeError, ValueError):
        return None


async def _is_privileged_inviter(event: GuildRequestEvent) -> bool:
    context = _request_context(event)
    if context is None:
        return False
    try:
        return await permission_checker.require_perm(context, Permission.BotAdmin)
    except Exception:
        # 权限数据库属于旧系统的可选读取边界；读取失败时按普通邀请
        # 进入待审队列，不能因为权限查询异常自动放行邀请。
        logger.exception("Could not check group invite inviter permission")
        return False


def _reviewer_ids(account: Any) -> tuple[str, ...]:
    if not EntariConfig._inited:
        return ()
    configured = EntariConfig.instance.basic.superusers
    return tuple(str(value) for value in configured.get(account.platform, ()))


async def _send_reviewer_notice(
    pending: PendingInvite,
    text: str,
) -> None:
    protocol = pending.account.protocol
    send_private = getattr(protocol, "send_private_message", None)
    if not callable(send_private):
        logger.warning(
            "Pending invite {} recorded but protocol has no private message API",
            pending.request_id,
        )
        return
    reviewer_ids = _reviewer_ids(pending.account)
    if not reviewer_ids:
        logger.warning(
            "Pending invite {} recorded without configured superusers",
            pending.request_id,
        )
        return
    for reviewer_id in reviewer_ids:
        try:
            result = send_private(reviewer_id, [Text(text)])
            if inspect.isawaitable(result):
                result = await result
            items = tuple(result or ())
            if items and getattr(items[-1], "id", None) is not None:
                pending.notification_id = str(items[-1].id)
                pending.notification_channel_id = f"private:{reviewer_id}"
        except Exception:
            logger.exception(
                "Failed to notify superuser {} about pending invite {}",
                reviewer_id,
                pending.request_id,
            )


async def _apply_invite_decision(
    pending: PendingInvite,
    approved: bool,
    comment: str,
) -> None:
    protocol = pending.account.protocol
    approve = getattr(protocol, "guild_approve", None)
    if not callable(approve):
        raise RuntimeError("当前协议没有 guild_approve 群邀请审批 API")
    result = approve(pending.request_id, approved, comment)
    if inspect.isawaitable(result):
        await result


def _cancel_invite_expiry(request_id: str) -> None:
    task = invite_expiry_tasks.pop(request_id, None)
    if task is not None and not task.done():
        task.cancel()


async def _expire_invite(request_id: str) -> None:
    try:
        await asyncio.sleep(INVITE_TIMEOUT_SECONDS)
    except asyncio.CancelledError:
        return
    pending = pending_invites.get(request_id)
    if pending is None:
        return
    try:
        await _apply_invite_decision(
            pending,
            False,
            "拒绝了你的入群邀请!",
        )
    except Exception:
        logger.exception("Failed to auto-reject expired invite {}", request_id)
        invite_expiry_tasks.pop(request_id, None)
        return
    pending_invites.pop(request_id, None)
    invite_expiry_tasks.pop(request_id, None)
    await _send_reviewer_notice(
        pending,
        f"入群邀请 {request_id} 已超过 1 小时，已自动拒绝。",
    )


def _invite_notice(pending: PendingInvite) -> str:
    group = f"{pending.group_name}({pending.group_id})"
    inviter = f"{pending.inviter_name}({pending.inviter_id})"
    return (
        f"群邀请待审\n群: {group}\n邀请人: {inviter}\n"
        f"请求 ID: {pending.request_id}\n"
        f"请在 1 小时内使用 /同意邀请 {pending.request_id} 或 "
        f"/拒绝邀请 {pending.request_id} [理由] 处理。"
    )


@plugin.listen(GuildRequestEvent)
async def invited_event(event: GuildRequestEvent):
    """迁移旧版群邀请处理：管理员邀请自动同意，其余进入待审队列。"""

    request_id = getattr(getattr(event, "message", None), "id", None)
    group = getattr(event, "guild", None)
    inviter = getattr(event, "user", None)
    account = getattr(event, "account", None)
    if request_id is None or group is None or inviter is None or account is None:
        logger.warning("Ignore malformed guild request event: {}", event)
        return

    pending = PendingInvite(
        request_id=str(request_id),
        account=account,
        group_id=str(group.id),
        group_name=str(getattr(group, "name", None) or group.id),
        inviter_id=str(inviter.id),
        inviter_name=str(getattr(inviter, "name", None) or inviter.id),
        comment=str(getattr(getattr(event, "message", None), "content", "") or ""),
        created_at=asyncio.get_running_loop().time(),
    )
    if await _is_privileged_inviter(event):
        try:
            await _apply_invite_decision(pending, True, "已同意您的邀请~")
        except Exception:
            # 审批 action 失败时不能丢掉平台仍在等待的请求；保留到待审队列，
            # 同时把 action 错误记录下来，交给管理员稍后重试。
            logger.exception(
                "Failed to automatically approve privileged group invite: "
                "request={} group={}",
                pending.request_id,
                pending.group_id,
            )
        else:
            logger.info(
                "Automatically approved privileged group invite: request={} group={} "
                "inviter={}",
                pending.request_id,
                pending.group_id,
                pending.inviter_id,
            )
            return

    pending_invites[pending.request_id] = pending
    _cancel_invite_expiry(pending.request_id)
    invite_expiry_tasks[pending.request_id] = asyncio.create_task(
        _expire_invite(pending.request_id)
    )
    await _send_reviewer_notice(pending, _invite_notice(pending))
    logger.info(
        "Recorded pending group invite: request={} group={} inviter={}",
        pending.request_id,
        pending.group_id,
        pending.inviter_id,
    )


def _pending_invite(request_id: str) -> PendingInvite | None:
    return pending_invites.get(str(request_id).strip())


async def _can_review_invite(session: Session, pending: PendingInvite) -> bool:
    context = context_from_session(session)
    if context.chat_type == "group" and context.channel_id == pending.group_id:
        return await permission_checker.require_group_perm(
            context, Permission.ActiveGroup
        ) and await permission_checker.require_perm(context, Permission.GroupAdmin)
    # Bot 未入目标群时，只有超管能从私聊或其他群处理，避免把审批权
    # 意外扩大到任意群管理员；这是当前没有旧 test_group 配置时的明确边界。
    return await permission_checker.require_perm(context, Permission.Master)


invite_approve_command = Alconna(
    "同意邀请",
    Args["request_id", str],
    meta=CommandMeta(
        "同意待审群邀请",
        usage="同意邀请 <请求ID>",
        example="同意邀请 abc123",
        compact=False,
    ),
)
invite_approve_command.shortcut("同意", command="同意邀请", prefix=True)


@command.on(invite_approve_command)
async def approve_invite(session: Session, request_id: Match[str]):
    pending = _pending_invite(request_id.result)
    if pending is None:
        return text_message(f"未找到待审邀请: {request_id.result}")
    if not await _can_review_invite(session, pending):
        return text_message("权限不足")
    try:
        await _apply_invite_decision(pending, True, "已同意您的邀请~")
    except Exception as error:
        logger.exception("Failed to approve invite {}", pending.request_id)
        await report_action_error(error, session)
        return text_message("处理邀请失败，已通知开发者")
    pending_invites.pop(pending.request_id, None)
    _cancel_invite_expiry(pending.request_id)
    return text_message(f"已同意邀请 {pending.request_id}")


invite_reject_command = Alconna(
    "拒绝邀请",
    Args["request_id", str],
    Args["reason", MultiVar(str, "*")],
    meta=CommandMeta(
        "拒绝待审群邀请",
        usage="拒绝邀请 <请求ID> [理由]",
        example="拒绝邀请 abc123 非工作群",
        compact=False,
    ),
)
invite_reject_command.shortcut("拒绝", command="拒绝邀请", prefix=True)


@command.on(invite_reject_command)
async def reject_invite(
    session: Session,
    request_id: Match[str],
    reason: Match[tuple[str, ...]],
):
    pending = _pending_invite(request_id.result)
    if pending is None:
        return text_message(f"未找到待审邀请: {request_id.result}")
    if not await _can_review_invite(session, pending):
        return text_message("权限不足")
    comment = " ".join(reason.result).strip() if reason.available else ""
    comment = comment or "BOT拒绝了你的入群邀请!"
    try:
        await _apply_invite_decision(pending, False, comment)
    except Exception as error:
        logger.exception("Failed to reject invite {}", pending.request_id)
        await report_action_error(error, session)
        return text_message("处理邀请失败，已通知开发者")
    pending_invites.pop(pending.request_id, None)
    _cancel_invite_expiry(pending.request_id)
    return text_message(f"已拒绝邀请 {pending.request_id}")


pending_invites_command = Alconna(
    "待审邀请",
    meta=CommandMeta(
        "查看待审群邀请（仅超管）",
        usage="待审邀请",
        compact=True,
    ),
)


@command.on(pending_invites_command)
async def pending_invite_list(session: Session):
    context = context_from_session(session)
    if context.chat_type != "private":
        return text_message("该指令仅支持 Master 私聊执行")
    if not await permission_checker.require_perm(context, Permission.Master):
        return text_message("权限不足")
    if not pending_invites:
        return text_message("当前没有待审邀请")
    lines = [
        f"{pending.request_id}: {pending.group_name}({pending.group_id}) "
        f"邀请人 {pending.inviter_name}({pending.inviter_id})"
        for pending in pending_invites.values()
    ]
    return text_message("待审邀请:\n" + "\n".join(lines))


reset_capability_command = Alconna(
    "重置能力",
    Args["account_id?", int],
    meta=CommandMeta(
        "重置账号的平台能力学习状态（仅超管）",
        usage="重置能力 [账号]",
        example="重置能力\n重置能力 10001",
        compact=False,
    ),
)


@command.on(reset_capability_command)
async def reset_capability(
    session: Session,
    account_id: Query[int] = Query("account_id", None),
):
    context = context_from_session(session)
    if context.chat_type != "private":
        return text_message("该指令仅支持 Master 私聊执行")
    if not await permission_checker.require_perm(context, Permission.Master):
        return text_message("权限不足")
    target_account = (
        str(account_id.result) if account_id.available else context.account_id
    )
    reset_count = action_service.reset_capabilities(target_account)
    return text_message(
        f"已重置账号 {target_account} 的 {reset_count} 项平台能力学习状态"
    )


async def read_group_settings(group_id: str) -> dict[str, object]:
    """只读查询群设置；数据库不可用时返回旧默认值。"""

    from tenko.db.errors import DatabaseUnavailableError

    try:
        from tenko.db.repositories import (
            group_perm_repository,
            group_setting_repository,
        )

        setting_row = await group_setting_repository.get(group_id)
        permission_row = await group_perm_repository.get(group_id)
    except DatabaseUnavailableError as error:
        if group_id not in _database_warning_groups:
            _database_warning_groups.add(group_id)
            logger.warning(
                "群 {} 的设置数据库不可用，使用默认设置: {}", group_id, error
            )
        return {
            "frequency_limitation": True,
            "response_type": "random",
            "permission_type": "default",
            "permission": 1,
            "active": True,
        }

    return {
        "frequency_limitation": (
            True if setting_row is None else bool(setting_row.frequency_limitation)
        ),
        "response_type": (
            "random" if setting_row is None else str(setting_row.response_type)
        ),
        "permission_type": (
            "default" if setting_row is None else str(setting_row.permission_type)
        ),
        "permission": 1 if permission_row is None else int(permission_row.perm),
        "active": True if permission_row is None else bool(permission_row.active),
    }


def format_group_settings(group_id: str, settings: dict[str, object]) -> str:
    return (
        f"群{group_id}设置:\n"
        f"群权限: {settings['permission']}\n"
        f"群状态: {'启用' if settings['active'] else '停用'}\n"
        f"频率限制: {'开启' if settings['frequency_limitation'] else '关闭'}\n"
        f"响应账号策略: {settings['response_type']}\n"
        f"权限类型: {settings['permission_type']}"
    )


group_setting_command = Alconna(
    "群设置",
    Option(
        "--group",
        Args["group_id", int],
        alias=["-g", "群"],
        help_text="群内仅查询当前群；跨群查询需 Master 私聊",
    ),
    meta=CommandMeta(
        "只读查询群设置",
        usage="群设置 [--group <群号>]",
        compact=True,
    ),
)


@command.on(group_setting_command)
async def group_setting(
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
        ):
            return text_message("当前群不可用")
        if not await permission_checker.require_perm(context, Permission.GroupAdmin):
            return text_message("权限不足")
    elif context.chat_type == "private":
        if not await permission_checker.require_perm(context, Permission.Master):
            return text_message("权限不足")
        if not group.available:
            return text_message("Master 私聊查询请提供 --group <群号>")
        target_group = str(group.result)
    else:
        return text_message("该指令仅支持群聊或 Master 私聊执行")
    settings = await read_group_settings(target_group)
    return text_message(format_group_settings(target_group, settings))


def _walk(elements: list[Element] | tuple[Element, ...]):
    for element in elements:
        yield element
        yield from _walk(tuple(element.children))


def _origin_message_elements(session: Session) -> tuple[Element, ...]:
    origin = getattr(session.event, "_origin", None)
    message = getattr(origin, "message", None)
    if message is None:
        return ()
    return tuple(getattr(message, "message", ()))


def _quoted_message(session: Session) -> Quote | None:
    return next(
        (
            element
            for element in _walk(_origin_message_elements(session))
            if isinstance(element, Quote)
        ),
        None,
    )


def _quoted_user_id(quote: Quote | None) -> str | None:
    if quote is None:
        return None
    author = next(
        (
            element
            for element in _walk(tuple(quote.children))
            if isinstance(element, Author)
        ),
        None,
    )
    return author.id if author is not None else None


def _value_id(value: object) -> str | None:
    if isinstance(value, At):
        return value.id
    if isinstance(value, Quote):
        return _quoted_user_id(value)
    normalized = str(value).strip()
    if normalized.startswith("@"):
        normalized = normalized[1:]
    return normalized if normalized.isdigit() else None


def _moderation_target(
    arguments: tuple[object, ...],
    session: Session,
    option_minutes: Match[int],
) -> tuple[str | None, int | None, bool]:
    """解析文本/At/回复三种目标，并保留旧命令的分钟单位。"""

    target: str | None = None
    target_from_argument = False
    numeric_values: list[str] = []
    invalid = False
    for value in arguments:
        if isinstance(value, At | Quote):
            target = target or _value_id(value)
            target_from_argument = True
            if target is None:
                invalid = True
            continue
        candidate = _value_id(value)
        if candidate is None:
            invalid = True
        else:
            numeric_values.append(candidate)

    quoted_target = _quoted_user_id(_quoted_message(session))
    target = target or quoted_target
    if target is None and numeric_values:
        target = numeric_values[0]

    minutes: int | None = option_minutes.result if option_minutes.available else None
    if minutes is None:
        if (target_from_argument or quoted_target is not None) and numeric_values:
            minutes = int(numeric_values[-1])
        elif len(numeric_values) > 1:
            minutes = int(numeric_values[1])
    return target, minutes, invalid


def _action_error(error: ActionServiceError) -> str:
    return action_error_message(error)


async def _guard(session: Session, required: Permission = Permission.GroupAdmin):
    context = context_from_session(session)
    if context.chat_type != "group":
        return text_message("该指令只能在群聊中使用")
    try:
        await action_service.authorize(
            context,
            required,
            checker=permission_checker,
        )
    except ActionPermissionDenied as error:
        return text_message(action_error_message(error))
    return context


async def _target_has_management_permission(context, target_id: str) -> bool:
    target_context = replace(context, user_id=target_id, member_role=None)
    return await permission_checker.require_perm(target_context, Permission.GroupAdmin)


_MODERATION_ARGS = Args["arguments", MultiVar(object, "*")]


mute_command = Alconna(
    "禁言",
    _MODERATION_ARGS,
    Option("--time", Args["time", int], alias=["-t"], default=2),
    meta=CommandMeta(
        "禁言群成员（时长单位为分钟）",
        usage="禁言 [@成员|成员ID] [分钟] [-t <分钟>]",
        example="禁言 @123456 5",
        compact=False,
    ),
)


@command.on(mute_command)
async def mute(
    session: Session,
    arguments: Match[tuple[object, ...]],
    time: Match[int],
):
    checked = await _guard(session)
    if not hasattr(checked, "user_id"):
        return checked
    context = checked
    target_id, minutes, invalid = _moderation_target(arguments.result, session, time)
    if invalid or target_id is None:
        return text_message("请@成员、填写成员ID或回复目标消息")
    if minutes is None:
        minutes = 2
    if not 0 < minutes <= 30 * 24 * 60:
        return text_message("时间非法!范围(分钟): `0 < time <= 43200`")
    if target_id == context.account_id:
        return text_message("禁言bot?给你一棒槌!")
    if await _target_has_management_permission(context, target_id):
        return text_message("bot权限不足!(目标权限>=32)")
    try:
        await action_service.mute_member(
            context.account_id,
            context.channel_id,
            target_id,
            minutes * 60,
            context=context,
            permission_checker=permission_checker,
        )
    except ActionServiceError as error:
        await report_action_error(error, session)
        return text_message(_action_error(error))
    return text_message(f"已设置【{target_id}】{minutes}分钟的禁言!")


unmute_command = Alconna(
    "解禁",
    _MODERATION_ARGS,
    meta=CommandMeta(
        "解除群成员禁言",
        usage="解禁 [@成员|成员ID]（也可回复目标消息）",
        example="解禁 @123456",
        compact=False,
    ),
)


@command.on(unmute_command)
async def unmute(
    session: Session,
    arguments: Match[tuple[object, ...]],
):
    checked = await _guard(session)
    if not hasattr(checked, "user_id"):
        return checked
    context = checked
    target_id, _, invalid = _moderation_target(
        arguments.result, session, Match(None, False)
    )
    if invalid or target_id is None:
        return text_message("请@成员、填写成员ID或回复目标消息")
    try:
        await action_service.unmute_member(
            context.account_id,
            context.channel_id,
            target_id,
            context=context,
            permission_checker=permission_checker,
        )
    except ActionServiceError as error:
        await report_action_error(error, session)
        return text_message(_action_error(error))
    return text_message(f"已解禁{target_id}!")


unmute_self_command = Alconna(
    "解禁自己",
    meta=CommandMeta(
        "解除当前 BOT 在本群的禁言状态",
        usage="解禁自己",
        compact=True,
    ),
)


@command.on(unmute_self_command)
async def unmute_self(session: Session):
    checked = await _guard(session)
    if not hasattr(checked, "user_id"):
        return checked
    context = checked
    try:
        await action_service.unmute_member(
            context.account_id,
            context.channel_id,
            context.account_id,
            context=context,
            permission_checker=permission_checker,
        )
    except ActionServiceError as error:
        await report_action_error(error, session)
        return text_message(_action_error(error))
    return text_message("已解除本BOT在当前群的禁言状态!")


whole_mute_command = Alconna(
    "全体禁言",
    meta=CommandMeta("开启全体禁言", usage="全体禁言", compact=False),
)


@command.on(whole_mute_command)
async def mute_all(session: Session):
    checked = await _guard(session)
    if not hasattr(checked, "user_id"):
        return checked
    context = checked
    try:
        await action_service.mute_group(
            context.account_id,
            context.channel_id,
            True,
            context=context,
            permission_checker=permission_checker,
        )
    except ActionServiceError as error:
        await report_action_error(error, session)
        return text_message(_action_error(error))
    return text_message("开启全体禁言成功!")


whole_unmute_command = Alconna(
    "全体解禁",
    meta=CommandMeta("关闭全体禁言", usage="全体解禁", compact=False),
)


@command.on(whole_unmute_command)
async def unmute_all(session: Session):
    checked = await _guard(session)
    if not hasattr(checked, "user_id"):
        return checked
    context = checked
    try:
        await action_service.unmute_group(
            context.account_id,
            context.channel_id,
            context=context,
            permission_checker=permission_checker,
        )
    except ActionServiceError as error:
        await report_action_error(error, session)
        return text_message(_action_error(error))
    return text_message("关闭全体禁言成功!")


recall_command = Alconna(
    "撤回",
    meta=CommandMeta(
        "撤回回复的消息",
        usage="撤回（回复一条消息）",
        compact=False,
    ),
)


@command.on(recall_command)
async def recall(session: Session):
    checked = await _guard(session)
    if not hasattr(checked, "user_id"):
        return checked
    context = checked
    quote = _quoted_message(session)
    if quote is None or quote.id is None:
        return text_message("请回复需要撤回的消息")
    try:
        await action_service.delete_message(
            context.account_id,
            quote.id,
            channel_id=context.channel_id,
            context=context,
            permission_checker=permission_checker,
        )
    except ActionServiceError as error:
        await report_action_error(error, session)
        return text_message(_action_error(error))
    return None


essence_command = Alconna(
    "加精",
    Args["message_id?", str],
    meta=CommandMeta(
        "设置回复消息或指定消息为群精华",
        usage="加精 [消息ID]（或回复消息）",
        example="/加精 60001\n/设精（回复消息）",
        compact=False,
    ),
)
essence_command.shortcut("设精", command="加精", prefix=True)


@command.on(essence_command)
async def set_essence(
    session: Session,
    message_id: Query[str] = Query("message_id", None),
):
    checked = await _guard(session)
    if not hasattr(checked, "user_id"):
        return checked
    context = checked
    target_message_id = str(message_id.result).strip() if message_id.available else None
    if target_message_id is None:
        quote = _quoted_message(session)
        target_message_id = str(quote.id).strip() if quote and quote.id else None
    if not target_message_id or not target_message_id.isdigit():
        return text_message("请提供数字消息ID或回复需要加精的消息")
    try:
        await action_service.set_essence(
            context.account_id,
            target_message_id,
            context=context,
            permission_checker=permission_checker,
        )
    except ActionServiceError as error:
        await report_action_error(error, session)
        return text_message(_action_error(error))
    return text_message("加精成功")


kick_command = Alconna(
    "踢出",
    _MODERATION_ARGS,
    meta=CommandMeta(
        "踢出群成员",
        usage="踢出 [@成员|成员ID]（也可回复目标消息）",
        example="踢出 @123456",
        compact=False,
    ),
)


@command.on(kick_command)
async def kick(
    session: Session,
    arguments: Match[tuple[object, ...]],
):
    checked = await _guard(session)
    if not hasattr(checked, "user_id"):
        return checked
    context = checked
    target_id, _, invalid = _moderation_target(
        arguments.result, session, Match(None, False)
    )
    if invalid or target_id is None:
        return text_message("请@成员、填写成员ID或回复目标消息")
    if target_id == context.account_id:
        return text_message("不能踢出bot!")
    if await _target_has_management_permission(context, target_id):
        return text_message("bot权限不足!(目标权限>=32)")
    try:
        await action_service.kick_member(
            context.account_id,
            context.channel_id,
            target_id,
            context=context,
            permission_checker=permission_checker,
        )
    except ActionServiceError as error:
        await report_action_error(error, session)
        return text_message(_action_error(error))
    return text_message(f"已将{target_id}踢出群聊!")
