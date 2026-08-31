from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from tenko.config import TenkoConfig, UpgradeConfig
from tenko.host.updater import (
    ArtifactVerificationError,
    AuditLogger,
    CheckResult,
    ConfigCompatibilityChecker,
    ConfigurationCompatibilityError,
    DefaultHealthChecker,
    GitHubReleaseSource,
    GitTagSource,
    HandoffResult,
    HealthCheckFailed,
    HealthCheckResult,
    NoRollbackAvailable,
    PrepareResult,
    Release,
    UpdateChannel,
    UpdatePolicy,
    UpdateRelation,
    UpdateSourceError,
    UpgradeLayout,
    UpgradeManager,
    UpgradeConfigError,
    SubprocessLauncher,
    UrlManifestSource,
    Version,
    compare_versions,
    parse_version,
    select_release,
    spawn_restart_watcher,
)


def git(*arguments: str, cwd: Path) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def make_git_repository(tmp_path: Path) -> Path:
    repository = tmp_path / "repository"
    repository.mkdir()
    git("init", "--quiet", cwd=repository)
    git("config", "user.email", "test@example.com", cwd=repository)
    git("config", "user.name", "Tenko Test", cwd=repository)
    (repository / "tenko").mkdir()
    (repository / "tenko" / "__init__.py").write_text(
        "VERSION = '1.0.0'\n", encoding="utf-8"
    )
    (repository / "payload.txt").write_text("one", encoding="utf-8")
    git("add", ".", cwd=repository)
    git("commit", "--quiet", "-m", "one", cwd=repository)
    git("tag", "v1.0.0", cwd=repository)

    (repository / "tenko" / "__init__.py").write_text(
        "VERSION = '1.1.0'\n", encoding="utf-8"
    )
    (repository / "payload.txt").write_text("two", encoding="utf-8")
    git("add", ".", cwd=repository)
    git("commit", "--quiet", "-m", "two", cwd=repository)
    git("tag", "v1.1.0-rc.1", cwd=repository)

    (repository / "tenko" / "__init__.py").write_text(
        "VERSION = '1.1.0'\n", encoding="utf-8"
    )
    (repository / "payload.txt").write_text("three", encoding="utf-8")
    git("add", ".", cwd=repository)
    git("commit", "--quiet", "-m", "three", cwd=repository)
    git("tag", "v1.1.0", cwd=repository)
    git("tag", "not-a-version", cwd=repository)
    return repository


def make_archive() -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("release-root/tenko/__init__.py", "VERSION = '2.0.0'\n")
        archive.writestr(
            "release-root/upgrade-manifest.json",
            json.dumps({"min_config_version": "1.0.0"}),
        )
    return output.getvalue()


@dataclass
class FakeHttpClient:
    payload: Any
    download_content: bytes = b""
    json_urls: list[str] = field(default_factory=list)
    download_urls: list[str] = field(default_factory=list)
    download_headers: list[dict[str, str] | None] = field(default_factory=list)

    async def get_json(self, url: str, *, headers=None) -> Any:
        self.json_urls.append(url)
        return self.payload

    async def download(self, url: str, destination: Path, *, headers=None) -> None:
        self.download_urls.append(url)
        self.download_headers.append(dict(headers) if headers else None)
        destination.write_bytes(self.download_content)


@dataclass
class MemorySource:
    releases: tuple[Release, ...]
    acquire_calls: int = 0
    name: str = "memory"

    async def discover(self, channel: UpdateChannel):
        return self.releases

    async def acquire(self, release: Release, destination: Path) -> Path:
        self.acquire_calls += 1
        destination.mkdir(parents=True)
        (destination / "tenko").mkdir()
        (destination / "tenko" / "__init__.py").write_text(
            f"VERSION = '{release.version}'\n", encoding="utf-8"
        )
        return destination


@dataclass
class SequenceHealthChecker:
    values: list[bool]
    calls: list[tuple[Path, str, Any]] = field(default_factory=list)

    async def check(self, candidate: Path, *, phase: str, process=None):
        self.calls.append((candidate, phase, process))
        return self.values.pop(0)


@dataclass
class RecordingLauncher:
    calls: list[Path] = field(default_factory=list)

    async def start(self, candidate: Path):
        self.calls.append(candidate)
        return type("Process", (), {"poll": lambda self: None})()


def make_manager(
    tmp_path: Path,
    *,
    policy: UpdatePolicy = UpdatePolicy.CHECK_ONLY,
    health: list[bool] | None = None,
    required_config_version: str | None = None,
) -> tuple[UpgradeManager, MemorySource, SequenceHealthChecker, Path, Path]:
    project = tmp_path / "project"
    (project / "tenko").mkdir(parents=True)
    (project / "tenko" / "__init__.py").write_text(
        "VERSION = '1.0.0'\n", encoding="utf-8"
    )
    (project / "config").mkdir()
    config_path = project / "config" / "tenko.toml"
    config_path.write_text("user_setting = true\n", encoding="utf-8")
    data_dir = project / "data"
    data_dir.mkdir()
    (data_dir / "user.db").write_text("keep", encoding="utf-8")
    release = Release(
        parse_version("1.1.0"),
        "v1.1.0",
        source="memory",
        required_config_version=required_config_version,
    )
    source = MemorySource((release,))
    checker = SequenceHealthChecker(health or [True, True, True])
    manager = UpgradeManager(
        "1.0.0",
        source,
        layout=UpgradeLayout(tmp_path / "upgrade-state"),
        project_root=project,
        config_path=config_path,
        data_dir=data_dir,
        config_version="1.0.0",
        policy=policy,
        health_checker=checker,
    )
    return manager, source, checker, config_path, data_dir


