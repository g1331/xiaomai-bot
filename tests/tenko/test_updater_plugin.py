from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from arclet.entari import MessageChain
from satori import (
    Channel,
    ChannelType,
    EventType,
    Guild,
    Login,
    MessageObject,
    Role,
    User,
)
from satori.model import Event, Member

from tenko.host.perm import Permission, PermissionChecker, PermissionRegistry
from tenko.host.updater import (
    CheckResult,
    CompatibilityResult,
    HandoffResult,
    NoRollbackAvailable,
    PrepareResult,
    Release,
    RollbackResult,
    UpdateChannel,
    Version,
)


def make_session(user_id: str, role: str = "member"):
    event = Event(
        type=EventType.MESSAGE_CREATED,
        timestamp=datetime.now(),
        login=Login(platform="onebot", user=User("10001")),
        channel=Channel("40001", ChannelType.TEXT),
        guild=Guild("40001", "Tenko"),
        member=Member(user=User(user_id), roles=[Role(role)]),
        user=User(user_id),
        message=MessageObject.from_elements("50001", []),
    )
    return SimpleNamespace(
        event=SimpleNamespace(
            _origin=event,
            channel=event.channel,
            guild=event.guild,
            user=event.user,
        )
    )


class FakeUpdater:
    check_interval_hours = 24

    def __init__(self, tmp_path: Path) -> None:
        self.layout = SimpleNamespace(handoff_file=tmp_path / "handoff.json")
        self.layout.handoff_file.write_text("handoff", encoding="utf-8")
        self.release = Release(Version(2, 0, 0), "v2.0.0", source="memory")
        self.check_result = CheckResult(
            Version(1, 0, 0),
            UpdateChannel.STABLE,
            "memory",
            "available",
            self.release,
            1,
        )
        self.prepare_result = PrepareResult(
            self.release,
            tmp_path / "versions" / "2.0.0",
            CompatibilityResult(Version(1, 0, 0), None, True, "compatible"),
        )
        self.handoff_result = HandoffResult(
            "activate", self.release.version, self.prepare_result.path
        )
        self.rollback_result = RollbackResult(
            True,
            Version(1, 0, 0),
            tmp_path / "versions" / "1.0.0",
            False,
            "已生成外部重启回滚记录",
        )
        self.check_calls = 0
        self.current_version = Version(1, 0, 0)
        self.enabled = True
        self.prepare_calls = 0
        self.request_install_calls = 0
        self.rollback_calls = 0
        self.spawn_restart_watcher_calls = 0
        self.shutdown_calls = 0
        self.watcher_armed = True
        self.audit = FakeAudit()

    async def check(self):
        self.check_calls += 1
        return self.check_result

    async def prepare(self, release):
        self.prepare_calls += 1
        assert release is self.release
        return self.prepare_result

    async def request_install(self):
        self.request_install_calls += 1
        return self.handoff_result

    async def rollback(self):
        self.rollback_calls += 1
        return self.rollback_result

    def spawn_restart_watcher(self):
        self.spawn_restart_watcher_calls += 1
        return self.watcher_armed

    def request_graceful_shutdown(self):
        self.shutdown_calls += 1
        return True


class FakeAudit:
    def __init__(self) -> None:
        self.records: list[dict[str, object]] = []

    def record(self, action: str, **details: object) -> None:
        self.records.append({"action": action, **details})


def authorize_master(loaded_plugin) -> None:
    registry = PermissionRegistry()
    registry.set_user_level(None, "90001", Permission.Master)
    loaded_plugin.permission_checker = PermissionChecker(registry=registry)


@pytest.mark.parametrize(
    "command",
    ["check_command", "upgrade_command", "rollback_command", "restart_command"],
)
@pytest.mark.parametrize("loaded_plugin", ["updater"], indirect=True)
def test_updater_commands_use_global_prefix_and_reject_bare_words(
    loaded_plugin, command: str
) -> None:
    parsed = getattr(loaded_plugin, command)
    assert parsed.parse(f"/{parsed.command}").matched
    assert not parsed.parse(parsed.command).matched


