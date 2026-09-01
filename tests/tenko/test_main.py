from __future__ import annotations

from pathlib import Path

import pytest

from tenko import __main__ as main_module
from tenko.config import TenkoConfig
from tenko.host.updater import InstallResult, RollbackResult, UpgradeLayout, Version


def _write_project_version(root: Path, version: str = "1.0.0") -> None:
    (root / "pyproject.toml").write_text(
        f'[project]\nversion = "{version}"\n', encoding="utf-8"
    )


def test_main_without_active_release_runs_stable_code(
    monkeypatch, tmp_path: Path
) -> None:
    _write_project_version(tmp_path)
    monkeypatch.chdir(tmp_path)
    calls: list[TenkoConfig] = []

    from tenko import runtime as runtime_module

    monkeypatch.setattr(runtime_module, "run", calls.append)

    assert main_module.main([]) == 0
    assert len(calls) == 1
    assert calls[0].upgrade.current_version is None


def test_main_dry_run_does_not_consume_handoff(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    handoff = tmp_path / ".tenko" / "upgrades" / "handoff.json"
    handoff.parent.mkdir(parents=True)
    handoff.write_text('{"action":"activate"}\n', encoding="utf-8")
    before = handoff.read_bytes()

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("dry-run must not enter startup bootstrap")

    monkeypatch.setattr(main_module, "_run_startup_bootstrap", fail_if_called)

    assert main_module.main(["--dry-run"]) == 0
    assert handoff.read_bytes() == before
    assert not (tmp_path / ".tenko" / "upgrades" / "failed-handoffs").exists()


def test_main_applies_handoff_and_reexecutes_active_release(
    monkeypatch, tmp_path: Path
) -> None:
    candidate = tmp_path / ".tenko" / "upgrades" / "versions" / "2.0.0"
    (candidate / "tenko").mkdir(parents=True)
    layout = UpgradeLayout(tmp_path / ".tenko" / "upgrades")
    layout.write_pointer(candidate, Version("2.0.0"))
    layout.handoff_file.write_text('{"action":"activate"}\n', encoding="utf-8")
    calls: dict[str, object] = {"apply": []}

    class FakeManager:
        def __init__(self) -> None:
            self.layout = layout

        @classmethod
        def from_config(cls, _config, *, project_root):
            calls["project_root"] = project_root
            return cls()

        async def apply_handoff(self, *, start_process: bool):
            calls["apply"].append(start_process)
            return InstallResult(True, Version("2.0.0"), candidate, False, "ok")

    import tenko.host.updater as updater_module

    monkeypatch.setattr(updater_module, "UpgradeManager", FakeManager)
    reexec: list[tuple[Path, Path, list[str]]] = []
    monkeypatch.setattr(
        main_module,
        "_exec_release_root",
        lambda release, stable, arguments: reexec.append(
            (release, stable, list(arguments))
        ),
    )
    monkeypatch.chdir(tmp_path)

    arguments = ["--config", "config/tenko.toml"]
    assert main_module.main(arguments) == 0
    assert calls["apply"] == [False]
    assert calls["project_root"] == tmp_path.resolve()
    assert reexec == [
        (candidate.resolve(), tmp_path.resolve(), arguments),
    ]


def test_main_continues_with_recovered_active_after_rolled_back_handoff(
    monkeypatch, tmp_path: Path
) -> None:
    candidate = tmp_path / ".tenko" / "upgrades" / "versions" / "1.0.0"
    (candidate / "tenko").mkdir(parents=True)
    layout = UpgradeLayout(tmp_path / ".tenko" / "upgrades")
    layout.write_pointer(candidate, Version("1.0.0"))
    layout.handoff_file.write_text('{"action":"activate"}\n', encoding="utf-8")
    calls: list[bool] = []

    class FakeManager:
        def __init__(self) -> None:
            self.layout = layout

        @classmethod
        def from_config(cls, _config, *, project_root):
            assert project_root == tmp_path.resolve()
            return cls()

        async def apply_handoff(self, *, start_process: bool):
            calls.append(start_process)
            return InstallResult(
                False, Version("2.0.0"), candidate, True, "health check failed"
            )

    import tenko.host.updater as updater_module

    monkeypatch.setattr(updater_module, "UpgradeManager", FakeManager)
    reexec: list[Path] = []
    monkeypatch.setattr(
        main_module,
        "_exec_release_root",
        lambda release, _stable, _arguments: reexec.append(release),
    )
    monkeypatch.chdir(tmp_path)

    assert main_module.main([]) == 0
    assert calls == [False]
    assert reexec == [candidate.resolve()]


def test_main_stops_when_automatic_rollback_handoff_fails(
    monkeypatch, tmp_path: Path
) -> None:
    candidate = tmp_path / ".tenko" / "upgrades" / "versions" / "2.0.0"
    (candidate / "tenko").mkdir(parents=True)
    layout = UpgradeLayout(tmp_path / ".tenko" / "upgrades")
    layout.write_pointer(candidate, Version("2.0.0"))
    layout.write_handoff(
        {
            "action": "rollback",
            "version": "1.0.0",
            "path": str(tmp_path / ".tenko" / "upgrades" / "versions" / "1.0.0"),
            "automatic_rollback": True,
        }
    )

    class FakeManager:
        def __init__(self) -> None:
            self.layout = layout

        @classmethod
        def from_config(cls, _config, *, project_root):
            assert project_root == tmp_path.resolve()
            return cls()

        async def apply_handoff(self, *, start_process: bool):
            assert start_process is False
            return RollbackResult(
                False,
                Version("1.0.0"),
                candidate,
                True,
                "rollback health check failed",
            )

    import tenko.host.updater as updater_module

    monkeypatch.setattr(updater_module, "UpgradeManager", FakeManager)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit, match="1"):
        main_module._run_startup_bootstrap(TenkoConfig(), [])


