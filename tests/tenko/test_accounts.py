from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from tenko.context import MessageContext
from tenko.host.accounts import AccountRegistry


@dataclass
class FakeAccount:
    self_id: str


def make_context(
    account_id: str,
    channel_id: str = "100",
    chat_type: Literal["private", "group", "other"] = "group",
) -> MessageContext:
    return MessageContext(
        account_id=account_id,
        event_type="message-created",
        protocol_event_type="message.group.normal",
        chat_type=chat_type,
        channel_id=channel_id,
        user_id="user-1",
        message_id="message-1",
        text="hello",
        image_urls=(),
    )


def test_register_and_unregister_account() -> None:
    registry = AccountRegistry()
    account = FakeAccount("10001")

    assert registry.register(account, groups=[100]) == "10001"
    assert registry.get(10001) is account
    assert registry.accounts_for_group(100) == (account,)

    assert registry.unregister("10001") is account
    assert registry.get("10001") is None
    assert registry.accounts_for_group(100) == ()


def test_availability_controls_group_routing() -> None:
    registry = AccountRegistry()
    first = FakeAccount("10001")
    second = FakeAccount("10002")
    registry.register(first, groups=[100])
    registry.register(second, available=False, groups=[100])

    assert registry.is_available(first)
    assert not registry.is_available(second)
    assert registry.accounts_for_group(100) == (first,)
    assert registry.select_account(100, source_id=1) is first

    registry.set_available(second, True)
    assert registry.accounts_for_group(100) == (first, second)
    registry.set_response_type(100, "deterministic")
    registry.set_deterministic_account(100, second)
    assert registry.select_account(100) is second


def test_group_message_routes_by_source_id_and_private_keeps_account() -> None:
    registry = AccountRegistry()
    first = FakeAccount("10001")
    second = FakeAccount("10002")
    registry.register(first, groups=[100])
    registry.register(second, groups=[100])

    assert registry.select_for_context(make_context("10001"), source_id=0) is first
    assert registry.select_for_context(make_context("10001"), source_id=1) is second
    assert (
        registry.select_for_context(make_context("10002", chat_type="private"))
        is second
    )
