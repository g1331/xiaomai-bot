from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from arclet.entari.plugin import get_plugins

from tenko.host.features import FeatureService
from tenko.host.perm import PermissionChecker, PermissionRegistry
from tenko.host.startup import (
    StartupHistory,
    StartupNotifier,
    build_startup_notice,
    calculate_beaten_percent,
    calculate_percentile,
)


class NotificationActions:
    def __init__(self) -> None:
        self.group_messages: list[tuple[str, str]] = []
        self.private_messages: list[tuple[str, str]] = []

    async def send_group_message(self, account, group_id, content, **kwargs):
        del account, kwargs
        self.group_messages.append((str(group_id), content))

    async def send_private_message(self, account, user_id, content):
        del account
        self.private_messages.append((str(user_id), content))


def make_notifier(
    actions: NotificationActions,
    *,
    notify_group: str | None = "40002",
    permission_checker: PermissionChecker | None = None,
    started_at: float = 10.0,
    now: float = 12.5,
) -> StartupNotifier:
    return StartupNotifier(
        notify_group=notify_group,
        history=StartupHistory(),
        action_service=actions,
        feature_service=FeatureService(),
        permission_checker=permission_checker,
        started_at=started_at,
        clock=lambda: now,
        version_provider=lambda: "4.0.0-pre6",
    )


def test_startup_notice_without_history_contains_version_and_duration() -> None:
    notice = build_startup_notice("4.0.0-pre6", 2.5, ())

    assert "Tenko 已启动" in notice
    assert "版本：v4.0.0-pre6" in notice
    assert "启动耗时：2.50 秒" in notice
    assert "首次启动，暂无对比数据" in notice


def test_beaten_percent_uses_sorted_linear_interpolation() -> None:
    assert calculate_beaten_percent(1.5, [3.0, 1.0, 2.0]) == pytest.approx(75.0)
    assert calculate_percentile(1.5, [3.0, 1.0, 2.0]) == pytest.approx(25.0)
    assert calculate_beaten_percent(1.5, ()) is None


@pytest.mark.parametrize("loaded_plugin", ["startup_notify"], indirect=True)
def test_startup_notify_is_a_global_feature_plugin(loaded_plugin) -> None:
    native = next(
        item
        for item in get_plugins(subplugged=True)
        if item.id == "tenko.plugins.startup_notify"
    )

    assert native.metadata.name == "启动通知"
    assert "required" in native.metadata.classifier
    assert native.metadata.feature_scope == "global"
    assert loaded_plugin.notifier is None


@pytest.mark.asyncio
@pytest.mark.parametrize("loaded_plugin", ["startup_notify"], indirect=True)
async def test_startup_notify_plugin_ready_listener_uses_configured_notifier(
    loaded_plugin,
) -> None:
    actions = NotificationActions()
    loaded_plugin.action_service = actions
    loaded_plugin.feature_service = FeatureService()
    loaded_plugin.permission_checker = PermissionChecker(
        registry=PermissionRegistry(master_id="90001")
    )
    loaded_plugin.configure_startup_notification(
        None,
        started_at=10.0,
        history=StartupHistory(),
    )
    loaded_plugin.notifier.clock = lambda: 12.5
    loaded_plugin.notifier.version_provider = lambda: "4.0.0-pre6"

    await loaded_plugin.on_account_online(
        SimpleNamespace(self_id="10001", platform="onebot")
    )
    await loaded_plugin.on_ready.callable_target()

    assert len(actions.private_messages) == 1
    assert actions.private_messages[0][0] == "90001"


@pytest.mark.asyncio
async def test_startup_notifier_waits_for_framework_and_account() -> None:
    actions = NotificationActions()
    notifier = make_notifier(actions)
    account = SimpleNamespace(self_id="10001", platform="onebot")

    await notifier.mark_account_online(account)
    assert actions.group_messages == []

    await notifier.mark_framework_ready()

    assert len(actions.group_messages) == 1
    group_id, notice = actions.group_messages[0]
    assert group_id == "40002"
    assert "启动耗时：2.50 秒" in notice
    assert "首次启动，暂无对比数据" in notice
    assert await notifier.history.load() == (2.5,)


@pytest.mark.asyncio
async def test_startup_notifier_persists_history_in_database(repositories) -> None:
    actions = NotificationActions()
    features = FeatureService(repositories["feature"])
    await features.initialize()
    history = StartupHistory(repositories["startup"])
    notifier = StartupNotifier(
        notify_group="40002",
        history=history,
        action_service=actions,
        feature_service=features,
        started_at=10.0,
        clock=lambda: 12.5,
    )

    await notifier.mark_framework_ready()
    await notifier.mark_account_online(
        SimpleNamespace(self_id="10001", platform="onebot")
    )

    assert "首次启动，暂无对比数据" in actions.group_messages[0][1]
    assert await repositories["startup"].list_durations() == (2.5,)
    restarted = StartupHistory(repositories["startup"])
    assert await restarted.load() == (2.5,)


