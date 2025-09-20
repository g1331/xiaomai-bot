"""
优化的Blaze连接管理器
针对性能问题进行优化，确保单连接高效复用
"""

import asyncio
import time
from typing import TypedDict

from loguru import logger


from utils.bf1.blaze.BlazeSocket import BlazeSocket
from utils.bf1.data_handle import BlazeData
from utils.bf1.default_account import BF1DA

from utils.bf1.performance_cache import bf1_performance_cache


class ConnectionInfo(TypedDict):
    """Blaze连接信息类型定义"""

    socket: BlazeSocket
    created_at: float


class OptimizedBlazeManager:
    """优化的Blaze管理器

    主要优化：
    1. 降低超时时间
    2. 智能连接复用
    3. 集成缓存机制
    4. 批量处理优化
    """

    # 类级常量配置
    CONNECTION_TIMEOUT = 20  # 从60秒降低到20秒
    API_TIMEOUT = 15  # API调用超时15秒
    MAX_CONNECTION_AGE_SECONDS = 300  # 连接最大生命周期5分钟

    def __init__(self):
        self._connection_cache: dict[int, ConnectionInfo] = {}
        self._lock = asyncio.Lock()

    async def get_optimized_player_list(
        self,
        game_ids: list[int],
        origin: bool = False,
        platoon: bool = False,
    ) -> dict | None | str:
        """优化的玩家列表获取

        主要优化：
        1. 降低超时时间
        2. 集成Platoon缓存
        3. 为后续战绩缓存做准备
        """
        # 检查game_ids类型
        if not isinstance(game_ids, list):
            game_ids = [game_ids]
        game_ids = [int(game_id) for game_id in game_ids]

        # 获取Blaze连接
        blaze_socket = await self._get_optimized_connection()
        if not blaze_socket:
            return "BlazeClient初始化出错!"

        # 构建请求包
        packet = {
            "method": "GameManager.getGameDataFromId",
            "type": "Command",
            "data": {
                "DNAM 1": "csFullGameList",
                "GLST 40": game_ids,
            },
        }

        try:
            # 使用优化的超时时间
            response = await asyncio.wait_for(
                blaze_socket.send(packet), timeout=self.CONNECTION_TIMEOUT
            )
        except asyncio.TimeoutError:
            try:
                await blaze_socket.close()
            except Exception as e:
                logger.error(f"关闭连接时出错: {e}")
            logger.error("Blaze后端超时!")
            return "Blaze后端超时!"

        if origin:
            return response

        # 处理响应数据
        response = BlazeData.player_list_handle(response)
        if not isinstance(response, dict):
            blaze_socket.authenticated = False
            return response

        # 优化的Platoon处理
        if platoon:
            response = await self._process_platoon_with_cache(response, game_ids)

        return response

    async def _get_optimized_connection(self) -> BlazeSocket | None:
        """获取优化的Blaze连接"""
        pid = int(BF1DA.pid)

        async with self._lock:
            # 检查现有连接
            if pid in self._connection_cache:
                connection_info = self._connection_cache[pid]
                socket = connection_info["socket"]

                # 检查连接是否仍然有效
                if socket.authenticated and socket.connect:
                    # 检查连接年龄，超过配置时间重新连接
                    if (
                        time.time() - connection_info["created_at"]
                        < self.MAX_CONNECTION_AGE_SECONDS
                    ):
                        logger.debug(f"复用现有Blaze连接: {pid}")
                        return socket
                    else:
                        logger.debug(f"Blaze连接过期，重新建立: {pid}")
                        try:
                            await socket.close()
                        except (ConnectionError, OSError) as e:
                            logger.debug(f"关闭过期Blaze连接时出错: {e!r}")
                        except Exception as e:
                            logger.warning(f"关闭Blaze连接时发生未知错误: {e!r}")
                        del self._connection_cache[pid]
                else:
                    logger.debug(f"Blaze连接无效，重新建立: {pid}")
                    del self._connection_cache[pid]

        # 建立新连接
        return await self._create_new_connection(pid)

    async def _create_new_connection(self, pid: int) -> BlazeSocket | None:
        """创建新的Blaze连接，统一走 BF1BlazeManager 的初始化逻辑（带自动重试/互斥）"""
        try:
            # 统一复用 BF1BlazeManager 的初始化与重试逻辑
            from utils.bf1.bf_utils import BF1BlazeManager

            blaze_socket = await BF1BlazeManager.init_socket(
                BF1DA.pid, BF1DA.remid, BF1DA.sid
            )
            if not blaze_socket:
                logger.error("无法初始化BlazeSocket")
                return None

            # 缓存连接（带时间戳，便于过期判断）
            async with self._lock:
                self._connection_cache[pid] = {
                    "socket": blaze_socket,
                    "created_at": time.time(),
                }

            return blaze_socket

        except Exception as e:
            logger.error(f"Blaze连接失败: {e}")
            return None

    async def _process_platoon_with_cache(
        self, response: dict, game_ids: list[int]
    ) -> dict:
        """使用缓存优化Platoon信息处理"""
        bf1_account = await BF1DA.get_api_instance()

        for game_id in game_ids:
            if game_id not in response:
                continue

            # 收集所有玩家PID
            pid_list = [player["pid"] for player in response[game_id]["players"]]

            # 批量检查缓存
            cached_platoons = (
                await bf1_performance_cache.platoon_cache.batch_get_platoon_info(
                    pid_list
                )
            )

            # 识别需要API调用的PID
            uncached_pids = [
                pid
                for pid, cached_data in cached_platoons.items()
                if cached_data is None
            ]

            logger.debug(
                f"Platoon缓存命中: {len(pid_list) - len(uncached_pids)}/{len(pid_list)}"
            )

            # 对未缓存的PID进行API调用
            new_platoon_data = {}
            if uncached_pids:
                platoon_tasks = [
                    bf1_account.getActivePlatoon(pid) for pid in uncached_pids
                ]
                try:
                    platoon_results = await asyncio.wait_for(
                        asyncio.gather(*platoon_tasks, return_exceptions=True),
                        timeout=self.API_TIMEOUT,
                    )

                    for i, result in enumerate(platoon_results):
                        pid = uncached_pids[i]
                        if isinstance(result, dict) and "result" in result:
                            platoon_data = result["result"] if result["result"] else {}
                            new_platoon_data[pid] = platoon_data
                        else:
                            new_platoon_data[pid] = {}

                    # 批量缓存新数据
                    await bf1_performance_cache.platoon_cache.batch_cache_platoon_info(
                        new_platoon_data
                    )

                except asyncio.TimeoutError:
                    logger.warning("Platoon API调用超时")
                    for pid in uncached_pids:
                        new_platoon_data[pid] = {}
                except Exception as e:
                    logger.error(f"获取Platoon信息失败: {e}")
                    for pid in uncached_pids:
                        new_platoon_data[pid] = {}

            # 合并缓存数据和新数据
            all_platoon_data = {**cached_platoons, **new_platoon_data}

            # 应用到响应数据
            platoons = []
            for i, player in enumerate(response[game_id]["players"]):
                pid = player["pid"]
                platoon_info = all_platoon_data.get(pid, {})

                if platoon_info and platoon_info not in platoons:
                    platoons.append(platoon_info)

                response[game_id]["players"][i]["platoon"] = platoon_info

            response[game_id]["platoons"] = platoons

        return response

    async def close_all_connections(self) -> None:
        """关闭所有连接"""
        async with self._lock:
            for connection_info in self._connection_cache.values():
                try:
                    await connection_info["socket"].close()
                except Exception as e:
                    logger.error(f"关闭Blaze连接时出错: {e}")
            self._connection_cache.clear()
            logger.info("所有Blaze连接已关闭")


# 全局优化管理器实例
optimized_blaze_manager = OptimizedBlazeManager()
