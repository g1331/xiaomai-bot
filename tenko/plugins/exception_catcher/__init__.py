from __future__ import annotations

import hashlib
import time
import traceback
from typing import Any

from arclet.entari import ExceptionEvent, plugin
from arclet.entari.config import EntariConfig
from arclet.entari.plugin import PluginRole
from loguru import logger
from satori import Text


plugin.metadata(
    "异常捕获",
    PluginRole.UTILITY,
    author=["13"],
    version="0.1.0",
    description="捕获 Entari 全局异常事件并向超级用户报告。",
    classifier=["required"],
)
# Entari 0.18.6 has no constructor field for default_switch.  Keep the
# compatibility marker on native metadata for host/plugins.py and inspectors.
plugin.get_plugin().metadata.default_switch = True


ERROR_COOLDOWN = 30.0
last_error_time: dict[str, float] = {}


def get_error_hash(exception: BaseException) -> str:
    return hashlib.md5(
        f"{exception.__class__.__name__}:{exception}".encode()
    ).hexdigest()


def generate_error_report(exception: BaseException) -> str:
    """Create a bounded plain-text report from the native exception object."""

    report = "".join(traceback.format_exception(exception))
    return f"[Tenko 异常] {exception.__class__.__name__}: {exception}\n{report}"[
        -12000:
    ]


def _superuser_ids(account: Any) -> tuple[str, ...]:
    configured = EntariConfig.instance.basic.superusers
    return tuple(configured.get(account.platform, ()))


async def send_error_report(exception: BaseException, origin: Any) -> None:
    """Send a native Satori text report to configured Entari superusers."""

    account = getattr(origin, "account", None)
    if account is None:
        logger.error("无法发送异常报告：ExceptionEvent 没有关联 Entari account")
        return
    user_ids = _superuser_ids(account)
    if not user_ids:
        logger.error(
            "无法发送异常报告：平台 {} 没有配置 Entari superusers",
            account.platform,
        )
        return
    report = generate_error_report(exception)
    for user_id in user_ids:
        try:
            await account.protocol.send_private_message(user_id, [Text(report)])
        except Exception:
            logger.exception("发送异常报告给 {} 失败", user_id)


@plugin.listen(ExceptionEvent)
async def except_handle(event: ExceptionEvent):
    """Handle the exception event emitted by Entari's dispatcher."""

    if isinstance(event.origin, ExceptionEvent):
        return
    error_hash = get_error_hash(event.exception)
    now = time.monotonic()
    last_time = last_error_time.get(error_hash)
    if last_time is not None and now - last_time < ERROR_COOLDOWN:
        return
    last_error_time[error_hash] = now
    await send_error_report(event.exception, event.origin)
