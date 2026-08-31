from __future__ import annotations

import time
from collections import deque
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from arclet.entari import SendResponse
import arclet.letoderea as le
from loguru import logger
from satori import ChannelType, EventType
from satori.client import Account
from satori.model import Event

from .config import DebugConfig
from .context import MessageContext, is_message_created
from .host.accounts import AccountRegistry


def _event_group_id(event: Event) -> str | None:
    """从标准 Satori 字段或 OneBot 原始数据中提取群 ID。"""

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
    if user_id is not None:
        return str(user_id)
    raw_data = getattr(event, "_data", None)
    if (
        isinstance(raw_data, Mapping)
        and (user_id := raw_data.get("user_id")) is not None
    ):
        return str(user_id)
    return None


def _event_message_id(event: Event) -> str | None:
    message = getattr(event, "message", None)
    message_id = getattr(message, "id", None)
    return None if message_id is None else str(message_id)


def _event_type_value(event: Event) -> str:
    event_type = getattr(event, "type", "")
    return str(getattr(event_type, "value", event_type))


_MEMBER_REMOVAL_EVENT_TYPES = {
    EventType.GUILD_MEMBER_REMOVED.value,
    EventType.GUILD_REMOVED.value,
}
_MEMBER_REMOVAL_PROTOCOL_TYPES = {
    "notice.group_decrease.leave",
    "notice.group_decrease.kick",
    "notice.group_decrease.kick_me",
}
_GUILD_INVITE_EVENT_TYPES = {EventType.GUILD_REQUEST.value}
_GUILD_INVITE_PROTOCOL_TYPES = {"request.group.invite"}
_RECEIVED_EVENT_CACHE_SIZE = 8192


def _is_member_removed_event(event: Event) -> bool:
    return (
        _event_type_value(event) in _MEMBER_REMOVAL_EVENT_TYPES
        or str(getattr(event, "_type", "") or "") in _MEMBER_REMOVAL_PROTOCOL_TYPES
    )


def _is_guild_invite_request_event(event: Event) -> bool:
    return (
        _event_type_value(event) in _GUILD_INVITE_EVENT_TYPES
        or str(getattr(event, "_type", "") or "") in _GUILD_INVITE_PROTOCOL_TYPES
    )


def _compact_text(value: object, limit: int = 160) -> str:
    """将消息内容压缩到可安全放入日志和异常报告的一行。"""

    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return f"{text[: limit - 1]}…"


def _message_timestamp(value: object | None) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class MessageLog:
    """一条供状态查询和异常报告使用的轻量消息记录。"""

    timestamp: datetime
    direction: str
    account_id: str
    platform: str
    chat_type: str
    channel_id: str
    user_id: str | None
    message_id: str | None
    text: str
    event_type: str | None = None

    def summary(self) -> str:
        """返回不包含换行且长度受限的审计摘要。"""

        direction = "收" if self.direction == "received" else "发"
        target = self.channel_id
        if self.chat_type == "private":
            target = f"私聊:{target}"
        elif self.chat_type == "group":
            target = f"群:{target}"
        user = f" user={self.user_id}" if self.user_id else ""
        content = _compact_text(self.text) or "<空消息>"
        return (
            f"{self.timestamp.isoformat(timespec='seconds')} {direction}"
            f" account={self.account_id} {target}{user}"
            f" message={self.message_id or '-'} text={content}"
        )