@pytest.mark.parametrize("loaded_plugin", ["updater"], indirect=True)
def test_upgrade_command_drops_legacy_dash_alias(loaded_plugin) -> None:
    assert not loaded_plugin.upgrade_command.parse("/-upgrade").matched
    assert not loaded_plugin.upgrade_command.parse("-upgrade").matched


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "handler_name",
    ["check_update", "upgrade", "rollback"],
)
@pytest.mark.parametrize("loaded_plugin", ["updater"], indirect=True)
async def test_updater_commands_block_non_superusers(loaded_plugin, handler_name: str):
    loaded_plugin.permission_checker = PermissionChecker(registry=PermissionRegistry())

    result = await getattr(loaded_plugin, handler_name).callable_target(
        make_session("90001", "owner")
    )

    assert isinstance(result, MessageChain)
    assert str(result) == "权限不足：仅超级用户可执行宿主升级操作"


@pytest.mark.asyncio
@pytest.mark.parametrize("loaded_plugin", ["updater"], indirect=True)
async def test_restart_command_blocks_bot_admins(loaded_plugin):
    registry = PermissionRegistry()
    registry.set_user_level(None, "90001", Permission.BotAdmin)
    loaded_plugin.permission_checker = PermissionChecker(registry=registry)

    result = await loaded_plugin.restart.callable_target(make_session("90001"))

    assert isinstance(result, MessageChain)
    assert str(result) == "权限不足：仅 Master 可执行重启操作"


@pytest.mark.asyncio
@pytest.mark.parametrize("loaded_plugin", ["updater"], indirect=True)
async def test_check_update_reports_candidate_for_superuser(loaded_plugin, tmp_path):
    authorize_master(loaded_plugin)
    fake = FakeUpdater(tmp_path)
    loaded_plugin.updater = fake

    result = await loaded_plugin.check_update.callable_target(make_session("90001"))

    assert "发现新版本：2.0.0" in str(result)
    assert fake.check_calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("loaded_plugin", ["updater"], indirect=True)
async def test_upgrade_command_prepares_and_requests_external_install(
    loaded_plugin, monkeypatch, tmp_path
):
    authorize_master(loaded_plugin)
    fake = FakeUpdater(tmp_path)
    loaded_plugin.updater = fake
    monkeypatch.setattr(loaded_plugin, "_RESTART_SHUTDOWN_DELAY_SECONDS", 0)

    result = await loaded_plugin.upgrade.callable_target(make_session("90001"))

    assert str(result) == "版本 2.0.0 已下载、校验通过，正在自动重启进入新版本。"
    assert fake.check_calls == 1
    assert fake.prepare_calls == 1
    assert fake.request_install_calls == 1
    assert fake.spawn_restart_watcher_calls == 1
    await asyncio.sleep(0.01)
    assert fake.shutdown_calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("loaded_plugin", ["updater"], indirect=True)
async def test_upgrade_command_reports_no_update_without_preparing(
    loaded_plugin, tmp_path
):
    authorize_master(loaded_plugin)
    fake = FakeUpdater(tmp_path)
    fake.check_result = CheckResult(
        Version(2, 0, 0), UpdateChannel.STABLE, "memory", "current"
    )
    loaded_plugin.updater = fake

    result = await loaded_plugin.upgrade.callable_target(make_session("90001"))

    assert "当前已是最新版本" in str(result)
    assert fake.prepare_calls == 0
    assert fake.request_install_calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("loaded_plugin", ["updater"], indirect=True)
async def test_rollback_command_requests_external_rollback(
    loaded_plugin, monkeypatch, tmp_path
):
    authorize_master(loaded_plugin)
    fake = FakeUpdater(tmp_path)
    loaded_plugin.updater = fake
    monkeypatch.setattr(loaded_plugin, "_RESTART_SHUTDOWN_DELAY_SECONDS", 0)

    result = await loaded_plugin.rollback.callable_target(make_session("90001"))

    assert str(result) == "已请求回滚到版本 1.0.0，正在自动重启。"
    assert fake.rollback_calls == 1
    assert fake.spawn_restart_watcher_calls == 1
    await asyncio.sleep(0.01)
    assert fake.shutdown_calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("loaded_plugin", ["updater"], indirect=True)
async def test_upgrade_command_only_mentions_manual_restart_when_watcher_arm_fails(
    loaded_plugin, tmp_path
):
    authorize_master(loaded_plugin)
    fake = FakeUpdater(tmp_path)
    fake.watcher_armed = False
    loaded_plugin.updater = fake

    result = await loaded_plugin.upgrade.callable_target(make_session("90001"))

    message = str(result)
    assert "请手动重启" in message
    assert str(tmp_path) not in message
    assert fake.shutdown_calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("loaded_plugin", ["updater"], indirect=True)
