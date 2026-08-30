"""官方 Entari database 插件的启动桥接。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from loguru import logger

from ..config import DatabaseConfig
from .errors import DatabaseUnavailableError

_DATABASE_PLUGIN = "entari_plugin_database"
_DATABASE_SERVICE = "database/sqlalchemy"


def _query_values(query: Any) -> dict[str, str | list[str]]:
    normalized: dict[str, str | list[str]] = {}
    for key, values in query.items():
        if isinstance(values, str):
            normalized[key] = values
        else:
            values = list(values)
            normalized[key] = values[0] if len(values) == 1 else values
    return normalized


def _official_config(config: DatabaseConfig) -> dict[str, Any]:
    from sqlalchemy.engine import make_url

    url = make_url(config.url)
    database_type, separator, driver = url.drivername.partition("+")
    if not separator:
        driver = ""
    if not database_type or not url.database:
        raise DatabaseUnavailableError(f"数据库 URL 必须包含类型和名称: {config.url!r}")

    result: dict[str, Any] = {
        "type": database_type,
        "name": url.database,
        "driver": driver,
        "query": _query_values(url.query),
        "options": {"echo": config.echo, "pool_pre_ping": True},
        "create_table_at": config.create_table_at,
    }
    if database_type != "sqlite":
        result.update(
            {
                "host": url.host,
                "port": url.port,
                "username": url.username,
                "password": url.password,
            }
        )
    return result


def _prepare_sqlite_path(config: DatabaseConfig, plugin_config: dict[str, Any]) -> None:
    if plugin_config["type"] != "sqlite":
        return
    database = str(plugin_config["name"])
    if database in {":memory:", ""} or database.startswith("file:"):
        return
    path = Path(database).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)


def load_database_plugin(config: DatabaseConfig):
    """加载官方 database 插件并注册 Tenko 模型。

    ``load_plugin`` 必须在 ``EntariConfig`` 初始化后调用；该函数只负责启动
    阶段的同步注册，实际引擎初始化和 Alembic 迁移仍由官方 Launart service
    在服务生命周期中执行。
    """

    try:
        from arclet.entari.plugin import load_plugin

        plugin_config = _official_config(config)
        _prepare_sqlite_path(config, plugin_config)
        plugin = load_plugin(_DATABASE_PLUGIN, plugin_config)
    except DatabaseUnavailableError:
        raise
    except Exception as error:
        raise DatabaseUnavailableError(
            f"加载官方数据库插件失败: {type(error).__name__}: {error}"
        ) from error

    if plugin is None:
        raise DatabaseUnavailableError("官方数据库插件未能加载")

    try:
        from . import models  # noqa: F401  # 注册所有 Tenko ORM 模型

        service = plugin._services[_DATABASE_SERVICE]
    except (AttributeError, KeyError, ImportError) as error:
        raise DatabaseUnavailableError(
            "官方数据库插件未提供 database/sqlalchemy 服务"
        ) from error

    logger.info(
        "Loaded official entari-plugin-database {} with URL {}",
        getattr(plugin, "id", _DATABASE_PLUGIN),
        config.url,
    )
    return service


__all__ = ["load_database_plugin"]
