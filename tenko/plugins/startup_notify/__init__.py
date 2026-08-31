from __future__ import annotations

from pathlib import Path

from arclet.entari import Ready, plugin
from arclet.entari.plugin import PluginRole, collect_disposes
from loguru import logger

from tenko.host.actions import action_service
from tenko.host.features import feature_service
from tenko.host.perm import PermissionChecker
from tenko.host.startup import (
    STARTUP_NOTIFY_FEATURE,
    StartupHistory,
    StartupNotifier,
    build_startup_notice,
    calculate_beaten_percent,
    calculate_percentile,
)


plugin.metadata(
    "启动通知",
    PluginRole.NORMAL,
    author=["13"],
    version="0.1.0",
    description="在 Tenko 与账号服务就绪后播报启动耗时。",
    classifier=["required"],
)
# Entari 0.18.6 的构造函数没有 default_switch 字段。将兼容性标记保留在原生
# metadata 上，供 host/plugins.py 和 inspectors 使用；启动通知是宿主级开关，
# 但仍允许 feature_manager 通过 features.json 动态控制。
plugin.get_plugin().metadata.default_switch = True
plugin.get_plugin().metadata.feature_scope = "global"


permission_checker = PermissionChecker()
notifier: StartupNotifier | None = None


def configure_startup_notification(
    notify_group: str | int | None,
    *,
    started_at: float | None = None,
    history_path: str | Path | None = None,
) -> StartupNotifier:
    """由 TenkoRuntime 注入启动起点和通知目标。"""

    global notifier
    notifier = StartupNotifier(
        notify_group=notify_group,
        started_at=started_at,
        history_path=history_path,
        action_service=action_service,
        feature_service=feature_service,
        permission_checker=permission_checker,
    )
    return notifier


async def on_account_online(account: object) -> None:
    if notifier is not None:
        await notifier.mark_account_online(account)


@plugin.listen(Ready)
async def on_ready() -> None:
    if notifier is None:
        logger.warning("Tenko startup notification has not been configured")
        return
    await notifier.mark_framework_ready()


def _dispose_startup_notification() -> None:
    global notifier
    notifier = None


collect_disposes(_dispose_startup_notification)


__all__ = [
    "STARTUP_NOTIFY_FEATURE",
    "StartupHistory",
    "StartupNotifier",
    "build_startup_notice",
    "calculate_beaten_percent",
    "calculate_percentile",
    "configure_startup_notification",
    "notifier",
    "on_account_online",
    "on_ready",
    "permission_checker",
]
