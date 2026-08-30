from __future__ import annotations

from dataclasses import replace
from typing import Any

from arclet.alconna import Alconna, Args, CommandMeta, MultiVar, Option
from arclet.entari import Session, command, plugin
from arclet.entari.command import Match, Query
from arclet.entari.plugin import PluginRole
from satori.element import At, Author, Element, Quote

from tenko.host.actions import (
    ActionAccountUnavailable,
    ActionCapabilityUnavailable,
    ActionExecutionError,
    ActionPermissionDenied,
    ActionServiceError,
    action_service,
)
from tenko.host.perm import Permission, PermissionChecker
from tenko.plugins._common import context_from_session, text_message


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


def _database() -> Any:
    from core.orm import orm

    return orm


def _tables():
    from core.orm.tables import GroupPerm, GroupSetting

    return GroupPerm, GroupSetting


def _select():
    """Load the legacy query builder only when the read-only query is used."""

    from sqlalchemy import select

    return select


def _row_value(row: object, index: int = 0) -> object | None:
    if row is None:
        return None
    try:
        return row[index]  # type: ignore[index]
    except (IndexError, KeyError, TypeError):
        return None


async def read_group_settings(group_id: str) -> dict[str, object]:
    """Read legacy group settings without creating or updating a row."""

    group_perm, group_setting = _tables()
    select = _select()
    database = _database()
    setting_row = await database.fetch_one(
        select(
            group_setting.frequency_limitation,
            group_setting.response_type,
            group_setting.permission_type,
        ).where(group_setting.group_id == int(group_id))
    )
    permission_row = await database.fetch_one(
        select(group_perm.perm, group_perm.active).where(
            group_perm.group_id == int(group_id)
        )
    )
    return {
        "frequency_limitation": (
            True if setting_row is None else bool(_row_value(setting_row, 0))
        ),
        "response_type": (
            "random" if setting_row is None else str(_row_value(setting_row, 1))
        ),
        "permission_type": (
            "default" if setting_row is None else str(_row_value(setting_row, 2))
        ),
        "permission": 1
        if permission_row is None
        else int(_row_value(permission_row, 0)),
        "active": True
        if permission_row is None
        else bool(_row_value(permission_row, 1)),
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
        help_text="查询指定群（跨群需要 BotAdmin）",
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
    if context.chat_type != "group":
        return text_message("该指令只能在群聊中使用")
    if not await permission_checker.require_group_perm(context, Permission.ActiveGroup):
        return text_message("当前群不可用")
    target_group = str(group.result) if group.available else context.channel_id
    required = (
        Permission.BotAdmin
        if target_group != context.channel_id
        else Permission.GroupAdmin
    )
    if not await permission_checker.require_perm(context, required):
        return text_message("权限不足")
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
    if isinstance(error, ActionPermissionDenied):
        return str(error)
    if isinstance(error, ActionAccountUnavailable):
        return f"账号不可用: {error}"
    if isinstance(error, ActionCapabilityUnavailable):
        return f"平台能力不可用: {error}"
    if isinstance(error, ActionExecutionError):
        return f"平台操作失败: {error}"
    return f"平台操作失败: {error}"


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
        return text_message(str(error))
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
        return text_message(_action_error(error))
    return None


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
        return text_message(_action_error(error))
    return text_message(f"已将{target_id}踢出群聊!")
