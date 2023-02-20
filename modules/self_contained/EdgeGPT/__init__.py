import argparse
import asyncio
import json
import os
import random
import re
import uuid
from pathlib import Path
from typing import Generator, TypedDict
from typing import Optional

import tls_client
import websockets.client as websockets
from creart import create
from graia.ariadne.app import Ariadne
from graia.ariadne.event.message import Group, GroupMessage, Member
from graia.ariadne.message.chain import MessageChain
from graia.ariadne.message.element import Source, Image
from graia.ariadne.message.parser.twilight import Twilight, FullMatch
from graia.ariadne.message.parser.twilight import WildcardMatch, RegexResult, ArgResult, ArgumentMatch
from graia.saya import Channel, Saya
from graia.saya.builtins.broadcast.schema import ListenerSchema
from loguru import logger

from core.config import GlobalConfig
from core.control import (
    Permission,
    Function,
    FrequencyLimitation,
    Distribute
)
from core.models import saya_model, response_model
from utils.text2img import md2img

module_controller = saya_model.get_module_controller()
account_controller = response_model.get_acc_controller()

channel = Channel.current()
channel.name("EdgeGPT")
channel.description("一个生成与必应AI对话的插件")
channel.author("十三")
channel.metadata = module_controller.get_metadata_from_path(Path(__file__))

config = create(GlobalConfig)
proxy = config.proxy if config.proxy != "proxy" else None
cookie_path = Path(__file__).parent / "cookies.json"
if not cookie_path.is_file():
    enable = False
    logger.error("EdgeGPT未识别到cookie文件,请将cookies.json放在插件目录下!")
else:
    enable = True

parser = argparse.ArgumentParser()
parser.add_argument("--no-stream", action="store_true")
parser.add_argument(
    "--cookie-file",
    type=str,
    default=str(cookie_path),
)
args = parser.parse_args()
os.environ["COOKIE_FILE"] = args.cookie_file
args = parser.parse_args()

DELIMITER = "\x1e"

# Generate random IP between range 13.104.0.0/14
FORWARDED_IP = (
    f"13.{random.randint(104, 107)}.{random.randint(0, 255)}.{random.randint(0, 255)}"
)

HEADERS = {
    "accept": "application/json",
    "accept-language": "en-US,en;q=0.9",
    "content-type": "application/json",
    "sec-ch-ua": '"Not_A Brand";v="99", "Microsoft Edge";v="109", "Chromium";v="109"',
    "sec-ch-ua-arch": '"x86"',
    "sec-ch-ua-bitness": '"64"',
    "sec-ch-ua-full-version": '"109.0.1518.78"',
    "sec-ch-ua-full-version-list": '"Not_A Brand";v="99.0.0.0", "Microsoft Edge";v="109.0.1518.78", "Chromium";v="109.0.5414.120"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-model": "",
    "sec-ch-ua-platform": '"Windows"',
    "sec-ch-ua-platform-version": '"15.0.0"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "x-ms-client-request-id": str(uuid.uuid4()),
    "x-ms-useragent": "azsdk-js-api-client-factory/1.0.0-beta.1 core-rest-pipeline/1.10.0 OS/Win32",
    "Referer": "https://www.bing.com/search?q=Bing+AI&showconv=1&FORM=hpcodx",
    "Referrer-Policy": "origin-when-cross-origin",
    "x-forwarded-for": FORWARDED_IP,
}


class NotAllowedToAccess(Exception):
    pass


def append_identifier(msg: dict) -> str:
    """
    Appends special character to end of message to identify end of message
    """
    # Convert dict to json string
    return json.dumps(msg) + DELIMITER


