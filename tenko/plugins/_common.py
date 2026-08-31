from __future__ import annotations

import inspect
import sys
from collections.abc import Mapping

from arclet.entari.config import EntariConfig
from arclet.entari import MessageChain, Session
from loguru import logger
from satori import Text

from tenko.context import MessageContext
from tenko.host.actions import (
    ActionAccountUnavailable,
    ActionCapabilityUnavailable,
    ActionExecutionError,
    ActionPermissionDenied,
    ActionService,
    ActionServiceError,
    ActionTargetUnavailable,
)


def context_from_session(session: Session) -> MessageContext:
    """将 Entari 的消息 Session 转换为 Tenko 权限上下文。"""

    origin = getattr(session.event, "_origin", None)
    if origin is None:
        raise ValueError("Entari session event does not expose a Satori origin")
    return MessageContext.from_event(origin)


def text_message(content: str) -> MessageChain:
    """从 Satori 文本元素构造 Entari 原生消息。"""

    return MessageChain(Text(content))


def master_id_for_account(account: object, permission_checker: object) -> str | None:
    """按现有通知策略解析账号对应的第一个 Master。"""

    def normalize(value: object) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    registry = getattr(permission_checker, "registry", None)
    configured_master = normalize(getattr(registry, "master_id", None))
    if configured_master is not None:
        return configured_master
    if not EntariConfig._inited:
        return None
    configured = EntariConfig.instance.basic.superusers
    platform = getattr(account, "platform", "onebot")
    if not isinstance(configured, Mapping):
        return None
    for value in configured.get(platform, ()):
        master_id = normalize(value)
        if master_id is not None:
            return master_id
    return None


async def send_private_message(session: Session, user_id: str, content: str) -> bool:
    """向指定用户发送文本，失败时只记录日志并返回 False。"""

    sender = getattr(session, "send_private_message", None)
    if callable(sender):
        try:
            result = sender([Text(content)], user_id=str(user_id))
            if inspect.isawaitable(result):
                await result
            return True
        except Exception:
            logger.exception("私聊消息发送失败: user_id={}", user_id)
            logger.error("私聊消息内容如下:\n{}", content)
            return False

    account = getattr(session, "account", None)
    protocol = getattr(account, "protocol", None)
    sender = getattr(protocol, "send_private_message", None)
    if not callable(sender):
        logger.error("当前会话没有私聊发送能力: user_id={}", user_id)
        logger.error("私聊消息内容如下:\n{}", content)
        return False
    try:
        result = sender(str(user_id), [Text(content)])
        if inspect.isawaitable(result):
            await result
        return True
    except Exception:
        logger.exception("私聊消息发送失败: user_id={}", user_id)
        logger.error("私聊消息内容如下:\n{}", content)
        return False


def action_error_message(error: BaseException) -> str:
    """将动作错误转换为不会泄漏平台回执的群内短消息。"""

    if isinstance(error, ActionPermissionDenied):
        return "权限不足"
    if isinstance(error, ActionCapabilityUnavailable):
        return "该账号暂不支持此操作（或已被临时限制），已通知开发者"
    if isinstance(error, ActionExecutionError):
        failure = error.failure
        if failure is not None and ActionService._is_permission_failure(failure):
            return "该账号在此群没有管理员权限"
        return "平台操作失败，已通知开发者"
    if isinstance(error, ActionAccountUnavailable):
        return "账号暂不可用，已通知开发者"
    if isinstance(error, ActionTargetUnavailable):
        return "当前群暂不可用，已通知开发者"
    if isinstance(error, ActionServiceError):
        return "平台操作失败，已通知开发者"
    return "平台操作失败，已通知开发者"


def _action_failure_fields(error: BaseException) -> tuple[object, ...]:
    failure = getattr(error, "failure", None)
    if failure is None:
        return (None,) * 7
    return (
        failure.account_id,
        getattr(failure.capability, "value", failure.capability),
        failure.action,
        failure.retcode,
        failure.message,
        failure.wording,
        failure.echo,
    )


async def report_action_error(error: BaseException, origin: object) -> None:
    """复用异常捕获插件向 superusers 报告动作错误，并吞掉投递异常。"""

    reporter = sys.modules.get("tenko.plugins.exception_catcher")
    send_error_report = getattr(reporter, "send_error_report", None)
    if not callable(send_error_report):
        account, capability, action, retcode, message, wording, echo = (
            _action_failure_fields(error)
        )
        logger.error(
            "Action error reporter unavailable: account={} capability={} "
            "action={} retcode={} message={} wording={} echo={}",
            account,
            capability,
            action,
            retcode,
            message,
            wording,
            echo,
        )
        return
    try:
        await send_error_report(error, origin)
    except Exception:
        account, capability, action, retcode, message, wording, echo = (
            _action_failure_fields(error)
        )
        logger.exception(
            "Action error report delivery failed: account={} capability={} "
            "action={} retcode={} message={} wording={} echo={}",
            account,
            capability,
            action,
            retcode,
            message,
            wording,
            echo,
        )


def normalize_targets(value: object) -> tuple[str, ...]:
    """将 Alconna 已解析的值规范化为数据库 ID。"""

    if isinstance(value, str):
        return (value,)
    return tuple(str(item) for item in value)  # type: ignore[union-attr]
