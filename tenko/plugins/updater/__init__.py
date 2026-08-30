"""Tenko 宿主升级管理命令。

命令只调用 ``tenko.host.updater`` 的控制平面 API。当前插件不执行进程内热
替换；``/升级`` 和 ``/回滚`` 只生成外部重启接管记录，避免当前事件处理器
在同一进程里混用新旧代码。
"""

from __future__ import annotations

from datetime import timedelta

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
# Entari 0.18.6 does not expose default_switch in PluginMetadata.  Keep the
# compatibility marker used by the host's legacy-state inspector.
plugin.get_plugin().metadata.default_switch = True


updater = get_upgrade_manager()
permission_checker = get_upgrade_permission_checker()


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
        hide_shortcut=True,
        usage="升级",
        example="/升级",
        compact=True,
    ),
)
upgrade_command.shortcut("-upgrade", command="升级", prefix=True)
rollback_command = Alconna(
    "回滚",
    meta=CommandMeta(
        "请求外部重启流程回到上一可用宿主版本",
        usage="回滚",
        example="/回滚",
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
        return text_message(_format_upgrade(prepared, handoff))
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
        return text_message(_format_rollback(result))
    except UpdaterError as exc:
        return text_message(_error_message(exc))


def _format_upgrade(prepared: PrepareResult, handoff: HandoffResult) -> str:
    return (
        f"版本 {prepared.release.version} 已下载、校验并通过切换前健康检查。\n"
        f"制品目录：{prepared.path}\n"
        f"已生成外部重启接管记录：{updater.layout.handoff_file}\n"
        "当前进程不会热替换；请由外部启动器接管重启和切换。"
    )


def _format_rollback(result: RollbackResult) -> str:
    return (
        f"已请求回滚到版本 {result.target_version}。\n"
        f"目标目录：{result.path}\n"
        "当前进程不会热替换；请由外部启动器接管重启。"
    )


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
