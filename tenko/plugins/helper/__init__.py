from __future__ import annotations

from arclet.alconna import Alconna, Args, CommandMeta
from arclet.alconna import command_manager
from arclet.entari import Session, command, plugin
from arclet.entari.command import Query
from arclet.entari.plugin import PluginRole

from tenko.host.perm import Permission, PermissionChecker
from tenko.plugins._common import context_from_session, text_message


plugin.metadata(
    "帮助系统",
    PluginRole.NORMAL,
    author=["13"],
    version="0.1.0",
    description="根据 Entari 当前注册命令生成帮助文本。",
    classifier=["required"],
)
# Entari 0.18.6 has no constructor field for default_switch.  Keep the
# compatibility marker on native metadata for host/plugins.py and inspectors.
plugin.get_plugin().metadata.default_switch = True


permission_checker = PermissionChecker()


help_command = Alconna(
    "帮助",
    Args["index?", int],
    meta=CommandMeta(
        "列出 Entari 已注册命令或查看单条命令详情",
        usage="帮助 [编号]",
        example="$帮助\n$帮助 1",
        compact=True,
    ),
)
help_command.shortcut("-help", command="帮助", prefix=True)
help_command.shortcut("-帮助", command="帮助", prefix=True)


def registered_commands():
    """Return the live command registry maintained by Alconna."""

    return [item for item in command_manager.get_commands() if not item.meta.hide]


def build_help(index: int | None = None) -> str:
    """Build help from native command registrations, without parsing text."""

    commands = registered_commands()
    if index is not None:
        if not 1 <= index <= len(commands):
            return "编号不在范围内~"
        return commands[index - 1].get_help()
    return command_manager.all_command_help(
        show_index=True,
        header="Tenko 已注册命令",
    )


@command.on(help_command)
async def helper(
    session: Session,
    index: Query[int] = Query("index", None),
):
    context = context_from_session(session)
    if not await permission_checker.require_group_perm(
        context, Permission.ActiveGroup
    ) or not await permission_checker.require_perm(context, Permission.User):
        return text_message("权限不足")
    value = index.result if index.available else None
    return text_message(build_help(value))
