from __future__ import annotations

import asyncio
import secrets
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import Any

from arclet.alconna import Alconna, Args, CommandMeta, MultiVar, Option
from arclet.entari import MessageChain, Session, command, plugin
from arclet.entari.command import Match
from arclet.entari.plugin import PluginRole, get_plugins
from satori import Text
from satori.element import At

from tenko.host.actions import (
    ActionAccountUnavailable,
    ActionCapabilityUnavailable,
    ActionPermissionDenied,
    ActionService,
    ActionServiceError,
    ActionTargetUnavailable,
    action_service,
)
from tenko.host.accounts import AccountRegistry, account_registry
from tenko.host.features import feature_service
from tenko.host.perm import Permission, PermissionChecker
from tenko.host.plugins import PluginInfo, PluginRuntime
from tenko.plugins._common import (
    action_error_message,
    context_from_session,
    report_action_error,
    send_private_message,
    text_message,
)

"""公告插件。

公告的群功能开关通过 ``PluginRuntime`` 只读兼容旧
``core/models/saya_model/modules_data.json`` 的 ``modules -> groups -> switch``
结构；当前仓库没有把这个结构迁成独立 ORM 表，因此真实数据库契约仍需
“待第⑧步真实数据库验证”。该实现不调用旧 ModulesController 的写入路径。

发送动作统一进入宿主 ``ActionService``，并用账号×群的 ``is_muted`` 状态在
发送前过滤。NapCat 的失败 retcode/message/wording 组合仍需
“待第⑧步 NapCat 实测确认”，测试只依赖 OneBot 11 标准失败回执形状。
"""


plugin.metadata(
    "公告",
    PluginRole.NORMAL,
    author=["13"],
    version="0.1.0",
    description="向开启指定功能的群推送公告，并逐条报告结果。",
    classifier=["required"],
)
# Entari 0.18.6 has no constructor field for default_switch.  Keep the
# compatibility marker on native metadata for host/plugins.py and inspectors.
plugin.get_plugin().metadata.default_switch = True


permission_checker = PermissionChecker()
plugin_runtime = PluginRuntime()


@dataclass(frozen=True, slots=True)
class PushTarget:
    """一个已通过功能开关和账号路由预检的群发送目标。"""

    group_id: str
    account_id: str


@dataclass(frozen=True, slots=True)
class PushResult:
    """一个群目标的最终或预检结果。"""

    group_id: str
    status: str
    detail: str
    account_id: str | None = None


def _native_plugin(info: PluginInfo):
    names = set(info.lookup_names)
    return next(
        (current for current in get_plugins(subplugged=True) if current.id in names),
        None,
    )


def resolve_feature(function_name: str) -> PluginInfo | None:
    """按旧 display_name、Tenko 插件名或兼容导入名解析功能。"""

    wanted = function_name.strip()
    if not wanted:
        return None
    for info in plugin_runtime.discover():
        native = _native_plugin(info)
        display_name = native.metadata.name if native and native.metadata else None
        if wanted in {info.name, info.qualified_name, *info.lookup_names}:
            return info
        if display_name == wanted:
            return info
    return None


def feature_enabled(feature: PluginInfo, group_id: str) -> bool:
    """同时读取新宿主开关和旧状态兼容开关，不创建或更新任一状态。"""

    return feature_service.is_enabled(
        feature.name, group_id
    ) and plugin_runtime.is_enabled(feature, group_id=group_id)


def _account_id(account: object) -> str:
    return str(getattr(account, "self_id", account))


