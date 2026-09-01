from __future__ import annotations

import pytest
from tenko.db.errors import (
    DatabaseIdentifierError,
    DatabaseUnavailableError,
    InvalidGroupPermissionError,
    InvalidGroupSettingError,
    InvalidPermissionError,
)


@pytest.mark.asyncio
async def test_member_repository_round_trip_and_lists(repositories) -> None:
    member = repositories["member"]

    assert await member.get_permission("10001", "20001") is None
    for index, permission in enumerate((-1, 0, 16, 32, 64, 128, 256), start=1):
        await member.set_permission(10001, 20010 + index, permission)

    await member.set_permission("10001", "20001", 16)
    await member.set_permission("10001", "20001", 32)
    assert await member.get_permission(10001, 20001) == 32

    rows = await member.list_group_permissions("10001")
    assert len(rows) == 8
    assert {row.perm for row in rows} == {-1, 0, 16, 32, 64, 128, 256}

    await member.set_permission(0, "30001", -1)
    await member.set_permission(0, "30002", 128)
    await member.set_permission(10001, "30003", 0)
    assert await member.list_global_blacklist() == (30001,)
    assert await member.list_bot_admins() == (20016, 30002)
    assert await member.list_group_blacklist(10001) == (20012, 30003)

    assert await member.delete_permission(10001, 99999) is False
    assert await member.delete_permission(10001, 20001) is True
    assert await member.get_permission(10001, 20001) is None


@pytest.mark.asyncio
async def test_member_repository_rejects_invalid_ids_and_permission_values(
    repositories,
) -> None:
    member = repositories["member"]

    with pytest.raises(DatabaseIdentifierError, match="纯数字"):
        await member.get_permission("guild-name", "20001")
    with pytest.raises(DatabaseIdentifierError, match="纯数字"):
        await member.set_permission("10001", "discord-user", 16)
    for invalid in (-2, 1, 15, True, "16"):
        with pytest.raises(InvalidPermissionError):
            await member.set_permission(10001, 20001, invalid)


@pytest.mark.asyncio
async def test_group_repository_preserves_name_and_active_on_partial_update(
    repositories,
) -> None:
    group = repositories["group"]

    assert await group.get("40001") is None
    await group.set("40001", 2, group_name="VIP 群", active=False)
    row = await group.get(40001)
    assert row is not None
    assert (row.group_name, row.perm, row.active) == ("VIP 群", 2, False)

    await group.set("40001", 1)
    row = await group.get(40001)
    assert row is not None
    assert (row.group_name, row.perm, row.active) == ("VIP 群", 1, False)
    await group.set_active(40001, True)
    await group.set_group_name(40001, "新群")
    row = await group.get(40001)
    assert row is not None
    assert (row.group_name, row.perm, row.active) == ("新群", 1, True)

    await group.set(40002, 2, group_name="另一个 VIP")
    assert [item.group_id for item in await group.list_vip()] == [40002]

    for invalid in (-1, 4, True, "2"):
        with pytest.raises(InvalidGroupPermissionError):
            await group.set(40001, invalid)
    with pytest.raises(DatabaseIdentifierError, match="纯数字"):
        await group.get("not-a-group")


@pytest.mark.asyncio
async def test_group_setting_repository_supports_defaults_partial_updates_and_validation(
    repositories,
) -> None:
    setting = repositories["setting"]

    assert await setting.get(50001) is None
    await setting.set(
        50001,
        frequency_limitation=False,
        response_type="deterministic",
        permission_type="admin",
    )
    row = await setting.get("50001")
    assert row is not None
    assert (
        row.frequency_limitation,
        row.response_type,
        row.permission_type,
    ) == (False, "deterministic", "admin")

    await setting.set_permission_type(50001, "default")
    await setting.set_response_type(50001, "random")
    await setting.set_frequency_limitation(50001, True)
    row = await setting.get(50001)
    assert row is not None
    assert (
        row.frequency_limitation,
        row.response_type,
        row.permission_type,
    ) == (True, "random", "default")

    for invalid in ("invalid", "ADMIN"):
        with pytest.raises(InvalidGroupSettingError):
            await setting.set_permission_type(50001, invalid)
    with pytest.raises(InvalidGroupSettingError):
        await setting.set_response_type(50001, "fixed")
    with pytest.raises(TypeError, match="frequency_limitation"):
        await setting.set_frequency_limitation(50001, 1)
    with pytest.raises(DatabaseIdentifierError, match="纯数字"):
        await setting.get("not-a-group")


@pytest.mark.asyncio
async def test_repository_without_session_factory_raises_explicit_error() -> None:
    from tenko.db.repositories import MemberPermRepository

    repository = MemberPermRepository()
    with pytest.raises(DatabaseUnavailableError, match="session 工厂"):
        await repository.get_permission("10001", "20001")


@pytest.mark.asyncio
async def test_feature_state_repository_round_trip(repositories) -> None:
    from tenko.db.repositories import FeatureStateRecord

    repository = repositories["feature"]

    assert await repository.list_states() == ()
    await repository.replace_states(
        (
            FeatureStateRecord("demo", None, False, True),
            FeatureStateRecord("demo", "40001", False, False),
            FeatureStateRecord("other", "40001", True, False),
        )
    )

    assert await repository.list_states() == (
        FeatureStateRecord("demo", None, False, True),
        FeatureStateRecord("demo", "40001", False, False),
        FeatureStateRecord("other", "40001", True, False),
    )


@pytest.mark.asyncio
async def test_account_state_repository_round_trip(repositories) -> None:
    from tenko.db.repositories import (
        AccountResponseRecord,
        AccountRouteRecord,
        AccountStateSnapshot,
    )

    repository = repositories["account"]

    await repository.replace_state(
        (
            AccountRouteRecord("40001", "10001", 0),
            AccountRouteRecord("40001", "10002", 1),
        ),
        (AccountResponseRecord("40001", "deterministic", "10002"),),
    )

    assert await repository.load_state() == AccountStateSnapshot(
        routes=(
            AccountRouteRecord("40001", "10001", 0),
            AccountRouteRecord("40001", "10002", 1),
        ),
        responses=(AccountResponseRecord("40001", "deterministic", "10002"),),
    )


@pytest.mark.asyncio
async def test_rate_limit_repository_round_trip(repositories) -> None:
    from tenko.db.repositories import RateLimitEventRecord, RateLimitSubjectRecord

    repository = repositories["rate"]

    await repository.replace_state(
        (RateLimitEventRecord("40001", "20001", 100.0, 2),),
        (RateLimitSubjectRecord("40001", "20001", 105.0, 200.0),),
    )

    snapshot = await repository.load_state()
    assert snapshot.events == (RateLimitEventRecord("40001", "20001", 100.0, 2),)
    assert snapshot.subjects == (
        RateLimitSubjectRecord("40001", "20001", 105.0, 200.0),
    )


@pytest.mark.asyncio
async def test_startup_time_repository_round_trip(repositories) -> None:
    repository = repositories["startup"]

    assert await repository.list_durations() == ()
    await repository.record(2.5)
    await repository.record(1.25)

    assert await repository.list_durations() == (2.5, 1.25)
