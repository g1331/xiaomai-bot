from __future__ import annotations

from arclet.alconna import Alconna, Args, CommandMeta
from arclet.entari import Session, command, plugin
from arclet.entari.command import Match
from arclet.entari.plugin import PluginRole, get_plugins

from tenko.host.features import feature_service
from tenko.host.perm import Permission, PermissionChecker
from tenko.host.plugins import PluginInfo, PluginRuntime
from tenko.plugins._common import context_from_session, text_message


plugin.metadata(
    "功能开关",
    PluginRole.NORMAL,
    author=["13"],
    version="0.1.0",
    description="管理群内插件功能开关。",
    classifier=["required", "host"],
)
# Entari 0.18.6 的构造函数没有 default_switch 字段。将兼容性标记保留在原生
# metadata 上，供 host/plugins.py 和 inspectors 使用。
plugin.get_plugin().metadata.default_switch = True


permission_checker = PermissionChecker()
plugin_runtime = PluginRuntime()


def _native_plugin(info: PluginInfo):
    names = set(info.lookup_names)
    return next(
        (item for item in get_plugins(subplugged=True) if item.id in names), None
    )


def resolve_plugin(value: str) -> PluginInfo | None:
    """按帮助编号、目录名、导入名或元数据名定位插件。"""

    normalized = str(value)
    infos = plugin_runtime.discover()
    if normalized.isdigit():
        index = int(normalized)
        if 1 <= index <= len(infos):
            return infos[index - 1]
        return None
    for info in infos:
        if normalized in info.lookup_names or normalized == info.display_name:
            return info
    return None


def _is_required(info: PluginInfo) -> bool:
    native = _native_plugin(info)
    classifiers = getattr(getattr(native, "metadata", None), "classifier", ())
    return "required" in classifiers


async def _change(session: Session, operation: str, feature: Match[str]):
    context = context_from_session(session)
    if context.chat_type != "group":
        return text_message("该指令只能在群聊中使用")
    if not await permission_checker.require_group_perm(context, Permission.ActiveGroup):
        return text_message("当前群不可用")
    if not await permission_checker.require_perm(context, Permission.GroupAdmin):
        return text_message("权限不足")

    info = resolve_plugin(feature.result)
    if info is None:
        return text_message("编号不在运行插件范围内~")
    target_name = info.display_name
    if _is_required(info):
        return text_message(f"无法操作必须插件<{target_name}>")

    enabled = feature_service.is_enabled(info.name, context.channel_id)
    requested_enabled = operation == "开启"
    if enabled == requested_enabled:
        return text_message(
            f"功能{target_name}已处于{operation}状态请不要重复{operation}!"
        )
    feature_service.set_enabled(info.name, context.channel_id, requested_enabled)
    return text_message(
        f"功能<{target_name}>{'已开启' if requested_enabled else '已关闭'}~"
    )


enable_command = Alconna(
    "开启",
    Args["feature", str],
    meta=CommandMeta(
        "开启当前群的插件功能",
        usage="开启 <插件编号或名称>",
        compact=False,
    ),
)


@command.on(enable_command)
async def enable(session: Session, feature: Match[str]):
    return await _change(session, "开启", feature)


disable_command = Alconna(
    "关闭",
    Args["feature", str],
    meta=CommandMeta(
        "关闭当前群的插件功能",
        usage="关闭 <插件编号或名称>",
        compact=False,
    ),
)


@command.on(disable_command)
async def disable(session: Session, feature: Match[str]):
    return await _change(session, "关闭", feature)
