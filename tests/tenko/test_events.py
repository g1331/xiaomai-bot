from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from satori import (
    Channel,
    ChannelType,
    EventType,
    Guild,
    Login,
    MessageObject,
    User,
)
from satori.exception import ActionFailed
from satori.model import Event

import tenko.events as events_module
import tenko.host.accounts as accounts_module
from tenko.context import MessageContext
from tenko.events import MessageEventHandler, MessageMetrics
from tenko.host.accounts import AccountRegistry
from tenko.host.features import CommandPolicy, FeatureService
from tenko.host.perm import PermissionChecker, PermissionRegistry
from tenko.host.ratelimit import RateLimitService
from tenko.config import DebugConfig


class FakeProtocol:
    def __init__(self, failure: BaseException | None = None) -> None:
        self.calls: list[tuple[Event, str]] = []
        self.failure = failure

    async def send(self, event: Event, message: str) -> list[MessageObject]:
        self.calls.append((event, message))
        if self.failure is not None:
            raise self.failure
        return [MessageObject("90001", message)]


class FakeAccount:
    self_id = "10001"

    def __init__(self) -> None:
        self.protocol = FakeProtocol()


class RoutedFakeAccount:
    def __init__(self, self_id: str) -> None:
        self.self_id = self_id


def make_private_event(user_id: str = "20001", text: str = "hello") -> Event:
    return Event(
        type=EventType.MESSAGE_CREATED,
        timestamp=datetime.now(),
        login=Login(platform="onebot", user=User("10001")),
        channel=Channel("private:20001", ChannelType.DIRECT),
        user=User(user_id),
        message=MessageObject("30001", text),
    )


def make_group_event(
    group_id: str = "40001", user_id: str = "20001", text: str = "hello"
) -> Event:
    return Event(
        type=EventType.MESSAGE_CREATED,
        timestamp=datetime.now(),
        login=Login(platform="onebot", user=User("10001")),
        channel=Channel(group_id, ChannelType.TEXT),
        guild=Guild(group_id, "Tenko"),
        user=User(user_id),
        message=MessageObject("30001", text),
    )


def make_userless_event() -> Event:
    return Event(
        type=EventType.GUILD_ADDED,
        timestamp=datetime.now(),
        login=Login(platform="onebot", user=User("10001")),
        guild=Guild("40001", "Tenko"),
    )


def make_member_removed_event(
    *,
    account_id: str = "10001",
    group_id: str = "40001",
    member_id: str = "10001",
    protocol_type: str = "notice.group_decrease.leave",
) -> Event:
    return Event(
        type=EventType.GUILD_MEMBER_REMOVED,
        timestamp=datetime.now(),
        login=Login(platform="onebot", user=User(account_id)),
        channel=Channel(group_id, ChannelType.TEXT),
        guild=Guild(group_id, "Tenko"),
        user=User(member_id),
        _type=protocol_type,
        _data={"group_id": group_id, "user_id": member_id},
    )


def make_context(text: str = "hello") -> MessageContext:
    return MessageContext(
        account_id="10001",
        event_type="message-created",
        protocol_event_type="message.group.normal",
        chat_type="group",
        channel_id="40001",
        user_id="20001",
        message_id="30001",
        text=text,
        image_urls=(),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "event_factory", [make_private_event, make_group_event], ids=["private", "group"]
)
@pytest.mark.parametrize(
    ("enabled", "user_id", "masters", "should_send"),
    [
        (False, "20001", ["20001"], True),
        (False, "30001", ["20001"], True),
        (True, "20001", ["20001"], True),
        (True, "30001", ["20001"], False),
    ],
)
async def test_debug_filter_matrix(
    event_factory,
    enabled: bool,
    user_id: str,
    masters: list[str],
    should_send: bool,
) -> None:
    account = FakeAccount()
    handler = MessageEventHandler(
        send_replies=True,
        reply_text="收到",
        debug_config=DebugConfig(enabled=enabled, masters=masters),
    )

    await handler.handle(account, event_factory(user_id=user_id))

    assert bool(account.protocol.calls) is should_send


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["hello", "/状态"], ids=["message", "command"])
async def test_debug_filter_applies_to_non_master_messages_and_commands(
    text: str,
) -> None:
    account = FakeAccount()
    handler = MessageEventHandler(
        send_replies=True,
        reply_text="收到",
        debug_config=DebugConfig(enabled=True, masters=["20001"]),
    )

    await handler.handle(account, make_group_event(user_id="30001", text=text))

    assert account.protocol.calls == []


