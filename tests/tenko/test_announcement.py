from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from arclet.entari.command import Match
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

from tenko.context import MessageContext
from tenko.host.actions import (
    ActionCapability,
    ActionExecutionError,
    ActionFailure,
    ActionService,
)
from tenko.host.accounts import AccountRegistry
from tenko.host.features import FeatureService
from tenko.host.perm import PermissionChecker, PermissionRegistry
from tenko.host.plugins import PluginInfo


@dataclass
class FakeAccount:
    self_id: str


def make_feature() -> PluginInfo:
    return PluginInfo(
        name="helper",
        path=Path("tenko/plugins/helper"),
        is_package=True,
        qualified_name="tenko.plugins.helper",
    )


def make_context() -> MessageContext:
    return MessageContext(
        account_id="10001",
        event_type="message-created",
        protocol_event_type="message.group.normal",
        chat_type="group",
        channel_id="40001",
        user_id="20001",
        message_id="50001",
        text="",
        image_urls=(),
        member_role="admin",
    )


def make_session():
    context = make_context()
    event = Event(
        type=EventType.MESSAGE_CREATED,
        timestamp=datetime.now(),
        login=Login(platform="onebot", user=User(context.account_id)),
        channel=Channel(context.channel_id, ChannelType.TEXT),
        guild=Guild(context.channel_id, "Tenko"),
        member=Member(user=User(context.user_id), roles=[Role("admin")]),
        user=User(context.user_id),
        message=MessageObject.from_elements(context.message_id, []),
    )
    return SimpleNamespace(event=SimpleNamespace(_origin=event))


@pytest.mark.parametrize(
    ("group_id", "status"),
    [
        ("40002", "skipped_muted"),
        ("40003", "skipped_account_unavailable"),
        ("40004", "skipped_feature_disabled"),
    ],
)
@pytest.mark.parametrize("loaded_plugin", ["announcement"], indirect=True)
def test_collect_targets_reports_each_unsupported_group(
    group_id: str, status: str, monkeypatch, loaded_plugin
) -> None:
    first = FakeAccount("10001")
    unavailable = FakeAccount("10002")
    registry = AccountRegistry()
    registry.register(first, groups=["40001", "40002", "40004"])
    registry.register(unavailable, available=False, groups=["40003"])
    registry.set_muted(first, "40002", True)
    monkeypatch.setattr(
        loaded_plugin, "feature_enabled", lambda feature, group: group != "40004"
    )

    targets, results = loaded_plugin.collect_targets(make_feature(), registry)

    assert targets == (loaded_plugin.PushTarget("40001", "10001"),)
    result = next(item for item in results if item.group_id == group_id)
    assert result.status == status


@pytest.mark.asyncio
@pytest.mark.parametrize("loaded_plugin", ["announcement"], indirect=True)
async def test_pusher_sends_one_payload_per_target_and_waits_between_targets(
    loaded_plugin,
) -> None:
    service = SimpleNamespace(
        send_group_message=AsyncMock(return_value=None),
    )
    sleep = AsyncMock()
    context = make_context()
    targets = (
        loaded_plugin.PushTarget("40001", "10001"),
        loaded_plugin.PushTarget("40002", "10002"),
    )

    results = await loaded_plugin.pusher(
        targets,
        "维护通知",
        2,
        context=context,
        service=service,
        sleep=sleep,
    )

    assert [result.status for result in results] == ["sent", "sent"]
    assert service.send_group_message.await_count == 2
    first_call = service.send_group_message.await_args_list[0]
    assert first_call.args[:2] == ("10001", "40001")
    assert "===BOT公告推送===" in first_call.args[2]
    assert "维护通知" in first_call.args[2]
    sleep.assert_awaited_once_with(120)


@pytest.mark.asyncio
@pytest.mark.parametrize("loaded_plugin", ["announcement"], indirect=True)
async def test_pusher_exposes_structured_action_failure_per_target(
    loaded_plugin,
) -> None:
    failure = ActionFailure(
        account_id="10001",
        capability=ActionCapability.SEND_GROUP_MESSAGE,
        action="send_group_msg",
        status="failed",
        retcode=1200,
        message="没有权限",
        wording="permission denied",
    )
    service = SimpleNamespace(
        send_group_message=AsyncMock(
            side_effect=ActionExecutionError("failed", failure=failure)
        ),
    )

    results = await loaded_plugin.pusher(
        [loaded_plugin.PushTarget("40001", "10001")],
        "维护通知",
        1,
        context=make_context(),
        service=service,
    )

    assert results == (
        loaded_plugin.PushResult(
            "40001",
            "failed",
            "该账号在此群没有管理员权限",
            "10001",
        ),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("loaded_plugin", ["announcement"], indirect=True)
async def test_announcement_command_uses_switches_and_returns_per_target_results(
    loaded_plugin, monkeypatch
) -> None:
    account = FakeAccount("10001")
    registry = AccountRegistry()
    registry.register(account, groups=["40001"])
    service = SimpleNamespace(
        authorize=AsyncMock(return_value=True),
        send_group_message=AsyncMock(return_value=None),
    )
    monkeypatch.setattr(loaded_plugin, "account_registry", registry)
    monkeypatch.setattr(loaded_plugin, "action_service", service)
    monkeypatch.setattr(loaded_plugin, "resolve_feature", lambda name: make_feature())
    monkeypatch.setattr(loaded_plugin, "feature_enabled", lambda feature, group: True)

    result = await loaded_plugin.push_handle.callable_target(
        make_session(),
        Match("帮助系统", True),
        Match(("维护", "通知"), True),
        Match(None, False),
    )

    assert "群40001: sent - 推送成功（账号10001）" in str(result)
    service.authorize.assert_awaited_once()
    service.send_group_message.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("loaded_plugin", ["announcement"], indirect=True)
async def test_announcement_preflight_honors_host_feature_switch(
    loaded_plugin, tmp_path, monkeypatch
) -> None:
    account = FakeAccount("10001")
    registry = AccountRegistry()
    registry.register(account, groups=["40001"])
    service = FeatureService(tmp_path / "features.json")
    service.disable("helper", "40001")
    monkeypatch.setattr(loaded_plugin, "feature_service", service)

    targets, results = loaded_plugin.collect_targets(make_feature(), registry)

    assert targets == ()
    assert results == (
        loaded_plugin.PushResult("40001", "skipped_feature_disabled", "功能未开启"),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("loaded_plugin", ["announcement"], indirect=True)
async def test_announcement_command_blocks_non_bot_admin(loaded_plugin) -> None:
    checker = PermissionChecker(registry=PermissionRegistry())
    loaded_plugin.permission_checker = checker
    loaded_plugin.action_service = ActionService(AccountRegistry(), checker)

    result = await loaded_plugin.push_handle.callable_target(
        make_session(),
        Match("帮助系统", True),
        Match(("维护",), True),
        Match(None, False),
    )

    assert str(result) == "权限不足"
