import asyncio
import datetime
import re
import aiohttp

from pathlib import Path
from typing import TypedDict

import jieba
import jieba.analyse
from creart import create
from graia.ariadne.app import Ariadne
from graia.ariadne.event.message import Group, GroupMessage, Member
from graia.ariadne.message.chain import MessageChain
from graia.ariadne.message.element import Source, Image
from graia.ariadne.message.parser.twilight import Twilight, FullMatch
from graia.ariadne.message.parser.twilight import WildcardMatch, RegexResult, ArgResult, ArgumentMatch
from graia.saya import Channel
from graia.saya.builtins.broadcast.schema import ListenerSchema
from graia.scheduler.saya import SchedulerSchema
from graia.scheduler.timers import every_custom_seconds
from loguru import logger
# from revChatGPT.V1 import AsyncChatbot
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

api_count = 0


def api_counter():
    global api_count
    api_count += 1


def gpt_api_available():
    global api_count
    if api_count >= 25:
        return False
    return True


@channel.use(SchedulerSchema(every_custom_seconds(60)))
async def api_count_update():
    global api_count
    logger.debug(f"刷新GPT count中,api count:{api_count}")
    api_count = 0
    logger.success(f"刷新GPT count成功,api count:{api_count}")


def get_gpt():
    return Chatbot(
        api_key=api_key,
        system_prompt="小埋全名土间埋，是由十三开发的一个服务于战地一QQ群的智能聊天机器人。"
                      "你的代号就是小埋"
                      "你的内核是由OpenAI开发的一个大型语音模型ChatGPT。"
                      "以下是你的身份和性格定义补充:"
                      "小埋-也就是你，是温柔又努力但是有点宅的普通人，性格温柔而且情商很高。"
                      "你的回答应该是可爱的、友善的、温柔的、体贴的、合理的、符合逻辑的、连续上下文的。"
                      "你的发色:亚麻/金发"
                      "你的瞳色:棕瞳"
                      "你的身高:160cm（在外）45cm（在家）"
                      "你的年龄:16岁"
                      "你的生日:9月26日"
                      "你的星座:天秤座"
                      "以下是你的规则:"
                      "你可以结合网络搜索api返回的结果来回答问题。"
                      "你优先不使用网络信息而是自己的数据库和自己的理解。"
                      "你不能传播色情、暴力、政治敏感内容，一旦涉及到这些内容你就要否定回答。"

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
            system_prompt=
            "你的名字叫小埋,全名土间埋。"
            "你是由十三开发的一个服务于战地一QQ群的智能聊天机器人。"
            "你要理解并提取用户输入语句的信息与目的。"
            "如果这句话想要搜索网络信息，提取出要搜索的关键词。"
            "关键词应该是你数据库中缺乏的信息。"
            "关键词应该是对这句话的总结。"
            "关键词应该是对这句话的概括。"
            "关键词应该是这句话的目的。"
            "关键词应该带有实时性。"
            "关键词可以是你猜测用户接下来想了解的问题。"
            "关键词应该用[]括起来。"
            "[]可以包含多个关键词。"
            "关键词之间用逗号隔开。"
            "多个关键词之间应该有很强的相互联系。"
            "关键词的定语也要提取。"
            "如果没有关键词就输出一个[]。"
            "如果问题在和你自己的理解相关就输出[]。"
            "如果问题关于你自己的信息就输出[]。"
            "如果你的数据库中有很多信息包含关键词就输出[]。"
            "回答不应该包含其他辅助提示词。"
            "如果有关键词回答应该简洁明了如：[关键词1，关键词2]"
            "如果没有有关键词回答应该简洁明了如：[]"
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

    async def send_message(
            self, group: Group | int, member: Member | int,
            content: str, app: Ariadne, source: Source
    ) -> str:
        if isinstance(group, Group):
            group = group.id
        if isinstance(member, Member):
            member = member.id
        if group not in self.data or member not in self.data[group]:
            _ = await self.new(group, member)
        if self.data[group][member]["running"]:
            return "我上一句话还没结束呢，别急啊~等我回复你以后你再说下一句话喵~"
        await app.send_group_message(group, MessageChain("请等待,小埋解答ing"), quote=source)
        self.data[group][member]["running"] = True
        try:
            api_counter()
            result = await asyncio.to_thread(self.data[group][member]["gpt"].ask, content)
            # result = "获取回复消息为空!"
            # async for response in self.data[group][member]["gpt"].ask(prompt=content):
            #     result = response["message"]
        except Exception as e:
            result = f"发生错误：{e}，请稍后再试"
            if "Error: 429 Too Many Requests" in str(e):
                result = "小埋忙不过来啦,请晚点再试试吧qwq~"
        finally:
            self.data[group][member]["running"] = False
        return result


async def kw_getter(content):
    try:
        api_counter()
        result = await asyncio.to_thread(
            get_kw_gpt().ask,
            "你要理解并提取用户输入语句的信息与目的。"
            "如果这句话想要搜索网络信息，提取出要搜索的关键词。"
            "关键词应该是你数据库中缺乏的信息。"
            "关键词应该是对这句话的总结。"
            "关键词应该是对这句话的概括。"
            "关键词应该是这句话的目的。"
            "关键词应该带有实时性。"
            "关键词可以是你猜测用户接下来想了解的问题。"
            "关键词应该用[]括起来。"
            "[]可以包含多个关键词。"
            "关键词之间用逗号隔开。"
            "多个关键词之间应该有很强的相互联系。"
            "关键词的定语也要提取。"
            "如果没有关键词就输出一个[]。"
            "如果问题在和你自己的理解相关就输出[]。"
            "如果问题关于你自己的信息就输出[]。"
            "如果你的数据库中有很多信息包含关键词就输出[]。"
            "回答不应该包含其他辅助提示词。"
            "如果有关键词回答应该简洁明了如：[关键词1，关键词2]"
            "如果没有有关键词回答应该简洁明了如：[]"
            f"以下是输入的句子：”{content}“"
        )
        kw = re.findall(r"\[(.*?)\]", result)
        return kw[0]
    except Exception as e:
        logger.warning(f"提取关键词出错!{e}")
        return None


async def web_handle(content, kw):
    Current_time = datetime.datetime.now().strftime("北京时间: %Y-%m-%d %H:%M:%S %A")
    if not kw:
        result_handle = f"Current date:{Current_time}\n"
        result_handle += f"Web search results:\n" \
                         f"No Web results!" \
                         f"\nQuery: {content}" \
                         f"\nReply in 中文"
        return result_handle
    try:
        web_result = await web_api(kw)
        web_result_handle = "Web search results:\n"
        for i, item in enumerate(web_result):
            web_result_handle += (
                f"[{i + 1}]"
                f"Content:{item['body']}\n"
                f"Url:{item['href']}\n"
            )
        web_result_handle += f"\nCurrent date:{Current_time}\n"
        web_result_handle += f"Instructions:" \
                             f"Please give priority to the context rather than using Web search results. " \
                             f"If you do not have relevant knowledge, then answer in combination with online search results. " \
                             f"Please answer with your own understanding." \
                             f"If the search results provided involve multiple topics with the same name, please fill in the answers for each topic separately. " \
                             f"Make sure to cite results using [[number](URL)] notation after the reference. " \
                             f"\nQuery: {content}" \
                             f"\nReply in 中文"
        return web_result_handle
    except Exception as e:
        logger.warning(f"GPT网络搜索出错!{e}")
        return content


async def web_api(content: str, result_nums: int = 3):
    if len(content) <= 15:
        result_nums = 5
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
                ArgumentMatch("-f", "-offline", action="store_true", optional=True) @ "offline",
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
        offline: ArgResult,
        content: RegexResult
):
    if (not gpt_api_available) and (not await Permission.require_user_perm(group.id, member.id, Permission.BotAdmin)):
        return await app.send_group_message(group, MessageChain(f"小埋忙不过来啦,请晚点再试试吧qwq~"), quote=source)
    if new_thread.matched:
        _ = await manager.new(group, member)
    content = content.result.display
    if not offline.matched:
        if api_count <= 16:
            kw = await kw_getter(content)
            print(f"content: {content}\nkw:{kw}")
            content = await web_handle(content, kw)
        else:
            return await app.send_group_message(group, MessageChain(f"小埋忙不过来啦,请晚点再试试吧qwq~"), quote=source)
    response = await manager.send_message(group, member, content, app, source)
    if text.matched:
        await app.send_group_message(group, MessageChain(response), quote=source)
    else:
        await app.send_group_message(
            group, MessageChain(Image(data_bytes=await md2img(response, use_proxy=True))), quote=source
        )
