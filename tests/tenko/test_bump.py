from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from scripts import bump


def _write_pyproject(
    path: Path, upgrade_section: str = 'min_config_version = "1.0.0"'
) -> None:
    path.write_text(
        '[project]\nversion = "4.0.0"\n\n'
        '[tool.bumpversion]\ncurrent_version = "4.0.0"\n\n'
        "[tool.tenko.upgrade]\n"
        f"{upgrade_section}\n",
        encoding="utf-8",
    )


@pytest.mark.parametrize(
    "value",
    [
        "1.2.3",
        "1.2.3-rc.1",
        "1.2.3+linux.x86",
        "1.2.3-rc.1+build.7",
    ],
)
def test_read_min_config_version_accepts_semver(tmp_path: Path, value: str) -> None:
    pyproject = tmp_path / "pyproject.toml"
    _write_pyproject(pyproject, f'min_config_version = "{value}"')

    assert bump.read_min_config_version(pyproject) == value


@pytest.mark.parametrize(
    "upgrade_section",
    [
        "",
        "min_config_version = 1",
        'min_config_version = ""',
        'min_config_version = "1.2"',
        'min_config_version = "01.2.3"',
        'min_config_version = "1.2.3-01"',
        'min_config_version = "v1.2.3"',
    ],
)
def test_read_min_config_version_rejects_missing_or_invalid_metadata(
    tmp_path: Path, upgrade_section: str
) -> None:
    pyproject = tmp_path / "pyproject.toml"
    _write_pyproject(pyproject, upgrade_section)

    with pytest.raises(bump.ReleaseMetadataError):
        bump.read_min_config_version(pyproject)


def test_generate_upgrade_manifest_uses_independent_config_version(
    tmp_path: Path,
) -> None:
    pyproject = tmp_path / "pyproject.toml"
    manifest = tmp_path / "upgrade-manifest.json"
    _write_pyproject(pyproject, 'min_config_version = "1.0.0"')

    assert (
        bump.generate_upgrade_manifest(
            pyproject_path=pyproject,
            manifest_path=manifest,
        )
        == manifest
    )
    assert json.loads(manifest.read_text(encoding="utf-8")) == {
        "min_config_version": "1.0.0"
    }
    assert manifest.read_text(encoding="utf-8") == (
        '{\n  "min_config_version": "1.0.0"\n}\n'
    )


def test_main_generates_manifest_without_commit(monkeypatch, tmp_path: Path) -> None:
    _write_pyproject(tmp_path / "pyproject.toml")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(bump, "check_bumpmyversion", lambda: None)
    monkeypatch.setattr(
        bump,
        "run_bumpmyversion",
        lambda part, new_version=None, no_pre=False: (True, "4.0.1"),
    )
    monkeypatch.setattr(bump, "update_uv_lock", lambda: None)
    monkeypatch.setattr(sys, "argv", ["bump.py", "patch", "--no-commit"])

    bump.main()

    assert json.loads((tmp_path / "upgrade-manifest.json").read_text()) == {
        "min_config_version": "1.0.0"
    }


def test_main_rejects_missing_metadata_before_running_bump(
    monkeypatch, tmp_path: Path
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nversion = "4.0.0"\n', encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    called = False

    def fail_if_called() -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(bump, "check_bumpmyversion", fail_if_called)
    monkeypatch.setattr(sys, "argv", ["bump.py", "patch"])

    with pytest.raises(SystemExit) as error:
        bump.main()

    assert error.value.code == 1
    assert not called
    assert not (tmp_path / "upgrade-manifest.json").exists()


def test_force_version_update_does_not_change_config_protocol_version(
    monkeypatch, tmp_path: Path
) -> None:
    pyproject = tmp_path / "pyproject.toml"
    _write_pyproject(pyproject, 'min_config_version = "1.0.0"')
    monkeypatch.chdir(tmp_path)

    assert bump.update_pyproject_version_directly("4.0.1")

    assert bump.read_min_config_version(pyproject) == "1.0.0"
    assert 'version = "4.0.1"' in pyproject.read_text(encoding="utf-8")
    assert 'current_version = "4.0.1"' in pyproject.read_text(encoding="utf-8")


def test_git_commit_and_tag_stages_manifest(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    calls: list[tuple[list[str], bool]] = []

    def fake_run(command: list[str], *, check: bool) -> None:
        calls.append((command, check))

    monkeypatch.setattr(bump.subprocess, "run", fake_run)

    bump.git_commit_and_tag("4.0.0", "4.0.1", tag=False)

    assert calls[0] == (
        ["git", "add", "pyproject.toml", "uv.lock", "upgrade-manifest.json"],
        True,
    )
