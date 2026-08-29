from __future__ import annotations

from datetime import datetime

import pytest
from satori import Channel, ChannelType, EventType, Login, MessageObject, User
from satori.model import Event

from tenko.events import MessageEventHandler


class FakeProtocol:
    def __init__(self) -> None:
        self.calls: list[tuple[Event, str]] = []

    async def send(self, event: Event, message: str) -> list[MessageObject]:
        self.calls.append((event, message))
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
