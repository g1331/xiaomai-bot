from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal

import pytest
from satori.exception import ActionFailed

import tenko.host.accounts as accounts_module
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


def test_event_random_selection_normalizes_account_id_in_cache(monkeypatch) -> None:
    registry = AccountRegistry()
    first = FakeAccount(10001)
    second = FakeAccount(10002)
    registry.register(first, groups=[100])
    registry.register(second, groups=[100])
    choices = iter((first, second))
    monkeypatch.setattr(accounts_module.random, "choice", lambda _: next(choices))

    selected = registry.select_for_event(100, source_id="message-1")

    assert selected is first
    assert registry.select_for_event(100, source_id="message-1") is first


def test_event_selection_does_not_reroute_after_selected_account_goes_offline(
    monkeypatch,
) -> None:
    registry = AccountRegistry()
    first = FakeAccount("10001")
    second = FakeAccount("10002")
    registry.register(first, groups=[100])
    registry.register(second, groups=[100])
    monkeypatch.setattr(accounts_module.random, "choice", lambda _: first)

    assert registry.select_for_event(100, source_id="message-1") is first
    registry.set_available(first, False)

    assert registry.select_for_event(100, source_id="message-1") is None


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


@pytest.mark.asyncio
async def test_response_strategy_round_trip_restores_after_restart(
    repositories,
) -> None:
    repository = repositories["account"]
    first = FakeAccount("10001")
    second = FakeAccount("10002")
    registry = AccountRegistry(repository)
    await registry.initialize()
    registry.register(first, groups=[100])
    registry.register(second, groups=[100])
    registry.set_response_type(100, "deterministic")
    registry.set_deterministic_account(100, second)
    await registry.flush_persistence()

    restored = AccountRegistry(repository)
    await restored.initialize()
    restored.register(first)
    restored.register(second)

    assert restored.response_type_for_group(100) == "deterministic"
    assert restored.deterministic_account_for_group(100) == "10002"
    assert restored.select_account(100) is second


@pytest.mark.asyncio
async def test_account_database_failure_disables_route_queries() -> None:
    class FailingRepository:
        async def load_state(self):
            raise RuntimeError("database offline")

    registry = AccountRegistry(FailingRepository())

    with pytest.raises(RuntimeError, match="database offline"):
        await registry.initialize()

    assert not registry.ready
    assert registry.group_ids == ()
    assert registry.accounts_for_group("40001") == ()


@pytest.mark.asyncio
async def test_account_database_failure_does_not_silently_accept_writes() -> None:
    from tenko.db.errors import DatabaseUnavailableError

    registry = AccountRegistry()
    registry.mark_unavailable()

    with pytest.raises(DatabaseUnavailableError, match="数据库不可用"):
        await registry.persist_state()


def test_clear_deterministic_account_restores_group_default() -> None:
    registry = AccountRegistry()
    first = FakeAccount("10001")
    second = FakeAccount("10002")
    registry.register(first, groups=[100])
    registry.register(second, groups=[100])
    registry.set_response_type(100, "deterministic")
    registry.set_deterministic_account(100, second)

    registry.clear_deterministic_account(100)

    assert registry.deterministic_account_for_group(100) == "10001"
    assert registry.select_account(100) is first