def test_debug_mode_without_masters_warns(monkeypatch) -> None:
    warning = Mock()
    monkeypatch.setattr(events_module.logger, "warning", warning)

    handler = MessageEventHandler(
        send_replies=False,
        reply_text="收到",
        debug_config=DebugConfig(enabled=True),
    )

    assert handler.should_skip(FakeAccount(), make_private_event())
    warning.assert_called_once()
    assert "masters" in warning.call_args.args[0]


@pytest.mark.asyncio
async def test_disabled_reply_only_logs_and_does_not_send() -> None:
    account = FakeAccount()
    handler = MessageEventHandler(send_replies=False, reply_text="收到")

    await handler.handle(account, make_private_event())

    assert account.protocol.calls == []


@pytest.mark.asyncio
async def test_enabled_reply_sends_fixed_message() -> None:
    account = FakeAccount()
    event = make_private_event()
    handler = MessageEventHandler(send_replies=True, reply_text="Tenko 已收到消息。")

    await handler.handle(account, event)

    assert account.protocol.calls == [(event, "Tenko 已收到消息。")]


@pytest.mark.asyncio
async def test_self_message_is_ignored() -> None:
    account = FakeAccount()
    event = make_private_event()
    event.user = User(account.self_id)
    handler = MessageEventHandler(send_replies=True, reply_text="收到")

    await handler.handle(account, event)

    assert account.protocol.calls == []


@pytest.mark.asyncio
async def test_muted_group_event_is_skipped_before_message_handling() -> None:
    account = FakeAccount()
    registry = AccountRegistry()
    registry.register(account, groups=[40001])
    registry.set_muted(account, 40001, True)
    handler = MessageEventHandler(
        send_replies=True,
        reply_text="收到",
        account_registry=registry,
    )

    await handler.handle(account, make_group_event())

    assert account.protocol.calls == []


@pytest.mark.asyncio
async def test_group_send_failure_marks_account_muted_and_blocks_next_event() -> None:
    failure = ActionFailed("1200: failed", {"status": "failed", "retcode": 1200})
    account = FakeAccount()
    account.protocol = FakeProtocol(failure=failure)
    registry = AccountRegistry()
    registry.register(account, groups=[40001])
    handler = MessageEventHandler(
        send_replies=True,
        reply_text="收到",
        account_registry=registry,
    )

    await handler.handle(account, make_group_event())
    account.protocol.failure = None
    await handler.handle(account, make_group_event())

    assert registry.is_muted(account, 40001)
    assert len(account.protocol.calls) == 1


@pytest.mark.asyncio
async def test_non_action_send_failure_does_not_mark_group_muted() -> None:
    account = FakeAccount()
    account.protocol = FakeProtocol(failure=RuntimeError("network down"))
    registry = AccountRegistry()
    registry.register(account, groups=[40001])
    handler = MessageEventHandler(
        send_replies=True,
        reply_text="收到",
        account_registry=registry,
    )

    await handler.handle(account, make_group_event())

    assert not registry.is_muted(account, 40001)


