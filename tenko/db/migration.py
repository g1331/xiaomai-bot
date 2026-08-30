"""Tenko 对官方 database 插件迁移器的窄适配。"""

from __future__ import annotations

from typing import Any

from .errors import DatabaseUnavailableError

LEGACY_SCHEMA_REVISION = "tenko-g1-legacy-schema-v1"


async def run_database_migrations(service: Any) -> None:
    """执行官方 Alembic 迁移器，并保留旧 schema 的 baseline 语义。

    官方插件会先对当前模型与数据库做结构比对，再把 revision 写入其
    ``migrations_lock.json``。Tenko 模型声明 ``LEGACY_SCHEMA_REVISION``，旧
    库结构完全一致时不会产生 DDL，只会完成 baseline 记录。
    """

    try:
        from entari_plugin_database.migration import run_migration
    except (ImportError, AttributeError, LookupError) as error:
        raise DatabaseUnavailableError("官方数据库插件迁移器不可用") from error
    await run_migration(service)


__all__ = ["LEGACY_SCHEMA_REVISION", "run_database_migrations"]
