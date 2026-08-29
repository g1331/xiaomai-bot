from __future__ import annotations

from arclet.alconna import Alconna, CommandMeta, Option, store_true
from arclet.entari import Session, command, plugin
from arclet.entari.command import Query
from arclet.entari.plugin import PluginRole

from tenko.host.perm import Permission, PermissionChecker
from tenko.plugins._common import context_from_session, text_message


plugin.metadata(
    "状态查询",
    PluginRole.NORMAL,
    author=["13"],
    version="0.1.0",
    description="查询 Tenko 当前会话和原生插件注册状态。",
    classifier=["required"],
)
# Entari 0.18.6 has no constructor field for default_switch.  Keep the
# compatibility marker on native metadata for host/plugins.py and inspectors.
plugin.get_plugin().metadata.default_switch = True


permission_checker = PermissionChecker()


status_command = Alconna(
    "-bot",
    Option(
        "-t",
        alias=["--text"],
        action=store_true,
        default=False,
        help_text="使用文本输出（当前版本默认即为文本）",
    ),
    meta=CommandMeta(
        "查询 Tenko 运行状态",
        usage="-bot [-t]",
        example="-bot -t",
        compact=True,
    ),
)
status_command.shortcut("状态", command="-bot", prefix=True)


def build_status(context, plugin_count: int) -> str:
    location = (
        f"群聊 {context.channel_id}"
        if context.chat_type == "group"
        else f"私聊 {context.channel_id}"
        if context.chat_type == "private"
        else f"频道 {context.channel_id}"
    )
    return (
        "Tenko 状态\n"
        f"账号: {context.account_id}\n"
        f"会话: {location}\n"
        f"用户: {context.user_id}\n"
        f"已注册插件: {plugin_count}"
    )


@command.on(status_command)
async def status(
    session: Session,
    text_mode: Query[bool] = Query("text.value", False),
):
    context = context_from_session(session)
    if not await permission_checker.require_group_perm(
        context, Permission.ActiveGroup
    ) or not await permission_checker.require_perm(context, Permission.User):
        return text_message("权限不足")
    return text_message(build_status(context, len(plugin.get_plugins())))
