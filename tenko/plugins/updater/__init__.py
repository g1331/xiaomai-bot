"""Tenko 宿主升级管理命令。

命令只调用 ``tenko.host.updater`` 的控制平面 API。当前插件不执行进程内热
替换；``/升级`` 和 ``/回滚`` 生成外部重启接管记录，``/重启`` 复用同一
watcher，随后安排当前运行时优雅退出，避免当前事件处理器在同一进程里混用新旧代码。
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime, timedelta

from arclet.alconna import Alconna, CommandMeta
from arclet.entari import Ready, Session, command, plugin, scheduler
from arclet.entari.plugin import PluginRole
from loguru import logger

from tenko.host.perm import Permission
from tenko.host.updater import (
    CheckResult,
    HandoffResult,
    NoUpdateAvailable,
    PrepareResult,
    RollbackResult,
    UpdaterError,
    get_upgrade_manager,
    get_upgrade_permission_checker,
)
from tenko.plugins._common import context_from_session, text_message


plugin.metadata(
    "宿主升级",
    PluginRole.NORMAL,
    author=["Tenko"],
    version="0.1.0",
    description="检查、准备并通过外部重启流程升级 Tenko 宿主。",
    classifier=["required", "host"],
)
# Entari 0.18.6 不会在 PluginMetadata 中暴露 default_switch。保留供 host 的
# legacy-state inspector 使用的兼容性标记。
plugin.get_plugin().metadata.default_switch = True


updater = get_upgrade_manager()
permission_checker = get_upgrade_permission_checker()
_RESTART_SHUTDOWN_DELAY_SECONDS = 4.0
_RESTART_COOLDOWN_SECONDS = 60.0
_RESTART_PERMISSION_DENIED = "权限不足：仅 Master 可执行重启操作"
_RESTART_COOLDOWN_MESSAGE = "重启操作冷却中，请稍后再试"
_restart_cooldown_until = 0.0
_shutdown_task: asyncio.Task[None] | None = None


check_command = Alconna(
    "检查更新",
    meta=CommandMeta(
        "检查配置通道中的 Tenko 宿主版本",
        usage="检查更新",
        example="/检查更新",
        compact=True,
    ),
)
upgrade_command = Alconna(
    "升级",
    meta=CommandMeta(
        "下载并准备经过校验的 Tenko 宿主版本",
        usage="升级",
        example="/升级",
        compact=True,
    ),
)
rollback_command = Alconna(
    "回滚",
    meta=CommandMeta(
        "请求外部重启流程回到上一可用宿主版本",
        usage="回滚",
        example="/回滚",
        compact=True,
    ),
)
restart_command = Alconna(
    "重启",
    meta=CommandMeta(
        "通过升级系统安全重启 Tenko 宿主",
        usage="重启",
        example="/重启",
        compact=True,
    ),
)


async def _authorized(session: Session) -> bool:
    context = context_from_session(session)
    return await permission_checker.require_perm(context, Permission.Master)


def _error_message(error: Exception) -> str:
    return f"升级操作失败：{str(error) or error.__class__.__name__}"


def _format_check(result: CheckResult) -> str:
    if result.status == "disabled":
        return "升级系统已停用"
    if result.candidate is None:
        return f"当前已是最新版本：{result.current_version}（通道：{result.channel.value}）"
    release = result.candidate
    return (
        f"发现新版本：{release.version}\n"
        f"当前版本：{result.current_version}\n"
        f"通道：{result.channel.value}\n"
        f"标签：{release.tag}\n"
        f"来源：{release.source}"
    )


@command.on(check_command)
async def check_update(session: Session):
    if not await _authorized(session):
        return text_message("权限不足：仅超级用户可执行宿主升级操作")
    try:
        return text_message(_format_check(await updater.check()))
    except UpdaterError as exc:
        return text_message(_error_message(exc))


@command.on(upgrade_command)
async def upgrade(session: Session):
    if not await _authorized(session):
        return text_message("权限不足：仅超级用户可执行宿主升级操作")
    try:
        checked = await updater.check()
        if checked.candidate is None:
            return text_message(_format_check(checked))
        prepared = await updater.prepare(checked.candidate)
        handoff = await updater.request_install()
        watcher_armed = _arm_restart_watcher()
        response = text_message(_format_upgrade(prepared, handoff, watcher_armed))
        if watcher_armed:
            _schedule_graceful_shutdown()
        return response
    except NoUpdateAvailable:
        return text_message("没有可安装的新版本")
    except UpdaterError as exc:
        return text_message(_error_message(exc))


@command.on(rollback_command)
async def rollback(session: Session):
    if not await _authorized(session):
        return text_message("权限不足：仅超级用户可执行宿主升级操作")
    try:
        result = await updater.rollback()
        watcher_armed = _arm_restart_watcher() if not result.applied else False
        response = text_message(_format_rollback(result, watcher_armed))
        if watcher_armed:
            _schedule_graceful_shutdown()
        return response
    except UpdaterError as exc:
        return text_message(_error_message(exc))


@command.on(restart_command)
async def restart(session: Session):
    context = context_from_session(session)
    if not await permission_checker.require_perm(context, Permission.Master):
        return text_message(_RESTART_PERMISSION_DENIED)
    if not getattr(updater, "enabled", False):
        _record_restart_audit(context, "disabled")
        return text_message("重启依赖升级系统，当前未启用")
    if not _claim_restart_cooldown():
        _record_restart_audit(context, "cooldown")
        return text_message(_RESTART_COOLDOWN_MESSAGE)

    watcher_armed = _arm_restart_watcher()
    if not watcher_armed:
        _release_restart_cooldown()
        _record_restart_audit(context, "watcher_failed")
        return text_message("重启失败：自动重启未能启动，请手动重启。")

    _record_restart_audit(context, "requested")
    _schedule_graceful_shutdown()
    return text_message("正在重启…")


def _claim_restart_cooldown() -> bool:
    global _restart_cooldown_until
    now = time.monotonic()
    if now < _restart_cooldown_until:
        return False
    _restart_cooldown_until = now + _RESTART_COOLDOWN_SECONDS
    return True


def _release_restart_cooldown() -> None:
    global _restart_cooldown_until
    _restart_cooldown_until = 0.0


def _record_restart_audit(context: object, result: str) -> None:
    details = {
        "user_id": getattr(context, "user_id", None),
        "account_id": getattr(context, "account_id", None),
        "platform": getattr(context, "platform", None),
        "chat_type": getattr(context, "chat_type", None),
        "channel_id": getattr(context, "channel_id", None),
        "message_id": getattr(context, "message_id", None),
    }
    payload = {
        "timestamp": datetime.now(UTC).isoformat(),
        "action": "restart",
        "result": result,
        **details,
    }
    audit = getattr(updater, "audit", None)
    record = getattr(audit, "record", None)
    if not callable(record):
        logger.bind(restart_audit=payload).info("restart audit")
        return
    try:
        record(
            "restart",
            current_version=getattr(updater, "current_version", None),
            result=result,
            **details,
        )
    except OSError:
        # watcher 已经 arm 时不能因为审计文件暂时不可写而留下半完成的退出链路。
        logger.exception("Tenko restart audit write failed")
        logger.bind(restart_audit=payload).info("restart audit")


def _arm_restart_watcher() -> bool:
    arm = getattr(updater, "spawn_restart_watcher", None)
    if not callable(arm):
        return False
    armed = arm()
    if not armed:
        logger.warning(
            "Tenko restart watcher was not armed; manual restart remains required"
        )
    return armed


def _schedule_graceful_shutdown() -> None:
    """在回复完成发送后，安排一次性优雅退出。"""

    global _shutdown_task
    loop = asyncio.get_running_loop()
    if _shutdown_task is not None and not _shutdown_task.done():
        if _shutdown_task.get_loop() is loop:
            return
        _shutdown_task.cancel()
    _shutdown_task = loop.create_task(
        _shutdown_after_reply(),
        name="tenko-upgrade-graceful-shutdown",
    )


async def _shutdown_after_reply() -> None:
    # handler 返回后，Entari 才会把已经构造的 MessageChain 投递出去；延迟
    # 给发送链路留出稳定窗口，退出本身仍交给运行时的 Launart 生命周期。
    await asyncio.sleep(_RESTART_SHUTDOWN_DELAY_SECONDS)
    try:
        if not updater.request_graceful_shutdown():
            logger.warning(
                "Tenko restart watcher armed but graceful shutdown request was not accepted"
            )
    except Exception:
        logger.exception("Tenko automatic graceful shutdown failed")


def _format_upgrade(
    prepared: PrepareResult, handoff: HandoffResult, watcher_armed: bool
) -> str:
    if watcher_armed:
        return f"版本 {prepared.release.version} 已下载、校验通过，正在自动重启进入新版本。"
    return f"版本 {prepared.release.version} 已下载、校验通过，但自动重启未能启动，请手动重启。"


def _format_rollback(result: RollbackResult, watcher_armed: bool) -> str:
    if result.applied:
        return f"已成功回滚到版本 {result.target_version}。"
    if watcher_armed:
        return f"已请求回滚到版本 {result.target_version}，正在自动重启。"
    return f"已请求回滚到版本 {result.target_version}，但自动重启未能启动，请手动重启。"


async def _run_policy() -> CheckResult | PrepareResult | HandoffResult:
    result = await updater.run_policy()
    if isinstance(result, CheckResult) and result.candidate is not None:
        logger.warning("Tenko upgrade available: {}", result.candidate.version)
    elif isinstance(result, PrepareResult):
        logger.info("Tenko upgrade artifact prepared: {}", result.path)
    elif isinstance(result, HandoffResult):
        logger.warning("Tenko upgrade handoff requested: {}", result.target_version)
    return result


@plugin.listen(Ready)
async def on_ready():
    try:
        await _run_policy()
    except UpdaterError as exc:
        logger.error("Tenko upgrade policy failed: {}", exc)


@scheduler.schedule(
    lambda: timedelta(hours=updater.check_interval_hours),
    label="tenko-upgrade-policy",
)
async def scheduled_policy():
    try:
        await _run_policy()
    except UpdaterError as exc:
        logger.error("Tenko scheduled upgrade policy failed: {}", exc)
