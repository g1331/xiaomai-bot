import asyncio
import re
from pathlib import Path

from graia.ariadne.app import Ariadne
from graia.ariadne.event.message import Group, GroupMessage
from graia.ariadne.message.chain import MessageChain
from graia.ariadne.message.element import Source, Image
from graia.ariadne.message.parser.twilight import Twilight, UnionMatch
from graia.ariadne.message.parser.twilight import WildcardMatch, RegexResult, ArgResult, ArgumentMatch
from graia.saya import Channel
from graia.saya.builtins.broadcast.schema import ListenerSchema
from slack_sdk.errors import SlackApiError
from slack_sdk.web.async_client import AsyncWebClient

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
channel.name("Claude")
channel.description("一个与Claude对话的插件")
channel.author("十三")
channel.metadata = module_controller.get_metadata_from_path(Path(__file__))

CLAUDE_BOT_ID = "你的slack bot id"
SLACK_USER_TOKEN = "你的slack token"


class SlackClient(AsyncWebClient):
    CHANNEL_ID = None
    LAST_TS = None

    async def chat(self, text):
        if not self.CHANNEL_ID:
            raise TypeError("Channel not found.")

        resp = await self.chat_postMessage(channel=self.CHANNEL_ID, text=text)
        print("c: ", resp)
        self.LAST_TS = resp["ts"]

    async def open_channel(self):
        if not self.CHANNEL_ID:
            print(111)
            response = await self.conversations_open(users=CLAUDE_BOT_ID)
            self.CHANNEL_ID = response["channel"]["id"]

    async def get_reply(self):
        for _ in range(150):
            try:
                resp = await self.conversations_history(channel=self.CHANNEL_ID, oldest=self.LAST_TS, limit=2)
                print("r: ", resp)
                msg = [msg["text"] for msg in resp["messages"] if msg["user"] == CLAUDE_BOT_ID]
                if msg and not msg[-1].endswith("Typing…_"):
                    return msg[-1]
            except (SlackApiError, KeyError) as e:
                print(f"Get reply error: {e}")

            await asyncio.sleep(1)

        raise RuntimeError("Get replay timeout")


client = SlackClient(token=SLACK_USER_TOKEN)


async def chat(text):
    await client.open_channel()
    await client.chat(text)
    return await client.get_reply()


lock = asyncio.Lock()
running = False


@channel.use(
    ListenerSchema(
        listening_events=[GroupMessage],
        inline_dispatchers=[
            Twilight([
                UnionMatch("-claude", "-cla"),
                ArgumentMatch("-t", "-text", action="store_true", optional=True) @ "text",
                WildcardMatch().flags(re.DOTALL) @ "content",
            ])
        ],
        decorators=[
            Distribute.require(),
            Function.require(channel.module),
            FrequencyLimitation.require(channel.module, 5),
            Permission.group_require(channel.metadata.level, if_noticed=True),
            Permission.user_require(Permission.User),
        ],
    )
)
async def claude_gpt(
        app: Ariadne,
        group: Group,
        source: Source,
        text: ArgResult,
        content: RegexResult
):
    global running
    if running:
        return await app.send_group_message(group, MessageChain("Claude正在与其他人说话哦~请稍后再试!"), quote=source)
    # 加锁，同一时间只能有一个人在和Claude对话
    async with lock:
        running = True
        try:
            response = await chat(content.result.display)
        except RuntimeError as e:
            response = f"Claude回复时出现了错误!{e}"
        finally:
            running = False
    if text.matched:
        await app.send_group_message(group, MessageChain(response), quote=source)
    else:
        await app.send_group_message(
            group, MessageChain(Image(data_bytes=await md2img(response, use_proxy=True))), quote=source
        )