@dataclass(slots=True)
class MessageMetrics:
    """维护消息总数、滑动速率和有限长度的消息环形缓冲。"""

    buffer_size: int = 10
    rate_window_seconds: float = 60.0
    clock: Callable[[], float] = time.monotonic
    _received_count: int = field(init=False, default=0, repr=False)
    _sent_count: int = field(init=False, default=0, repr=False)
    _received_timestamps: deque[float] = field(init=False, repr=False)
    _sent_timestamps: deque[float] = field(init=False, repr=False)
    _recent: deque[MessageLog] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if type(self.buffer_size) is not int or self.buffer_size <= 0:
            raise ValueError("message buffer_size 必须是正整数")
        if self.rate_window_seconds <= 0:
            raise ValueError("message rate_window_seconds 必须大于 0")
        # 速率样本也必须是有上限的；单次发送回执通常只有一条，8192 条
        # 足以覆盖短时间突发，同时不会让状态对象随消息数无限增长。
        self._received_timestamps = deque(maxlen=8192)
        self._sent_timestamps = deque(maxlen=8192)
        self._recent = deque(maxlen=self.buffer_size)

    @property
    def received_count(self) -> int:
        return self._received_count

    @property
    def sent_count(self) -> int:
        return self._sent_count

    @property
    def recent_messages(self) -> tuple[MessageLog, ...]:
        """按时间顺序返回当前环形缓冲快照。"""

        return tuple(self._recent)

    @property
    def latest_received(self) -> MessageLog | None:
        for record in reversed(self._recent):
            if record.direction == "received":
                return record
        return None

    def configure_buffer(self, buffer_size: int) -> None:
        if type(buffer_size) is not int or buffer_size <= 0:
            raise ValueError("message buffer_size 必须是正整数")
        self.buffer_size = buffer_size
        self._recent = deque(self._recent, maxlen=buffer_size)

    def _trim_rates(self, now: float, window_seconds: float) -> None:
        cutoff = now - window_seconds
        for samples in (self._received_timestamps, self._sent_timestamps):
            while samples and samples[0] < cutoff:
                samples.popleft()

    def rates(self, window_seconds: float | None = None) -> tuple[int, int]:
        """返回窗口内的收发数量，调用方可格式化为每分钟速率。"""

        window = self.rate_window_seconds if window_seconds is None else window_seconds
        if window <= 0:
            raise ValueError("rate window 必须大于 0")
        now = self.clock()
        self._trim_rates(now, window)
        return len(self._received_timestamps), len(self._sent_timestamps)

    def record_received(
        self, context: MessageContext, *, timestamp: object | None = None
    ) -> None:
        now = self.clock()
        self._received_count += 1
        self._received_timestamps.append(now)
        text = _compact_text(context.text)
        if not text and context.image_urls:
            text = f"[图片×{len(context.image_urls)}]"
        self._recent.append(
            MessageLog(
                timestamp=_message_timestamp(timestamp),
                direction="received",
                account_id=str(context.account_id),
                platform=str(context.platform),
                chat_type=context.chat_type,
                channel_id=str(context.channel_id),
                user_id=str(context.user_id),
                message_id=str(context.message_id),
                text=text,
                event_type=context.protocol_event_type or context.event_type,
            )
        )

    def record_sent(
        self,
        *,
        account_id: str,
        platform: str,
        chat_type: str,
        channel_id: str,
        text: object,
        count: int = 1,
        user_id: str | None = None,
        message_id: str | None = None,
        event_type: str | None = None,
        timestamp: object | None = None,
    ) -> None:
        if type(count) is not int or count <= 0:
            raise ValueError("sent message count 必须是正整数")
        now = self.clock()
        self._sent_count += count
        for _ in range(count):
            self._sent_timestamps.append(now)
        self._recent.append(
            MessageLog(
                timestamp=_message_timestamp(timestamp),
                direction="sent",
                account_id=str(account_id),
                platform=str(platform),
                chat_type=chat_type,
                channel_id=str(channel_id),
                user_id=None if user_id is None else str(user_id),
                message_id=None if message_id is None else str(message_id),
                text=_compact_text(text),
                event_type=event_type,
            )
        )

    def record_sent_for_context(
        self,
        context: MessageContext,
        text: object,
        *,
        count: int = 1,
        message_id: str | None = None,
    ) -> None:
        self.record_sent(
            account_id=context.account_id,
            platform=context.platform,
            chat_type=context.chat_type,
            channel_id=context.channel_id,
            user_id=None,
            message_id=message_id,
            text=text,
            count=count,
            event_type="message_sent",
        )

    def record_send_response(self, response: SendResponse) -> None:
        """消费 Entari ``after_send``，覆盖插件通过 ``Session.send`` 的发送。"""

        account = getattr(response, "account", None)
        account_id = str(getattr(account, "self_id", "-"))
        platform = str(getattr(account, "platform", "unknown"))
        channel_id = str(getattr(response, "channel", "-"))
        chat_type = "private" if channel_id.startswith("private:") else "group"
        session = getattr(response, "session", None)
        event = getattr(session, "event", None)
        origin = getattr(event, "_origin", event)
        try:
            context = MessageContext.from_event(origin)
        except (AttributeError, TypeError, ValueError):
            context = None
        if context is not None:
            platform = context.platform
            chat_type = context.chat_type
            channel_id = context.channel_id

        message = getattr(response, "message", "")
        display = getattr(message, "display", None)
        text = display() if callable(display) else str(message)
        result = getattr(response, "result", ())
        try:
            result_items = tuple(result or ())
        except TypeError:
            result_items = ()
        message_id = (
            str(getattr(result_items[-1], "id", ""))
            if result_items and getattr(result_items[-1], "id", None) is not None
            else None
        )
        self.record_sent(
            account_id=account_id,
            platform=platform,
            chat_type=chat_type,
            channel_id=channel_id,
            user_id=None,
            message_id=message_id,
            text=text,
            count=max(len(result_items), 1),
            event_type="entari.after_send",
        )


