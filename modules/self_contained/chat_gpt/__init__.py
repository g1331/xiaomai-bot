import asyncio
import re
from pathlib import Path
from typing import TypedDict

from creart import create
from graia.ariadne.app import Ariadne
from graia.ariadne.event.message import Group, GroupMessage, Member
from graia.ariadne.message.chain import MessageChain
from graia.ariadne.message.element import Source, Image
from graia.ariadne.message.parser.twilight import Twilight, FullMatch
from graia.ariadne.message.parser.twilight import WildcardMatch, RegexResult, ArgResult, ArgumentMatch
from graia.saya import Channel
from graia.saya.builtins.broadcast.schema import ListenerSchema
from revChatGPT.V1 import AsyncChatbot
from revChatGPT.V3 import Chatbot

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
channel.name("ChatGPT")
channel.description("一个与ChatGPT对话的插件")
channel.author("十三")
channel.metadata = module_controller.get_metadata_from_path(Path(__file__))

config = create(GlobalConfig)
proxy = config.proxy if config.proxy != "proxy" else None
session_token = config.functions.get("ChatGPT", {}).get("session_token")
api_key = config.functions.get("ChatGPT", {}).get("api_key")


def get_gpt():
    return Chatbot(
        api_key=api_key,
        system_prompt="你的名字叫小埋，是由十三开发的一个服务于战地一QQ群的智能聊天机器人，内核是由OpenAI开发的一个大型语音模型ChatGPT。"
    )
    # return AsyncChatbot(config={
    #     "session_token": session_token
    # })


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
                # self.data[group][member]["gpt"].reset_chat()
                self.data[group][member]["gpt"] = get_gpt()
            else:
                self.data[group][member] = {"running": False, "gpt": get_gpt()}
        else:
            self.data[group] = {}
            self.data[group][member] = {"running": False, "gpt": get_gpt()}

    def close(self, group: Group | int, member: Member | int):
        if isinstance(group, Group):
            group = group.id
        if isinstance(member, Member):
            member = member.id
        if group in self.data and member in self.data[group]:
            # self.data[group][member]["gpt"].reset_chat()
            self.data[group][member]["gpt"] = get_gpt()

    async def send_message(self, group: Group | int, member: Member | int, content: str, app: Ariadne,
                           source: Source) -> str:
        if isinstance(group, Group):
            group = group.id
        if isinstance(member, Member):
            member = member.id
        await app.send_group_message(group, MessageChain("请等待,ChatGPT解答ing"), quote=source)
        if group not in self.data or member not in self.data[group]:
            _ = await self.new(group, member)
        if self.data[group][member]["running"]:
            return "我上一句话还没结束呢，别急阿~等我回复你以后你再说下一句话喵~"
        self.data[group][member]["running"] = True
        try:
            result = await asyncio.to_thread(self.data[group][member]["gpt"].ask, content)
            # result = "获取回复消息为空!"
            # async for response in self.data[group][member]["gpt"].ask(prompt=content):
            #     result = response["message"]
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
                FullMatch("-chat"),
                ArgumentMatch("-n", "-new", action="store_true", optional=True) @ "new_thread",
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
async def chat_gpt(
        app: Ariadne,
        group: Group,
        member: Member,
        source: Source,
        new_thread: ArgResult,
        text: ArgResult,
        content: RegexResult
):
    if new_thread.matched:
        _ = await manager.new(group, member)
    response = await manager.send_message(group, member, content.result.display.strip(), app, source)
    if text.matched:
        await app.send_group_message(group, MessageChain(response), quote=source)
    else:
        await app.send_group_message(
            group, MessageChain(Image(data_bytes=await md2img(response, use_proxy=True))), quote=source
        )