from __future__ import annotations

import asyncio
import signal

from arclet.entari import Entari
from arclet.letoderea.utils import set_event_loop
from launart import Launart
from loguru import logger
from satori import EventType, LoginStatus
from satori.client import Account

from .config import TenkoConfig
from .connection import OneBotConnection
from .events import MessageEventHandler


class TenkoRuntime:
    """Tenko 第一阶段运行时的服务编排。"""

    def __init__(self, config: TenkoConfig) -> None:
        self.config = config
        self.connection = OneBotConnection(config.onebot)
        self.message_handler = MessageEventHandler(
            send_replies=config.runtime.send_replies,
            reply_text=config.runtime.reply_text,
        )
        self.app: Entari | None = None
        self.manager: Launart | None = None

    def build_app(self) -> Entari:
        if self.app is not None:
            return self.app

        set_event_loop(asyncio.get_running_loop())
        app = Entari(
            self.connection.client_config,
            log_level=self.config.runtime.log_level,
            ignore_self_message=True,
        )
        app.register_on(EventType.MESSAGE_CREATED)(self.message_handler.handle)
        app.lifecycle(self._on_lifecycle)
        self.app = app
        return app

    async def _on_lifecycle(self, account: Account, state: LoginStatus) -> None:
        if state == LoginStatus.ONLINE:
            logger.info("OneBot account {} is online", account.self_id)
        elif state in (LoginStatus.CONNECT, LoginStatus.RECONNECT):
            logger.info("OneBot account {} is connecting/reconnecting", account.self_id)
        elif state in (LoginStatus.DISCONNECT, LoginStatus.OFFLINE):
            logger.warning(
                "OneBot account {} disconnected; waiting for reverse WebSocket "
                "reconnection",
                account.self_id,
            )
        else:
            logger.warning(
                "OneBot account {} changed to unknown state {}",
                account.self_id,
                state,
            )

    async def run_async(self) -> None:
        manager = Launart()
        self.manager = manager
        self.connection.install(manager)

        logger.info(
            "Tenko starting; NapCat reverse WebSocket endpoint: {}",
            self.config.onebot.reverse_ws_url,
        )
        logger.info(
            "Fixed replies are {}",
            "enabled" if self.config.runtime.send_replies else "disabled",
        )
        app = self.build_app()
        # The Satori client must start after the server socket is accepting
        # connections. Otherwise its first connection attempt can race Uvicorn
        # and events arriving in that window would not be replayed to a client.
        app.required = {*app.required, self.connection.ready_service.id}
        for connection in app.connections:
            connection.required = {
                *connection.required,
                self.connection.ready_service.id,
            }
        await app.run_async(
            manager,
            stop_signal=(signal.SIGINT, signal.SIGTERM),
        )


def run(config: TenkoConfig) -> None:
    asyncio.run(TenkoRuntime(config).run_async())