def _preflight_group(
    feature: PluginInfo,
    group_id: str,
    registry: AccountRegistry,
) -> tuple[PushTarget | None, PushResult | None]:
    if not feature_enabled(feature, group_id):
        return None, PushResult(group_id, "skipped_feature_disabled", "功能未开启")

    bound = registry.bound_accounts_for_group(group_id)
    if not bound:
        return None, PushResult(group_id, "skipped_no_account", "没有绑定账号")

    available = [account for account in bound if registry.is_available(account)]
    if not available:
        account_ids = ",".join(_account_id(account) for account in bound)
        return None, PushResult(
            group_id,
            "skipped_account_unavailable",
            f"账号不可用: {account_ids}",
        )

    unmuted = [
        account
        for account in available
        if not registry.is_muted(_account_id(account), group_id)
    ]
    if not unmuted:
        account_ids = ",".join(_account_id(account) for account in available)
        return None, PushResult(
            group_id,
            "skipped_muted",
            f"账号在群内禁言: {account_ids}",
        )

    selected = registry.select_account(group_id)
    if selected is None:
        preferred = registry.deterministic_account_for_group(group_id)
        if preferred and registry.is_muted(preferred, group_id):
            return None, PushResult(
                group_id,
                "skipped_muted",
                f"账号在群内禁言: {preferred}",
                preferred,
            )
        return None, PushResult(
            group_id,
            "skipped_account_unavailable",
            "路由指定账号不可用",
            preferred,
        )
    return PushTarget(group_id, _account_id(selected)), None


def collect_targets(
    feature: PluginInfo,
    registry: AccountRegistry | None = None,
) -> tuple[tuple[PushTarget, ...], tuple[PushResult, ...]]:
    """按群路由规划一次公告，只选择每群一个可用账号。"""

    registry = registry or account_registry
    targets: list[PushTarget] = []
    results: list[PushResult] = []
    for group_id in registry.group_ids:
        target, result = _preflight_group(feature, group_id, registry)
        if target is not None:
            targets.append(target)
        if result is not None:
            results.append(result)
    return tuple(targets), tuple(results)


def _nonce() -> str:
    return secrets.token_hex(10)


def format_announcement(content: str, nonce: str | None = None) -> str:
    """保留旧公告标题，并为每个目标附加独立去重串。"""

    return f"    ===BOT公告推送===\n    {content}\n    ({nonce or _nonce()})"


async def pusher(
    push_list: Iterable[PushTarget],
    content: str,
    interval: int,
    *,
    context,
    service: ActionService | None = None,
    sleep: Callable[[float], Awaitable[Any]] | None = None,
    report_origin: Any | None = None,
) -> tuple[PushResult, ...]:
    """逐群发送并返回每个目标结果；间隔只发生在两个目标之间。"""

    targets = tuple(push_list)
    service = service or action_service
    sleep = sleep or asyncio.sleep
    results: list[PushResult] = []
    for index, target in enumerate(targets):
        try:
            await service.send_group_message(
                target.account_id,
                target.group_id,
                format_announcement(content),
                context=context,
                permission_checker=permission_checker,
            )
        except ActionServiceError as error:
            if report_origin is not None:
                await report_action_error(error, report_origin)
            if isinstance(error, ActionTargetUnavailable):
                status = "skipped_muted"
            elif isinstance(error, ActionAccountUnavailable):
                status = "skipped_account_unavailable"
            elif isinstance(error, ActionCapabilityUnavailable):
                status = "failed_capability_unavailable"
            elif isinstance(error, ActionPermissionDenied):
                status = "failed_permission"
            else:
                status = "failed"
            results.append(
                PushResult(
                    target.group_id,
                    status,
                    action_error_message(error),
                    target.account_id,
                )
            )
        else:
            results.append(
                PushResult(target.group_id, "sent", "推送成功", target.account_id)
            )
        if index < len(targets) - 1:
            await sleep(interval * 60)
    return tuple(results)


def format_results(results: Iterable[PushResult]) -> str:
    """Format an announcement result summary safe for the source group."""

    entries = tuple(results)
    succeeded = sum(result.status == "sent" for result in entries)
    skipped = sum(result.status.startswith("skipped_") for result in entries)
    failed = len(entries) - succeeded - skipped
    return (
        f"公告推送完成：目标数 {len(entries)}；成功数 {succeeded}；"
        f"失败数 {failed}；跳过数 {skipped}"
    )


