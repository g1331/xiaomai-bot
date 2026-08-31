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
from tenko.render import RenderService
from tenko.render import render_or_none


plugin.metadata(
    "帮助系统",
    PluginRole.NORMAL,
    author=["13"],
    version="0.1.0",
    description="根据 Entari 当前注册命令生成帮助文本。",
    classifier=["required"],
)
# Entari 0.18.6 的构造函数没有 default_switch 字段。将兼容性标记保留在原生
# metadata 上，供 host/plugins.py 和 inspectors 使用。
plugin.get_plugin().metadata.default_switch = True


permission_checker = PermissionChecker()
plugin_runtime = PluginRuntime()

_HELP_SECTIONS = (
    ("required", "内置插件", "系统必需功能"),
    ("available", "运行插件", "当前可用功能"),
    ("unavailable", "维护插件", "暂不可用功能"),
)
_COMMAND_HELP_FIELDS = (("说明", "description"), ("用法", "usage"), ("示例", "example"))


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


def registered_commands():
    """返回 Alconna 维护的实时命令注册表。"""

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


def _first_prefix(value: object) -> str | None:
    if isinstance(value, str):
        return value or None
    if isinstance(value, Iterable):
        return next(
            (str(item) for item in value if item is not None and str(item)), None
        )
    return None


def _command_prefix(command: object, prefixes: object) -> str:
    return (
        _first_prefix(getattr(command, "prefixes", None))
        or _first_prefix(prefixes)
        or "/"
    )


def _command_meta_text(command: object, field: str) -> str | None:
    value = getattr(getattr(command, "meta", None), field, None)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _prefix_command_line(line: str, command_name: str, prefix: str) -> str:
    if line.startswith(command_name) and not line.startswith(prefix):
        return f"{prefix}{line}"
    return line


def _format_command_value(
    value: str, field: str, command_name: str, prefix: str
) -> str:
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    if field in {"usage", "example"}:
        lines = [_prefix_command_line(line, command_name, prefix) for line in lines]
    return "\n".join(lines)


def _format_command_help(command: object, command_name: str, prefixes: object) -> str:
    display_name = str(getattr(command, "command", None) or command_name)
    prefix = _command_prefix(command, prefixes)
    fields: list[tuple[str, str]] = []
    for label, field in _COMMAND_HELP_FIELDS:
        value = _command_meta_text(command, field)
        if value is None:
            continue
        formatted = _format_command_value(value, field, display_name, prefix)
        if formatted:
            fields.append((label, formatted))

    lines = [f"{prefix}{display_name}"]
    for index, (label, value) in enumerate(fields):
        is_last = index == len(fields) - 1
        branch = "└" if is_last else "├"
        value_lines = value.splitlines()
        lines.append(f"{branch} {label}：{value_lines[0]}")
        continuation = "  " if is_last else "│ "
        lines.extend(f"{continuation}{line}" for line in value_lines[1:])
    return "\n".join(lines)


def _plugin_help(native_plugin: object) -> str:
    """将插件注册的命令元数据格式化为纯文本帮助。"""

    commands = getattr(native_plugin, "_extra", {}).get("commands", ())
    if not commands:
        return "该插件未注册命令"
    return "\n\n".join(
        _format_command_help(
            command_manager.get_command(command_name), command_name, prefixes
        )
        for prefixes, command_name in commands
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
    """根据已加载的原生插件构建由三个部分组成的帮助模型。

    目录扫描由 ``PluginRuntime`` 负责并刻意保留在那里。这里只显示当前已向
    Entari 注册的插件，因此未导入的目录不会作为看似可运行的功能误显示。
    """

    sections: dict[str, list[dict[str, Any]]] = {
        key: [] for key, _, _ in _HELP_SECTIONS
    }
    for number, (info, native_plugin) in enumerate(_help_plugins(), 1):
        classifiers = _classifiers(native_plugin)
        if "host" in classifiers:
            key = "required"
            state_label = "内置"
        elif feature_service.is_maintenance(info.name):
            key = "unavailable"
            state_label = "维护中"
        elif "required" in classifiers:
            key = "required"
            state_label = (
                "运行中"
                if feature_service.is_enabled(info.name, group_id)
                else "已关闭"
            )
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
    """将帮助模型格式化为文本回退结果。"""

    lines = [str(data["title"]), f"用法：{data['usage']}"]
    for section in data["sections"]:
        lines.extend(("", f"{section['title']}："))
        if not section["items"]:
            lines.append("└ 暂无")
            continue
        for index, item in enumerate(section["items"]):
            branch = "└" if index == len(section["items"]) - 1 else "├"
            lines.append(
                f"{branch} {item['number']}. {item['name']}（{item['state_label']}）"
            )
    return "\n".join(lines)


def build_help(index: int | None = None, *, group_id: str | int | None = None) -> str:
    """构建完整的插件帮助，或某个插件的单项命令帮助。"""

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
