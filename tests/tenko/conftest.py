from required_plugin_support import entari_plugin_host, loaded_plugin  # noqa: F401

from pathlib import Path

import pytest_asyncio
from arclet.entari.config import EntariConfig
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from tenko.config import DatabaseConfig
from tenko.db.bootstrap import load_database_plugin


@pytest_asyncio.fixture
async def tenko_database():
    """为调用点测试提供独立的内存 SQLite repository。"""

    if not EntariConfig._inited:
        EntariConfig(Path("/tmp/tenko-database-callsite-test.yml"))
    load_database_plugin(DatabaseConfig(url="sqlite+aiosqlite:///:memory:"))

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