@pytest.mark.asyncio
async def test_entari_event_guard_blocks_only_muted_account_group_pair() -> None:
    account = FakeAccount()
    registry = AccountRegistry()
    registry.register(account, groups=[40001, 40002])
    registry.set_muted(account, 40001, True)
    callback = AsyncMock()
    handler = MessageEventHandler(
        send_replies=False,
        reply_text="收到",
        account_registry=registry,
    )
    guarded = handler.guard(callback)
    other_group_event = make_group_event("40002")

    await guarded(account, make_group_event("40001"))
    await guarded(account, other_group_event)

    callback.assert_awaited_once_with(account, other_group_event)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "event_factory", [make_private_event, make_group_event], ids=["private", "group"]
)
async def test_entari_event_guard_filters_non_master_events(
    event_factory,
) -> None:
    account = FakeAccount()
    callback = AsyncMock()
    handler = MessageEventHandler(
        send_replies=False,
        reply_text="收到",
        debug_config=DebugConfig(enabled=True, masters=["20001"]),
    )
    guarded = handler.guard(callback)
    non_master_event = event_factory(user_id="30001")
    master_event = event_factory(user_id="20001")

    await guarded(account, non_master_event)
    await guarded(account, master_event)

    callback.assert_awaited_once_with(account, master_event)


@pytest.mark.asyncio
async def test_debug_event_guard_filters_events_without_user_source() -> None:
    account = FakeAccount()
    callback = AsyncMock()
    handler = MessageEventHandler(
        send_replies=False,
        reply_text="收到",
        debug_config=DebugConfig(enabled=True, masters=["20001"]),
    )

    await handler.guard(callback)(account, make_userless_event())

    callback.assert_not_awaited()


def test_debug_filter_does_not_block_member_removal_events() -> None:
    account = FakeAccount()
    handler = MessageEventHandler(
        send_replies=False,
        reply_text="收到",
        debug_config=DebugConfig(enabled=True, masters=["20001"]),
    )

    assert not handler.should_skip(
        account,
        make_member_removed_event(member_id=account.self_id),
    )


@pytest.mark.asyncio
async def test_guild_invite_event_bypasses_account_group_selection() -> None:
    first = RoutedFakeAccount("10001")
    second = RoutedFakeAccount("10002")
    registry = AccountRegistry()
    registry.register(first, groups=[40001])
    registry.register(second, groups=[40001])
    registry.set_response_type(40001, "deterministic")
    registry.set_deterministic_account(40001, second)
    callback = AsyncMock()
    handler = MessageEventHandler(
        send_replies=False,
        reply_text="收到",
        account_registry=registry,
    )
    event = Event(
        type=EventType.GUILD_REQUEST,
        timestamp=datetime.now(),
        login=Login(platform="onebot", user=User(first.self_id)),
        channel=Channel("40001", ChannelType.TEXT),
        guild=Guild("40001", "Tenko"),
        user=User("20001"),
        message=MessageObject("request-1", "邀请机器人"),
        _type="request.group.invite",
        _data={"group_id": "40001", "user_id": "20001", "sub_type": "invite"},
    )

    await handler.guard(callback)(first, event)

    callback.assert_awaited_once_with(first, event)


@pytest.mark.asyncio
async def test_group_event_guard_randomly_selects_one_online_account(
    monkeypatch,
) -> None:
    first = RoutedFakeAccount("10001")
    second = RoutedFakeAccount("10002")
    registry = AccountRegistry()
    registry.register(first, groups=[40001])
    registry.register(second, groups=[40001])
    monkeypatch.setattr(accounts_module.random, "choice", lambda accounts: second)
    callback = AsyncMock()
    handler = MessageEventHandler(
        send_replies=False,
        reply_text="收到",
        account_registry=registry,
    )
    guarded = handler.guard(callback)
    event = make_group_event()

    await guarded(first, event)
    await guarded(second, event)

    callback.assert_awaited_once_with(second, event)


@pytest.mark.asyncio
async def test_group_event_guard_binds_unknown_account_as_message_fallback() -> None:
    account = RoutedFakeAccount("10001")
    registry = AccountRegistry()
    callback = AsyncMock()
    handler = MessageEventHandler(
        send_replies=False,
        reply_text="收到",
        account_registry=registry,
    )
    event = make_group_event()

    await handler.guard(callback)(account, event)

    callback.assert_awaited_once_with(account, event)
    assert registry.get(account.self_id) is account
    assert registry.bound_accounts_for_group("40001") == (account,)


