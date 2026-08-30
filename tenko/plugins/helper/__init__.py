from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from arclet.alconna import Alconna, Args, CommandMeta
from arclet.alconna import command_manager
from arclet.entari import MessageChain, Session, command, plugin
from arclet.entari.command import Query
from arclet.entari.plugin import PluginRole, get_plugins
from satori import Image

from tenko.host.features import feature_service
from tenko.host.perm import Permission, PermissionChecker
from tenko.host.plugins import PluginInfo, PluginRuntime
from tenko.plugins._common import context_from_session, text_message
from tenko.plugins.render import RenderService  # entari: plugin
from tenko.render import render_or_none


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
plugin_runtime = PluginRuntime()

_HELP_SECTIONS = (
    ("required", "内置插件", "系统必需功能"),
    ("available", "运行插件", "当前可用功能"),
    ("unavailable", "维护插件", "暂不可用功能"),
)


help_command = Alconna(
    "帮助",
    Args["index?", int],
    meta=CommandMeta(
        "列出 Entari 已注册命令或查看单条命令详情",
        hide_shortcut=True,
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


def _native_plugin(info: PluginInfo):
    names = set(info.lookup_names)
    return next(
        (item for item in get_plugins(subplugged=True) if item.id in names), None
    )


def _help_plugins() -> tuple[tuple[PluginInfo, object], ...]:
    plugins: list[tuple[PluginInfo, object]] = []
    for info in plugin_runtime.discover():
        native_plugin = _native_plugin(info)
        if native_plugin is not None:
            plugins.append((info, native_plugin))
    return tuple(plugins)


def _plugin_help(native_plugin: object) -> str:
    commands = getattr(native_plugin, "_extra", {}).get("commands", ())
    if not commands:
        return "该插件未注册命令"
    return "\n\n".join(
        command_manager.get_command(command_name).get_help()
        for _prefixes, command_name in commands
    )


def _metadata_value(native_plugin: object | None, field: str) -> object | None:
    return getattr(getattr(native_plugin, "metadata", None), field, None)


def _classifiers(native_plugin: object | None) -> tuple[str, ...]:
    value = _metadata_value(native_plugin, "classifier")
    if isinstance(value, str):
        return (value,)
    if isinstance(value, Iterable):
        return tuple(str(item) for item in value)
    return ()


def _plugin_item(
    info: PluginInfo,
    native_plugin: object | None,
    number: int,
    state: str,
    state_label: str,
) -> dict[str, Any]:
    name = _metadata_value(native_plugin, "name") or info.name
    description = _metadata_value(native_plugin, "description") or ""
    return {
        "number": number,
        "name": str(name),
        "plugin": info.name,
        "description": str(description),
        "state": state,
        "state_label": state_label,
    }


def build_help_data(group_id: str | int | None = None) -> dict[str, Any]:
    """Build the three-section help model from loaded native plugins.

    The directory scan is deliberately kept in ``PluginRuntime``.  Only
    plugins that are currently registered with Entari are displayed, so an
    unimported directory cannot appear as a misleading runnable feature.
    """

    sections: dict[str, list[dict[str, Any]]] = {
        key: [] for key, _, _ in _HELP_SECTIONS
    }
    for number, (info, native_plugin) in enumerate(_help_plugins(), 1):
        if "required" in _classifiers(native_plugin):
            key = "required"
            state_label = "内置"
        elif feature_service.is_maintenance(info.name):
            key = "unavailable"
            state_label = "维护中"
        else:
            key = "available"
            state_label = (
                "运行中"
                if feature_service.is_enabled(info.name, group_id)
                else "已关闭"
            )
        sections[key].append(
            _plugin_item(info, native_plugin, number, key, state_label)
        )

    section_data = tuple(
        {
            "key": key,
            "title": title,
            "subtitle": subtitle,
            "items": tuple(sections[key]),
            "count": len(sections[key]),
        }
        for key, title, subtitle in _HELP_SECTIONS
    )
    return {
        "title": "Tenko 已注册命令",
        "subtitle": "按插件状态整理可用功能",
        "usage": "/帮助 [编号] 查看单项命令详情",
        "group_id": None if group_id is None else str(group_id),
        "sections": section_data,
        "required": tuple(sections["required"]),
        "available": tuple(sections["available"]),
        "unavailable": tuple(sections["unavailable"]),
        "total": number,
        "enabled_count": sum(
            item["state"] in {"required", "available"}
            and item["state_label"] != "已关闭"
            for item in (
                *sections["required"],
                *sections["available"],
                *sections["unavailable"],
            )
        ),
    }


def format_help_text(data: dict[str, Any]) -> str:
    """Format the help model into its text fallback."""

    lines = [str(data["title"]), "用法：/帮助 [编号] 查看单项命令详情"]
    for section in data["sections"]:
        lines.extend(("", f"{section['title']}："))
        if not section["items"]:
            lines.append("暂无")
            continue
        for item in section["items"]:
            lines.append(f"{item['number']}. {item['name']}（{item['state_label']}）")
    return "\n".join(lines)


def build_help(index: int | None = None, *, group_id: str | int | None = None) -> str:
    """Build the full plugin help or one plugin's native command help."""

    if index is not None:
        plugins = _help_plugins()
        if not 1 <= index <= len(plugins):
            return "编号不在范围内~"
        return _plugin_help(plugins[index - 1][1])
    return format_help_text(build_help_data(group_id))


@command.on(help_command)
async def helper(
    session: Session,
    index: Query[int] = Query("index", None),
    *,
    render_service: RenderService,
):
    context = context_from_session(session)
    if not await permission_checker.require_group_perm(
        context, Permission.ActiveGroup
    ) or not await permission_checker.require_perm(context, Permission.User):
        return text_message("权限不足")
    value = index.result if index.available else None
    if value is not None:
        return text_message(build_help(value))

    group_id = context.channel_id if context.chat_type == "group" else None
    help_data = build_help_data(group_id)
    image = await render_or_none(
        render_service,
        "render_template",
        "help.html",
        help_data,
    )
    if image is not None:
        return MessageChain(Image.of(raw=image, mime="image/jpeg"))
    return text_message(format_help_text(help_data))
