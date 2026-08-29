from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock

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

from tenko.events import MessageEventHandler
from tenko.host.accounts import AccountRegistry


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


def make_private_event() -> Event:
    return Event(
        type=EventType.MESSAGE_CREATED,
        timestamp=datetime.now(),
        login=Login(platform="onebot", user=User("10001")),
        channel=Channel("private:20001", ChannelType.DIRECT),
        user=User("20001"),
        message=MessageObject("30001", "hello"),
    )


def make_group_event(group_id: str = "40001") -> Event:
    return Event(
        type=EventType.MESSAGE_CREATED,
        timestamp=datetime.now(),
        login=Login(platform="onebot", user=User("10001")),
        channel=Channel(group_id, ChannelType.TEXT),
        guild=Guild(group_id, "Tenko"),
        user=User("20001"),
        message=MessageObject("30001", "hello"),
    )


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
