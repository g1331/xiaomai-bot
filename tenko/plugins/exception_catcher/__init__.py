from __future__ import annotations

import hashlib
import time
import traceback
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from arclet.entari import ExceptionEvent, plugin
from arclet.entari.config import EntariConfig
from arclet.entari.plugin import PluginRole
from loguru import logger
from satori import Image, Text
from satori.exception import NotFoundException

from tenko.context import MessageContext
from tenko.events import MessageLog, message_metrics
from tenko.host.actions import (
    ActionExecutionError,
    ActionFailure,
    ActionTargetUnavailable,
)
from tenko.render import RenderService
from tenko.render import render_or_none


plugin.metadata(
    "异常捕获",
    PluginRole.UTILITY,
    author=["13"],
    version="0.1.0",
    description="捕获 Entari 全局异常并向超级用户发送带上下文的取证报告。",
    classifier=["required"],
)
# Entari 0.18.6 的构造函数没有 default_switch 字段。将兼容性标记保留在原生
# metadata 上，供 host/plugins.py 和 inspectors 使用。
plugin.get_plugin().metadata.default_switch = True


ERROR_COOLDOWN = 30.0
last_error_time: dict[str, float] = {}
EVIDENCE_DIR = Path(".tenko/exceptions")
_IGNORED_EXCEPTION_NAMES = frozenset(
    {"AccountMuted", "UnknownTarget", "ActionTargetUnavailable"}
)
_IGNORED_EXCEPTION_PHRASES = (
    "account muted",
    "unknown target",
    "target not found",
    "目标不存在",
    "目标不可用",
    "对象位置未知",
    "对象不存在或不可及",
    "账号在对象所在聊天区域被封禁",
    "账号在群内禁言",
)


def configure_evidence_directory(path: str | Path) -> None:
    """由 TenkoRuntime 在插件加载后设置异常报告落盘目录。"""

    global EVIDENCE_DIR
    EVIDENCE_DIR = Path(path)


def get_error_hash(exception: BaseException) -> str:
    return hashlib.md5(
        f"{exception.__class__.__name__}:{exception}".encode()
    ).hexdigest()


def _ignored_exception_details(exception: BaseException) -> str:
    failure = getattr(exception, "failure", None)
    if not isinstance(failure, ActionFailure):
        return ""
    return " ".join(
        str(value).lower()
        for value in (
            failure.error_type,
            failure.message,
            failure.wording,
            failure.detail,
        )
        if value
    )


def is_ignored_exception(exception: BaseException) -> bool:
    """匹配旧版不报告的“目标不可达/账号被禁言”异常。"""

    if isinstance(exception, ActionTargetUnavailable | NotFoundException):
        return True
    if type(exception).__name__ in _IGNORED_EXCEPTION_NAMES:
        return True
    details = _ignored_exception_details(exception)
    if isinstance(exception, ActionExecutionError) and details:
        if any(phrase in details for phrase in _IGNORED_EXCEPTION_PHRASES):
            return True
        if "notfoundexception" in details or "unknowntarget" in details:
            return True
        if "accountmuted" in details:
            return True
    cause = exception.__cause__
    return cause is not None and cause is not exception and is_ignored_exception(cause)


def _compact(value: object, limit: int = 160) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else f"{text[: limit - 1]}…"


def _context_details(origin: Any) -> tuple[str, ...]:
    event = getattr(origin, "_origin", None)
    if event is None:
        event = getattr(origin, "event", origin)
    raw_event = getattr(event, "_origin", event)
    try:
        context = MessageContext.from_event(raw_event)
    except (AttributeError, TypeError, ValueError):
        context = None
    if context is not None:
        group = context.channel_id if context.chat_type == "group" else "-"
        message = _compact(context.text)
        if not message and context.image_urls:
            message = f"[图片×{len(context.image_urls)}]"
        return (
            f"账号={context.account_id}",
            f"平台={context.platform}",
            f"群={group}",
            f"用户={context.user_id}",
            f"消息摘要={message or '<空消息>'}",
        )

    account = getattr(origin, "account", None) or getattr(event, "account", None)
    account_id = getattr(account, "self_id", "-")
    platform = getattr(account, "platform", "-")
    return (
        f"账号={account_id}",
        f"平台={platform}",
        "群=-",
        "用户=-",
        "消息摘要=-",
    )