@pytest.mark.asyncio
async def test_group_event_guard_random_falls_back_to_the_only_online_account() -> None:
    first = RoutedFakeAccount("10001")
    second = RoutedFakeAccount("10002")
    registry = AccountRegistry()
    registry.register(first, groups=[40001])
    registry.register(second, available=False, groups=[40001])
    callback = AsyncMock()
    handler = MessageEventHandler(
        send_replies=False,
        reply_text="收到",
        account_registry=registry,
    )

    await handler.guard(callback)(first, make_group_event())
    await handler.guard(callback)(second, make_group_event())

    callback.assert_awaited_once()
    assert callback.await_args.args[0] is first


@pytest.mark.asyncio
@pytest.mark.parametrize("unavailable", [False, True])
async def test_group_event_guard_deterministic_account_is_unique_and_has_no_fallback(
    unavailable: bool,
) -> None:
    first = RoutedFakeAccount("10001")
    second = RoutedFakeAccount("10002")
    registry = AccountRegistry()
    registry.register(first, groups=[40001])
    registry.register(second, available=not unavailable, groups=[40001])
    registry.set_response_type(40001, "deterministic")
    registry.set_deterministic_account(40001, second)
    callback = AsyncMock()
    handler = MessageEventHandler(
        send_replies=False,
        reply_text="收到",
        account_registry=registry,
    )

    await handler.guard(callback)(first, make_group_event())
    await handler.guard(callback)(second, make_group_event())

    if unavailable:
        callback.assert_not_awaited()
    else:
        callback.assert_awaited_once()
        assert callback.await_args.args[0] is second


@pytest.mark.asyncio
async def test_group_event_guard_deterministic_muted_account_has_no_fallback() -> None:
    first = RoutedFakeAccount("10001")
    second = RoutedFakeAccount("10002")
    registry = AccountRegistry()
    registry.register(first, groups=[40001])
    registry.register(second, groups=[40001])
    registry.set_response_type(40001, "deterministic")
    registry.set_deterministic_account(40001, second)
    registry.set_muted(second, 40001, True)
    callback = AsyncMock()
    handler = MessageEventHandler(
        send_replies=False,
        reply_text="收到",
        account_registry=registry,
    )

    await handler.guard(callback)(first, make_group_event())
    await handler.guard(callback)(second, make_group_event())

    callback.assert_not_awaited()


@pytest.mark.asyncio
async def test_muted_account_can_receive_only_its_recovery_command() -> None:
    account = FakeAccount()
    registry = AccountRegistry()
    registry.register(account, groups=[40001])
    registry.set_muted(account, 40001, True)
    callback = AsyncMock()
    handler = MessageEventHandler(
        send_replies=False,
        reply_text="收到",
        account_registry=registry,
    )
    guarded = handler.guard(callback)

    await guarded(account, make_group_event(text="/解禁自己"))
    await guarded(account, make_group_event(text="/帮助"))

    callback.assert_awaited_once()
    assert callback.await_args.args[1].message.content == "/解禁自己"


@pytest.mark.asyncio
async def test_command_guard_blocks_disabled_plugin_and_allows_after_enable() -> None:
    class FakePluginRuntime:
        def command_owner(self, text: str):
            return (
                type("Owner", (), {"name": "demo", "display_name": "演示"})()
                if text.startswith("/演示")
                else None
            )

    features = FeatureService()
    features.disable("demo", "40001")
    policy = CommandPolicy(features, plugin_runtime=FakePluginRuntime())
    callback = AsyncMock()
    account = FakeAccount()
    handler = MessageEventHandler(
        send_replies=False,
        reply_text="收到",
        command_policy=policy,
    )

    await handler.guard(callback)(account, make_group_event(text="/演示"))

    callback.assert_not_awaited()
    assert account.protocol.calls[-1][1].startswith("演示插件已关闭")

    features.enable("demo", "40001")
    await handler.guard(callback)(account, make_group_event(text="/演示"))

    callback.assert_awaited_once()

    features.set_maintenance("demo", True)
    await handler.guard(callback)(account, make_group_event(text="/演示"))

    callback.assert_awaited_once()
    assert account.protocol.calls[-1][1] == "演示插件正在维护~"


