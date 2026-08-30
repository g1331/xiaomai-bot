from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from arclet.entari import ExceptionEvent
from arclet.entari.config import EntariConfig
from arclet.letoderea import Subscriber
from satori import Channel, ChannelType, EventType, Guild, Login, MessageObject, User
from satori.model import Event

from tenko.events import MessageLog
from tenko.host.actions import ActionCapability, ActionExecutionError, ActionFailure


def make_exception_event(message: str) -> ExceptionEvent:
    return ExceptionEvent(
        origin=SimpleNamespace(account=SimpleNamespace(platform="onebot")),
        subscriber=SimpleNamespace(spec=Subscriber),
        exception=RuntimeError(message),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("loaded_plugin", ["exception_catcher"], indirect=True)
async def test_exception_event_trigger_reports_once(loaded_plugin) -> None:
    loaded_plugin.last_error_time.clear()
    loaded_plugin.send_error_report = AsyncMock()
    event = make_exception_event("boom")

    await loaded_plugin.except_handle.callable_target(event)

    loaded_plugin.send_error_report.assert_awaited_once_with(
        event.exception, event.origin
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("loaded_plugin", ["exception_catcher"], indirect=True)
async def test_exception_cooldown_filters_duplicate_error(loaded_plugin) -> None:
    loaded_plugin.last_error_time.clear()
    loaded_plugin.send_error_report = AsyncMock()
    event = make_exception_event("same error")

    await loaded_plugin.except_handle.callable_target(event)
    await loaded_plugin.except_handle.callable_target(event)

    loaded_plugin.send_error_report.assert_awaited_once()


def make_context_origin():
    event = Event(
        type=EventType.MESSAGE_CREATED,
        timestamp=datetime.now(),
        login=Login(platform="onebot", user=User("10001")),
        channel=Channel("40001", ChannelType.TEXT),
        guild=Guild("40001", "Tenko"),
        user=User("20001"),
        message=MessageObject("50001", "触发异常的消息"),
    )
    return SimpleNamespace(
        account=SimpleNamespace(self_id="10001", platform="onebot"),
        _origin=event,
    )


@pytest.mark.parametrize("loaded_plugin", ["exception_catcher"], indirect=True)
def test_error_report_contains_context_traceback_and_recent_messages(
    loaded_plugin,
) -> None:
    recent = [
        MessageLog(
            timestamp=datetime(2026, 1, 1),
            direction="received",
            account_id="10001",
            platform="onebot",
            chat_type="group",
            channel_id="40001",
            user_id="20001",
            message_id="50001",
            text="recent message",
        )
    ]
    try:
        raise ValueError("broken")
    except ValueError as error:
        report = loaded_plugin.generate_error_report(
            error,
            make_context_origin(),
            recent_messages=recent,
            recent_limit=1,
            occurred_at=datetime(2026, 2, 3, 4, 5, 6),
        )

    assert "发生时间: 2026-02-03T04:05:06+00:00" in report
    assert "异常类型: builtins.ValueError" in report
    assert "完整 traceback:" in report
    assert "Traceback (most recent call last)" in report
    assert "账号=10001" in report
    assert "群=40001" in report
    assert "用户=20001" in report
    assert "消息摘要=触发异常的消息" in report
    assert "recent message" in report


@pytest.mark.parametrize("loaded_plugin", ["exception_catcher"], indirect=True)
def test_action_error_report_contains_structured_failure_fields(loaded_plugin) -> None:
    failure = ActionFailure(
        account_id="10001",
        capability=ActionCapability.MEMBER_MUTE,
        action="set_group_ban",
        status="failed",
        retcode=1200,
        data=None,
        message="ERR_NOT_GROUP_ADMIN",
        wording="ERR_NOT_GROUP_ADMIN",
        echo="echo-1",
        error_type="ActionFailed",
        detail="1200: {'status': 'failed'}",
    )
    try:
        raise ActionExecutionError("平台动作失败", failure=failure)
    except ActionExecutionError as error:
        report = loaded_plugin.generate_error_report(error, make_context_origin())

    assert "账号=10001" in report
    assert "群=40001" in report
    assert "action=set_group_ban" in report
    assert "retcode=1200" in report
    assert "message='ERR_NOT_GROUP_ADMIN'" in report
    assert "wording='ERR_NOT_GROUP_ADMIN'" in report
    assert "完整 traceback:" in report


@pytest.mark.asyncio
@pytest.mark.parametrize("loaded_plugin", ["exception_catcher"], indirect=True)
async def test_failed_exception_delivery_is_written_to_local_evidence(
    loaded_plugin,
    tmp_path,
) -> None:
    class FailingProtocol:
        async def send_private_message(self, user_id, content):
            raise RuntimeError(f"send failed for {user_id}")

    account = SimpleNamespace(
        self_id="10001",
        platform="onebot",
        protocol=FailingProtocol(),
    )
    origin = SimpleNamespace(account=account)
    failure = ActionFailure(
        account_id="10001",
        capability=ActionCapability.MEMBER_MUTE,
        action="set_group_ban",
        status="failed",
        retcode=1200,
        message="ERR_NOT_GROUP_ADMIN",
        wording="ERR_NOT_GROUP_ADMIN",
    )
    exception = ActionExecutionError("evidence required", failure=failure)
    original = EntariConfig.instance.basic.superusers
    EntariConfig.instance.basic.superusers = {"onebot": ["90001"]}
    try:
        await loaded_plugin.send_error_report(
            exception,
            origin,
            evidence_dir=tmp_path,
        )
    finally:
        EntariConfig.instance.basic.superusers = original

    evidence = tuple(tmp_path.glob("*.log"))
    assert len(evidence) == 1
    content = evidence[0].read_text(encoding="utf-8")
    assert "发生时间:" in content
    assert "异常类型: tenko.host.actions.ActionExecutionError" in content
    assert "evidence required" in content
    assert "action=set_group_ban" in content
    assert "retcode=1200" in content
    assert "message='ERR_NOT_GROUP_ADMIN'" in content
    assert "wording='ERR_NOT_GROUP_ADMIN'" in content
    assert "完整 traceback:" in content


@pytest.mark.asyncio
@pytest.mark.parametrize("loaded_plugin", ["exception_catcher"], indirect=True)
async def test_successful_exception_delivery_does_not_write_duplicate_evidence(
    loaded_plugin,
    tmp_path,
) -> None:
    class WorkingProtocol:
        def __init__(self) -> None:
            self.calls = []

        async def send_private_message(self, user_id, content):
            self.calls.append((user_id, str(content[0])))
            return []

    protocol = WorkingProtocol()
    account = SimpleNamespace(
        self_id="10001",
        platform="onebot",
        protocol=protocol,
    )
    origin = SimpleNamespace(account=account)
    original = EntariConfig.instance.basic.superusers
    EntariConfig.instance.basic.superusers = {"onebot": ["90001"]}
    try:
        await loaded_plugin.send_error_report(
            RuntimeError("delivered"),
            origin,
            evidence_dir=tmp_path,
        )
    finally:
        EntariConfig.instance.basic.superusers = original

    assert protocol.calls and protocol.calls[0][0] == "90001"
    assert tuple(tmp_path.glob("*.log")) == ()


@pytest.mark.parametrize("loaded_plugin", ["exception_catcher"], indirect=True)
def test_error_report_respects_recent_message_limit(loaded_plugin) -> None:
    records = [
        MessageLog(
            timestamp=datetime(2026, 1, index + 1),
            direction="received",
            account_id="10001",
            platform="onebot",
            chat_type="private",
            channel_id="private:20001",
            user_id="20001",
            message_id=str(index),
            text=f"message-{index}",
        )
        for index in range(3)
    ]

    report = loaded_plugin.generate_error_report(
        RuntimeError("boom"),
        recent_messages=records,
        recent_limit=2,
    )

    assert "message-0" not in report
    assert "message-1" in report
    assert "message-2" in report


@pytest.mark.parametrize("loaded_plugin", ["exception_catcher"], indirect=True)
def test_error_report_uses_configured_default_recent_message_limit(
    loaded_plugin,
) -> None:
    records = [
        MessageLog(
            timestamp=datetime(2026, 1, 1),
            direction="received",
            account_id="10001",
            platform="onebot",
            chat_type="private",
            channel_id="private:20001",
            user_id="20001",
            message_id=str(index),
            text=f"message-{index}",
        )
        for index in range(12)
    ]

    report = loaded_plugin.generate_error_report(
        RuntimeError("boom"),
        recent_messages=records,
    )

    assert "text=message-1\n" not in report
    assert "message-2" in report
    assert "message-11" in report