async def test_rollback_command_reports_missing_previous_version(
    loaded_plugin, tmp_path
):
    authorize_master(loaded_plugin)
    fake = FakeUpdater(tmp_path)

    async def rollback_without_previous():
        raise NoRollbackAvailable("没有可回滚的上一可用版本")

    fake.rollback = rollback_without_previous
    loaded_plugin.updater = fake

    result = await loaded_plugin.rollback.callable_target(make_session("90001"))

    assert "升级操作失败：没有可回滚的上一可用版本" in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("loaded_plugin", ["updater"], indirect=True)
async def test_restart_command_rejects_when_upgrade_is_disabled(
    loaded_plugin, monkeypatch, tmp_path
):
    authorize_master(loaded_plugin)
    fake = FakeUpdater(tmp_path)
    fake.enabled = False
    loaded_plugin.updater = fake
    monkeypatch.setattr(loaded_plugin, "_restart_cooldown_until", 0.0)

    result = await loaded_plugin.restart.callable_target(make_session("90001"))

    assert str(result) == "重启依赖升级系统，当前未启用"
    assert fake.spawn_restart_watcher_calls == 0
    assert fake.shutdown_calls == 0
    assert fake.audit.records[-1]["result"] == "disabled"


@pytest.mark.asyncio
@pytest.mark.parametrize("loaded_plugin", ["updater"], indirect=True)
async def test_restart_command_arms_watcher_audits_actor_and_shuts_down(
    loaded_plugin, monkeypatch, tmp_path
):
    authorize_master(loaded_plugin)
    fake = FakeUpdater(tmp_path)
    loaded_plugin.updater = fake
    monkeypatch.setattr(loaded_plugin, "_RESTART_SHUTDOWN_DELAY_SECONDS", 0)
    monkeypatch.setattr(loaded_plugin, "_restart_cooldown_until", 0.0)

    result = await loaded_plugin.restart.callable_target(make_session("90001"))

    assert str(result) == "正在重启…"
    assert fake.spawn_restart_watcher_calls == 1
    assert fake.audit.records[-1] == {
        "action": "restart",
        "current_version": Version(1, 0, 0),
        "result": "requested",
        "user_id": "90001",
        "account_id": "10001",
        "platform": "onebot",
        "chat_type": "group",
        "channel_id": "40001",
        "message_id": "50001",
    }
    await asyncio.sleep(0.01)
    assert fake.shutdown_calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("loaded_plugin", ["updater"], indirect=True)
async def test_restart_command_applies_global_cooldown(
    loaded_plugin, monkeypatch, tmp_path
):
    authorize_master(loaded_plugin)
    fake = FakeUpdater(tmp_path)
    loaded_plugin.updater = fake
    monkeypatch.setattr(loaded_plugin, "_RESTART_SHUTDOWN_DELAY_SECONDS", 0)
    monkeypatch.setattr(loaded_plugin, "_restart_cooldown_until", 0.0)

    first = await loaded_plugin.restart.callable_target(make_session("90001"))
    second = await loaded_plugin.restart.callable_target(make_session("90001"))

    assert str(first) == "正在重启…"
    assert str(second) == "重启操作冷却中，请稍后再试"
    assert fake.spawn_restart_watcher_calls == 1
    assert [record["result"] for record in fake.audit.records[-2:]] == [
        "requested",
        "cooldown",
    ]
    await asyncio.sleep(0.01)
    assert fake.shutdown_calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("loaded_plugin", ["updater"], indirect=True)
async def test_restart_command_releases_cooldown_when_watcher_arm_fails(
    loaded_plugin, monkeypatch, tmp_path
):
    authorize_master(loaded_plugin)
    fake = FakeUpdater(tmp_path)
    fake.watcher_armed = False
    loaded_plugin.updater = fake
    monkeypatch.setattr(loaded_plugin, "_restart_cooldown_until", 0.0)

    result = await loaded_plugin.restart.callable_target(make_session("90001"))

    assert str(result) == "重启失败：自动重启未能启动，请手动重启。"
    assert fake.shutdown_calls == 0
    assert fake.audit.records[-1]["result"] == "watcher_failed"
    assert loaded_plugin._restart_cooldown_until == 0.0