@pytest.mark.parametrize(
    "value",
    ["1.2.3", "v1.2.3", "1.2.3-rc.1", "1.2.3+linux.x86", "1.2.3-rc.1+build"],
)
def test_parse_version_accepts_semver_and_v_tag(value: str) -> None:
    assert isinstance(parse_version(value), Version)


@pytest.mark.parametrize(
    "value",
    [
        "",
        " 1.2.3",
        "1.2.3 ",
        "1",
        "1.2",
        "01.2.3",
        "1.02.3",
        "1.2.03",
        "1.2.3-",
        "1.2.3-01",
    ],
)
def test_parse_version_rejects_invalid_version(value: str) -> None:
    with pytest.raises(ValueError):
        parse_version(value)


@pytest.mark.parametrize(
    ("current", "remote", "expected"),
    [
        ("1.0.0", "1.0.0", UpdateRelation.SAME),
        ("1.0.0", "1.0.1", UpdateRelation.UPDATE_AVAILABLE),
        ("1.1.0", "1.0.9", UpdateRelation.CURRENT_AHEAD),
        ("1.0.0-rc.1", "1.0.0", UpdateRelation.UPDATE_AVAILABLE),
    ],
)
def test_compare_versions_boundaries(
    current: str, remote: str, expected: UpdateRelation
) -> None:
    assert compare_versions(current, remote) is expected


def test_semver_prerelease_precedence_ignores_build_metadata() -> None:
    assert parse_version("1.0.0-alpha") < parse_version("1.0.0-alpha.1")
    assert parse_version("1.0.0-alpha.1") < parse_version("1.0.0-beta")
    assert parse_version("1.0.0+one") == parse_version("1.0.0+two")


def test_select_release_obeys_stable_and_prerelease_channels() -> None:
    releases = (
        Release(parse_version("1.1.0-rc.1"), "v1.1.0-rc.1", prerelease=True),
        Release(parse_version("1.0.2"), "v1.0.2-preview", prerelease=True),
        Release(parse_version("1.0.1"), "v1.0.1"),
    )
    assert select_release(
        releases, "1.0.0", UpdateChannel.STABLE
    ).version == parse_version("1.0.1")
    assert select_release(
        releases, "1.0.0", UpdateChannel.PRERELEASE
    ).version == parse_version("1.1.0-rc.1")


@pytest.mark.asyncio
async def test_git_tag_source_discovers_tags_and_ignores_invalid_and_stable_prerelease(
    tmp_path: Path,
) -> None:
    repository = make_git_repository(tmp_path)
    source = GitTagSource(repository)

    stable = await source.discover(UpdateChannel.STABLE)
    preview = await source.discover(UpdateChannel.PRERELEASE)

    assert [str(item.version) for item in stable] == ["1.0.0", "1.1.0"]
    assert [str(item.version) for item in preview] == [
        "1.0.0",
        "1.1.0-rc.1",
        "1.1.0",
    ]
    assert all(item.commit_sha for item in preview)


@pytest.mark.asyncio
async def test_git_tag_source_acquires_and_verifies_commit_sha(tmp_path: Path) -> None:
    repository = make_git_repository(tmp_path)
    source = GitTagSource(repository)
    release = next(
        item
        for item in await source.discover(UpdateChannel.STABLE)
        if str(item.version) == "1.1.0"
    )

    destination = tmp_path / "stage" / "release"
    acquired = await source.acquire(release, destination)

    assert acquired == destination.resolve()
    assert (acquired / "payload.txt").read_text(encoding="utf-8") == "three"
    assert git("rev-parse", "HEAD", cwd=acquired) == release.commit_sha


@pytest.mark.asyncio
async def test_git_tag_source_rejects_sha_mismatch_and_cleans_destination(
    tmp_path: Path,
) -> None:
    repository = make_git_repository(tmp_path)
    source = GitTagSource(repository)
    release = next(
        item
        for item in await source.discover(UpdateChannel.STABLE)
        if str(item.version) == "1.1.0"
    )
    tampered = Release(
        release.version,
        release.tag,
        source=release.source,
        commit_sha="0" * 40,
    )

    with pytest.raises(ArtifactVerificationError):
        await source.acquire(tampered, tmp_path / "stage" / "release")
    assert not (tmp_path / "stage" / "release").exists()


def make_stable_git_repository(tmp_path: Path) -> tuple[Path, Path]:
    repository = make_git_repository(tmp_path)
    stable = tmp_path / "stable"
    git("clone", "--quiet", str(repository), str(stable), cwd=tmp_path)
    return repository, stable


@pytest.mark.asyncio
async def test_from_config_normalizes_named_remote_for_discover_and_prepare(
    tmp_path: Path,
) -> None:
    repository, stable = make_stable_git_repository(tmp_path)
    config = UpgradeConfig(
        repository="origin",
        current_version="1.0.0",
        install_root=str(tmp_path / "upgrades"),
    )

    manager = UpgradeManager.from_config(config, project_root=stable)
    source = manager.sources[0]
    prepared = await manager.prepare()

    assert isinstance(source, GitTagSource)
    assert source.repository == str(repository.resolve())
    assert prepared.release.version == parse_version("1.1.0")
    assert prepared.path.is_dir()


