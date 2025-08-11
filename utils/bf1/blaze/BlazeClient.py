import asyncio
import random

from utils.bf1.blaze.BlazeSocket import BlazeServerREQ, BlazeSocket


class BlazeClient:
    def __init__(self):
        self.socket: BlazeSocket = None

    async def connect(
        self, host: str = "diceprodblapp-08.ea.com", port: int = 10539, callback=None
    ) -> BlazeSocket:
        if not self.socket:
            self.socket = await BlazeSocket.create(host, port, callback)
        return self.socket

    async def close(self):
        if self.socket:
            await self.socket.close()
            self.socket = None


class BlazeClientManager:
    def __init__(self):
        self.clients_by_pid = {}

    async def get_socket_for_pid(self, pid=None) -> BlazeSocket | None:
        if not pid:
            connected_clients = [
                client for client in self.clients_by_pid.values() if client.connect
            ]
            try:
                return random.choice(connected_clients)
            except IndexError:
                return None

        if pid in self.clients_by_pid:
            client = self.clients_by_pid[pid]
            if client.connect and client.authenticated:
                # 测试连接是否真正可用
                if hasattr(client, 'test_connection'):
                    try:
                        is_healthy = await asyncio.wait_for(client.test_connection(), timeout=3.0)
                        if is_healthy:
                            return client
                    except Exception as e:
                        logger.debug(f"连接健康检查失败: {e}")
                elif client.is_connection_healthy():
                    return client
            
            # 连接不健康，清理并重新创建
            try:
                await client.close()
            except Exception as e:
                from loguru import logger
                logger.error(f"关闭客户端连接时出错: {e}")
            del self.clients_by_pid[pid]

        new_client = BlazeClient()
        host, port = await BlazeServerREQ.get_server_address()
        await new_client.connect(host, port, callback=None)
        if new_client.socket and new_client.socket.connect:
            self.clients_by_pid[pid] = new_client.socket
            return self.clients_by_pid[pid]
        else:
            return None

    async def ensure_connection(self, pid: int, max_retries: int = 2) -> BlazeSocket | None:
        """确保指定PID有有效的连接，支持自动重试"""
        for attempt in range(max_retries + 1):
            try:
                socket = await self.get_socket_for_pid(pid)
                if socket and socket.is_connection_healthy():
                    return socket
            except Exception as e:
                logger.warning(f"获取连接失败 (第{attempt + 1}次): {e}")
            
            if attempt < max_retries:
                await asyncio.sleep(1)  # 重试前等待
        
        return None

    async def close_all(self):
        from loguru import logger

        for client in self.clients_by_pid.values():
            try:
                await client.close()
            except Exception as e:
                logger.error(f"关闭客户端连接时出错: {e}")
        self.clients_by_pid.clear()

    async def remove_client(self, pid: str):
        if pid in self.clients_by_pid:
            client = self.clients_by_pid[pid]
            try:
                await client.close()
            except Exception as e:
                from loguru import logger

                logger.error(f"关闭客户端连接时出错: {e}")
            del self.clients_by_pid[pid]


BlazeClientManagerInstance = BlazeClientManager()
