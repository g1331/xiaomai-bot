"""Tenko 运行期数据库状态的 Launart 生命周期桥接。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from launart import Launart, Service


class RuntimeStateService(Service):
    """在官方数据库服务就绪后加载并在退出前刷新宿主状态。"""

    id = "tenko/runtime-state"

    def __init__(
        self,
        initialize: Callable[[], Awaitable[None]],
        flush: Callable[[], Awaitable[None]],
    ) -> None:
        super().__init__()
        self._initialize = initialize
        self._flush = flush

    @property
    def required(self) -> set[str]:
        return {"database/sqlalchemy"}

    @property
    def stages(self) -> set[str]:
        return {"preparing", "blocking", "cleanup"}

    async def launch(self, manager: Launart) -> None:
        async with self.stage("preparing"):
            await self.wait_for_required()
            await self._initialize()

        async with self.stage("blocking"):
            await manager.status.wait_for_sigexit()

        async with self.stage("cleanup"):
            await self._flush()


__all__ = ["RuntimeStateService"]
