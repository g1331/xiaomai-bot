from __future__ import annotations

from datetime import datetime

import pytest
from satori import (
    Bold,
    Channel,
    ChannelType,
    EventType,
    Guild,
    Image,
    Login,
    MessageObject,
    Text,
    User,
)
from satori.model import Event

from tenko.context import MessageContext, is_message_created


def make_event(
    *,
    channel: Channel,
    user: User,
    message: MessageObject,
    guild: Guild | None = None,
) -> Event:
    event = Event(
        type=EventType.MESSAGE_CREATED,
        timestamp=datetime.now(),
        login=Login(platform="onebot", adapter="onebot", user=User("10001")),
        channel=channel,
        guild=guild,
        user=user,
        message=message,
    )
    event._type = "message.group.normal" if guild else "message.private.friend"
    return event


def test_private_message_context_extracts_text_and_source_type() -> None:
    event = make_event(
        channel=Channel("private:20001", ChannelType.DIRECT),
        user=User("20001", "Alice"),
        message=MessageObject.from_elements("30001", [Text("hello")]),
    )

    context = MessageContext.from_event(event)

    assert context.account_id == "10001"
    assert context.event_type == "message-created"
    assert context.protocol_event_type == "message.private.friend"
    assert context.chat_type == "private"
    assert context.channel_id == "private:20001"
    assert context.user_id == "20001"
    assert context.message_id == "30001"
    assert context.text == "hello"
    assert context.image_urls == ()
    assert is_message_created(event)


def test_group_message_context_extracts_nested_text_and_images() -> None:
    image_url = "https://example.test/image.png"
    event = make_event(
        channel=Channel("40001", ChannelType.TEXT),
        guild=Guild("40001", "Tenko Group"),
        user=User("20002", "Bob"),
        message=MessageObject.from_elements(
            "30002",
            [Bold("hello"), Text(" "), Image.of(url=image_url)],
        ),
    )

    context = MessageContext.from_event(event)

    assert context.chat_type == "group"
    assert context.channel_id == "40001"
    assert context.text == "hello "
    assert context.image_urls == (image_url,)


def test_context_rejects_message_without_channel() -> None:
    event = Event(
        type=EventType.MESSAGE_CREATED,
        timestamp=datetime.now(),
        login=Login(platform="onebot", user=User("10001")),
        user=User("20001"),
        message=MessageObject("30001", "hello"),
    )

    with pytest.raises(ValueError, match="channel"):
        MessageContext.from_event(event)
