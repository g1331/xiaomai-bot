"""隔离真实进程、HTTP 和 OneBot WebSocket 的管理闭环验证。"""

from __future__ import annotations

import asyncio
import os
import socket
import sys
from pathlib import Path

import aiohttp
import httpx
import pytest


@pytest.mark.asyncio
async def test_webui_real_connection_disable_restart_enable_and_forget(tmp_path):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "4.0.0-pre12"\n')
    config = tmp_path / "tenko.toml"
    config.write_text(f"""[onebot]
listen_port = {port}
access_token = "protocol-test-token"
[webui]
enabled = true
token = "reader-test-token"
admin_token = "admin-test-token"
[basic.log]
level = "INFO"
save = {{rotation = "1 MB", compression = "gz", colorize = false}}
""")
    environment = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[2]))
    log_path = tmp_path / "process.log"
    process = None
    tasks = []
    websockets = []
    async with httpx.AsyncClient(
        base_url=f"http://127.0.0.1:{port}",
        timeout=3,
        headers={"Authorization": "Bearer admin-test-token"},
    ) as client:

        async def wait_for(check):
            for _ in range(200):
                if process is not None and process.returncode is not None:
                    pytest.fail(log_path.read_text()[-8000:])
                try:
                    value = await check()
                    if value:
                        return value
                except (httpx.ConnectError, httpx.ReadError, httpx.RemoteProtocolError):
                    pass
                await asyncio.sleep(0.1)
            pytest.fail("等待管理状态超时\n" + log_path.read_text()[-8000:])

        async def state():
            response = await client.get("/webui/api/manage/accounts")
            return (
                response.json()["data"]["accounts"]
                if response.status_code == 200
                else None
            )

        async def ready():
            return await state() is not None

        async def start():
            nonlocal process
            with log_path.open("ab") as log:
                process = await asyncio.create_subprocess_exec(
                    sys.executable,
                    "-m",
                    "tenko",
                    "--config",
                    str(config),
                    cwd=tmp_path,
                    env=environment,
                    stdout=log,
                    stderr=log,
                )
            await wait_for(ready)

        async def stop():
            if process is not None and process.returncode is None:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), 15)
                except TimeoutError:
                    process.kill()
                    await process.wait()
                    pytest.fail("宿主未能正常退出\n" + log_path.read_text()[-8000:])

        async def protocol(ws):
            await ws.send_json(
                {
                    "time": 1,
                    "self_id": 10001,
                    "post_type": "meta_event",
                    "meta_event_type": "lifecycle",
                    "sub_type": "connect",
                }
            )
            async for message in ws:
                if message.type != aiohttp.WSMsgType.TEXT:
                    continue
                request = message.json()
                result = {
                    "get_login_info": {"user_id": 10001, "nickname": "WebUI Test Bot"},
                    "get_group_list": [{"group_id": 40001, "group_name": "Test Group"}],
                }.get(request.get("action"), {})
                await ws.send_json(
                    {
                        "status": "ok",
                        "retcode": 0,
                        "data": result,
                        "echo": request.get("echo"),
                    }
                )

        async def connect(session):
            ws = await session.ws_connect(
                f"http://127.0.0.1:{port}/onebot/v11/ws",
                headers={
                    "Authorization": "Bearer protocol-test-token",
                    "X-Self-ID": "10001",
                },
            )
            websockets.append(ws)
            tasks.append(asyncio.create_task(protocol(ws)))

            async def online():
                rows = await state()
                return rows and rows[0]["online"] and rows[0]["group_count"] == 1

            await wait_for(online)
            return ws

        async def action(name, body=None):
            response = await client.post(
                f"/webui/api/manage/accounts/onebot/10001/{name}",
                json={"confirm": True} if body is None else body,
            )
            assert response.status_code == 200, response.text

        try:
            await start()
            async with aiohttp.ClientSession() as session:
                async with session.ws_connect(
                    f"http://127.0.0.1:{port}/onebot/v11/ws",
                    headers={
                        "Authorization": "Bearer protocol-test-token",
                        "X-Self-ID": "10003",
                    },
                ) as mismatched:
                    await mismatched.send_json(
                        {
                            "self_id": 10001,
                            "post_type": "meta_event",
                            "meta_event_type": "lifecycle",
                            "sub_type": "connect",
                        }
                    )
                    message = await asyncio.wait_for(mismatched.receive(), 3)
                    assert (
                        message.type == aiohttp.WSMsgType.CLOSE and message.data == 1008
                    )
                async with session.ws_connect(
                    f"http://127.0.0.1:{port}/onebot/v11/ws",
                    headers={
                        "Authorization": "Bearer protocol-test-token",
                        "X-Self-ID": "10004",
                    },
                ) as incomplete:
                    await incomplete.send_json(
                        {
                            "self_id": 10004,
                            "post_type": "meta_event",
                            "meta_event_type": "lifecycle",
                            "sub_type": "connect",
                        }
                    )
                    message = await asyncio.wait_for(incomplete.receive(), 3)
                    assert message.json()["action"] == "get_login_info"
                assert await state() == []
                await connect(session)
                await action(
                    "preferences",
                    {"alias": "重启后保留", "capabilities": {"member_mute": False}},
                )
                response = await client.post(
                    "/webui/api/manage/features/status",
                    json={"group_id": "40001", "enabled": False},
                )
                assert response.status_code == 200, response.text
                response = await client.post(
                    "/webui/api/manage/plugins/status",
                    json={"enabled": False, "confirm": True},
                )
                assert response.status_code == 200, response.text
                response = await client.post(
                    "/webui/api/manage/plugins/updater",
                    json={"enabled": False, "confirm": True},
                )
                assert response.status_code == 403
                response = await client.post(
                    "/webui/api/manage/settings", json={"default_enabled": False}
                )
                assert response.status_code == 200
                await action("disable")

                async def disconnected():
                    rows = await state()
                    return rows and not rows[0]["online"] and not rows[0]["connected"]

                await wait_for(disconnected)
                with pytest.raises(aiohttp.WSServerHandshakeError):
                    await connect(session)
                await stop()
                await start()
                response = await client.get("/webui/api/features")
                feature = next(
                    row
                    for row in response.json()["data"]["features"]
                    if row["plugin"] == "status"
                )
                assert feature["loaded"] and not feature["enabled"]
                assert feature["groups"]["40001"] is False
                response = await client.get("/webui/api/manage/settings")
                assert response.json()["data"]["default_enabled"] is False
                rows = await state()
                assert rows[0]["alias"] == "重启后保留"
                assert rows[0]["capabilities"] == {"member_mute": False}
                assert not rows[0]["enabled"]
                with pytest.raises(aiohttp.WSServerHandshakeError):
                    await connect(session)
                await action("enable")
                await connect(session)
                await action("kick")
                await wait_for(disconnected)
                await connect(session)
                await action("disable")
                await wait_for(disconnected)
                await action("forget")
                assert await state() == []
                logs = await client.get("/webui/api/manage/logs")
                assert (
                    logs.status_code == 200 and logs.json()["data"]["history_enabled"]
                )
                assert not any(
                    secret in logs.text
                    for secret in ("protocol-test-token", "admin-test-token")
                )
        finally:
            for ws in websockets:
                await ws.close()
            await asyncio.gather(*tasks, return_exceptions=True)
            await stop()
