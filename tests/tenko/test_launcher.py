from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _write_code_root(root: Path, marker: str) -> None:
    package = root / "tenko"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text(f"SOURCE = {marker!r}\n", encoding="utf-8")
    (package / "__main__.py").write_text(
        "import os\n"
        "from pathlib import Path\n"
        "from . import SOURCE\n"
        "Path('launcher-marker').write_text(\n"
        "    f'{SOURCE}|{__file__}|{os.getcwd()}', encoding='utf-8'\n"
        ")\n",
        encoding="utf-8",
    )


@pytest.mark.parametrize(
    ("stable_version", "active_version", "expected_source"),
    [
        ("1.0.0", None, "stable"),
        ("1.0.0", "2.0.0", "candidate"),
        ("2.0.0", "1.0.0", "stable"),
        ("4.0.0-pre9", "4.0.0-pre10", "candidate"),
    ],
    ids=["without-active", "active-newer", "stable-newer", "numeric-prerelease"],
)
def test_launcher_selects_active_code_with_stable_cwd(
    tmp_path: Path,
    stable_version: str,
    active_version: str | None,
    expected_source: str,
) -> None:
    stable_root = tmp_path / "stable"
    scripts = stable_root / "scripts"
    scripts.mkdir(parents=True)
    _write_code_root(stable_root, "stable")
    (stable_root / "pyproject.toml").write_text(
        f'[project]\nversion = "{stable_version}"\n', encoding="utf-8"
    )
    launcher = scripts / "launcher.sh"
    shutil.copy2(PROJECT_ROOT / "scripts" / "launcher.sh", launcher)
    launcher.chmod(launcher.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    upgrade_root = stable_root / ".tenko" / "upgrades"
    candidate = upgrade_root / "versions" / "2.0.0"
    if active_version is not None:
        _write_code_root(candidate, "candidate")
        active_file = upgrade_root / "active.json"
        active_file.parent.mkdir(parents=True, exist_ok=True)
        active_file.write_text(
            json.dumps({"version": active_version, "path": str(candidate)}) + "\n",
            encoding="utf-8",
        )

    handoff = upgrade_root / "handoff.json"
    handoff.parent.mkdir(parents=True, exist_ok=True)
    handoff.write_text('{"action":"activate"}\n', encoding="utf-8")
    before_handoff = handoff.read_bytes()

    fake_uv = tmp_path / "fake-uv"
    fake_uv.write_text(
        "#!/bin/sh\n"
        "set -eu\n"
        '[ "$1" = run ]\n'
        "shift\n"
        '[ "$1" = --project ]\n'
        "shift 2\n"
        '[ "$1" = --no-sync ]\n'
        "shift\n"
        '[ "$1" = python ]\n'
        "shift\n"
        'exec "$TENKO_TEST_PYTHON" "$@"\n',
        encoding="utf-8",
    )
    fake_uv.chmod(0o755)
    environment = os.environ.copy()
    environment.update(
        UV=str(fake_uv),
        TENKO_TEST_PYTHON=sys.executable,
    )
    environment.pop("PYTHONPATH", None)

    completed = subprocess.run(
        [str(launcher)],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr
    marker = (stable_root / "launcher-marker").read_text(encoding="utf-8")
    source, source_file, cwd = marker.split("|", 2)
    assert source == expected_source
    expected_root = candidate if expected_source == "candidate" else stable_root
    assert Path(source_file).resolve() == expected_root / "tenko" / "__main__.py"
    assert cwd == str(stable_root.resolve())
    assert handoff.read_bytes() == before_handoff
