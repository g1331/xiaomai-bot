from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field

import aiohttp
from arclet.entari import WS
from launart import Launart, Service
from launart.status import Phase
from satori.adapters.onebot11.reverse import (
    OneBot11ReverseAdapter,
    OneBot11ReverseConfig,
)
from satori.model import Opcode
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


@dataclass(slots=True)
class OneBotConnection:
    """组装 OneBot 反向适配器、Satori Server 和 Entari 客户端配置。"""

    config: OneBotConfig
    adapter: OneBot11ReverseAdapter = field(init=False)
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
        self.adapter = OneBot11ReverseAdapter(adapter_config)
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
