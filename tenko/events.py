from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from loguru import logger
from satori import ChannelType
from satori.client import Account
from satori.exception import ActionFailed
from satori.model import Event

from .config import DebugConfig
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


def _event_user_id(event: Event) -> str | None:
    user = getattr(event, "user", None)
    user_id = getattr(user, "id", None)
    return None if user_id is None else str(user_id)


def _event_message_id(event: Event) -> str | None:
    message = getattr(event, "message", None)
    message_id = getattr(message, "id", None)
    return None if message_id is None else str(message_id)


@dataclass(slots=True)
class MessageEventHandler:
    """最小消息闭环及事件入口过滤处理器。"""

    send_replies: bool
    reply_text: str
    account_registry: AccountRegistry | None = None
    debug_config: DebugConfig = DebugConfig()
    command_policy: Any | None = None
    command_prefix: str = "/"

    def __post_init__(self) -> None:
        if self.debug_config.enabled and not self.debug_config.masters:
            logger.warning(
                "Debug mode is enabled but no masters are configured; "
                "all events will be ignored"
            )

    def should_skip(self, account: Account, event: Event) -> bool:
        """判断事件是否应在进入消息和插件处理前被跳过。"""

        if self.debug_config.enabled:
            user_id = _event_user_id(event)
            if user_id not in self.debug_config.masters:
                logger.debug(
                    "Ignore event in debug mode: account={} user_id={} "
                    "protocol_type={}",
                    account.self_id,
                    user_id,
                    getattr(event, "_type", "-"),
                )
                return True

        if (
            self.account_registry is None
            or (group_id := _event_group_id(event)) is None
        ):
            return False

        # 消息事件可能是启动时群列表发现之前抵达的第一条消息。先把事件
        # 所属账号加入当前群路由，再执行统一选路；这样后续账号收到同一条
        # 群消息时会在进入 Entari 原生命令分发前被过滤。
        if self.account_registry.get(account.self_id) is not None:
            self.account_registry.bind_group(group_id, account)

        if not self.account_registry.is_muted(account.self_id, group_id):
            selected = self.account_registry.select_for_event(
                group_id,
                source_id=_event_message_id(event),
            )
            if selected is not None and selected.self_id == account.self_id:
                return False
            if selected is not None:
                logger.debug(
                    "Ignore event for non-selected account={} selected={} group={} "
                    "protocol_type={}",
                    account.self_id,
                    selected.self_id,
                    group_id,
                    getattr(event, "_type", "-"),
                )
            else:
                logger.debug(
                    "Ignore event because no response account is available: "
                    "account={} group={} response_type={} deterministic_account={} "
                    "protocol_type={}",
                    account.self_id,
                    group_id,
                    self.account_registry.response_type_for_group(group_id),
                    self.account_registry.deterministic_account_for_group(group_id),
                    getattr(event, "_type", "-"),
                )
            return True

        if self._is_mute_recovery_event(event):
            logger.debug(
                "Allow mute recovery command for muted account={} group={}",
                account.self_id,
                group_id,
            )
            return False

        logger.debug(
            "Ignore event for muted account={} group={} protocol_type={}",
            account.self_id,
            group_id,
            getattr(event, "_type", "-"),
        )
        return True

    def _is_mute_recovery_event(self, event: Event) -> bool:
        try:
            context = MessageContext.from_event(event)
        except ValueError:
            return False
        return context.text.strip() == f"{self.command_prefix}解禁自己"

    def guard(
        self,
        callback: Callable[[Account, Event], Awaitable[Any]],
    ) -> Callable[[Account, Event], Awaitable[Any]]:
        """在 Entari 发布事件前执行 Tenko 的整个事件过滤链。

        这是宿主与 Entari 原生 ``event_callbacks`` 之间的边界：插件仍由
        Entari 负责发布和生命周期管理，Tenko 在进入发布链前执行调试白名单
        与账号×群禁言判定，避免只过滤固定回复而让其他插件继续处理同一事件。
        """

        async def dispatch(account: Account, event: Event) -> Any:
            if self.should_skip(account, event):
                return None
            if self.command_policy is not None:
                notice = await self.command_policy.check(account, event)
                if notice:
                    try:
                        await account.protocol.send(event, notice)
                    except Exception:
                        logger.exception("Failed to send command policy notice")
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
        if (
            context.chat_type == "group"
            and self.account_registry is not None
            and self.account_registry.get(account.self_id) is not None
            and self.account_registry.is_muted(account, context.channel_id)
        ):
            self.account_registry.set_muted(account, context.channel_id, False)
            logger.info(
                "Cleared stale mute after successful group send: account={} group={}",
                account.self_id,
                context.channel_id,
            )
