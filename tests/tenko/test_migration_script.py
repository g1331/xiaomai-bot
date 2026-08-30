from __future__ import annotations

import pytest

from scripts.migrate_tenko_db import _database_config
from tenko.config import TenkoConfig


def test_migration_script_reuses_source_without_copying(tmp_path) -> None:
    source = tmp_path / "old.db"
    source.write_bytes(b"legacy")

    config = _database_config(TenkoConfig(), source, None, False)

    assert config.database.url == f"sqlite+aiosqlite:///{source.resolve()}"


def test_migration_script_copies_source_and_protects_existing_target(tmp_path) -> None:
    source = tmp_path / "old.db"
    target = tmp_path / "tenko.db"
    source.write_bytes(b"legacy")

    config = _database_config(TenkoConfig(), source, target, False)
    assert config.database.url == f"sqlite+aiosqlite:///{target.resolve()}"
    assert target.read_bytes() == b"legacy"

    with pytest.raises(FileExistsError, match="--force"):
        _database_config(TenkoConfig(), source, target, False)

    source.write_bytes(b"new-legacy")
    _database_config(TenkoConfig(), source, target, True)
    assert target.read_bytes() == b"new-legacy"


def test_migration_script_rejects_target_without_source(tmp_path) -> None:
    with pytest.raises(ValueError, match="--source"):
        _database_config(TenkoConfig(), None, tmp_path / "tenko.db", False)
