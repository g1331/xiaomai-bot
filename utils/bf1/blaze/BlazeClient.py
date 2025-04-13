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
            if client.connect:
                return client
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
