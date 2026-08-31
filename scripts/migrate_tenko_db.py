"""将旧 Graia SQLite 文件接入 Tenko 的官方数据库服务。"""

from __future__ import annotations

import argparse
import asyncio
import shutil
from dataclasses import replace
from pathlib import Path
from typing import Final


from arclet.entari.config import EntariConfig
from tenko.config import TenkoConfig
from tenko.db.bootstrap import load_database_plugin
from tenko.db.migration import run_database_migrations

_DEFAULT_CONFIG: Final = Path("config/tenko.toml")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="迁移 Tenko 的旧 SQLite 数据库")
    parser.add_argument(
        "--config",
        type=Path,
        default=_DEFAULT_CONFIG,
        help="Tenko TOML 配置路径（默认：config/tenko.toml）",
    )
    parser.add_argument(
        "--source",
        type=Path,
        help="旧 Graia SQLite 文件；指定后默认直接复用该文件",
    )
    parser.add_argument(
        "--target",
        type=Path,
        help="可选的新 SQLite 文件；与 --source 一起使用时复制数据库",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="允许覆盖已存在的 --target 文件",
    )
    return parser


def _sqlite_url(path: Path) -> str:
    return f"sqlite+aiosqlite:///{path.resolve()}"


def _database_config(
    config: TenkoConfig,
    source: Path | None,
    target: Path | None,
    force: bool,
) -> TenkoConfig:
    if target is not None and source is None:
        raise ValueError("--target 必须与 --source 一起使用")
    if source is None:
        if force:
            raise ValueError("--force 只能与 --source 和 --target 一起使用")
        return config

    source_path = source.expanduser().resolve()
    if not source_path.is_file():
        raise FileNotFoundError(f"旧 SQLite 文件不存在: {source_path}")

    database_path = source_path
    if target is not None:
        target_path = target.expanduser().resolve()
        if target_path != source_path:
            if target_path.exists() and not force:
                raise FileExistsError(
                    f"目标 SQLite 文件已存在（如需覆盖请明确传 --force）: {target_path}"
                )
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, target_path)
        database_path = target_path

    return replace(
        config, database=replace(config.database, url=_sqlite_url(database_path))
    )


async def _migrate(config: TenkoConfig) -> None:
    service = load_database_plugin(config.database)
    try:
        await service.initialize()
        async with service.engines[""].begin() as connection:
            await connection.run_sync(
                service.base_class.metadata.create_all,
                checkfirst=True,
            )
        await run_database_migrations(service)
    finally:
        for engine in service.engines.values():
            await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = TenkoConfig.load(args.config)
    # 框架 EntariConfig 的文件 loader 不支持 TOML；迁移场景不需要 Entari 文件配置，
    # 用一个必然不存在的 YAML 路径触发空配置初始化，仅满足 load_plugin 的前提。
    if not EntariConfig._inited:
        EntariConfig(Path(".tenko/entari-boot.yaml"))
    config = _database_config(config, args.source, args.target, args.force)
    asyncio.run(_migrate(config))
    print(f"Tenko 数据库迁移完成: {config.database.url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