def format_diagnostic_results(results: Iterable[PushResult]) -> str:
    """Format the full per-group result for a Master private message."""

    entries = tuple(results)
    if not entries:
        return "公告推送结果：没有满足条件的群哦~"
    lines = ["公告推送结果:"]
    lines.extend(
        f"群{result.group_id}: {result.status} - {result.detail}"
        + (f"（账号{result.account_id}）" if result.account_id else "")
        for result in entries
    )
    return "\n".join(lines)


async def _confirm(session: Session, content: str, count: int, interval: int) -> bool:
    """使用 Entari 原生 prompt 保留旧公告的二次确认语义。"""

    if not hasattr(session, "prompt") or not hasattr(session, "send"):
        return True
    await session.send(
        text_message(
            f"推送内容:\n“{content}”\n预计推送到{count}个群（间隔:{interval}分钟），确定吗?（是/否）"
        )
    )
    reply = await session.prompt(timeout=30, timeout_message="回复等待超时,进程退出")
    if reply is None:
        return False
    answer = str(reply).strip().lower()
    return answer in {"是", "y", "yes", "确认"}


async def _send_progress(session: Session, target_count: int) -> None:
    sender = getattr(session, "send", None)
    if callable(sender):
        await sender(text_message(f"开始推送：目标数 {target_count}"))


announcement_command = Alconna(
    "公告",
    Args["function_name", str],
    Args["content", MultiVar(str)],
    Option("--time", Args["time", int], alias=["-t", "--interval"], default=1),
    meta=CommandMeta(
        "向开启指定功能的群推送公告",
        hide_shortcut=True,
        usage="公告 <功能名> <内容...> [-t <间隔分钟>]",
        example="公告 帮助系统 识图插件维护啦",
        compact=False,
    ),
)
announcement_command.shortcut("-公告", command="公告", prefix=True)


@command.on(announcement_command)
async def push_handle(
    session: Session,
    function_name: Match[str],
    content: Match[tuple[str, ...]],
    time: Match[int],
):
    context = context_from_session(session)
    if context.chat_type != "group":
        return text_message("该指令只能在群聊中使用")
    try:
        await action_service.authorize(
            context,
            Permission.BotAdmin,
            checker=permission_checker,
        )
    except ActionPermissionDenied as error:
        return text_message(action_error_message(error))
    is_master = await permission_checker.require_perm(context, Permission.Master)

    interval = time.result if time.available else 1
    if not 0 < interval < 10:
        return text_message(f"间隔时间需要在0~10之间哦!匹配到的时间:{interval}")
    feature_name = function_name.result.strip()
    announcement_content = " ".join(content.result).strip()
    if not announcement_content:
        return text_message("公告内容不能为空")
    feature = resolve_feature(feature_name)
    if feature is None:
        return text_message(f"没有在运行插件中找到 {feature_name} 哦~")

    targets, preflight = collect_targets(feature)
    target_count = len(targets) + len(preflight)
    if not targets:
        results = preflight
        if target_count:
            await _send_progress(session, target_count)
        if is_master:
            await send_private_message(
                session,
                context.user_id,
                format_diagnostic_results(results),
            )
        return text_message(format_results(results))
    if not await _confirm(session, announcement_content, len(targets), interval):
        return text_message("未预期回复,操作退出")

    await _send_progress(session, target_count)
    pushed = await pusher(
        targets,
        announcement_content,
        interval,
        context=context,
        report_origin=session,
    )
    results = (*preflight, *pushed)
    if is_master:
        await send_private_message(
            session,
            context.user_id,
            format_diagnostic_results(results),
        )
    return MessageChain([At(context.user_id), Text(format_results(results))])


__all__ = [
    "PushResult",
    "PushTarget",
    "announcement_command",
    "collect_targets",
    "feature_enabled",
    "format_announcement",
    "format_diagnostic_results",
    "format_results",
    "plugin_runtime",
    "pusher",
    "push_handle",
    "resolve_feature",
]