class ChatHubRequest:
    """
    Request object for ChatHub
    """

    def __init__(
            self,
            conversation_signature: str,
            client_id: str,
            conversation_id: str,
            invocation_id: int = 0,
    ) -> None:
        self.struct: dict = {}

        self.client_id: str = client_id
        self.conversation_id: str = conversation_id
        self.conversation_signature: str = conversation_signature
        self.invocation_id: int = invocation_id

    def update(
            self,
            prompt: str,
            options: list = [
                "deepleo",
                "enable_debug_commands",
                "disable_emoji_spoken_text",
                "enablemm",
            ],
    ) -> None:
        """
        Updates request object
        """
        self.struct = {
            "arguments": [
                {
                    "source": "cib",
                    "optionsSets": options,
                    "isStartOfSession": self.invocation_id == 0,
                    "message": {
                        "author": "user",
                        "inputMethod": "Keyboard",
                        "text": prompt,
                        "messageType": "Chat",
                    },
                    "conversationSignature": self.conversation_signature,
                    "participant": {
                        "id": self.client_id,
                    },
                    "conversationId": self.conversation_id,
                },
            ],
            "invocationId": str(self.invocation_id),
            "target": "chat",
            "type": 4,
        }
        self.invocation_id += 1


class Conversation:
    """
    Conversation API
    """

    def __init__(self, cookiePath: str = "") -> None:
        self.struct: dict = {
            "conversationId": None,
            "clientId": None,
            "conversationSignature": None,
            "result": {"value": "Success", "message": None},
        }
        self.session = tls_client.Session(client_identifier="chrome_108")
        if cookiePath == "":
            f = open(os.environ.get("COOKIE_FILE"), encoding="utf-8").read()
        else:
            f = open(cookiePath, encoding="utf8").read()
        cookie_file = json.loads(f)
        for cookie in cookie_file:
            self.session.cookies.set(cookie["name"], cookie["value"])
        url = "https://edgeservices.bing.com/edgesvc/turing/conversation/create"
        # Send GET request
        response = self.session.get(
            url,
            timeout_seconds=30,
            headers=HEADERS,
            allow_redirects=True,
        )
        if response.status_code != 200:
            print(f"Status code: {response.status_code}")
            print(response.text)
            raise Exception("Authentication failed")
        try:
            self.struct = response.json()
            if self.struct["result"]["value"] == "UnauthorizedRequest":
                raise NotAllowedToAccess(self.struct["result"]["message"])
        except (json.decoder.JSONDecodeError, NotAllowedToAccess) as exc:
            raise Exception(
                "Authentication failed. You have not been accepted into the beta.",
            ) from exc


class ChatHub:
    """
    Chat API
    """

    def __init__(self, conversation: Conversation) -> None:
        self.wss: Optional[websockets.WebSocketClientProtocol] = None
        self.request: ChatHubRequest
        self.loop: bool
        self.task: asyncio.Task
        self.request = ChatHubRequest(
            conversation_signature=conversation.struct["conversationSignature"],
            client_id=conversation.struct["clientId"],
            conversation_id=conversation.struct["conversationId"],
        )

    async def ask_stream(self, prompt: str) -> Generator[str, None, None]:
        """
        Ask a question to the bot
        """
        # Check if websocket is closed
        if self.wss:
            if self.wss.closed:
                self.wss = await websockets.connect(
                    "wss://sydney.bing.com/sydney/ChatHub",
                    extra_headers=HEADERS,
                    max_size=None,
                )
                await self.__initial_handshake()
        else:
            self.wss = await websockets.connect(
                "wss://sydney.bing.com/sydney/ChatHub",
                extra_headers=HEADERS,
                max_size=None,
            )
            await self.__initial_handshake()
        # Construct a ChatHub request
        self.request.update(prompt=prompt)
        # Send request
        await self.wss.send(append_identifier(self.request.struct))
        final = False
        while not final:
            objects = str(await self.wss.recv()).split(DELIMITER)
            for obj in objects:
                if obj is None or obj == "":
                    continue
                response = json.loads(obj)
                if response.get("type") == 1:
                    yield False, response["arguments"][0]["messages"][0][
                        "adaptiveCards"
                    ][0]["body"][0]["text"]
                elif response.get("type") == 2:
                    final = True
                    yield True, response

    async def __initial_handshake(self):
        await self.wss.send(append_identifier({"protocol": "json", "version": 1}))
        await self.wss.recv()

    async def close(self):
        """
        Close the connection
        """
        if self.wss:
            if not self.wss.closed:
                await self.wss.close()


