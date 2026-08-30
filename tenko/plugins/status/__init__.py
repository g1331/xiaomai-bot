from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from arclet.alconna import Alconna, CommandMeta, Option, store_true
from arclet.entari import Session, command, plugin
from arclet.entari.command import Query
from arclet.entari.plugin import PluginRole

from tenko.events import MessageMetrics, message_metrics
from tenko.host.accounts import AccountRegistry, account_registry
from tenko.host.perm import Permission, PermissionChecker
from tenko.plugins._common import context_from_session, text_message

try:
    import psutil
except ImportError:  # pragma: no cover - exercised in minimal deployments
    psutil = None


plugin.metadata(
    "状态查询",
    PluginRole.NORMAL,
    author=["13"],
    version="0.1.0",
    description="查询 Tenko 当前会话、资源、消息统计和账号路由状态。",
    classifier=["required"],
)
# Entari 0.18.6 has no constructor field for default_switch.  Keep the
# compatibility marker on native metadata for host/plugins.py and inspectors.
plugin.get_plugin().metadata.default_switch = True


permission_checker = PermissionChecker()
_PROCESS_START_TIME = time.time()
_RATE_WINDOW_SECONDS = 60.0


@dataclass(frozen=True, slots=True)
class SystemResources:
    cpu_percent: float
    memory_used: int
    memory_total: int
    memory_percent: float
    disk_used: int
    disk_total: int
    disk_percent: float
    net_sent: int
    net_received: int


@dataclass(frozen=True, slots=True)
class ProcessInfo:
    start_time: datetime
    uptime_seconds: float
    rss: int | None


def _format_bytes(value: int | float) -> str:
    size = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(size) < 1024 or unit == "TB":
            return f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}TB"  # pragma: no cover


def _format_duration(seconds: float) -> str:
    total = max(int(seconds), 0)
    days, remainder = divmod(total, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    if days:
        return f"{days}天{hours}小时{minutes}分"
    if hours:
        return f"{hours}小时{minutes}分{seconds}秒"
    if minutes:
        return f"{minutes}分{seconds}秒"
    return f"{seconds}秒"


def _format_time(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone().isoformat(timespec="seconds")


def collect_system_resources() -> SystemResources | None:
    """读取系统资源；psutil 缺失或某次读取失败时返回 None。"""

    if psutil is None:
        return None
    try:
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        network = psutil.net_io_counters()
        try:
            cpu_percent = psutil.cpu_percent(interval=0.0)
        except TypeError:
            # 兼容测试替身及极少数旧版 psutil 的无参实现。
            cpu_percent = psutil.cpu_percent()
        return SystemResources(
            cpu_percent=float(cpu_percent),
            memory_used=int(memory.used),
            memory_total=int(memory.total),
            memory_percent=float(memory.percent),
            disk_used=int(disk.used),
            disk_total=int(disk.total),
            disk_percent=float(disk.percent),
            net_sent=int(network.bytes_sent),
            net_received=int(network.bytes_recv),
        )
    except Exception:
        # status 是诊断入口，不能因为权限受限、容器裁剪或 psutil 版本
        # 差异让正常的文本状态也无法返回。
        return None


def collect_process_info() -> ProcessInfo:
    """读取 Bot 进程启动时间和 RSS，RSS 不可读时仍保留运行时信息。"""

    start_timestamp = _PROCESS_START_TIME
    rss: int | None = None
    if psutil is not None:
        try:
            process = psutil.Process()
            start_timestamp = float(process.create_time())
            rss = int(process.memory_info().rss)
        except Exception:
            pass
    now = time.time()
    return ProcessInfo(
        start_time=datetime.fromtimestamp(start_timestamp, tz=timezone.utc),
        uptime_seconds=max(now - start_timestamp, 0.0),
        rss=rss,
    )


def _registry_lines(registry: AccountRegistry) -> tuple[str, str, str]:
    accounts = tuple(registry.accounts.values())
    online_ids = tuple(
        str(account.self_id) for account in accounts if registry.is_available(account)
    )
    online = ", ".join(online_ids) if online_ids else "无"

    mute_entries: list[str] = []
    for group_id in registry.group_ids:
        for account in registry.bound_accounts_for_group(group_id):
            if not registry.is_muted(account, group_id):
                state = "正常"
            elif (until := registry.mute_until(account, group_id)) is None:
                state = "永久"
            else:
                state = f"至 {_format_time(until)}"
            mute_entries.append(f"{account.self_id}@{group_id}={state}")
    mute_summary = ", ".join(mute_entries) if mute_entries else "无"
    return f"{len(online_ids)}/{len(accounts)}", online, mute_summary


def build_status(
    context: Any,
    plugin_count: int,
    *,
    registry: AccountRegistry | None = None,
    metrics: MessageMetrics | None = None,
    resources: SystemResources | None = None,
    process: ProcessInfo | None = None,
) -> str:
    registry = account_registry if registry is None else registry
    metrics = message_metrics if metrics is None else metrics
    resources = collect_system_resources() if resources is None else resources
    process = collect_process_info() if process is None else process
    location = (
        f"群聊 {context.channel_id}"
        if context.chat_type == "group"
        else f"私聊 {context.channel_id}"
        if context.chat_type == "private"
        else f"频道 {context.channel_id}"
    )
    received_rate, sent_rate = metrics.rates(_RATE_WINDOW_SECONDS)
    online_count, online_ids, mute_summary = _registry_lines(registry)

    lines = [
        "Tenko 状态",
        f"账号: {context.account_id}",
        f"会话: {location}",
        f"用户: {context.user_id}",
        f"已注册插件: {plugin_count}",
        (
            f"消息: 收 {metrics.received_count} / 发 {metrics.sent_count}；"
            f"近60秒 收 {received_rate} ({received_rate / _RATE_WINDOW_SECONDS:.2f}/秒)"
            f" / 发 {sent_rate} ({sent_rate / _RATE_WINDOW_SECONDS:.2f}/秒)"
        ),
        f"账号在线: {online_count}",
        f"在线账号: {online_ids}",
        f"活跃群: {len(registry.group_ids)}",
        f"账号×群禁言: {mute_summary}",
        (
            f"进程: 启动 {_format_time(process.start_time)}；"
            f"运行 {_format_duration(process.uptime_seconds)}"
            + (f"；RSS {_format_bytes(process.rss)}" if process.rss is not None else "")
        ),
    ]
    if resources is not None:
        lines.extend(
            [
                (
                    f"系统: CPU {resources.cpu_percent:.1f}%；"
                    f"内存 {_format_bytes(resources.memory_used)}/"
                    f"{_format_bytes(resources.memory_total)}"
                    f" ({resources.memory_percent:.1f}%)；"
                    f"磁盘 {_format_bytes(resources.disk_used)}/"
                    f"{_format_bytes(resources.disk_total)}"
                    f" ({resources.disk_percent:.1f}%)"
                ),
                (
                    f"网络 IO: ↑ {_format_bytes(resources.net_sent)}；"
                    f"↓ {_format_bytes(resources.net_received)}"
                ),
            ]
        )
    return "\n".join(lines)


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


@command.on(status_command)
async def status(
    session: Session,
    text_mode: Query[bool] = Query("text.value", False),
):
    del text_mode  # 图片渲染暂缓，保留旧命令的文本选项兼容性。
    context = context_from_session(session)
    if not await permission_checker.require_group_perm(
        context, Permission.ActiveGroup
    ) or not await permission_checker.require_perm(context, Permission.User):
        return text_message("权限不足")
    return text_message(build_status(context, len(plugin.get_plugins())))