def test_from_config_reports_named_remote_resolution_context(tmp_path: Path) -> None:
    stable = tmp_path / "stable"
    stable.mkdir()
    git("init", "--quiet", cwd=stable)
    config = UpgradeConfig(
        repository="missing",
        current_version="1.0.0",
        install_root=str(tmp_path / "upgrades"),
    )

    with pytest.raises(UpgradeConfigError) as error:
        UpgradeManager.from_config(config, project_root=stable)

    message = str(error.value)
    assert "missing" in message
    assert str(stable.resolve()) in message
    assert "git remote get-url" in message
    assert "请检查该 remote" in message
    assert "完整 URL/本地路径" in message


def test_from_config_reports_non_worktree_named_remote(tmp_path: Path) -> None:
    stable = tmp_path / "not-a-worktree"
    stable.mkdir()
    config = UpgradeConfig(
        repository="origin",
        current_version="1.0.0",
        install_root=str(tmp_path / "upgrades"),
    )

    with pytest.raises(UpgradeConfigError, match="Git 工作树") as error:
        UpgradeManager.from_config(config, project_root=stable)

    assert "not a git repository" in str(error.value)


@pytest.mark.parametrize(
    ("repository", "expected"),
    [
        ("https://example.test/tenko.git", "https://example.test/tenko.git"),
        ("git@example.test:tenko/tenko.git", "git@example.test:tenko/tenko.git"),
    ],
)
def test_from_config_preserves_complete_git_repository_addresses(
    tmp_path: Path, repository: str, expected: str
) -> None:
    config = UpgradeConfig(
        repository=repository,
        current_version="1.0.0",
        install_root=str(tmp_path / "upgrades"),
    )

    manager = UpgradeManager.from_config(config, project_root=tmp_path)

    assert manager.sources[0].repository == expected


