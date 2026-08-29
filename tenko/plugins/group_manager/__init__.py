from __future__ import annotations

from typing import Any

from arclet.alconna import Alconna, Args, CommandMeta, Option
from arclet.entari import Session, command, plugin
from arclet.entari.command import Query
from arclet.entari.plugin import PluginRole

from tenko.host.perm import Permission, PermissionChecker
from tenko.plugins._common import context_from_session, text_message


plugin.metadata(
    "群管理",
    PluginRole.NORMAL,
    author=["13"],
    version="0.1.0",
    description="查询 Tenko 的群设置；平台管理动作由 capability-aware service 负责。",
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


# 群禁言、撤回、精华、邀请和退群均依赖平台 capability，本迁移阶段不注册这些动作。
