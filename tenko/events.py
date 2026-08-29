from __future__ import annotations

from dataclasses import dataclass

from loguru import logger
from satori.client import Account
from satori.model import Event

from .context import MessageContext


@dataclass(frozen=True, slots=True)
class MessageEventHandler:
    """最小消息闭环的事件层处理器。"""

    send_replies: bool
    reply_text: str

    async def handle(self, account: Account, event: Event) -> None:
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
