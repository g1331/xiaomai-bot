from required_plugin_support import entari_plugin_host, loaded_plugin  # noqa: F401

from pathlib import Path

import pytest_asyncio
from arclet.entari.config import EntariConfig
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool


@pytest_asyncio.fixture
async def tenko_database():
    """为调用点测试提供独立的内存 SQLite repository。"""

    if not EntariConfig._inited:
        EntariConfig(Path("/tmp/tenko-database-callsite-test.yml"))

    from entari_plugin_database import BaseOrm
    from tenko.db.repositories import configure_session_factory

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(BaseOrm.metadata.create_all)
    configure_session_factory(async_sessionmaker(engine, expire_on_commit=False))
    try:
        yield engine
    finally:
        configure_session_factory(None)
        await engine.dispose()


@pytest_asyncio.fixture
async def repositories():
    """为状态迁移和 repository 调用点测试提供独立的内存 SQLite。"""

    if not EntariConfig._inited:
        EntariConfig(Path("/tmp/tenko-repositories-test.yml"))

    from entari_plugin_database import BaseOrm
    from tenko.db.models import (
        AccountResponseState,
        AccountRoute,
        FeatureState,
        GroupPerm,
        GroupSetting,
        MemberPerm,
        RateLimitEvent,
        RateLimitSubjectState,
        StartupTime,
    )
    from tenko.db.repositories import (
        AccountStateRepository,
        FeatureStateRepository,
        GroupPermRepository,
        GroupSettingRepository,
        MemberPermRepository,
        RateLimitRepository,
        StartupTimeRepository,
        configure_session_factory,
    )

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(BaseOrm.metadata.create_all)

    configure_session_factory(async_sessionmaker(engine, expire_on_commit=False))
    try:
        yield {
            "member": MemberPermRepository(),
            "group": GroupPermRepository(),
            "setting": GroupSettingRepository(),
            "feature": FeatureStateRepository(),
            "account": AccountStateRepository(),
            "rate": RateLimitRepository(),
            "startup": StartupTimeRepository(),
            "models": (
                MemberPerm,
                GroupPerm,
                GroupSetting,
                FeatureState,
                AccountRoute,
                AccountResponseState,
                RateLimitEvent,
                RateLimitSubjectState,
                StartupTime,
            ),
        }
    finally:
        configure_session_factory(None)
        await engine.dispose()
