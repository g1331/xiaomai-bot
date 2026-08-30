from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal

from satori.exception import ActionFailed

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


def test_event_random_selection_is_cached_per_message() -> None:
    registry = AccountRegistry()
    first = FakeAccount("10001")
    second = FakeAccount("10002")
    registry.register(first, groups=[100])
    registry.register(second, groups=[100])

    selected = registry.select_for_event(100, source_id="message-1")

    assert selected is registry.select_for_event(100, source_id="message-1")


def test_event_random_selection_normalizes_account_id_in_cache() -> None:
    registry = AccountRegistry()
    first = FakeAccount(10001)
    second = FakeAccount(10002)
    registry.register(first, groups=[100])
    registry.register(second, groups=[100])

    selected = registry.select_for_event(100, source_id="message-1")

    assert selected is registry.select_for_event(100, source_id="message-1")


def test_partial_group_mute_excludes_only_the_muted_account_from_selection() -> None:
    registry = AccountRegistry()
    first = FakeAccount("10001")
    second = FakeAccount("10002")
    registry.register(first, groups=[100])
    registry.register(second, groups=[100])

    registry.set_muted(first, 100, True)

    assert registry.bound_accounts_for_group(100) == (first, second)
    assert registry.online_accounts_for_group(100) == (first, second)
    assert registry.accounts_for_group(100) == (second,)
    assert registry.select_account(100, source_id=0) is second
    assert registry.select_account(100, source_id=1) is second


def test_deterministic_muted_account_returns_none_without_fallback() -> None:
    registry = AccountRegistry()
    first = FakeAccount("10001")
    second = FakeAccount("10002")
    registry.register(first, groups=[100])
    registry.register(second, groups=[100])
    registry.set_response_type(100, "deterministic")
    registry.set_deterministic_account(100, second)

    registry.set_muted(second, 100, True)
    assert registry.select_account(100) is None

    registry.set_muted(second, 100, False)
    assert registry.select_account(100) is second


def test_expired_mute_is_lazily_removed_and_routing_recovers() -> None:
    registry = AccountRegistry()
    account = FakeAccount("10001")
    registry.register(account, groups=[100])
    expired = datetime.now(timezone.utc) - timedelta(seconds=1)

    registry.set_muted(account, 100, True, until=expired)

    assert not registry.is_muted(account, 100)
    assert registry.mute_until(account, 100) is None
    assert registry.accounts_for_group(100) == (account,)


def test_group_send_action_failure_is_an_explicit_mute_source() -> None:
    registry = AccountRegistry()
    account = FakeAccount("10001")
    registry.register(account, groups=[100])
    failed = ActionFailed("1200: failed", {"status": "failed", "retcode": 1200})
    succeeded = ActionFailed("0: ok", {"status": "ok", "retcode": 0})

    assert registry.observe_send_failure(account, 100, failed)
    assert registry.is_muted(account, 100)
    assert not registry.observe_send_failure(account, 100, succeeded)


def test_response_strategy_round_trip_restores_after_restart(tmp_path) -> None:
    state_path = tmp_path / "accounts.json"
    first = FakeAccount("10001")
    second = FakeAccount("10002")
    registry = AccountRegistry(state_path)
    registry.register(first, groups=[100])
    registry.register(second, groups=[100])
    registry.set_response_type(100, "deterministic")
    registry.set_deterministic_account(100, second)

    restored = AccountRegistry(state_path)
    restored.register(first, groups=[100])
    restored.register(second, groups=[100])

    assert restored.response_type_for_group(100) == "deterministic"
    assert restored.deterministic_account_for_group(100) == "10002"
    assert restored.select_account(100) is second
