from __future__ import annotations

import pytest

from tenko.host.features import FeatureService


@pytest.mark.asyncio
async def test_feature_group_switch_round_trip(repositories) -> None:
    repository = repositories["feature"]
    service = FeatureService(repository)
    await service.initialize()

    assert service.is_enabled("demo", "40001")
    assert service.disable("demo", "40001") is False
    assert not service.is_enabled("demo", "40001")
    assert service.is_enabled("demo", "40002")
    await service.persist_state()

    restored = FeatureService(repository)
    await restored.initialize()
    assert not restored.is_enabled("demo", "40001")
    assert restored.is_enabled("demo", "40002")

    restored.enable("demo", "40001")
    await restored.persist_state()
    final = FeatureService(repository)
    await final.initialize()
    assert final.is_enabled("demo", "40001")


@pytest.mark.asyncio
async def test_feature_maintenance_overrides_group_state(repositories) -> None:
    service = FeatureService(repositories["feature"])
    await service.initialize()
    service.disable("demo", "40001")
    service.set_maintenance("demo", True)
    await service.persist_state()

    assert not service.is_enabled("demo", "40001")
    assert not service.is_enabled("demo", "40002")

    service.set_maintenance("demo", False)
    await service.persist_state()
    assert not service.is_enabled("demo", "40001")
    assert service.is_enabled("demo", "40002")


@pytest.mark.asyncio
async def test_global_feature_switch_round_trip(repositories) -> None:
    repository = repositories["feature"]
    service = FeatureService(repository)
    await service.initialize()

    assert service.is_enabled("startup_notify", "40001")
    assert service.set_global_enabled("startup_notify", False) is False
    assert not service.is_enabled("startup_notify", "40001")
    assert not service.is_enabled("startup_notify", "40002")
    await service.persist_state()

    restored = FeatureService(repository)
    await restored.initialize()
    assert not restored.is_enabled("startup_notify")
    assert restored.state["startup_notify"]["global_enabled"] is False

    restored.set_global_enabled("startup_notify", True)
    await restored.persist_state()
    final = FeatureService(repository)
    await final.initialize()
    assert final.is_enabled("startup_notify", "40001")


@pytest.mark.asyncio
async def test_feature_database_failure_disables_feature_queries() -> None:
    class FailingRepository:
        async def list_states(self):
            raise RuntimeError("database offline")

    service = FeatureService(FailingRepository())

    with pytest.raises(RuntimeError, match="database offline"):
        await service.initialize()

    assert not service.ready
    assert not service.is_enabled("demo", "40001")
    assert service.is_maintenance("demo")


@pytest.mark.asyncio
async def test_feature_database_failure_does_not_silently_accept_writes() -> None:
    from tenko.db.errors import DatabaseUnavailableError

    service = FeatureService()
    service.mark_unavailable()

    with pytest.raises(DatabaseUnavailableError, match="数据库不可用"):
        await service.persist_state()
