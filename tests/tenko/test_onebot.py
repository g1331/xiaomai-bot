from __future__ import annotations

import asyncio
import json

import pytest
from satori.adapters.onebot11.reverse import (
    OneBot11ReverseAdapter,
    OneBot11ReverseConfig,
    _Connection,
)
from satori.adapters.onebot11.utils import onebot11_event_type


class FakeWebSocket:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_text(self, message: str) -> None:
        self.sent.append(json.loads(message))


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            {"post_type": "message", "message_type": "private", "sub_type": "friend"},
            "message.private.friend",
        ),
        (
            {"post_type": "message", "message_type": "group", "sub_type": "normal"},
            "message.group.normal",
        ),
        (
            {
                "post_type": "message_sent",
                "message_type": "group",
                "sub_type": "normal",
            },
            "message_sent.group.normal",
        ),
    ],
)
def test_onebot_event_type_parser(raw: dict, expected: str) -> None:
    assert onebot11_event_type(raw) == expected


@pytest.mark.asyncio
async def test_reverse_adapter_shapes_send_action_json() -> None:
    # The pinned official adapter owns this wire shaping path; lock its JSON
    # contract here so a dependency upgrade cannot silently change the action.
    adapter = OneBot11ReverseAdapter(
        OneBot11ReverseConfig(access_token="test-token", timeout=1)
    )
    websocket = FakeWebSocket()
    connection = _Connection(adapter, websocket)
    task = asyncio.create_task(
        connection.call_api(
            "send_private_msg",
            {
                "user_id": 20001,
                "message": [{"type": "text", "data": {"text": "收到"}}],
            },
        )
    )

    for _ in range(20):
        if websocket.sent:
            break
        await asyncio.sleep(0)
    else:
        pytest.fail("OneBot action was not sent")

    payload = websocket.sent[0]
    assert payload["action"] == "send_private_msg"
    assert payload["params"] == {
        "user_id": 20001,
        "message": [{"type": "text", "data": {"text": "收到"}}],
    }
    assert isinstance(payload["echo"], str)

    connection.response_waiters[payload["echo"]].set_result(
        {
            "status": "ok",
            "retcode": 0,
            "data": {"message_id": 90001},
            "echo": payload["echo"],
        }
    )
    assert await task == {"message_id": 90001}
