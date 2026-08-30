from __future__ import annotations

import importlib.metadata
import os
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 fallback
    import tomli as tomllib

from arclet.alconna import Alconna, CommandMeta, Option, store_true
from arclet.entari import MessageChain, Session, command, plugin
from arclet.entari.command import Query
from arclet.entari.plugin import PluginRole
from satori import Image

from tenko.events import MessageMetrics, message_metrics
from tenko.host.accounts import AccountRegistry, account_registry
from tenko.host.perm import Permission, PermissionChecker
from tenko.plugins._common import context_from_session, text_message
from tenko.plugins.render import RenderService  # entari: plugin
from tenko.render import render_or_none

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
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_PROJECT_NAME = "bot-xiaomai-open"
_PROJECT_ADDRESS = "项目地址：https://github.com/g1331/xiaomai-bot"


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
    return f"{days}天{hours}小时{minutes}分{seconds}秒"


def _format_time(value: datetime) -> str:
    if value.tzinfo is None:
        local_value = value
    else:
        local_value = value.astimezone()
    return local_value.strftime("%Y年%m月%d日%H时%M分%S秒")


def _project_version() -> str:
    try:
        return importlib.metadata.version(_PROJECT_NAME)
    except importlib.metadata.PackageNotFoundError:
        pass

    try:
        with (_PROJECT_ROOT / "pyproject.toml").open("rb") as project_file:
            project_data = tomllib.load(project_file)
        version = project_data["project"]["version"]
    except (
        OSError,
        KeyError,
        TypeError,
        tomllib.TOMLDecodeError,
    ):
        return "0.0.0"
    return str(version)


def _git_output(*arguments: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *arguments],
            cwd=_PROJECT_ROOT,
            capture_output=True,
            check=True,
            text=True,
            timeout=1.0,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    output = result.stdout.strip()
    return output or None


def get_version_details() -> tuple[str, ...]:
    """按旧版文本状态的顺序组装版本与构建信息。"""

    lines = [f"版本信息：v{_project_version()}"]
    branch = _git_output("branch", "--show-current") or "未知分支"
    commit_output = _git_output("log", "-1", "--format=%h%x1f%an%x1f%s")
    if commit_output is not None:
        commit_short, separator, commit_rest = commit_output.partition("\x1f")
        if separator:
            author, separator, message = commit_rest.partition("\x1f")
        else:
            author = message = "未知"
        if commit_short:
            lines.extend(
                [
                    f"Git分支：{branch}",
                    f"最新提交：{commit_short} ({author})",
                    f"提交信息：{message}",
                ]
            )

    build_number = os.environ.get("B2V_BUILD_NUMBER", "开发环境")
    if build_number != "开发环境":
        lines.append(f"构建编号：{build_number}")
        if build_date := os.environ.get("B2V_BUILD_DATE", ""):
            lines.append(f"构建日期：{build_date}")
        lines.append(f"构建类型：{os.environ.get('B2V_BUILD_TYPE', 'dev')}")
    return tuple(lines)


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


def _online_bot_count(registry: AccountRegistry) -> str:
    accounts = tuple(registry.accounts.values())
    online_count = sum(registry.is_available(account) for account in accounts)
    return f"{online_count}/{len(accounts)}"


def _current_group_mute(context: Any, registry: AccountRegistry) -> str | None:
    if context.chat_type != "group":
        return None

    accounts = registry.bound_accounts_for_group(context.channel_id)
    muted = sum(
        registry.is_muted(getattr(account, "self_id", account), context.channel_id)
        for account in accounts
    )
    return f"当前群禁言：{muted}/{len(accounts)}"


