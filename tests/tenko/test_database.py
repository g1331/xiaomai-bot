from __future__ import annotations

import json
from pathlib import Path

import pytest
from arclet.entari.config import EntariConfig
from graia.amnesia.builtins.sqla import SqlalchemyService
from sqlalchemy import (
    Boolean,
    Column,
    Integer,
    MetaData,
    String,
    Table,
    inspect,
    insert,
    select,
)
from sqlalchemy.ext.asyncio import create_async_engine

from tenko.config import TenkoConfig
from tenko.db.bootstrap import _official_config
from tenko.db.migration import LEGACY_SCHEMA_REVISION, run_database_migrations


def _legacy_metadata() -> MetaData:
    metadata = MetaData()
    Table(
        "MemberPerm",
        metadata,
        Column("group_id", Integer, primary_key=True),
        Column("qq", Integer, primary_key=True),
        Column("perm", Integer, nullable=False, default=16),
    )
    Table(
        "GroupPerm",
        metadata,
        Column("group_id", Integer, primary_key=True),
        Column("group_name", String(length=60), nullable=False),
        Column("perm", Integer, nullable=False, default=1),
        Column("active", Boolean, default=True),
    )
    Table(
        "GroupSetting",
        metadata,
        Column("group_id", Integer, primary_key=True),
        Column("frequency_limitation", Boolean, default=True),
        Column(
            "response_type",
            String,
            default="random",
        ),
        Column("permission_type", String, default="default"),
    )
    return metadata


async def _create_legacy_database(path: Path) -> MetaData:
    metadata = _legacy_metadata()
    engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
    async with engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
        await connection.execute(
            insert(metadata.tables["MemberPerm"]),
            [
                {"group_id": 1, "qq": index, "perm": permission}
                for index, permission in enumerate(
                    (-1, 0, 16, 32, 64, 128, 256), start=1
                )
            ],
        )
        await connection.execute(
            insert(metadata.tables["GroupPerm"]),
            {"group_id": 1, "group_name": "旧群", "perm": 2, "active": True},
        )
        await connection.execute(
            insert(metadata.tables["GroupSetting"]),
            {
                "group_id": 1,
                "frequency_limitation": False,
                "response_type": "deterministic",
                "permission_type": "admin",
            },
        )
    await engine.dispose()
    return metadata


def test_runtime_state_bootstrap_creates_tables_before_state_load() -> None:
    config = TenkoConfig.from_mapping(
        {
            "database": {
                "url": "sqlite+aiosqlite:///tmp/tenko.db",
                "create_table_at": "prepared",
            }
        }
    )

    assert _official_config(config.database)["create_table_at"] == "prepared"
    assert (
        _official_config(config.database, runtime_state_service=object())[
            "create_table_at"
        ]
        == "preparing"
    )


@pytest.mark.asyncio
async def test_official_database_plugin_preserves_legacy_schema_and_rows(
    tmp_path, monkeypatch
):
    if not EntariConfig._inited:
        EntariConfig(Path("/tmp/tenko-database-test.yml"))

    database_path = tmp_path / "legacy.db"
    legacy = await _create_legacy_database(database_path)
    service = SqlalchemyService(
        f"sqlite+aiosqlite:///{database_path}",
        engine_options={"echo": False, "pool_pre_ping": True},
    )
    from tenko.db.models import (
        MODEL_CLASSES,
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

    await service.initialize()

    async with service.engines[""].begin() as connection:
        await connection.run_sync(
            service.base_class.metadata.create_all,
            checkfirst=True,
        )

    from entari_plugin_database import migration as official_migration

    migration_state = tmp_path / "migrations_lock.json"
    monkeypatch.setattr(official_migration, "_STATE_FILE", migration_state)
    await run_database_migrations(service)
    state = json.loads(migration_state.read_text(encoding="utf-8"))
    legacy_tables = {
        "MemberPerm",
        "GroupPerm",
        "GroupSetting",
    }
    assert legacy_tables <= set(state)
    assert all(
        state[table]["revision"] == LEGACY_SCHEMA_REVISION for table in legacy_tables
    )

    async with service.get_session() as session:
        permissions = (
            await session.execute(
                select(MemberPerm.group_id, MemberPerm.qq, MemberPerm.perm).order_by(
                    MemberPerm.qq
                )
            )
        ).all()
        group = await session.scalar(select(GroupPerm).where(GroupPerm.group_id == 1))
        setting = await session.scalar(
            select(GroupSetting).where(GroupSetting.group_id == 1)
        )

    assert [row.perm for row in permissions] == [-1, 0, 16, 32, 64, 128, 256]
    assert group is not None
    assert (group.group_name, group.perm, group.active) == ("旧群", 2, True)
    assert setting is not None
    assert (
        setting.frequency_limitation,
        setting.response_type,
        setting.permission_type,
    ) == (False, "deterministic", "admin")

    expected_models = {
        "MemberPerm": MemberPerm,
        "GroupPerm": GroupPerm,
        "GroupSetting": GroupSetting,
        "TenkoFeatureState": FeatureState,
        "TenkoAccountRoute": AccountRoute,
        "TenkoAccountResponseState": AccountResponseState,
        "TenkoRateLimitEvent": RateLimitEvent,
        "TenkoRateLimitSubjectState": RateLimitSubjectState,
        "TenkoStartupTime": StartupTime,
    }
    assert {model.__tablename__ for model in MODEL_CLASSES} == set(expected_models)
    assert set(expected_models) <= set(state)
    assert all(
        state[table]["revision"] for table in set(expected_models) - legacy_tables
    )
    async with service.engines[""].connect() as connection:
        table_names = await connection.run_sync(
            lambda sync_connection: set(inspect(sync_connection).get_table_names())
        )
        assert table_names == set(expected_models)
        for table_name, model in expected_models.items():
            columns = await connection.run_sync(
                lambda sync_connection, name=table_name: inspect(
                    sync_connection
                ).get_columns(name)
            )
            assert [column["name"] for column in columns] == [
                column.name for column in model.__table__.columns
            ]
            if table_name in legacy_tables:
                assert [column["name"] for column in columns] == [
                    column.name for column in legacy.tables[table_name].columns
                ]

        member_pk = await connection.run_sync(
            lambda sync_connection: inspect(sync_connection).get_pk_constraint(
                "MemberPerm"
            )["constrained_columns"]
        )
    assert set(member_pk) == {"group_id", "qq"}
    await service.engines[""].dispose()