@pytest.mark.parametrize(
    ("stable_version", "active_version", "current_root", "expected_release"),
    [
        ("2.0.0", "1.0.0", "old", "stable"),
        ("1.0.0", "1.0.0", "stable", "active"),
        ("1.0.0", "2.0.0", "stable", "active"),
    ],
    ids=["stable-newer", "same-version", "active-newer"],
)
def test_startup_bootstrap_compares_active_with_stable_version(
    monkeypatch,
    tmp_path: Path,
    stable_version: str,
    active_version: str,
    current_root: str,
    expected_release: str,
) -> None:
    candidate = tmp_path / ".tenko" / "upgrades" / "versions" / "candidate"
    (candidate / "tenko").mkdir(parents=True)
    layout = UpgradeLayout(tmp_path / ".tenko" / "upgrades")
    layout.write_pointer(candidate, Version(active_version))

    class FakeManager:
        def __init__(self) -> None:
            self.layout = layout

        @classmethod
        def from_config(cls, _config, *, project_root):
            assert project_root == tmp_path.resolve()
            return cls()

    import tenko.host.updater as updater_module

    monkeypatch.setattr(updater_module, "UpgradeManager", FakeManager)
    monkeypatch.setattr(
        updater_module,
        "read_project_version",
        lambda _root: Version(stable_version),
    )
    monkeypatch.setattr(
        main_module,
        "_current_code_root",
        lambda: (tmp_path / current_root).resolve(),
    )
    reexec: list[Path] = []
    monkeypatch.setattr(
        main_module,
        "_exec_release_root",
        lambda release, _stable, _arguments: reexec.append(release),
    )
    warnings: list[tuple[object, ...]] = []
    monkeypatch.setattr(
        main_module.logger,
        "warning",
        lambda *arguments: warnings.append(arguments),
    )
    monkeypatch.chdir(tmp_path)

    result = main_module._run_startup_bootstrap(TenkoConfig(), [])

    assert result is True
    expected = tmp_path if expected_release == "stable" else candidate
    assert reexec == [expected.resolve()]
    if expected_release == "stable":
        assert len(warnings) == 1
        assert "稳定根版本 {} 新于 active 指针 {}" in warnings[0][0]
    else:
        assert warnings == []