def build_status_data(
    context: Any,
    plugin_count: int,
    *,
    registry: AccountRegistry | None = None,
    metrics: MessageMetrics | None = None,
    resources: SystemResources | None = None,
    process: ProcessInfo | None = None,
    detailed: bool = False,
    version_details: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    registry = account_registry if registry is None else registry
    metrics = message_metrics if metrics is None else metrics
    resources = collect_system_resources() if resources is None else resources
    process = collect_process_info() if process is None else process
    received_rate, sent_rate = metrics.rates(_RATE_WINDOW_SECONDS)
    current_group_mute = _current_group_mute(context, registry)
    version_lines = (
        get_version_details() if version_details is None else tuple(version_details)
    )

    lines = [
        f"开机时间：{_format_time(process.start_time)}",
        f"运行时长：{_format_duration(process.uptime_seconds)}",
        (f"接收消息：{metrics.received_count}条 (实时:{received_rate}条/m)"),
        f"发送消息：{metrics.sent_count}条 (实时:{sent_rate}条/m)",
    ]
    if resources is not None:
        lines.extend(
            [
                (
                    f"内存使用：{round(resources.memory_used / 1024**2)}MB "
                    f"({resources.memory_percent:.0f}%)"
                ),
                f"CPU占比：{resources.cpu_percent:.1f}%",
                f"磁盘占比：{resources.disk_percent:.1f}%",
            ]
        )
    lines.extend(
        [
            f"在线bot数量：{_online_bot_count(registry)}",
            f"活动群组数量：{len(registry.group_ids)}",
            *version_lines,
            _PROJECT_ADDRESS,
        ]
    )
    if current_group_mute is not None:
        lines.append(current_group_mute)

    if detailed and context.chat_type == "private":
        diagnostic_lines: list[str] = []
        if process.rss is not None:
            diagnostic_lines.append(f"进程 RSS：{_format_bytes(process.rss)}")
        if resources is not None:
            diagnostic_lines.append(
                f"网络 IO：↑ {_format_bytes(resources.net_sent)}；"
                f"↓ {_format_bytes(resources.net_received)}"
            )
        lines.extend(diagnostic_lines)
    content = "\n".join(lines)
    return {
        "title": "Tenko 状态",
        "content": content,
        "lines": tuple(lines),
        "plugin_count": plugin_count,
        "chat_type": context.chat_type,
        "detailed": detailed,
        "current_group_mute": current_group_mute,
        "project_address": _PROJECT_ADDRESS,
        "version_details": version_lines,
        "metrics": {
            "received_count": metrics.received_count,
            "sent_count": metrics.sent_count,
            "received_rate": received_rate,
            "sent_rate": sent_rate,
        },
        "process": {
            "start_time": _format_time(process.start_time),
            "uptime_seconds": process.uptime_seconds,
            "uptime": _format_duration(process.uptime_seconds),
            "rss": process.rss,
            "rss_display": (
                _format_bytes(process.rss) if process.rss is not None else None
            ),
        },
        "resources": (
            None
            if resources is None
            else {
                "cpu_percent": resources.cpu_percent,
                "memory_used": resources.memory_used,
                "memory_total": resources.memory_total,
                "memory_percent": resources.memory_percent,
                "disk_used": resources.disk_used,
                "disk_total": resources.disk_total,
                "disk_percent": resources.disk_percent,
                "net_sent": resources.net_sent,
                "net_received": resources.net_received,
            }
        ),
        "online_bots": _online_bot_count(registry),
        "active_groups": len(registry.group_ids),
    }


def build_status(
    context: Any,
    plugin_count: int,
    *,
    registry: AccountRegistry | None = None,
    metrics: MessageMetrics | None = None,
    resources: SystemResources | None = None,
    process: ProcessInfo | None = None,
    detailed: bool = False,
    version_details: tuple[str, ...] | None = None,
) -> str:
    """Build the legacy text form from the shared status context."""

    return str(
        build_status_data(
            context,
            plugin_count,
            registry=registry,
            metrics=metrics,
            resources=resources,
            process=process,
            detailed=detailed,
            version_details=version_details,
        )["content"]
    )


status_command = Alconna(
    "状态",
    Option(
        "-t",
        alias=["--text"],
        action=store_true,
        default=False,
        help_text="强制使用文本输出",
    ),
    meta=CommandMeta(
        "查询 Tenko 运行状态",
        usage="状态 [-t]",
        example="/状态 -t",
        compact=True,
    ),
)


@command.on(status_command)
async def status(
    session: Session,
    text_mode: Query[bool] = Query("text.value", False),
    *,
    render_service: RenderService,
):
    context = context_from_session(session)
    if not await permission_checker.require_group_perm(
        context, Permission.ActiveGroup
    ) or not await permission_checker.require_perm(context, Permission.User):
        return text_message("权限不足")
    is_master_private = (
        context.chat_type == "private"
        and await permission_checker.require_perm(context, Permission.Master)
    )
    status_data = build_status_data(
        context,
        len(plugin.get_plugins()),
        detailed=is_master_private,
    )
    if not text_mode.result:
        image = await render_or_none(
            render_service,
            "render_template",
            "status.html",
            status_data,
        )
        if image is not None:
            return MessageChain(Image.of(raw=image, mime="image/jpeg"))
    return text_message(str(status_data["content"]))