def _report_time(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _recent_lines(
    recent_messages: Iterable[MessageLog] | None,
    recent_limit: int | None,
) -> tuple[str, ...]:
    if recent_messages is None:
        recent = message_metrics.recent_messages
        limit = message_metrics.buffer_size if recent_limit is None else recent_limit
    else:
        recent = tuple(recent_messages)
        limit = message_metrics.buffer_size if recent_limit is None else recent_limit
    if type(limit) is not int or limit <= 0:
        raise ValueError("recent_limit 必须是正整数")
    return tuple(record.summary() for record in recent[-limit:])


def _action_failure_lines(exception: BaseException) -> tuple[str, ...]:
    failure = getattr(exception, "failure", None)
    if not isinstance(failure, ActionFailure):
        return ()
    return (
        "平台动作结构化失败:",
        f"account_id={failure.account_id}",
        f"capability={failure.capability.value}",
        f"action={failure.action}",
        f"status={failure.status!r}",
        f"retcode={failure.retcode!r}",
        f"data={failure.data!r}",
        f"message={failure.message!r}",
        f"wording={failure.wording!r}",
        f"echo={failure.echo!r}",
        f"error_type={failure.error_type!r}",
        f"detail={failure.detail!r}",
        f"raw={failure.raw!r}",
    )


def generate_error_report(
    exception: BaseException,
    origin: Any | None = None,
    *,
    recent_messages: Iterable[MessageLog] | None = None,
    recent_limit: int | None = None,
    occurred_at: datetime | None = None,
) -> str:
    """生成包含异常、当前会话和最近消息的完整文本报告。"""

    occurred_at = _report_time(occurred_at)
    traceback_text = "".join(
        traceback.format_exception(type(exception), exception, exception.__traceback__)
    )
    recent = _recent_lines(recent_messages, recent_limit)
    lines = [
        "[Tenko 异常]",
        f"发生时间: {occurred_at.isoformat(timespec='seconds')}",
        f"异常类型: {type(exception).__module__}.{type(exception).__qualname__}",
        f"异常消息: {exception}",
        "当前会话: " + " ".join(_context_details(origin)),
    ]
    lines.extend(_action_failure_lines(exception))
    lines.append("最近消息（环形缓冲）:")
    if recent:
        lines.extend(f"{index}. {line}" for index, line in enumerate(recent, 1))
    else:
        lines.append("<无记录>")
    lines.extend(("完整 traceback:", traceback_text.rstrip("\n")))
    return "\n".join(lines)


def _write_local_evidence(
    exception: BaseException,
    report: str,
    *,
    evidence_dir: str | Path | None = None,
) -> Path | None:
    directory = Path(EVIDENCE_DIR if evidence_dir is None else evidence_dir)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    path = directory / f"{stamp}-{time.time_ns()}-{get_error_hash(exception)[:12]}.log"
    try:
        directory.mkdir(parents=True, exist_ok=True)
        path.write_text(report + "\n", encoding="utf-8")
    except Exception:
        logger.exception("落盘异常取证报告失败: {}", path)
        logger.error("异常取证报告内容如下:\n{}", report)
        return None
    logger.warning("异常报告已落盘: {}", path)
    return path


def _superuser_ids(account: Any) -> tuple[str, ...]:
    if not EntariConfig._inited:
        return ()
    configured = EntariConfig.instance.basic.superusers
    platform = getattr(account, "platform", None)
    return (
        tuple(str(value) for value in configured.get(platform, ())) if platform else ()
    )


async def send_error_report(
    exception: BaseException,
    origin: Any,
    *,
    render_service: RenderService | None = None,
    evidence_dir: str | Path | None = None,
) -> None:
    """先向所有 superusers 发送报告，投递不完整时保留本地证据。

    ``render_service=None`` 仅覆盖直接调用这个工具函数、无法经过 Entari
    listener 注入的边界；生产 listener ``except_handle`` 总是显式传入注入的
    服务实例。
    """

    if is_ignored_exception(exception):
        return
    report = generate_error_report(exception, origin)
    account = getattr(origin, "account", None)
    delivery_failed = account is None
    if account is None:
        logger.error("无法发送异常报告：ExceptionEvent 没有关联 Entari account")
    else:
        user_ids = _superuser_ids(account)
        if not user_ids:
            delivery_failed = True
            logger.error(
                "无法发送异常报告：平台 {} 没有配置 Entari superusers",
                getattr(account, "platform", "-"),
            )
        else:
            image = await render_or_none(render_service, "render_markdown", report)
            for user_id in user_ids:
                try:
                    content = (
                        [Image.of(raw=image, mime="image/jpeg")]
                        if image is not None
                        else [Text(report)]
                    )
                    await account.protocol.send_private_message(user_id, content)
                except Exception:
                    delivery_failed = True
                    failure = getattr(exception, "failure", None)
                    logger.exception(
                        "发送异常报告给 {} 失败: account={} action={} retcode={} "
                        "message={} wording={}",
                        user_id,
                        getattr(failure, "account_id", None),
                        getattr(failure, "action", None),
                        getattr(failure, "retcode", None),
                        getattr(failure, "message", None),
                        getattr(failure, "wording", None),
                    )

    if delivery_failed:
        _write_local_evidence(
            exception,
            report,
            evidence_dir=evidence_dir,
        )


@plugin.listen(ExceptionEvent)
async def except_handle(
    event: ExceptionEvent,
    *,
    render_service: RenderService,
):
    """处理 Entari dispatcher 发出的异常事件。"""

    if isinstance(event.origin, ExceptionEvent):
        return
    if is_ignored_exception(event.exception):
        return
    error_hash = get_error_hash(event.exception)
    now = time.monotonic()
    last_time = last_error_time.get(error_hash)
    if last_time is not None and now - last_time < ERROR_COOLDOWN:
        return
    last_error_time[error_hash] = now
    await send_error_report(
        event.exception,
        event.origin,
        render_service=render_service,
    )
