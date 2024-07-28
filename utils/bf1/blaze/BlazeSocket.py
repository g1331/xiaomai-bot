import asyncio
import ssl
from typing import Union

import httpx
from loguru import logger

from utils.bf1.blaze.Blaze import Blaze, keepalive

context = ssl.create_default_context()
context.options |= ssl.OP_LEGACY_SERVER_CONNECT
context.check_hostname = False
context.verify_mode = ssl.CERT_NONE
context.set_ciphers('ALL')


class BlazeServerREQ:
    BF1 = '<serverinstancerequest><name>battlefield-1-pc</name><connectionprofile>standardSecure_v4' \
          '</connectionprofile></serverinstancerequest> '
    BFV = '<serverinstancerequest><name>battlefield-casablanca-pc</name><connectionprofile>standardSecure_v4' \
          '</connectionprofile></serverinstancerequest> '
    BF2042 = '<serverinstancerequest><name>bf-2021-pc-gen5</name><connectionprofile>standardSecure_v4' \
             '</connectionprofile></serverinstancerequest> '

    @staticmethod
    async def get_server_address(game_code: Union['BF1', 'BFV', 'BF2042'] = BF1) -> (str, int):
        """
        获取服务器地址
        :param game_code: 游戏代码, 默认为BF1, 可选BF1, BFV, BF2042
        :return: Blaze服务器地址
        eg:
        {
            'address': {
                'ipAddress': {
                    'hostname': 'diceprodblapp-08.ea.com',
                    'ip': 2677614132,
                    'port': 10483
                }
            },
            'addressRemaps': [],
            'certificateList': [],
            'messages': [],
            'nameRemaps': [],
            'secure': 1,
            'trialServiceName': '',
            'defaultDnsAddress': 0
        }
        """
        async with httpx.AsyncClient(verify=False) as client:
            response = await client.post(
                'https://spring18.gosredirector.ea.com:42230/redirector/getServerInstance',
                headers={
                    'Content-Type': 'application/xml',
                    'Accept': 'application/json'
                },
                data=game_code
            )
            response.raise_for_status()
            host = response.json()["address"]["ipAddress"]["hostname"]
            port = response.json()["address"]["ipAddress"]["port"]
            return host, port


class BlazeSocket:
    readable = True

    def __init__(self, host: str, port: int, callback=None):
        self.callback = callback
        self.connect = False
        self.finish = True
        self.map = {}
        self.id = 1
        self.temp = {}
        self.ssl_context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
        self.ssl_context.check_hostname = False
        self.ssl_context.verify_mode = ssl.CERT_NONE
        self.ssl_context.set_ciphers('ALL')
        self.host = host
        self.port = port
        self.reader: asyncio.StreamReader = None
        self.writer: asyncio.StreamWriter = None

    @classmethod
    async def create(cls, host: str = "diceprodblapp-08.ea.com", port: int = 10539, callback=None):
        self = BlazeSocket(host, port, callback)
        await self.connect_to_server()
        _ = asyncio.create_task(self.keepalive())
        return self

    async def connect_to_server(self):
        # 异步连接到服务器
        self.reader, self.writer = await asyncio.open_connection(
            self.host, self.port, ssl=self.ssl_context
        )
        self.connect = True
        logger.success(f"已连接到Blaze服务器 {self.host}:{self.port}")
        _ = asyncio.create_task(self.receive_data())

    async def close(self):
        # 关闭连接
        self.connect = False
        self.writer.close()
        await self.writer.wait_closed()
        logger.success(f"已断开与Blaze服务器 {self.host}:{self.port} 的连接")

    async def keepalive(self):
        while self.connect:
            await asyncio.sleep(60)
            if self.writer:
                self.writer.write(keepalive)

    async def send(self, packet, timeout=60, readable: bool = True):
        BlazeSocket.readable = readable
        # 发送数据包
        if not self.connect:
            raise ConnectionError("连接已关闭")
        if self.id > 65535:
            self.id = 1
        if isinstance(packet, bytes):
            packet = Blaze(packet).decode()

        future = asyncio.Future()
        if "id" not in packet:
            packet["id"] = self.id
            self.id += 1
        if packet["id"] in self.map:
            packet["id"] = self.id
            self.id += 1
        self.map[packet['id']] = future
        self.id += 1
        await self.request(packet)
        try:
            return await asyncio.wait_for(future, timeout)
        except asyncio.TimeoutError as e:
            del self.map[packet['id']]
            raise TimeoutError(
                f"Timeout waiting for response to packet ID: {packet['id']}"
            ) from e

    async def request(self, packet):
        # 请求数据包
        if not self.connect:
            raise ConnectionError("连接已关闭")
        if isinstance(packet, dict):
            self.writer.write(Blaze(packet).encode())
        elif isinstance(packet, bytes):
            self.writer.write(packet)
        else:
            raise TypeError("packet must be dict or bytes")

    async def receive_data(self):
        # 接收数据
        while self.connect:
            try:
                data = await self.reader.read(65565)
            except ConnectionResetError:
                self.connect = False
                break
            if not data:
                self.connect = False
                break
            await self.concat(data)

    async def concat(self, buffer):
        if self.finish:
            header = Blaze(buffer[:16]).decode()
            # logger.debug(f"Header received: {header}")
            if len(buffer) - 16 < header['length']:
                self.temp['data'] = bytearray(header['length'] + 16)
                self.temp['length'] = len(buffer)
                self.temp['origin'] = header['length'] + 16
                self.finish = False
                self.temp['data'][:len(buffer)] = buffer
            else:
                await self.response(Blaze(buffer).decode(BlazeSocket.readable))
                self.temp = {}
        elif self.temp['length'] >= self.temp['origin']:
            # 超长了
            self.finish = True
            self.temp = {}
        else:
            self.temp['data'][self.temp['length']:self.temp['length'] + len(buffer)] = buffer
            self.temp['length'] += len(buffer)
            if self.temp['length'] >= self.temp['origin']:
                self.finish = True
                await self.response(Blaze(self.temp['data']).decode(BlazeSocket.readable))
                self.temp = {}

    async def response(self, packet):
        # 处理接收到的数据包
        if packet['method'] == "KeepAlive":
            return
        if packet['id'] in self.map:
            # logger.debug(f"Response received for packet ID: {packet['id']}")
            future = self.map[packet['id']]
            future.set_result(packet)
            del self.map[packet['id']]
        elif packet['method'] == 'UserSessions.getPermissions':
            logger.error(f"用户登录信息已过期，请重新登录/连接！\n{packet}")
            await self.close()
        elif packet['type'] in ["Message", "Result"]:
            logger.info(f"Message received:\n{packet}")
        elif packet['type'] == "Pong":
            # logger.debug("BlazeSocket working normally")
            pass
        else:
            logger.warning(f"No matching request found for packet ID: {packet['id']}\n{packet}")
        if self.callback:
            self.callback(packet)

    @staticmethod
    def callback(packet):
        logger.debug(packet)