def test_from_config_resolves_existing_local_repository_against_stable_root(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    config = UpgradeConfig(
        repository="repository",
        current_version="1.0.0",
        install_root=str(tmp_path / "upgrades"),
    )

    manager = UpgradeManager.from_config(config, project_root=tmp_path)

    assert manager.sources[0].repository == str(repository.resolve())


@pytest.mark.asyncio
async def test_git_source_errors_redact_credentials_in_invalid_url(
    monkeypatch, tmp_path: Path
) -> None:
    import tenko.host.updater as updater_module

    repository = "https://user:secret@example.invalid/tenko.git"
    config = UpgradeConfig(
        repository=repository,
        current_version="1.0.0",
        install_root=str(tmp_path / "upgrades"),
    )
    manager = UpgradeManager.from_config(config, project_root=tmp_path)

    def fail_git(*_arguments, **_kwargs):
        raise subprocess.CalledProcessError(
            128,
            ["git"],
            stderr=f"fatal: unable to access '{repository}'",
        )

    monkeypatch.setattr(updater_module.subprocess, "run", fail_git)

    with pytest.raises(UpdateSourceError) as error:
        await manager.check()

    message = str(error.value)
    assert "secret" not in message
    assert "https://***@example.invalid/tenko.git" in message


@pytest.mark.asyncio
async def test_github_release_source_uses_official_release_endpoint_and_asset_digest(
    tmp_path: Path,
) -> None:
    archive = make_archive()
    client = FakeHttpClient(
        [
            {
                "tag_name": "v2.0.0-rc.1",
                "prerelease": True,
                "assets": [
                    {
                        "name": "tenko.zip",
                        "browser_download_url": "https://download/tenko.zip",
                        "digest": f"sha256:{hashlib.sha256(archive).hexdigest()}",
                    }
                ],
            },
            {
                "tag_name": "v1.5.0",
                "prerelease": False,
                "assets": [],
            },
        ],
        download_content=archive,
    )
    source = GitHubReleaseSource(
        "owner/repository",
        client=client,
        token="secret",
        asset_name="tenko.zip",
    )

    stable = await source.discover(UpdateChannel.STABLE)
    preview = await source.discover(UpdateChannel.PRERELEASE)
    release = next(item for item in preview if str(item.version) == "2.0.0-rc.1")
    acquired = await source.acquire(release, tmp_path / "release")

    assert [str(item.version) for item in stable] == ["1.5.0"]
    assert [str(item.version) for item in preview] == ["1.5.0", "2.0.0-rc.1"]
    assert client.json_urls[0] == (
        "https://api.github.com/repos/owner/repository/releases?per_page=100"
    )
    assert client.download_headers == [
        {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Authorization": "Bearer secret",
        }
    ]
    assert (acquired / "tenko" / "__init__.py").is_file()


@pytest.mark.asyncio
async def test_github_release_source_requires_asset_digest(tmp_path: Path) -> None:
    client = FakeHttpClient(
        [
            {
                "tag_name": "v2.0.0",
                "assets": [
                    {
                        "name": "tenko.zip",
                        "browser_download_url": "https://download/tenko.zip",
                    }
                ],
            }
        ],
        download_content=make_archive(),
    )
    source = GitHubReleaseSource("owner/repository", client=client)
    release = (await source.discover(UpdateChannel.STABLE))[0]

    with pytest.raises(ArtifactVerificationError):
        await source.acquire(release, tmp_path / "release")
    assert not (tmp_path / "release").exists()


@pytest.mark.asyncio
async def test_github_release_source_rejects_bad_asset_digest(tmp_path: Path) -> None:
    client = FakeHttpClient(
        [
            {
                "tag_name": "v2.0.0",
                "assets": [
                    {
                        "name": "tenko.zip",
                        "browser_download_url": "https://download/tenko.zip",
                        "digest": "sha256:" + "0" * 64,
                    }
                ],
            }
        ],
        download_content=make_archive(),
    )
    source = GitHubReleaseSource("owner/repository", client=client)
    release = (await source.discover(UpdateChannel.STABLE))[0]

    with pytest.raises(ArtifactVerificationError):
        await source.acquire(release, tmp_path / "release")


@pytest.mark.asyncio
async def test_url_manifest_source_resolves_relative_artifact_url(
    tmp_path: Path,
) -> None:
    archive = make_archive()
    client = FakeHttpClient(
        {
            "releases": [
                {
                    "version": "2.0.0",
                    "tag": "v2.0.0",
                    "artifact_url": "artifacts/tenko.zip",
                    "artifact_sha256": hashlib.sha256(archive).hexdigest(),
                    "artifact_name": "tenko.zip",
                }
            ]
        },
        download_content=archive,
    )
    source = UrlManifestSource(
        "https://example.test/releases/manifest.json", client=client
    )

    releases = await source.discover(UpdateChannel.STABLE)
    await source.acquire(releases[0], tmp_path / "release")

    assert (
        releases[0].artifact_url == "https://example.test/releases/artifacts/tenko.zip"
    )


def test_config_compatibility_compares_versions() -> None:
    checker = ConfigCompatibilityChecker()

    assert checker.check("1.0.0", "1.0.0").compatible
    assert checker.check("1.1.0", "1.0.0").compatible
    incompatible = checker.check("1.0.0", "1.1.0")
    assert not incompatible.compatible
    assert "1.1.0" in incompatible.reason
    assert checker.check("1.0.0", None).compatible


def test_config_compatibility_reads_release_manifest(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate"
    (candidate / "tenko").mkdir(parents=True)
    (candidate / "tenko" / "upgrade-manifest.json").write_text(
        '{"min_config_version": "2.0.0"}', encoding="utf-8"
    )
    release = Release(parse_version("2.0.0"), "v2.0.0")

    with pytest.raises(ConfigurationCompatibilityError, match="低于"):
        ConfigCompatibilityChecker().check_candidate(candidate, "1.0.0", release)


def test_config_compatibility_uses_stricter_release_or_manifest_requirement(
    tmp_path: Path,
) -> None:
    candidate = tmp_path / "candidate"
    (candidate / "tenko").mkdir(parents=True)
    (candidate / "tenko" / "upgrade-manifest.json").write_text(
        '{"min_config_version": "1.2.0"}', encoding="utf-8"
    )
    release = Release(
        parse_version("2.0.0"),
        "v2.0.0",
        required_config_version="1.1.0",
    )

    result = ConfigCompatibilityChecker().check_candidate(candidate, "1.2.0", release)

    assert result.compatible
    assert result.required_version == parse_version("1.2.0")


@pytest.mark.asyncio
async def test_subprocess_launcher_passes_shared_upgrade_paths(
    monkeypatch, tmp_path: Path
) -> None:
    captured: dict[str, Any] = {}

    def fake_popen(command, *, cwd, env):
        captured.update(command=command, cwd=cwd, env=env)
        return object()

    import tenko.host.updater as updater_module

    monkeypatch.setattr(updater_module.subprocess, "Popen", fake_popen)
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    config_path = tmp_path / "config" / "tenko.toml"
    data_dir = tmp_path / "data"
    upgrade_root = tmp_path / "upgrades"
    stable_root = tmp_path / "stable"
    stable_root.mkdir()

    launcher = SubprocessLauncher(
        ["{python}", "-m", "tenko", "--config", "{config_path}"],
        config_path=config_path,
        data_dir=data_dir,
        upgrade_root=upgrade_root,
        stable_root=stable_root,
    )
    await launcher.start(candidate)

    assert captured["command"][0].endswith("python")
    assert captured["cwd"] == stable_root.resolve()
    assert captured["env"]["TENKO_CONFIG_PATH"] == str(config_path)
    assert captured["env"]["TENKO_DATA_DIR"] == str(data_dir)
    assert captured["env"]["TENKO_UPGRADE_ROOT"] == str(upgrade_root)


def test_from_config_current_version_prefers_active_then_config_then_project(
    tmp_path: Path,
) -> None:
    stable_root = tmp_path / "stable"
    stable_root.mkdir()
    (stable_root / "pyproject.toml").write_text(
        '[project]\nversion = "1.0.0"\n', encoding="utf-8"
    )
    upgrade_root = tmp_path / "upgrades"
    candidate = upgrade_root / "versions" / "2.0.0"
    (candidate / "tenko").mkdir(parents=True)

    layout = UpgradeLayout(upgrade_root)
    layout.write_pointer(candidate, Version(2, 0, 0))
    configured = UpgradeConfig(current_version="1.5.0", install_root=str(upgrade_root))

    manager = UpgradeManager.from_config(configured, project_root=stable_root)
    assert manager.current_version == Version(2, 0, 0)

    layout.active_file.unlink()
    manager = UpgradeManager.from_config(configured, project_root=stable_root)
    assert manager.current_version == Version(1, 5, 0)

    from_project = UpgradeConfig(install_root=str(upgrade_root))
    manager = UpgradeManager.from_config(from_project, project_root=stable_root)
    assert manager.current_version == Version(1, 0, 0)


def test_upgrade_manager_restart_command_uses_stable_launcher(
    monkeypatch, tmp_path: Path
) -> None:
    launcher = tmp_path / "scripts" / "launcher.sh"
    launcher.parent.mkdir(parents=True)
    launcher.write_text("#!/bin/sh\n", encoding="utf-8")
    manager = UpgradeManager(
        Version(1, 0, 0),
        project_root=tmp_path,
        layout=UpgradeLayout(tmp_path / ".tenko" / "upgrades"),
    )
    monkeypatch.setattr(sys, "argv", ["tenko", "--config", "config/custom.toml"])

    assert manager.restart_command() == (
        str(launcher),
        "--config",
        "config/custom.toml",
    )


@pytest.mark.asyncio
async def test_default_health_checker_uses_stable_cwd_and_candidate_code(
    tmp_path: Path,
) -> None:
    stable_root = tmp_path / "stable"
    candidate = tmp_path / "candidate"
    for root, marker in ((stable_root, "stable"), (candidate, "candidate")):
        package = root / "tenko"
        package.mkdir(parents=True)
        (package / "__init__.py").write_text(f"MARKER = {marker!r}\n", encoding="utf-8")

    command = [
        sys.executable,
        "-c",
        "import os, tenko; raise SystemExit(0 if "
        f"tenko.MARKER == 'candidate' and os.getcwd() == {str(stable_root)!r} "
        "else 1)",
    ]
    checker = DefaultHealthChecker(command, stable_root=stable_root)

    result = await checker.check(candidate, phase="pre-switch")

    assert result.ok, result.reason


@pytest.mark.skipif(os.name != "posix", reason="POSIX detached watcher semantics")
def test_restart_watcher_deduplicates_pid_and_detaches(
    monkeypatch, tmp_path: Path
) -> None:
    import tenko.host.updater as updater_module

    captured: dict[str, Any] = {}

    def fake_popen(command, **kwargs):
        captured.update(command=command, kwargs=kwargs)
        return object()

    monkeypatch.setattr(updater_module.subprocess, "Popen", fake_popen)
    watcher_dir = tmp_path / "restart-watchers"
    command = (sys.executable, "-m", "tenko")

    assert spawn_restart_watcher(
        12345,
        command,
        stable_root=tmp_path,
        watcher_dir=watcher_dir,
        timeout=3,
        poll_interval=0.05,
    )
    assert not spawn_restart_watcher(
        12345,
        command,
        stable_root=tmp_path,
        watcher_dir=watcher_dir,
        timeout=3,
        poll_interval=0.05,
    )

    record = watcher_dir / "12345.json"
    payload = json.loads(record.read_text(encoding="utf-8"))
    assert payload["old_pid"] == 12345
    assert payload["command"] == list(command)
    assert payload["cwd"] == str(tmp_path.resolve())
    assert captured["kwargs"]["cwd"] == str(tmp_path.resolve())
    assert captured["kwargs"]["stdin"] is subprocess.DEVNULL
    assert captured["kwargs"]["start_new_session"] is True


@pytest.mark.skipif(os.name != "posix", reason="POSIX detached watcher semantics")
def test_restart_watcher_restarts_once_after_old_pid_exits(tmp_path: Path) -> None:
    marker = tmp_path / "restarted.txt"
    old_process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(0.35)"]
    )
    watcher_dir = tmp_path / "restart-watchers"
    command = (
        sys.executable,
        "-c",
        "from pathlib import Path; import sys; "
        "Path(sys.argv[1]).write_text('started', encoding='utf-8')",
        str(marker),
    )
    record = watcher_dir / f"{old_process.pid}.json"

    try:
        assert spawn_restart_watcher(
            old_process.pid,
            command,
            stable_root=tmp_path,
            watcher_dir=watcher_dir,
            timeout=5,
            poll_interval=0.05,
        )
        assert old_process.wait(timeout=5) == 0

        deadline = time.monotonic() + 5
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert marker.read_text(encoding="utf-8") == "started"

        deadline = time.monotonic() + 5
        while record.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert not record.exists()
    finally:
        if old_process.poll() is None:
            old_process.terminate()
            old_process.wait(timeout=5)


def test_tenko_upgrade_config_defaults_to_conservative_policy() -> None:
    config = TenkoConfig()
    assert config.upgrade.policy == "check"
    assert config.upgrade.channel == "stable"
    assert config.upgrade.check_interval_hours == 24


def test_tenko_upgrade_config_parses_source_policy_and_superusers() -> None:
    config = TenkoConfig.from_mapping(
        {
            "upgrade": {
                "source": "github_release",
                "github_repository": "owner/repository",
                "channel": "prerelease",
                "policy": "auto-download",
                "superuser_ids": [123, "456"],
                "health_command": ["{python}", "-c", "pass"],
            }
        }
    )
    assert config.upgrade.channel == "prerelease"
    assert config.upgrade.policy == "auto-download"
    assert config.upgrade.superuser_ids == ("123", "456")


@pytest.mark.asyncio
async def test_prepare_keeps_config_and_data_outside_staging(tmp_path: Path) -> None:
    manager, source, checker, config_path, data_dir = make_manager(tmp_path)
    config_before = config_path.read_bytes()
    data_before = (data_dir / "user.db").read_bytes()

    prepared = await manager.prepare()

    assert prepared.path.parent.name == "versions"
    assert manager.layout.pending_file.is_file()
    assert source.acquire_calls == 1
    assert config_path.read_bytes() == config_before
    assert (data_dir / "user.db").read_bytes() == data_before
    assert [call[1] for call in checker.calls] == ["pre-switch"]


@pytest.mark.asyncio
async def test_prepare_rejects_incompatible_config_before_promotion(
    tmp_path: Path,
) -> None:
    manager, source, _checker, _config_path, _data_dir = make_manager(
        tmp_path, required_config_version="2.0.0"
    )

    with pytest.raises(ConfigurationCompatibilityError):
        await manager.prepare()

    assert not manager.layout.pending_file.exists()
    assert not list(manager.layout.versions_dir.glob("*"))
    assert source.acquire_calls == 1


@pytest.mark.asyncio
async def test_prepare_rejects_pre_switch_health_failure(tmp_path: Path) -> None:
    manager, _source, checker, _config_path, _data_dir = make_manager(
        tmp_path, health=[False, True]
    )

    with pytest.raises(HealthCheckFailed, match="健康检查"):
        await manager.prepare()

    assert not manager.layout.pending_file.exists()
    assert [call[1] for call in checker.calls] == ["pre-switch"]


@pytest.mark.asyncio
async def test_install_policy_only_checks_without_acquiring(tmp_path: Path) -> None:
    manager, source, _checker, _config_path, _data_dir = make_manager(
        tmp_path, policy=UpdatePolicy.CHECK_ONLY
    )

    result = await manager.run_policy()

    assert isinstance(result, CheckResult)
    assert source.acquire_calls == 0


@pytest.mark.asyncio
async def test_download_policy_prepares_but_does_not_request_install(
    tmp_path: Path,
) -> None:
    manager, source, _checker, _config_path, _data_dir = make_manager(
        tmp_path, policy=UpdatePolicy.AUTO_DOWNLOAD, health=[True]
    )

    result = await manager.run_policy()

    assert isinstance(result, PrepareResult)
    assert source.acquire_calls == 1
    assert not manager.layout.handoff_file.exists()


@pytest.mark.asyncio
async def test_install_policy_writes_external_handoff_without_hot_replacement(
    tmp_path: Path,
) -> None:
    manager, _source, _checker, _config_path, _data_dir = make_manager(
        tmp_path, policy=UpdatePolicy.AUTO_INSTALL, health=[True]
    )

    result = await manager.run_policy()

    assert isinstance(result, HandoffResult)
    assert result.action == "activate"
    assert (
        json.loads(manager.layout.handoff_file.read_text(encoding="utf-8"))["action"]
        == "activate"
    )
    assert manager.layout.read_active() is None


@pytest.mark.asyncio
async def test_apply_handoff_can_skip_child_process_launch(tmp_path: Path) -> None:
    manager, _source, checker, _config_path, _data_dir = make_manager(tmp_path)
    await manager.prepare()
    await manager.request_install()
    launcher = RecordingLauncher()
    manager.launcher = launcher

    result = await manager.apply_handoff(start_process=False)

    assert result.success
    assert launcher.calls == []
    assert [call[1] for call in checker.calls] == ["pre-switch", "post-switch"]


@pytest.mark.asyncio
async def test_corrupt_handoff_is_quarantined_without_changing_active_pointer(
    tmp_path: Path,
) -> None:
    manager, _source, _checker, _config_path, _data_dir = make_manager(tmp_path)
    manager.layout.ensure()
    manager.layout.handoff_file.write_text("{", encoding="utf-8")

    result = await manager.apply_handoff(start_process=False)

    assert not result.success
    assert manager.layout.read_active() is None
    assert not manager.layout.handoff_file.exists()
    failed = list(manager.layout.failed_handoffs_dir.glob("*.json"))
    assert len(failed) == 1
    assert failed[0].read_text(encoding="utf-8") == "{"
    assert "handoff 记录损坏" in result.reason


@pytest.mark.asyncio
async def test_invalid_utf8_handoff_is_quarantined_without_startup_failure(
    tmp_path: Path,
) -> None:
    manager, _source, _checker, _config_path, _data_dir = make_manager(tmp_path)
    manager.layout.ensure()
    manager.layout.handoff_file.write_bytes(b"\xff\xfe")

    result = await manager.apply_handoff(start_process=False)

    assert not result.success
    assert not manager.layout.handoff_file.exists()
    failed = list(manager.layout.failed_handoffs_dir.glob("*.json"))
    assert len(failed) == 1
    assert failed[0].read_bytes() == b"\xff\xfe"


@pytest.mark.asyncio
async def test_inconsistent_activate_handoff_is_quarantined_and_pending_cleared(
    tmp_path: Path,
) -> None:
    manager, _source, _checker, _config_path, _data_dir = make_manager(tmp_path)
    prepared = await manager.prepare()
    manager.layout.write_handoff(
        {
            "action": "activate",
            "version": str(prepared.release.version),
            "path": str(tmp_path / "not-the-prepared-version"),
        }
    )

    result = await manager.apply_handoff(start_process=False)

    assert not result.success
    assert manager.layout.read_active() is None
    assert not manager.layout.pending_file.exists()
    assert not manager.layout.handoff_file.exists()
    assert len(list(manager.layout.failed_handoffs_dir.glob("*.json"))) == 1
    audit_entries = [
        json.loads(line)
        for line in manager.layout.audit_file.read_text(encoding="utf-8").splitlines()
    ]
    assert "不一致" in audit_entries[-1]["error"]


@pytest.mark.asyncio
async def test_invalid_activation_recovery_does_not_create_baseline_pointer(
    tmp_path: Path,
) -> None:
    manager, _source, _checker, _config_path, _data_dir = make_manager(tmp_path)
    prepared = await manager.prepare()
    pending = json.loads(manager.layout.pending_file.read_text(encoding="utf-8"))
    pending["activation_recovery"] = {
        "from": {"version": "1.0.0", "path": str(tmp_path / "outside")}
    }
    manager.layout.write_pending(pending)
    manager.layout.write_handoff(
        {
            "action": "activate",
            "version": str(prepared.release.version),
            "path": str(prepared.path),
        }
    )

    result = await manager.apply_handoff(start_process=False)

    assert not result.success
    assert manager.layout.read_active() is None
    assert not manager.layout.pending_file.exists()
    assert not manager.layout.handoff_file.exists()


@pytest.mark.asyncio
async def test_unknown_handoff_action_is_quarantined_and_not_retried(
    tmp_path: Path,
) -> None:
    manager, _source, _checker, _config_path, _data_dir = make_manager(tmp_path)
    manager.layout.write_handoff({"action": "future-action"})

    result = await manager.apply_handoff(start_process=False)

    assert not result.success
    assert not manager.layout.handoff_file.exists()
    assert len(list(manager.layout.failed_handoffs_dir.glob("*.json"))) == 1
    assert "future-action" in result.reason


@pytest.mark.asyncio
async def test_failed_handoff_retention_is_bounded(tmp_path: Path) -> None:
    manager, _source, _checker, _config_path, _data_dir = make_manager(tmp_path)

    for index in range(12):
        manager.layout.write_handoff({"action": f"unknown-{index}"})
        result = await manager.apply_handoff(start_process=False)
        assert not result.success

    assert len(list(manager.layout.failed_handoffs_dir.glob("*.json"))) == 10


@pytest.mark.asyncio
async def test_activate_pending_switches_atomically_and_preserves_previous_copy(
    tmp_path: Path,
) -> None:
    manager, _source, checker, config_path, data_dir = make_manager(tmp_path)
    prepared = await manager.prepare()
    result = await manager.activate_pending()

    active = manager.layout.read_active()
    previous = manager.layout.read_previous()
    assert result.success
    assert not result.rolled_back
    assert active is not None and active.path == prepared.path
    assert previous is not None and previous.version == parse_version("1.0.0")
    assert (previous.path / "tenko" / "__init__.py").is_file()
    assert [call[1] for call in checker.calls] == ["pre-switch", "post-switch"]
    assert config_path.read_text(encoding="utf-8") == "user_setting = true\n"
    assert (data_dir / "user.db").read_text(encoding="utf-8") == "keep"


@pytest.mark.asyncio
async def test_post_switch_health_failure_automatically_restores_previous_pointer(
    tmp_path: Path,
) -> None:
    manager, _source, checker, _config_path, _data_dir = make_manager(
        tmp_path, health=[True, False]
    )
    prepared = await manager.prepare()

    result = await manager.activate_pending()

    active = manager.layout.read_active()
    assert not result.success
    assert result.rolled_back
    assert active is not None
    assert active.version == parse_version("1.0.0")
    assert active.path != prepared.path
    entries = [
        json.loads(line)
        for line in manager.layout.audit_file.read_text(encoding="utf-8").splitlines()
    ]
    assert any(
        item["action"] == "rollback" and item["result"] == "success" for item in entries
    )
    assert manager.layout.pending_file.exists() is False
    assert [call[1] for call in checker.calls] == ["pre-switch", "post-switch"]


@pytest.mark.asyncio
async def test_activation_recovers_after_active_pointer_write_crash(
    monkeypatch, tmp_path: Path
) -> None:
    manager, _source, checker, _config_path, _data_dir = make_manager(
        tmp_path, health=[True, True]
    )
    prepared = await manager.prepare()
    await manager.request_install()
    original_write_pointer = UpgradeLayout.write_pointer
    pointer_writes = 0

    def crash_after_target_write(layout, target, version, *, previous=False) -> None:
        nonlocal pointer_writes
        pointer_writes += 1
        original_write_pointer(layout, target, version, previous=previous)
        if pointer_writes == 2 and not previous:
            raise SystemExit("simulated process crash")

    monkeypatch.setattr(UpgradeLayout, "write_pointer", crash_after_target_write)
    with pytest.raises(SystemExit, match="simulated process crash"):
        await manager.activate_pending(start_process=False)

    pending = json.loads(manager.layout.pending_file.read_text(encoding="utf-8"))
    assert pending["activation_recovery"]["from"]["version"] == "1.0.0"
    assert manager.layout.read_active().path == prepared.path

    checker.values = [True]
    recovered = await manager.apply_handoff(start_process=False)

    assert recovered.success
    assert manager.layout.read_active().path == prepared.path
    previous = manager.layout.read_previous()
    assert previous is not None
    assert previous.path != prepared.path
    assert not manager.layout.pending_file.exists()
    assert not manager.layout.handoff_file.exists()


@pytest.mark.asyncio
async def test_activation_recovers_when_cleanup_crashes_after_health_check(
    monkeypatch, tmp_path: Path
) -> None:
    manager, _source, checker, _config_path, _data_dir = make_manager(
        tmp_path, health=[True, True, True]
    )
    await manager.prepare()
    await manager.request_install()
    original_clear_pending = UpgradeLayout.clear_pending
    crashed = False

    def crash_once(layout) -> None:
        nonlocal crashed
        if not crashed:
            crashed = True
            raise SystemExit("simulated cleanup crash")
        original_clear_pending(layout)

    monkeypatch.setattr(UpgradeLayout, "clear_pending", crash_once)
    with pytest.raises(SystemExit, match="simulated cleanup crash"):
        await manager.activate_pending(start_process=False)

    assert manager.layout.pending_file.exists()
    assert manager.layout.handoff_file.exists()
    checker.values = [True]

    recovered = await manager.apply_handoff(start_process=False)

    assert recovered.success
    assert not manager.layout.pending_file.exists()
    assert not manager.layout.handoff_file.exists()
    assert manager.layout.read_previous() is not None


@pytest.mark.asyncio
async def test_rollback_request_is_deferred_and_apply_handoff_checks_old_version(
    tmp_path: Path,
) -> None:
    manager, _source, checker, _config_path, _data_dir = make_manager(tmp_path)
    await manager.prepare()
    await manager.activate_pending()
    requested = await manager.rollback()

    assert not requested.applied
    assert (
        json.loads(manager.layout.handoff_file.read_text(encoding="utf-8"))["action"]
        == "rollback"
    )
    applied = await manager.apply_handoff()
    assert applied.success
    assert applied.applied
    assert manager.layout.read_active().version == parse_version("1.0.0")
    assert [call[1] for call in checker.calls] == [
        "pre-switch",
        "post-switch",
        "rollback",
    ]


@pytest.mark.asyncio
async def test_rollback_failure_restores_active_and_quarantines_live_handoff(
    tmp_path: Path,
) -> None:
    manager, _source, checker, _config_path, _data_dir = make_manager(
        tmp_path, health=[True, True, False]
    )
    await manager.prepare()
    await manager.activate_pending(start_process=False)
    requested = await manager.rollback()
    assert not requested.applied

    result = await manager.apply_handoff(start_process=False)

    assert not result.success
    active = manager.layout.read_active()
    previous = manager.layout.read_previous()
    assert active is not None and active.version == parse_version("1.1.0")
    assert previous is not None and previous.version == parse_version("1.0.0")
    assert not manager.layout.handoff_file.exists()
    assert len(list(manager.layout.failed_handoffs_dir.glob("*.json"))) == 1
    assert [call[1] for call in checker.calls] == [
        "pre-switch",
        "post-switch",
        "rollback",
    ]


@pytest.mark.asyncio
async def test_rollback_recovers_after_active_pointer_write_crash(
    monkeypatch, tmp_path: Path
) -> None:
    manager, _source, checker, _config_path, _data_dir = make_manager(
        tmp_path, health=[True, True, True]
    )
    await manager.prepare()
    await manager.activate_pending(start_process=False)
    await manager.rollback()
    original_write_pointer = UpgradeLayout.write_pointer
    crashed = False

    def crash_once(layout, target, version, *, previous=False) -> None:
        nonlocal crashed
        original_write_pointer(layout, target, version, previous=previous)
        if not crashed and not previous:
            crashed = True
            raise SystemExit("simulated rollback crash")

    monkeypatch.setattr(UpgradeLayout, "write_pointer", crash_once)
    with pytest.raises(SystemExit, match="simulated rollback crash"):
        await manager.apply_handoff(start_process=False)

    checker.values = [True]
    recovered = await manager.apply_handoff(start_process=False)

    assert recovered.success
    active = manager.layout.read_active()
    previous = manager.layout.read_previous()
    assert active is not None and active.version == parse_version("1.0.0")
    assert previous is not None and previous.version == parse_version("1.1.0")
    assert not manager.layout.handoff_file.exists()


@pytest.mark.asyncio
async def test_rollback_without_previous_version_is_rejected_and_audited(
    tmp_path: Path,
) -> None:
    manager, _source, _checker, _config_path, _data_dir = make_manager(tmp_path)

    with pytest.raises(NoRollbackAvailable):
        await manager.rollback()

    entry = json.loads(
        manager.layout.audit_file.read_text(encoding="utf-8").splitlines()[-1]
    )
    assert entry["action"] == "rollback"
    assert entry["result"] == "failed"


def test_layout_rejects_pointer_outside_upgrade_root(tmp_path: Path) -> None:
    layout = UpgradeLayout(tmp_path / "state")
    layout.ensure()
    layout.active_file.write_text(
        json.dumps({"version": "1.0.0", "path": str(tmp_path)}), encoding="utf-8"
    )

    with pytest.raises(ValueError):
        layout.read_active()


def test_audit_logger_writes_required_structured_fields(tmp_path: Path) -> None:
    audit = AuditLogger(tmp_path / "audit.jsonl")
    audit.record("check", current_version="1.0.0", result="current")

    entry = json.loads((tmp_path / "audit.jsonl").read_text(encoding="utf-8"))
    assert entry["action"] == "check"
    assert entry["current_version"] == "1.0.0"
    assert entry["target_version"] is None
    assert entry["result"] == "current"
    assert entry["timestamp"].endswith("+00:00")


@pytest.mark.asyncio
async def test_default_health_checker_checks_minimal_entry_and_dead_process(
    tmp_path: Path,
) -> None:
    candidate = tmp_path / "candidate"
    (candidate / "tenko").mkdir(parents=True)
    (candidate / "tenko" / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
    checker = DefaultHealthChecker()

    good = await checker.check(candidate, phase="pre-switch")
    bad = await checker.check(
        candidate, phase="post-switch", process=type("P", (), {"poll": lambda _: 1})()
    )

    assert isinstance(good, HealthCheckResult) and good.ok
    assert not bad.ok
