from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from arclet.entari import ExceptionEvent
from arclet.letoderea import Subscriber


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
