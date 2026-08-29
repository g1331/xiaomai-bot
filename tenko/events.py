from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from loguru import logger
from satori import ChannelType
from satori.client import Account
from satori.exception import ActionFailed
from satori.model import Event

from .context import MessageContext
from .host.accounts import AccountRegistry


def _event_group_id(event: Event) -> str | None:
    """Extract a group ID from standard Satori fields or OneBot raw data."""

    guild = getattr(event, "guild", None)
    if (group_id := getattr(guild, "id", None)) is not None:
        return str(group_id)

    raw_data = getattr(event, "_data", None)
    if (
        isinstance(raw_data, Mapping)
        and (group_id := raw_data.get("group_id")) is not None
    ):
        return str(group_id)

    channel = getattr(event, "channel", None)
    channel_id = getattr(channel, "id", None)
    if channel_id is None:
        return None
    protocol_type = str(getattr(event, "_type", "") or "")
    if ".group." in protocol_type or getattr(channel, "type", None) == ChannelType.TEXT:
        return str(channel_id)
    return None


@dataclass(frozen=True, slots=True)
class MessageEventHandler:
    """最小消息闭环的事件层处理器。"""

    send_replies: bool
    reply_text: str
    account_registry: AccountRegistry | None = None

    def should_skip(self, account: Account, event: Event) -> bool:
        """判断事件是否来自该账号在群内仍被禁言的路由。"""

        if (
            self.account_registry is None
            or (group_id := _event_group_id(event)) is None
        ):
            return False
        if not self.account_registry.is_muted(account.self_id, group_id):
            return False
        logger.debug(
            "Ignore event for muted account={} group={} protocol_type={}",
            account.self_id,
            group_id,
            getattr(event, "_type", "-"),
        )
        return True

    def guard(
        self,
        callback: Callable[[Account, Event], Awaitable[Any]],
    ) -> Callable[[Account, Event], Awaitable[Any]]:
        """在 Entari 发布事件前阻断被禁言账号的整个事件分发链。

        这是宿主与 Entari 原生 ``event_callbacks`` 之间的边界：插件仍由
        Entari 负责发布和生命周期管理，Tenko 只在进入发布链前执行账号×群
        禁言判定，避免只过滤固定回复而让其他插件继续处理同一事件。
        """

        async def dispatch(account: Account, event: Event) -> Any:
            if self.should_skip(account, event):
                return None
            return await callback(account, event)

        return dispatch

    async def handle(self, account: Account, event: Event) -> None:
        if self.should_skip(account, event):
            return

        try:
            context = MessageContext.from_event(event)
        except ValueError:
            logger.exception("Invalid message event received; event was ignored")
            return

        if context.user_id == account.self_id:
            logger.debug(
                "Ignore message sent by the bot itself: {}", context.message_id
            )
            return

        if (
            context.chat_type == "group"
            and self.account_registry is not None
            and self.account_registry.get(account.self_id) is not None
        ):
            self.account_registry.bind_group(context.channel_id, account)

        logger.info(
            "Message received: account={} chat={} channel={} user={} message={} "
            "text={!r} images={} protocol_type={}",
            context.account_id,
            context.chat_type,
            context.channel_id,
            context.user_id,
            context.message_id,
            context.text,
            len(context.image_urls),
            context.protocol_event_type or "-",
        )

        if not self.send_replies:
            logger.info("Fixed reply is disabled; no OneBot action will be sent")
            return

        try:
            receipts = await account.protocol.send(event, self.reply_text)
        except ActionFailed as error:
            if (
                context.chat_type == "group"
                and self.account_registry is not None
                and self.account_registry.get(account.self_id) is not None
                and self.account_registry.observe_send_failure(
                    account, context.channel_id, error
                )
            ):
                logger.warning(
                    "Group send failed for account={} group={}; marked muted "
                    "until an explicit recovery or expiry",
                    account.self_id,
                    context.channel_id,
                )
            logger.exception(
                "Failed to send fixed reply for message {}", context.message_id
            )
            return
        except Exception:
            logger.exception(
                "Failed to send fixed reply for message {}", context.message_id
            )
            return

        logger.info(
            "Fixed reply sent: account={} message={} receipts={}",
            context.account_id,
            context.message_id,
            len(receipts),
        )