@pytest.mark.asyncio
async def test_command_guard_applies_rate_limit_before_entari_dispatch() -> None:
    class FakePluginRuntime:
        def command_owner(self, text: str):
            return type("Owner", (), {"name": "demo", "display_name": "演示"})()

    limiter = RateLimitService(
        max_weight=2,
        cooldown_seconds=10,
        blacklist_seconds=0,
    )
    policy = CommandPolicy(
        FeatureService(),
        limiter,
        plugin_runtime=FakePluginRuntime(),
        permission_checker=PermissionChecker(registry=PermissionRegistry()),
    )
    callback = AsyncMock()
    account = FakeAccount()
    handler = MessageEventHandler(
        send_replies=False,
        reply_text="收到",
        command_policy=policy,
    )
    guarded = handler.guard(callback)

    await guarded(account, make_group_event(text="/演示"))
    await guarded(account, make_group_event(text="/演示"))

    callback.assert_awaited_once()
    assert "超过频率调用限制" in account.protocol.calls[-1][1]


def test_message_metrics_counts_rates_and_evicts_oldest_records() -> None:
    current = [0.0]
    metrics = MessageMetrics(
        buffer_size=2,
        rate_window_seconds=3.0,
        clock=lambda: current[0],
    )

    metrics.record_received(make_context("first"))
    current[0] = 1.0
    metrics.record_received(make_context("second"))
    current[0] = 2.0
    metrics.record_received(make_context("third"))
    metrics.record_sent(
        account_id="10001",
        platform="onebot",
        chat_type="group",
        channel_id="40001",
        text="reply",
        count=2,
    )

    assert metrics.received_count == 3
    assert metrics.sent_count == 2
    assert [record.text for record in metrics.recent_messages] == ["third", "reply"]
    assert metrics.rates() == (3, 2)
    current[0] = 5.0
    assert metrics.rates() == (1, 2)


def test_message_metrics_records_entari_plugin_send_response() -> None:
    metrics = MessageMetrics()
    response = SimpleNamespace(
        account=SimpleNamespace(self_id="10001", platform="onebot"),
        channel="40001",
        message=SimpleNamespace(display=lambda: "plugin reply"),
        result=[MessageObject("90001", "plugin reply")],
        session=None,
    )

    metrics.record_send_response(response)

    assert metrics.sent_count == 1
    record = metrics.recent_messages[0]
    assert record.direction == "sent"
    assert record.text == "plugin reply"
    assert record.message_id == "90001"


@pytest.mark.asyncio
async def test_message_handler_records_received_and_fixed_reply() -> None:
    metrics = MessageMetrics(buffer_size=10)
    account = FakeAccount()
    handler = MessageEventHandler(
        send_replies=True,
        reply_text="收到",
        metrics=metrics,
    )

    await handler.handle(account, make_private_event(text="hello"))

    assert metrics.received_count == 1
    assert metrics.sent_count == 1
    assert [record.direction for record in metrics.recent_messages] == [
        "received",
        "sent",
    ]


def test_image_only_message_is_visible_in_message_evidence() -> None:
    context = MessageContext(
        account_id="10001",
        event_type="message-created",
        protocol_event_type="message.group.normal",
        chat_type="group",
        channel_id="40001",
        user_id="20001",
        message_id="30001",
        text="",
        image_urls=("https://example.invalid/image.png",),
    )
    metrics = MessageMetrics()

    metrics.record_received(context)

    assert metrics.recent_messages[0].text == "[图片×1]"


def test_send_response_with_non_iterable_result_still_records_one_message() -> None:
    metrics = MessageMetrics()
    response = SimpleNamespace(
        account=SimpleNamespace(self_id="10001", platform="onebot"),
        channel="40001",
        message=SimpleNamespace(display=lambda: "plugin reply"),
        result=object(),
        session=None,
    )

    metrics.record_send_response(response)

    assert metrics.sent_count == 1
    assert metrics.recent_messages[0].text == "plugin reply"


