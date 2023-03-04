import asyncio
import datetime
import re
import aiohttp

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
from loguru import logger
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


kw_gpt = None


def get_kw_gpt():
    global kw_gpt
    if not kw_gpt:
        kw_gpt = Chatbot(
            api_key=api_key,
            system_prompt="用户输入一句话，如果这句话是带有搜索性质的，你就提取出要搜索的关键词。"
                          "关键词应该是你数据库中缺乏的信息。"
                          "关键词应该带有实时效应。"
                          "关键词应该用[]括起来。"
                          "[]应该包含一个或者多个关键词。"
                          "关键词之间用的逗号隔开。"
                          "多个关键词之间应该有很强的相互联系。"
                          "关键词的定语也要酌情提取。"
                          "如果没有关键词就输出一个[]。"
                          "回答不应该包含其他辅助提示词。"
                          "回答应该简洁明了如：[关键词1，关键词2]"
        )
    return kw_gpt


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
        if group not in self.data or member not in self.data[group]:
            _ = await self.new(group, member)
        if self.data[group][member]["running"]:
            return "我上一句话还没结束呢，别急阿~等我回复你以后你再说下一句话喵~"
        await app.send_group_message(group, MessageChain("请等待,ChatGPT解答ing"), quote=source)
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


async def kw_getter(content):
    result = await asyncio.to_thread(
        get_kw_gpt().ask,
        "用户输入一句话，如果这句话是带有搜索性质的，你就提取出要搜索的关键词。"
        "关键词应该是你数据库中缺乏的信息。"
        "关键词应该带有实时效应。"
        "关键词应该用[]括起来。"
        "[]应该包含一个或者多个关键词。"
        "关键词之间用的逗号隔开。"
        "多个关键词之间应该有很强的相互联系。"
        "关键词的定语也要酌情提取。"
        "如果没有关键词就输出一个[]。"
        "回答不应该包含其他辅助提示词。"
        "回答应该简洁明了如：[关键词1，关键词2]"
        f"这里是输入的句子：”{content}“"
    )
    kw = re.findall(r"\[(.*?)\]", result)
    return kw[0]


async def web_handle(content):
    try:
        web_result = await web_api(content)
        web_result_handle = "Web search results:\n"
        for i, item in enumerate(web_result):
            web_result_handle += (
                f"[{i + 1}]"
                f"Content:{item['body']}\n"
                f"Url:{item['href']}\n"
            )
        Current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S %A")
        web_result_handle += f"\nCurrent date:{Current_time}\n"
        web_result_handle += f"Instructions:" \
                             f"Please give priority to the context rather than using Web search results. " \
                             f"If you do not have relevant knowledge, then answer in combination with online search results. " \
                             f"Please answer with your own understanding." \
                             f"If the search results provided involve multiple topics with the same name, please fill in the answers for each topic separately. " \
                             f"If your reply uses web search results, make sure to cite results using [[number](URL)] notation after the reference." \
                             f"\nQuery: {content}" \
                             f"\nReply in 中文"
        return web_result_handle
    except Exception as e:
        logger.warning(f"GPT网络搜索出错!{e}")
        return content


async def web_api(content, result_nums: int = 3):
    api_url = f"https://ddg-webapp-aagd.vercel.app/search?q={content}?&max_results={result_nums}&region=cn-zh"
    async with aiohttp.ClientSession() as session:
        async with session.get(
                url=api_url,
                timeout=10
        ) as response:
            return await response.json()


manager = ConversationManager()


@channel.use(
    ListenerSchema(
        listening_events=[GroupMessage],
        inline_dispatchers=[
            Twilight([
                FullMatch("-chat"),
                ArgumentMatch("-n", "-new", action="store_true", optional=True) @ "new_thread",
                ArgumentMatch("-t", "-text", action="store_true", optional=True) @ "text",
                ArgumentMatch("-w", "-web", action="store_true", optional=True) @ "web",
                WildcardMatch().flags(re.DOTALL) @ "content",
            ])
        ],
        decorators=[
            Distribute.require(),
            Function.require(channel.module),
            FrequencyLimitation.require(channel.module, 7),
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
        web: ArgResult,
        content: RegexResult
):
    if new_thread.matched:
        _ = await manager.new(group, member)
    content = content.result.display.strip()
    if web.matched:
        content = await web_handle(await kw_getter(content))
    kw = await kw_getter(content)
    if kw:
        # print(f"kw:{kw}")
        content = await web_handle(content)
        # print(content)
    # else:
    #     print("no kw")
    response = await manager.send_message(group, member, content, app, source)
    if text.matched:
        await app.send_group_message(group, MessageChain(response), quote=source)
    else:
        await app.send_group_message(
            group, MessageChain(Image(data_bytes=await md2img(response, use_proxy=True))), quote=source
        )
