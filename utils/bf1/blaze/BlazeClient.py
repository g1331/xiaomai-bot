import random
from typing import Union

from utils.bf1.blaze.BlazeSocket import BlazeSocket, BlazeServerREQ


class BlazeClient:
    def __init__(self):
        self.socket = None

    async def connect(self, host: str = "diceprodblapp-08.ea.com", port: int = 10539, callback=None) -> BlazeSocket:
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

    async def get_socket_for_pid(self, pid: str = None) -> Union[BlazeSocket, None]:
        if not pid:
            connected_clients = [client for client in self.clients_by_pid.values() if
                                 client.socket and client.socket.connect]
            try:
                return random.choice(connected_clients).socket
            except IndexError:
                return None

        if pid in self.clients_by_pid:
            client = self.clients_by_pid[pid]
            if client.socket and client.socket.connect:
                return client.socket
            await client.close()
            del self.clients_by_pid[pid]

        new_client = BlazeClient()
        host, port = await BlazeServerREQ.get_server_address()
        await new_client.connect(host, port, callback=None)
        if new_client.socket and new_client.socket.connect:
            self.clients_by_pid[pid] = new_client
            return new_client.socket
        else:
            return None

    async def close_all(self):
        for client in self.clients_by_pid.values():
            await client.close()
        self.clients_by_pid.clear()

    async def remove_client(self, pid: str):
        if pid in self.clients_by_pid:
            client = self.clients_by_pid[pid]
            await client.close()
            del self.clients_by_pid[pid]


BlazeClientManagerInstance = BlazeClientManager()
