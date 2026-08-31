from __future__ import annotations

import asyncio
import json
import os
import shutil
import sqlite3
import stat
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

from tenko.config import TenkoConfig
from tenko.host.updater import (
    DefaultHealthChecker,
    GitTagSource,
    Release,
    SubprocessLauncher,
    UpgradeLayout,
    UpgradeManager,
    Version,
    spawn_restart_watcher,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
STABLE_MARKER = "stable-1.0.0"
CANDIDATE_MARKER = "candidate-2.0.0"
REMOTE_MARKER = "candidate-remote-2.0.0"
E2E_RELEASE = Release(Version(2, 0, 0), "v2.0.0", source="e2e")
_COPY_IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc")


_TEST_MAIN = """
from __future__ import annotations

import json
import os
import signal
import sqlite3
import sys
import time
import traceback
from pathlib import Path

from tenko import SOURCE
from tenko._production_main import _run_startup_bootstrap
from tenko.config import TenkoConfig


ROOT = Path.cwd().resolve()


def _config_path(arguments):
    for index, value in enumerate(arguments):
        if value == "--config" and index + 1 < len(arguments):
            return Path(arguments[index + 1]).expanduser()
        if value.startswith("--config="):
            return Path(value.partition("=")[2]).expanduser()
    return Path("config/tenko.toml")


def _rooted(value):
    path = Path(value).expanduser()
    return path if path.is_absolute() else ROOT / path


def _database_path(url):
    prefix = "sqlite+aiosqlite:///"
    if not url.startswith(prefix):
        raise ValueError(f"E2E 只支持 SQLite URL: {url!r}")
    path = Path(url[len(prefix) :]).expanduser()
    return path if path.is_absolute() else ROOT / path


def _health_check():
    if (ROOT / "fail-health").is_file():
        if (ROOT / "server-expected").is_file():
            deadline = time.monotonic() + 3
            while not (ROOT / "candidate-server.pid").is_file():
                if time.monotonic() >= deadline:
                    break
                time.sleep(0.02)
        raise SystemExit(23)
    raise SystemExit(0)


def _server():
    (ROOT / "candidate-server.pid").write_text(
        str(os.getpid()), encoding="utf-8"
    )

    def stop(_signum, _frame):
        (ROOT / "candidate-server-exited").write_text(SOURCE, encoding="utf-8")
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    while True:
        time.sleep(1)


def _update_json(path, field):
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TypeError(f"{field} 状态必须是 object")
    data["candidate_marker"] = SOURCE
    data["candidate_write_count"] = int(data.get("candidate_write_count", 0)) + 1
    path.write_text(
        json.dumps(data, ensure_ascii=False, sort_keys=True) + "\\n",
        encoding="utf-8",
    )


def _write_evidence(config):
    evidence_dir = _rooted(config.exception.evidence_dir)
    evidence_dir.mkdir(parents=True, exist_ok=True)
    evidence = evidence_dir / f"{SOURCE}-{time.time_ns()}.log"
    try:
        raise RuntimeError("candidate e2e evidence")
    except RuntimeError:
        report = f"{SOURCE} evidence\\n{traceback.format_exc()}"
    evidence.write_text(report, encoding="utf-8")
    return evidence


def _run_normal(arguments):
    config_path = _config_path(arguments)
    config = TenkoConfig.load(config_path)
    if _run_startup_bootstrap(config, arguments):
        return 0

    database_path = _database_path(config.database.url).resolve()
    with sqlite3.connect(database_path) as connection:
        row_count = connection.execute(
            "SELECT COUNT(*) FROM e2e_rows"
        ).fetchone()[0]

    state_paths = {
        "accounts": _rooted(config.accounts.state_path).resolve(),
        "features": _rooted(config.features.state_path).resolve(),
        "ratelimit": _rooted(config.ratelimit.state_path).resolve(),
    }
    for name, path in state_paths.items():
        _update_json(path, name)

    evidence_path = _write_evidence(config)
    observation = {
        "source": SOURCE,
        "source_file": str(Path(__file__).resolve()),
        "cwd": str(ROOT),
        "config_path": str(config_path.resolve()),
        "database_path": str(database_path),
        "database_row_count": row_count,
        "state_paths": {name: str(path) for name, path in state_paths.items()},
        "evidence_path": str(evidence_path.resolve()),
        "arguments": arguments,
        "python": sys.executable,
    }
    (ROOT / "candidate-observation.json").write_text(
        json.dumps(observation, ensure_ascii=False, sort_keys=True) + "\\n",
        encoding="utf-8",
    )
    return 0


def main():
    arguments = list(sys.argv[1:])
    if "--e2e-health" in arguments:
        _health_check()
    if "--e2e-server" in arguments:
        _server()
    return _run_normal(arguments)


if __name__ == "__main__":
    raise SystemExit(main())
""".lstrip()


@dataclass(frozen=True, slots=True)
class E2EFixture:
    stable_root: Path
    config_path: Path
    data_dir: Path
    database_path: Path
    state_paths: dict[str, Path]
    upgrade_root: Path
    launcher: Path
    fake_uv: Path
    observation: Path
    fail_health: Path
    server_expected: Path


@dataclass
class E2ECandidateSource:
    stable_root: Path
    name: str = "e2e"

    async def discover(self, _channel):
        return (E2E_RELEASE,)

    async def acquire(self, _release: Release, destination: Path) -> Path:
        destination.mkdir(parents=True)
        _install_test_package(
            destination,
            self.stable_root / "tenko",
            CANDIDATE_MARKER,
        )
        return destination


def _git(*arguments: str, cwd: Path) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _write_package_marker(package: Path, marker: str) -> None:
    lines = [
        line
        for line in (package / "__init__.py").read_text(encoding="utf-8").splitlines()
        if not line.startswith("SOURCE = ")
    ]
    lines.append(f"SOURCE = {marker!r}")
    (package / "__init__.py").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _install_test_package(
    destination_root: Path,
    source_package: Path,
    marker: str,
) -> None:
    package = destination_root / "tenko"
    shutil.copytree(source_package, package, ignore=_COPY_IGNORE)
    _write_package_marker(package, marker)


def _write_test_entrypoint(package: Path) -> None:
    production_main = (PROJECT_ROOT / "tenko" / "__main__.py").read_text(
        encoding="utf-8"
    )
    (package / "_production_main.py").write_text(production_main, encoding="utf-8")
    (package / "__main__.py").write_text(_TEST_MAIN, encoding="utf-8")


def _config_text(repository: str = ".") -> str:
    return (
        "[upgrade]\n"
        'source = "git_tag"\n'
        f"repository = {repository!r}\n"
        'current_version = "1.0.0"\n'
        'install_root = ".tenko/upgrades"\n'
        'config_path = "config/tenko.toml"\n'
        'data_dir = "data"\n'
        'health_command = ["{python}", "-m", "tenko", "--e2e-health"]\n'
        "health_timeout = 5\n"
    )


def _make_fixture(tmp_path: Path) -> E2EFixture:
    stable_root = tmp_path / "stable"
    stable_root.mkdir()
    (stable_root / "config").mkdir()
    package = stable_root / "tenko"
    _install_test_package(package.parent, PROJECT_ROOT / "tenko", STABLE_MARKER)
    _write_test_entrypoint(package)

    scripts = stable_root / "scripts"
    scripts.mkdir()
    launcher = scripts / "launcher.sh"
    shutil.copy2(PROJECT_ROOT / "scripts" / "launcher.sh", launcher)
    launcher.chmod(launcher.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    (stable_root / "pyproject.toml").write_text(
        '[project]\nname = "tenko-e2e"\nversion = "1.0.0"\n',
        encoding="utf-8",
    )
    (stable_root / "config" / "tenko.toml").write_text(_config_text(), encoding="utf-8")

    data_dir = stable_root / "data"
    data_dir.mkdir()
    tenko_dir = stable_root / ".tenko"
    exceptions_dir = tenko_dir / "exceptions"
    upgrade_root = tenko_dir / "upgrades"
    exceptions_dir.mkdir(parents=True)
    for relative in ("versions", "staging", "failed-handoffs", "restart-watchers"):
        (upgrade_root / relative).mkdir(parents=True)

    database_path = tenko_dir / "tenko.db"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "CREATE TABLE e2e_rows (id INTEGER PRIMARY KEY, marker TEXT NOT NULL)"
        )
        connection.execute("INSERT INTO e2e_rows(marker) VALUES (?)", ("preseed",))
        connection.commit()

    state_paths = {
        "accounts": tenko_dir / "accounts.json",
        "features": tenko_dir / "features.json",
        "ratelimit": tenko_dir / "ratelimit.json",
    }
    state_paths["accounts"].write_text(
        json.dumps(
            {
                "version": 1,
                "groups": {
                    "preseed-group": {
                        "response_type": "deterministic",
                        "deterministic_account": "preseed-account",
                    }
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    state_paths["features"].write_text(
        json.dumps(
            {
                "version": 1,
                "plugins": {
                    "preseed-plugin": {
                        "maintenance": False,
                        "groups": {"preseed-group": True},
                    }
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    state_paths["ratelimit"].write_text(
        json.dumps(
            {
                "version": 1,
                "events": {"preseed-user": [{"at": 0, "weight": 1}]},
                "cooldowns": {},
                "blacklist": {},
            }
        )
        + "\n",
        encoding="utf-8",
    )

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
    fake_uv.chmod(fake_uv.stat().st_mode | stat.S_IXUSR)
    return E2EFixture(
        stable_root=stable_root,
        config_path=stable_root / "config" / "tenko.toml",
        data_dir=data_dir,
        database_path=database_path,
        state_paths=state_paths,
        upgrade_root=upgrade_root,
        launcher=launcher,
        fake_uv=fake_uv,
        observation=stable_root / "candidate-observation.json",
        fail_health=stable_root / "fail-health",
        server_expected=stable_root / "server-expected",
    )


def _subprocess_environment(fixture: E2EFixture) -> dict[str, str]:
    environment = os.environ.copy()
    for name in (
        "PYTHONPATH",
        "TENKO_CONFIG_PATH",
        "TENKO_DATA_DIR",
        "TENKO_UPGRADE_ROOT",
    ):
        environment.pop(name, None)
    environment.update(
        UV=str(fixture.fake_uv),
        TENKO_TEST_PYTHON=sys.executable,
    )
    return environment


def _run_launcher(
    fixture: E2EFixture,
    *arguments: str,
    timeout: float = 15,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(fixture.launcher), *arguments],
        cwd=fixture.stable_root.parent,
        env=_subprocess_environment(fixture),
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )


def _make_manager(
    fixture: E2EFixture,
    *,
    source=None,
    launch_command=(),
) -> UpgradeManager:
    config = TenkoConfig.load(fixture.config_path)
    checker = DefaultHealthChecker(
        config.upgrade.health_command,
        timeout=config.upgrade.health_timeout,
        config_path=fixture.config_path,
        data_dir=fixture.data_dir,
        upgrade_root=fixture.upgrade_root,
        stable_root=fixture.stable_root,
    )
    launcher = None
    if launch_command:
        launcher = SubprocessLauncher(
            launch_command,
            config_path=fixture.config_path,
            data_dir=fixture.data_dir,
            upgrade_root=fixture.upgrade_root,
            stable_root=fixture.stable_root,
        )
    return UpgradeManager(
        Version(1, 0, 0),
        source or E2ECandidateSource(fixture.stable_root),
        layout=UpgradeLayout(fixture.upgrade_root),
        project_root=fixture.stable_root,
        config_path=fixture.config_path,
        data_dir=fixture.data_dir,
        config_version=config.upgrade.config_version,
        health_checker=checker,
        launcher=launcher,
    )


def _read_observation(fixture: E2EFixture) -> dict[str, object]:
    return json.loads(fixture.observation.read_text(encoding="utf-8"))


def _read_audit(fixture: E2EFixture) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in fixture.upgrade_root.joinpath("audit.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]


def _wait_for(path: Path, *, timeout: float = 8) -> None:
    deadline = time.monotonic() + timeout
    while not path.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert path.is_file(), f"等待文件超时: {path}"


def _wait_until_gone(path: Path, *, timeout: float = 8) -> None:
    deadline = time.monotonic() + timeout
    while path.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not path.exists(), f"文件未按预期清理: {path}"


def _assert_candidate_process_result(
    completed: subprocess.CompletedProcess[str],
) -> None:
    assert completed.returncode == 0, (
        f"stdout={completed.stdout}\nstderr={completed.stderr}"
    )


def test_launcher_without_active_uses_stable_code_and_cwd(tmp_path: Path) -> None:
    fixture = _make_fixture(tmp_path)

    completed = _run_launcher(fixture, "--e2e-mode", "stable")

    _assert_candidate_process_result(completed)
    observation = _read_observation(fixture)
    assert observation["source"] == STABLE_MARKER
    assert observation["source_file"] == str(
        fixture.stable_root / "tenko" / "__main__.py"
    )
    assert observation["cwd"] == str(fixture.stable_root.resolve())
    assert not (fixture.upgrade_root / "active.json").exists()
    assert not any((fixture.upgrade_root / "versions").iterdir())


def test_launcher_with_active_uses_candidate_code_and_stable_data_root(
    tmp_path: Path,
) -> None:
    fixture = _make_fixture(tmp_path)
    candidate = fixture.upgrade_root / "versions" / "2.0.0-manual"
    _install_test_package(candidate, fixture.stable_root / "tenko", CANDIDATE_MARKER)
    layout = UpgradeLayout(fixture.upgrade_root)
    layout.write_pointer(candidate, Version(2, 0, 0))

    completed = _run_launcher(fixture, "--e2e-mode", "active")

    _assert_candidate_process_result(completed)
    observation = _read_observation(fixture)
    assert observation["source"] == CANDIDATE_MARKER
    assert observation["source_file"] == str(candidate / "tenko" / "__main__.py")
    assert observation["cwd"] == str(fixture.stable_root.resolve())
    assert observation["config_path"] == str(fixture.config_path.resolve())
    assert not (candidate / ".tenko").exists()
    assert not (candidate / "config" / "tenko.toml").exists()
    assert not (candidate / ".venv").exists()


@pytest.mark.asyncio
async def test_subprocess_upgrade_persists_data_and_runs_candidate(
    tmp_path: Path,
) -> None:
    fixture = _make_fixture(tmp_path)
    manager = _make_manager(fixture)
    database_inode = fixture.database_path.stat().st_ino

    prepared = await manager.prepare(E2E_RELEASE)
    await manager.request_install()

    completed = _run_launcher(fixture, "--e2e-mode", "upgrade")

    _assert_candidate_process_result(completed)
    layout = UpgradeLayout(fixture.upgrade_root)
    active = layout.read_active()
    previous = layout.read_previous()
    assert active is not None
    assert active.path == prepared.path
    assert active.version == E2E_RELEASE.version
    assert previous is not None
    assert previous.version == Version(1, 0, 0)
    assert previous.path.is_dir()
    assert not layout.pending_file.exists()
    assert not layout.handoff_file.exists()

    observation = _read_observation(fixture)
    assert observation["source"] == CANDIDATE_MARKER
    assert observation["source_file"] == str(prepared.path / "tenko" / "__main__.py")
    assert observation["cwd"] == str(fixture.stable_root.resolve())
    assert observation["config_path"] == str(fixture.config_path.resolve())
    assert observation["database_path"] == str(fixture.database_path.resolve())
    assert observation["database_row_count"] == 1
    assert observation["python"] == sys.executable
    assert os.path.samefile(fixture.database_path, observation["database_path"])
    assert fixture.database_path.stat().st_ino == database_inode

    with sqlite3.connect(fixture.database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM e2e_rows").fetchone()[0] == 1
        assert connection.execute("SELECT marker FROM e2e_rows").fetchone()[0] == (
            "preseed"
        )
    for name, path in fixture.state_paths.items():
        state = json.loads(path.read_text(encoding="utf-8"))
        assert state["candidate_marker"] == CANDIDATE_MARKER, name
        assert state["candidate_write_count"] == 1, name
        assert observation["state_paths"][name] == str(path.resolve())
        if name == "accounts":
            assert state["groups"]["preseed-group"]["deterministic_account"] == (
                "preseed-account"
            )
        elif name == "features":
            assert state["plugins"]["preseed-plugin"]["groups"]["preseed-group"]
        else:
            assert state["events"]["preseed-user"] == [{"at": 0, "weight": 1}]
    evidence = Path(observation["evidence_path"])
    assert evidence.parent == fixture.stable_root / ".tenko" / "exceptions"
    assert evidence.is_file()
    assert CANDIDATE_MARKER in evidence.read_text(encoding="utf-8")
    assert not (prepared.path / ".tenko").exists()
    assert not (prepared.path / "config" / "tenko.toml").exists()
    assert not (prepared.path / ".venv").exists()


@pytest.mark.asyncio
async def test_subprocess_rollback_swaps_pointers_and_returns_to_old_code(
    tmp_path: Path,
) -> None:
    fixture = _make_fixture(tmp_path)
    manager = _make_manager(fixture)
    prepared = await manager.prepare(E2E_RELEASE)
    await manager.request_install()
    _assert_candidate_process_result(_run_launcher(fixture, "--e2e-mode", "upgrade"))

    requested = await manager.rollback()
    assert not requested.applied
    assert (
        json.loads(
            fixture.upgrade_root.joinpath("handoff.json").read_text(encoding="utf-8")
        )["action"]
        == "rollback"
    )

    completed = _run_launcher(fixture, "--e2e-mode", "rollback")

    _assert_candidate_process_result(completed)
    layout = UpgradeLayout(fixture.upgrade_root)
    active = layout.read_active()
    previous = layout.read_previous()
    assert active is not None and active.version == Version(1, 0, 0)
    assert previous is not None and previous.path == prepared.path
    assert previous.version == E2E_RELEASE.version
    assert not layout.handoff_file.exists()
    assert not layout.pending_file.exists()
    observation = _read_observation(fixture)
    assert observation["source"] == STABLE_MARKER
    assert observation["source_file"] == str(active.path / "tenko" / "__main__.py")


@pytest.mark.asyncio
async def test_failed_candidate_health_check_rolls_back_and_next_start_is_stable(
    tmp_path: Path,
) -> None:
    fixture = _make_fixture(tmp_path)
    manager = _make_manager(fixture)
    prepared = await manager.prepare(E2E_RELEASE)
    await manager.request_install()
    fixture.fail_health.touch()

    completed = _run_launcher(fixture, "--e2e-mode", "failed-upgrade")

    _assert_candidate_process_result(completed)
    layout = UpgradeLayout(fixture.upgrade_root)
    active = layout.read_active()
    assert active is not None
    assert active.version == Version(1, 0, 0)
    assert active.path != prepared.path
    assert not layout.pending_file.exists()
    assert not layout.handoff_file.exists()
    assert _read_observation(fixture)["source"] == STABLE_MARKER
    audit = _read_audit(fixture)
    assert any(
        entry["action"] == "rollback" and entry["result"] == "success"
        for entry in audit
    )
    assert any(
        entry["action"] == "install" and entry["result"] == "failed" for entry in audit
    )

    next_start = _run_launcher(fixture, "--e2e-mode", "recovery")

    _assert_candidate_process_result(next_start)
    recovered = layout.read_active()
    assert recovered is not None and recovered.version == Version(1, 0, 0)
    assert _read_observation(fixture)["source"] == STABLE_MARKER
    assert not layout.handoff_file.exists()


@pytest.mark.asyncio
async def test_subprocess_launcher_terminates_candidate_after_health_failure(
    tmp_path: Path,
) -> None:
    fixture = _make_fixture(tmp_path)
    manager = _make_manager(
        fixture,
        launch_command=("{python}", "-m", "tenko", "--e2e-server"),
    )
    await manager.prepare(E2E_RELEASE)
    await manager.request_install()
    fixture.fail_health.touch()
    fixture.server_expected.touch()

    result = await manager.activate_pending(start_process=True)

    assert not result.success
    assert result.rolled_back
    _wait_for(fixture.stable_root / "candidate-server-exited")
    layout = UpgradeLayout(fixture.upgrade_root)
    active = layout.read_active()
    assert active is not None and active.version == Version(1, 0, 0)
    assert not layout.pending_file.exists()
    assert not layout.handoff_file.exists()


@pytest.mark.skipif(os.name != "posix", reason="POSIX detached watcher semantics")
def test_real_watcher_relaunches_launcher_after_old_process_exits(
    monkeypatch, tmp_path: Path
) -> None:
    fixture = _make_fixture(tmp_path)
    manager = _make_manager(fixture)
    prepared = asyncio.run(manager.prepare(E2E_RELEASE))
    asyncio.run(manager.request_install())
    old_process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(0.3)"]
    )
    watcher_file = fixture.upgrade_root / "restart-watchers" / f"{old_process.pid}.json"
    monkeypatch.setenv("UV", str(fixture.fake_uv))
    monkeypatch.setenv("TENKO_TEST_PYTHON", sys.executable)
    monkeypatch.delenv("PYTHONPATH", raising=False)
    monkeypatch.delenv("TENKO_CONFIG_PATH", raising=False)
    monkeypatch.delenv("TENKO_DATA_DIR", raising=False)
    monkeypatch.delenv("TENKO_UPGRADE_ROOT", raising=False)

    try:
        assert spawn_restart_watcher(
            old_process.pid,
            (str(fixture.launcher),),
            stable_root=fixture.stable_root,
            watcher_dir=fixture.upgrade_root / "restart-watchers",
            timeout=8,
            poll_interval=0.05,
        )
        assert watcher_file.is_file()
        assert old_process.wait(timeout=5) == 0
        _wait_for(fixture.observation)
        observation = _read_observation(fixture)
        assert observation["source"] == CANDIDATE_MARKER
        assert observation["source_file"] == str(
            prepared.path / "tenko" / "__main__.py"
        )
        active = UpgradeLayout(fixture.upgrade_root).read_active()
        assert active is not None and active.path == prepared.path
        layout = UpgradeLayout(fixture.upgrade_root)
        assert not layout.handoff_file.exists()
        assert not layout.pending_file.exists()
        _wait_until_gone(watcher_file)
    finally:
        if old_process.poll() is None:
            old_process.terminate()
            old_process.wait(timeout=5)


@pytest.mark.asyncio
async def test_named_remote_check_and_prepare_use_local_git_remote(
    tmp_path: Path,
) -> None:
    fixture = _make_fixture(tmp_path)
    remote = tmp_path / "remote"
    remote.mkdir()
    _git("init", "--quiet", cwd=remote)
    _git("config", "user.email", "e2e@example.test", cwd=remote)
    _git("config", "user.name", "Tenko E2E", cwd=remote)
    _install_test_package(remote, fixture.stable_root / "tenko", REMOTE_MARKER)
    (remote / "pyproject.toml").write_text(
        '[project]\nname = "tenko-remote"\nversion = "2.0.0"\n',
        encoding="utf-8",
    )
    _git("add", ".", cwd=remote)
    _git("commit", "--quiet", "-m", "release", cwd=remote)
    _git("tag", "v2.0.0", cwd=remote)

    _git("init", "--quiet", cwd=fixture.stable_root)
    _git("remote", "add", "origin", str(remote), cwd=fixture.stable_root)
    fixture.config_path.write_text(_config_text("origin"), encoding="utf-8")
    config = TenkoConfig.load(fixture.config_path)

    manager = UpgradeManager.from_config(
        config.upgrade,
        project_root=fixture.stable_root,
    )
    source = manager.sources[0]
    assert isinstance(source, GitTagSource)
    assert source.repository == str(remote.resolve())

    checked = await manager.check()
    assert checked.candidate is not None
    assert checked.candidate.version == Version(2, 0, 0)
    prepared = await manager.prepare(checked.candidate)

    assert prepared.path.is_dir()
    assert (prepared.path / "tenko" / "__main__.py").is_file()
    assert (
        (prepared.path / "tenko" / "__init__.py")
        .read_text(encoding="utf-8")
        .rstrip()
        .endswith(f"SOURCE = {REMOTE_MARKER!r}")
    )
    assert not (prepared.path / ".tenko").exists()
    assert not (prepared.path / "config" / "tenko.toml").exists()
    assert not (prepared.path / ".venv").exists()
    assert manager.layout.pending_file.is_file()