message_metrics = MessageMetrics()


def configure_message_metrics(buffer_size: int) -> MessageMetrics:
    """应用配置并返回宿主共享的消息统计对象。"""

    message_metrics.configure_buffer(buffer_size)
    return message_metrics


@le.on(SendResponse)
async def _record_entari_send(event: SendResponse) -> None:
    # Entari 的 Session.send 在 action 成功后发布 SendResponse；插件发送
    # 不会经过 Account.protocol.send，因此在这里补齐出站统计和取证日志。
    message_metrics.record_send_response(event)


@dataclass(slots=True)
class MessageEventHandler:
    """最小消息闭环及事件入口过滤处理器。"""

    account_registry: AccountRegistry | None = None
    debug_config: DebugConfig = DebugConfig()
    command_policy: Any | None = None
    command_prefix: str = "/"
    metrics: MessageMetrics | None = None
    action_service: Any | None = None
    # 在有界缓存中保留 origin 引用，确保在重复检查前，object ID 不会被其他
    # 事件复用。
    _received_event_cache: deque[tuple[int, object]] = field(
        init=False,
        default_factory=lambda: deque(maxlen=_RECEIVED_EVENT_CACHE_SIZE),
        repr=False,
        compare=False,
    )
    _received_event_ids: set[int] = field(
        init=False,
        default_factory=set,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if self.metrics is None:
            self.metrics = message_metrics
        if self.debug_config.enabled and not self.debug_config.masters:
            logger.warning(
                "Debug mode is enabled but no masters are configured; "
                "all events will be ignored"
            )

    def should_skip(self, account: Account, event: Event) -> bool:
        """判断事件是否应在进入消息和插件处理前被跳过。"""

        # 群成员减少和 bot 邀请都是账号状态来源，不能被调试白名单或账号×群
        # 选路过滤；否则解绑监听器收不到事件，或者邀请恰好由非选中账号收到时
        # 会被丢弃。
        if _is_member_removed_event(event) or _is_guild_invite_request_event(event):
            return False

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

        # 消息事件可能是启动时群列表发现之前抵达的第一条消息。事件本身
        # 证明账号当前在线，因此先登记账号并加入当前群路由，再执行统一
        # 选路；这样群列表拉取失败时仍保留消息触发绑定的兜底路径。
        if self.account_registry.get(account.self_id) is None:
            self.account_registry.register(account, available=True)
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
            self._record_received_event(event)
            if self.should_skip(account, event):
                return None
            if self.command_policy is not None:
                notice = await self.command_policy.check(account, event)
                if notice:
                    try:
                        receipts = await account.protocol.send(event, notice)
                        self._record_sent_for_event(account, event, notice, receipts)
                    except Exception:
                        logger.exception("Failed to send command policy notice")
                    return None
            return await callback(account, event)

        return dispatch

    async def handle(self, account: Account, event: Event) -> None:
        self._record_received_event(event)
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

    async def handle_member_removed(self, account: Account, event: Event) -> None:
        """消费群成员减少事件并立即解除被移除账号的群路由。"""

        if self.account_registry is None or not _is_member_removed_event(event):
            return
        group_id = _event_group_id(event)
        member_id = _event_user_id(event)
        if group_id is None or member_id is None:
            logger.debug(
                "Ignore member-removed event without group/member: account={} "
                "group={} member={} protocol_type={}",
                account.self_id,
                group_id,
                member_id,
                getattr(event, "_type", "-"),
            )
            return

        removed_account = self.account_registry.get(member_id)
        if removed_account is None:
            # 普通成员退群不能影响任何账号×群路由。
            return
        # 让 AccountRegistry.unbind_group() 统一处理 deterministic：指定账号
        # 被移除后回退到剩余成员首个账号；群无成员时同时删除群路由状态。
        if not self.account_registry.unbind_group(group_id, member_id):
            return

        protocol_type = str(getattr(event, "_type", "") or "")
        kicked = protocol_type.endswith(".kick") or protocol_type.endswith(".kick_me")
        action = "被踢出" if kicked else "退出"
        logger.info(
            "Unbound account={} from group={} after bot {}",
            member_id,
            group_id,
            action,
        )

        if not kicked or self.action_service is None:
            return
        verify = getattr(self.action_service, "verify_group_membership", None)
        if not callable(verify):
            return
        try:
            still_member = await verify(removed_account, group_id)
        except Exception as error:
            # 事件已提供权威的解绑信号；群信息查询只是被踢场景的可选
            # 二次确认，权限不足或连接失败不能阻塞实时路由收缩。
            logger.debug(
                "Could not verify kicked account membership: account={} group={} "
                "error={}",
                member_id,
                group_id,
                error,
            )
        else:
            logger.debug(
                "Verified kicked account membership: account={} group={} "
                "still_member={}",
                member_id,
                group_id,
                still_member,
            )

    def _record_received_event(
        self, event: Event, context: MessageContext | None = None
    ) -> None:
        if self.metrics is None or not is_message_created(event):
            return
        origin = getattr(event, "_origin", None)
        if origin is None:
            origin = event
        origin_id = id(origin)
        if origin_id in self._received_event_ids:
            return
        if context is None:
            try:
                context = MessageContext.from_event(event)
            except (AttributeError, TypeError, ValueError):
                return
        self.metrics.record_received(
            context, timestamp=getattr(event, "timestamp", None)
        )
        if len(self._received_event_cache) == _RECEIVED_EVENT_CACHE_SIZE:
            expired_id, _ = self._received_event_cache.popleft()
            self._received_event_ids.discard(expired_id)
        self._received_event_cache.append((origin_id, origin))
        self._received_event_ids.add(origin_id)

    @staticmethod
    def _receipt_count(receipts: object) -> int:
        try:
            return max(len(receipts), 1)  # type: ignore[arg-type]
        except TypeError:
            return 1

    def _record_sent_for_context(
        self,
        context: MessageContext,
        text: object,
        receipts: object,
    ) -> None:
        if self.metrics is None:
            return
        message_id = None
        try:
            result = tuple(receipts or ())  # type: ignore[arg-type]
        except TypeError:
            result = ()
        if result and getattr(result[-1], "id", None) is not None:
            message_id = str(result[-1].id)
        self.metrics.record_sent_for_context(
            context,
            text,
            count=self._receipt_count(receipts),
            message_id=message_id,
        )

    def _record_sent_for_event(
        self,
        account: Account,
        event: Event,
        text: object,
        receipts: object,
    ) -> None:
        if self.metrics is None:
            return
        try:
            context = MessageContext.from_event(event)
        except (AttributeError, TypeError, ValueError):
            channel_id = _event_group_id(event) or getattr(
                getattr(event, "channel", None), "id", "-"
            )
            self.metrics.record_sent(
                account_id=str(account.self_id),
                platform=str(getattr(account, "platform", "unknown")),
                chat_type="group" if _event_group_id(event) else "other",
                channel_id=str(channel_id),
                text=text,
                count=self._receipt_count(receipts),
            )
            return
        self._record_sent_for_context(context, text, receipts)