@pytest.mark.asyncio
async def test_startup_notifier_continues_when_history_database_is_unavailable() -> (
    None
):
    class FailingRepository:
        async def list_durations(self):
            raise RuntimeError("database offline")

        async def record(self, duration):
            del duration
            raise RuntimeError("database offline")

    actions = NotificationActions()
    notifier = StartupNotifier(
        notify_group="40002",
        history=StartupHistory(FailingRepository()),
        action_service=actions,
        feature_service=FeatureService(),
        started_at=10.0,
        clock=lambda: 12.5,
    )

    await notifier.mark_framework_ready()
    await notifier.mark_account_online(
        SimpleNamespace(self_id="10001", platform="onebot")
    )

    assert "首次启动，暂无对比数据" in actions.group_messages[0][1]
    assert not notifier.history.ready


@pytest.mark.asyncio
async def test_startup_notifier_skips_send_when_feature_is_disabled() -> None:
    actions = NotificationActions()
    features = FeatureService()
    features.set_global_enabled("startup_notify", False)
    notifier = StartupNotifier(
        notify_group="40002",
        history=StartupHistory(),
        action_service=actions,
        feature_service=features,
        started_at=10.0,
        clock=lambda: 12.5,
    )

    await notifier.mark_framework_ready()
    await notifier.mark_account_online(
        SimpleNamespace(self_id="10001", platform="onebot")
    )

    assert actions.group_messages == []
    assert await notifier.history.load() == ()


@pytest.mark.asyncio
async def test_startup_notifier_falls_back_to_master_private_message() -> None:
    actions = NotificationActions()
    checker = PermissionChecker(registry=PermissionRegistry(master_id="90001"))
    notifier = make_notifier(
        actions,
        notify_group=None,
        permission_checker=checker,
    )

    await notifier.mark_framework_ready()
    await notifier.mark_account_online(
        SimpleNamespace(self_id="10001", platform="onebot")
    )

    assert actions.group_messages == []
    assert len(actions.private_messages) == 1
    user_id, notice = actions.private_messages[0]
    assert user_id == "90001"
    assert "版本：v4.0.0-pre6" in notice


@pytest.mark.asyncio
async def test_startup_notifier_sends_and_clears_recovery_notice_first(
    tmp_path,
) -> None:
    actions = NotificationActions()
    notice_path = tmp_path / "recovery-notice.json"
    notice_path.write_text('{"message":"已自动回滚至 1.0.0 版本"}\n', encoding="utf-8")
    features = FeatureService()
    features.set_global_enabled("startup_notify", False)
    notifier = StartupNotifier(
        notify_group="40002",
        history=StartupHistory(),
        action_service=actions,
        feature_service=features,
        recovery_notice_path=notice_path,
        started_at=10.0,
        clock=lambda: 12.5,
    )

    await notifier.mark_framework_ready()
    await notifier.mark_account_online(
        SimpleNamespace(self_id="10001", platform="onebot")
    )

    assert actions.group_messages == [("40002", "已自动回滚至 1.0.0 版本")]
    assert not notice_path.exists()


@pytest.mark.asyncio
async def test_recovery_notice_uses_master_fallback_when_group_is_unset(
    tmp_path,
) -> None:
    actions = NotificationActions()
    notice_path = tmp_path / "recovery-notice.json"
    notice_path.write_text('{"message":"已自动回滚至 1.0.0 版本"}\n', encoding="utf-8")
    features = FeatureService()
    features.set_global_enabled("startup_notify", False)
    notifier = StartupNotifier(
        notify_group=None,
        history=StartupHistory(),
        action_service=actions,
        feature_service=features,
        permission_checker=PermissionChecker(
            registry=PermissionRegistry(master_id="90001")
        ),
        recovery_notice_path=notice_path,
        started_at=10.0,
        clock=lambda: 12.5,
    )

    await notifier.mark_framework_ready()
    await notifier.mark_account_online(
        SimpleNamespace(self_id="10001", platform="onebot")
    )

    assert actions.group_messages == []
    assert actions.private_messages == [("90001", "已自动回滚至 1.0.0 版本")]
    assert not notice_path.exists()


@pytest.mark.asyncio
async def test_startup_notification_failure_does_not_escape_or_skip_history() -> None:
    actions = NotificationActions()
    actions.send_group_message = AsyncMock(side_effect=RuntimeError("offline"))
    notifier = make_notifier(actions)

    await notifier.mark_framework_ready()
    await notifier.mark_account_online(
        SimpleNamespace(self_id="10001", platform="onebot")
    )

    actions.send_group_message.assert_awaited_once()
    assert await notifier.history.load() == (2.5,)
