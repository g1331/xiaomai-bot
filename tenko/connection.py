from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from collections.abc import Callable
from datetime import datetime

import aiohttp
from arclet.entari import WS
from launart import Launart, Service
from launart.status import Phase
from satori.adapters.onebot11.reverse import (
    OneBot11ReverseAdapter,
    OneBot11ReverseConfig,
    _Connection,
)
from satori.model import Opcode, Event
from satori import EventType, LoginStatus
from starlette.websockets import WebSocket, WebSocketState
from satori.server import Server

from .config import OneBotConfig


class ServerReadyService(Service):
    """在内部 HTTP socket 可接受连接后，才允许 Entari client 启动。"""

    id = "tenko.satori.server-ready"
    required = {"satori-python.server"}
    stages: set[Phase] = {"preparing", "blocking", "cleanup"}

    def __init__(
        self,
        host: str,
        port: int,
        satori_path: str,
        satori_token: str | None,
        timeout: float = 10,
    ) -> None:
        self.host = host
        self.port = port
        self.satori_path = satori_path.strip("/")
        self.satori_token = satori_token
        self.timeout = timeout
        super().__init__()

    @property
    def satori_events_url(self) -> str:
        path = f"/{self.satori_path}" if self.satori_path else ""
        host = self.host
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        return f"ws://{host}:{self.port}{path}/v1/events"

    async def _wait_for_socket(self) -> None:
        deadline = asyncio.get_running_loop().time() + self.timeout
        async with aiohttp.ClientSession() as session:
            while True:
                try:
                    async with session.ws_connect(
                        self.satori_events_url, timeout=0.5
                    ) as websocket:
                        await websocket.send_str(
                            json.dumps(
                                {
                                    "op": Opcode.IDENTIFY.value,
                                    "body": {"token": self.satori_token},
                                }
                            )
                        )
                        response = await websocket.receive(timeout=0.5)
                        if response.type != aiohttp.WSMsgType.TEXT:
                            raise RuntimeError(
                                "Satori server readiness probe did not receive READY"
                            )
                        payload = json.loads(response.data)
                        if payload.get("op") != Opcode.READY.value:
                            raise RuntimeError(
                                "Satori server readiness probe was rejected"
                            )
                        return
                except (TimeoutError, aiohttp.ClientError, OSError):
                    if asyncio.get_running_loop().time() >= deadline:
                        raise RuntimeError(
                            "Satori server did not accept an internal WebSocket "
                            f"connection at {self.satori_events_url}"
                        ) from None
                    await asyncio.sleep(0.05)

    async def launch(self, manager: Launart) -> None:
        async with self.stage("preparing"):
            await self._wait_for_socket()
        async with self.stage("blocking"):
            await manager.status.wait_for_sigexit()
        async with self.stage("cleanup"):
            pass


class _ManagedConnection(_Connection):
    """校验握手身份，阻止断开后尚未完成的登录请求创建幽灵账户。"""

    def __init__(self, adapter, ws: WebSocket, account_id: str) -> None:
        super().__init__(adapter, ws)
        self.account_id = account_id
        self.closed = False

    async def message_receive(self):
        async for connection, data in super().message_receive():
            if not isinstance(data, dict) or (
                not data.get("echo") and str(data.get("self_id")) != self.account_id
            ):
                await self.ws.close(1008, "Event self_id does not match X-Self-ID")
                return
            yield connection, data

    async def call_api(self, action: str, params: dict | None = None) -> dict:
        result = await super().call_api(action, params)
        if self.closed:
            raise asyncio.CancelledError
        return result


class ManagedOneBotAdapter(OneBot11ReverseAdapter):
    """在已锁定的 OneBot 适配器边界增加准入和主动断开。"""

    admission: Callable[[str, str], bool] | None = None

    async def websocket_server_handler(self, ws: WebSocket) -> None:
        import secrets

        authorization = ws.headers.get("Authorization", "")
        expected = f"Bearer {self.access_token}" if self.access_token else ""
        if not secrets.compare_digest(authorization.encode(), expected.encode()):
            await ws.close(1008, "Authorization Header is invalid")
            return
        account_id = ws.headers.get("X-Self-ID", "")
        if not account_id or len(account_id) > 128 or account_id in self.connections:
            await ws.close(1008, "Invalid or duplicate X-Self-ID")
            return
        if self.admission is not None and not self.admission("onebot", account_id):
            await ws.close(1008, "Account is disabled or state is not ready")
            return
        await ws.accept()
        if account_id in self.connections or (
            self.admission is not None and not self.admission("onebot", account_id)
        ):
            await ws.close(1008, "Account is disabled")
            return
        connection = _ManagedConnection(self, ws, account_id)
        self.connections[account_id] = connection
        tasks = [
            asyncio.create_task(connection.message_handle()),
            asyncio.create_task(connection.close_signal.wait()),
        ]
        try:
            done, _pending = await asyncio.wait(
                tasks, return_when=asyncio.FIRST_COMPLETED
            )
            for task in done:
                task.result()
        finally:
            connection.closed = True
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            self.connections.pop(account_id, None)
            for future in connection.response_waiters.values():
                future.cancel()
            # 配对中途断线时还没有 Login，不应覆盖原错误或制造幽灵账户。
            login = self.logins.pop(account_id, None)
            if login is not None:
                login.status = LoginStatus.OFFLINE
                await self.server.post(
                    Event(EventType.LOGIN_REMOVED, datetime.now(), login)
                )
            if ws.application_state != WebSocketState.DISCONNECTED:
                await ws.close()

    async def disconnect(self, account_id: str) -> bool:
        connection = self.connections.get(account_id)
        if connection is None:
            return False
        connection.close_signal.set()
        return True


@dataclass(slots=True)
class OneBotConnection:
    """组装 OneBot 反向适配器、Satori Server 和 Entari 客户端配置。"""

    config: OneBotConfig
    adapter: ManagedOneBotAdapter = field(init=False)
    server: Server = field(init=False)
    ready_service: ServerReadyService = field(init=False)
    client_config: WS = field(init=False)

    def __post_init__(self) -> None:
        adapter_config = OneBot11ReverseConfig(
            prefix=self.config.reverse_ws_prefix,
            path=self.config.reverse_ws_path,
            endpoint=self.config.reverse_ws_endpoint,
            access_token=self.config.access_token,
            timeout=self.config.api_timeout,
        )
        self.adapter = ManagedOneBotAdapter(adapter_config)
        self.server = Server(
            host=self.config.listen_host,
            port=self.config.listen_port,
            path=self.config.satori_path,
            token=self.config.satori_token,
        )
        self.server.apply(self.adapter)
        self.ready_service = ServerReadyService(
            host=self.config.listen_probe_host,
            port=self.config.listen_port,
            satori_path=self.config.satori_path,
            satori_token=self.config.satori_token,
        )
        self.client_config = WS(
            host=self.config.satori_client_host,
            port=self.config.listen_port,
            path=self.config.satori_path,
            token=self.config.satori_token,
        )

    def install(self, manager: Launart) -> None:
        """把 ASGI、Satori Server 和启动就绪检查加入 Launart。"""

        manager.add_component(self.server.asgi_service)
        manager.add_component(self.server)
        manager.add_component(self.ready_service)
