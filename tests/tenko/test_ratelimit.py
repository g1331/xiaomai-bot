from __future__ import annotations

from tenko.host.ratelimit import RateLimitService


def test_rate_limit_blocks_during_cooldown_and_recovers_after_window(tmp_path) -> None:
    now = [100.0]
    service = RateLimitService(
        tmp_path / "ratelimit.json",
        window_seconds=5,
        max_weight=3,
        cooldown_seconds=2,
        blacklist_seconds=0,
        clock=lambda: now[0],
    )

    assert service.check("40001", "20001").allowed
    assert service.check("40001", "20001").allowed
    limited = service.check("40001", "20001")
    assert not limited.allowed
    assert limited.retry_after == 2

    now[0] += 1
    assert not service.check("40001", "20001").allowed
    now[0] += 5
    assert service.check("40001", "20001").allowed


def test_rate_limit_blacklist_survives_service_recreation(tmp_path) -> None:
    now = [100.0]
    state_path = tmp_path / "ratelimit.json"
    service = RateLimitService(
        state_path,
        max_weight=2,
        cooldown_seconds=0,
        blacklist_seconds=30,
        clock=lambda: now[0],
    )

    assert service.check("40001", "20001").allowed
    assert not service.check("40001", "20001").allowed
    assert service.is_blacklisted("40001", "20001")

    restored = RateLimitService(
        state_path,
        max_weight=2,
        cooldown_seconds=0,
        blacklist_seconds=30,
        clock=lambda: now[0],
    )
    assert not restored.check("40001", "20001").allowed

    now[0] += 31
    assert not restored.is_blacklisted("40001", "20001")
    restored.clear("40001", "20001")
    assert restored.check("40001", "20001").allowed