@pytest.mark.asyncio
async def test_member_leave_unbinds_self_but_preserves_other_groups() -> None:
    account = RoutedFakeAccount("10001")
    registry = AccountRegistry()
    registry.register(account, groups=[40001, 40002])
    handler = MessageEventHandler(
        send_replies=False,
        reply_text="收到",
        account_registry=registry,
    )

    await handler.handle_member_removed(
        account,
        make_member_removed_event(group_id="40001", member_id="10001"),
    )

    assert registry.get(account.self_id) is account
    assert registry.groups_for_account(account) == ("40002",)
    assert registry.bound_accounts_for_group("40001") == ()


@pytest.mark.asyncio
async def test_member_leave_for_other_user_does_not_change_account_routes() -> None:
    account = RoutedFakeAccount("10001")
    registry = AccountRegistry()
    registry.register(account, groups=[40001])
    handler = MessageEventHandler(
        send_replies=False,
        reply_text="收到",
        account_registry=registry,
    )

    await handler.handle_member_removed(
        account,
        make_member_removed_event(group_id="40001", member_id="20001"),
    )

    assert registry.groups_for_account(account) == ("40001",)
    assert registry.bound_accounts_for_group("40001") == (account,)


@pytest.mark.asyncio
async def test_unbinding_deterministic_account_uses_registry_fallback() -> None:
    first = RoutedFakeAccount("10001")
    second = RoutedFakeAccount("10002")
    registry = AccountRegistry()
    registry.register(first, groups=[40001])
    registry.register(second, groups=[40001])
    registry.set_response_type(40001, "deterministic")
    registry.set_deterministic_account(40001, second)
    handler = MessageEventHandler(
        send_replies=False,
        reply_text="收到",
        account_registry=registry,
    )

    await handler.handle_member_removed(
        first,
        make_member_removed_event(
            account_id="10002",
            group_id="40001",
            member_id="10002",
        ),
    )

    assert registry.deterministic_account_for_group("40001") == "10001"
    assert registry.accounts_for_group("40001") == (first,)


@pytest.mark.asyncio
async def test_unbound_group_can_be_rebound_by_message_fallback() -> None:
    account = RoutedFakeAccount("10001")
    registry = AccountRegistry()
    registry.register(account, groups=[40001])
    handler = MessageEventHandler(
        send_replies=False,
        reply_text="收到",
        account_registry=registry,
    )
    await handler.handle_member_removed(
        account,
        make_member_removed_event(member_id="10001"),
    )
    callback = AsyncMock()

    await handler.guard(callback)(account, make_group_event())

    callback.assert_awaited_once()
    assert registry.bound_accounts_for_group("40001") == (account,)


@pytest.mark.asyncio
async def test_kicked_account_route_shrinks_before_optional_membership_check() -> None:
    account = RoutedFakeAccount("10001")
    registry = AccountRegistry()
    registry.register(account, groups=[40001])
    actions = Mock()
    actions.verify_group_membership = AsyncMock(return_value=False)
    handler = MessageEventHandler(
        send_replies=False,
        reply_text="收到",
        account_registry=registry,
        action_service=actions,
    )

    await handler.handle_member_removed(
        account,
        make_member_removed_event(
            member_id="10001",
            protocol_type="notice.group_decrease.kick",
        ),
    )

    assert registry.bound_accounts_for_group("40001") == ()
    actions.verify_group_membership.assert_awaited_once_with(account, "40001")


@pytest.mark.asyncio
async def test_raw_internal_member_leave_is_handled_when_adapter_enrichment_fails() -> (
    None
):
    account = RoutedFakeAccount("10001")
    registry = AccountRegistry()
    registry.register(account, groups=[40001])
    handler = MessageEventHandler(
        send_replies=False,
        reply_text="收到",
        account_registry=registry,
    )
    event = make_member_removed_event(
        protocol_type="notice.group_decrease.kick_me",
    )
    event.type = EventType.INTERNAL
    event.user = None

    await handler.handle_member_removed(account, event)

    assert registry.bound_accounts_for_group("40001") == ()