class Chatbot:
    """
    Combines everything to make it seamless
    """

    def __init__(self, cookiePath: str = "") -> None:
        self.cookiePath: str = cookiePath
        self.chat_hub: ChatHub = ChatHub(Conversation(self.cookiePath))

    async def ask(self, prompt: str) -> dict:
        """
        Ask a question to the bot
        """
        async for final, response in self.chat_hub.ask_stream(prompt=prompt):
            if final:
                return response
        await self.chat_hub.wss.close()

    async def ask_stream(self, prompt: str) -> Generator[str, None, None]:
        """
        Ask a question to the bot
        """
        async for response in self.chat_hub.ask_stream(prompt=prompt):
            yield response

    async def close(self):
        """
        Close the connection
        """
        await self.chat_hub.close()

    async def reset(self):
        """
        Reset the conversation
        """
        await self.close()
        self.chat_hub = ChatHub(Conversation(self.cookiePath))


class MemberGPT(TypedDict):
    running: bool
    gpt: Chatbot


class ConversationManager(object):
    def __init__(self):
        self.data: dict[int, dict[int, MemberGPT]] = {}

    async def new(self, group: Group | int, member: Member | int):
        if isinstance(group, Group):
            group = group.id
        if isinstance(member, Member):
            member = member.id
        if group in self.data:
            if member in self.data[group]:
                await self.data[group][member]["gpt"].reset()
            else:
                self.data[group][member] = {"running": False, "gpt": Chatbot()}
        else:
            self.data[group] = {}
            self.data[group][member] = {"running": False, "gpt": Chatbot()}

    def close(self, group: Group | int, member: Member | int):
        if isinstance(group, Group):
            group = group.id
        if isinstance(member, Member):
            member = member.id
        if group in self.data and member in self.data[group]:
            self.data[group][member]["gpt"].close()

    async def send_message(self, group: Group | int, member: Member | int, content: str) -> str:
        if isinstance(group, Group):
            group = group.id
        if isinstance(member, Member):
            member = member.id
        if group not in self.data or member not in self.data[group]:
            _ = await self.new(group, member)
        if self.data[group][member]["running"]:
            return "我上一句话还没结束呢，别急阿~等我回复你以后你再说下一句话喵~"
        self.data[group][member]["running"] = True
        try:
            result = (await self.data[group][member]["gpt"].ask(prompt=content))["item"]["messages"][1]["adaptiveCards"][0]["body"][0]["text"]
        except Exception as e:
            result = f"发生错误：{e}，请稍后再试"
        finally:
            self.data[group][member]["running"] = False
        return result


manager = ConversationManager()


@channel.use(
    ListenerSchema(
        listening_events=[GroupMessage],
        inline_dispatchers=[
            Twilight([
                FullMatch("-bing"),
                ArgumentMatch("-n", "-new", action="store_true", optional=True) @ "new_thread",
                ArgumentMatch("-t", "-text", action="store_true", optional=True) @ "text",
                WildcardMatch().flags(re.DOTALL) @ "content",
            ])
        ],
        decorators=[
            Distribute.require(),
            Function.require(channel.module),
            FrequencyLimitation.require(channel.module, 5),
            Permission.group_require(channel.metadata.level),
            Permission.user_require(Permission.User),
        ],
    )
)
async def chat_gpt(
        app: Ariadne,
        group: Group,
        member: Member,
        source: Source,
        new_thread: ArgResult,
        text: ArgResult,
        content: RegexResult
):
    if not enable:
        return await app.send_group_message(group, MessageChain("当前EdgeGPT没有配置cookie无法使用哦~"), quote=source)
    if new_thread.matched:
        _ = await manager.new(group, member)
    response = await manager.send_message(group, member, content.result.display.strip())
    if text.matched:
        await app.send_group_message(group, MessageChain(response), quote=source)
    else:
        await app.send_group_message(
            group, MessageChain(Image(data_bytes=await md2img(response, use_proxy=True))), quote=source
        )
