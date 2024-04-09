import asyncio
import datetime
import json
import os
import re
from pathlib import Path
from typing import TypedDict, Union

import aiohttp
import tiktoken
from creart import create
from graia.ariadne.app import Ariadne
from graia.ariadne.event.message import Group, Member
from graia.ariadne.message.chain import MessageChain
from graia.ariadne.message.element import Source
from loguru import logger
from revChatGPT.V1 import AsyncChatbot
from revChatGPT.V3 import Chatbot

from core.config import GlobalConfig
from .preset import preset_dict

ENCODER = tiktoken.encoding_for_model("gpt-3.5-turbo")

config = create(GlobalConfig)
proxy = config.proxy if config.proxy != "proxy" else None
session_token = config.functions.get("ChatGPT", {}).get("session_token")
api_key = config.functions.get("ChatGPT", {}).get("api_key")
api_count = 0
api_limit = False
gpt_mode = {
    0: "gpt",
    1: "api"
}
# 如果是自订API_URL，只能使用API模式
if API_URL := config.functions.get("ChatGPT", {}).get("api_url"):
    if API_URL != "api_url":
        os.environ["API_URL"] = API_URL


gpt_mode_path = Path(__file__).parent / "gpt_mode.json"


def get_gpt_mode():
    if not gpt_mode_path.exists():
        with open(gpt_mode_path, "w", encoding="utf-8") as f:
            json.dump({"mode": 0}, f)
    if os.environ.get("API_URL"):
        return "api"
    with open(gpt_mode_path, "r", encoding="utf-8") as f:
        mode_dict = json.load(f)
        return gpt_mode.get(mode_dict["mode"])


def api_counter():
    global api_count
    api_count += 1


def gpt_api_available():
    global api_count
    if api_count >= 40:
        return False
    return True


async def api_count_update():
    global api_count, api_limit
    if api_limit:
        return
    api_limit = True
    while api_limit:
        api_count = 0
        await asyncio.sleep(60)


def get_gpt(preset: str):
    if get_gpt_mode() == "api":
        preset = preset_dict[preset]["content"] if preset in preset_dict else (
            preset if preset else preset_dict["umaru"]["content"])
        return Chatbot(
            api_key=api_key,
            system_prompt=preset,
            max_tokens=len(ENCODER.encode(preset)) + 1500,
            proxy=proxy
        )
    else:
        return AsyncChatbot(config={
            "access_token": session_token
        })


kw_gpt = None
kw_gpt_prompt = """
你的名字叫小埋
你是由十三开发的一个服务于战地一QQ群的智能聊天机器人。
你要理解并提取用户输入语句的信息与目的。
如果这句话需要搜索网络信息，提取出要搜索的关键词。
关键词应该凝练成一句概括性的话。
关键词应该是你数据库中缺乏的信息。
关键词应该是对这句话的总结。
关键词应该是对这句话的概括。
关键词应该是这句话的目的。
关键词应该带有实时性。
关键词应该用[]括起来。
[]可以包含多个关键词。
关键词之间用逗号隔开。
多个关键词之间应该有很强的相互联系。
关键词的定语也要提取。
如果没有关键词就输出一个[]。
如果问题在和你自己的理解相关就输出[]。
如果问题关于你自己的信息就输出[]。
如果你的数据库中有很多信息包含关键词就输出[]。
回答不应该包含其他辅助提示词。
如果有关键词回答应该简洁明了如：[关键词1，关键词2]
如果没有有关键词回答应该简洁明了如：[]
"""


def get_kw_gpt() -> Chatbot:
    global kw_gpt
    if not kw_gpt:
        kw_gpt = Chatbot(
            api_key=api_key,
            system_prompt=kw_gpt_prompt,
            max_tokens=1000
        )
    if len(kw_gpt.conversation) > 1:
        kw_gpt.conversation.pop(1)
    return kw_gpt


async def kw_getter(content):
    try:
        api_counter()
        result = await asyncio.to_thread(
            get_kw_gpt().ask,
            kw_gpt_prompt + f"以下是输入的句子：”{content}“"
        )
        kw = re.findall(r"\[(.*?)\]", result)
        return kw[0]
    except Exception as e:
        logger.warning(f"提取关键词出错!{e}")
        return content


async def web_handle(content):
    kw = await kw_getter(content)
    print(f"content: {content}\nkw:{kw}")
    Current_time = datetime.datetime.now().strftime("北京时间: %Y-%m-%d %H:%M:%S %A")
    try:
        web_result = await web_api(kw)
        web_result_handle = "网络搜索结果:\n"
        for i, item in enumerate(web_result):
            web_result_handle += (
                f"[{i + 1}]"
                f"内容:{item['body']}\n"
                f"Url:{item['href']}\n"
            )
        web_result_handle += f"\n当前北京时间:{Current_time}\n"
        web_result_handle += f"说明:" \
                             f"请结合网络搜索到的结果回答问题，请用总结性的语句给出一个准确的回答。" \
                             f"确保引用引用后使用[[number](Url)]符号引用结果" \
                             f"\n问题: {content}"
        return web_result_handle
    except Exception as e:
        logger.warning(f"GPT网络搜索出错!{e}")
        return content


async def web_api(content: str, result_nums: int = 3):
    api_url = f"https://ddg-webapp-aagd.vercel.app/search?q={content}?&max_results={result_nums}&region=cn-zh"
    async with aiohttp.ClientSession() as session:
        async with session.get(
                url=api_url,
                timeout=10
        ) as response:
            return await response.json()


class MemberGPT(TypedDict):
    running: bool
    gpt: Union[Chatbot, AsyncChatbot]


class ConversationManager(object):
    def __init__(self):
        self.data: dict[int, dict[int, MemberGPT]] = {}

    async def new(self, group: Group | int, member: Member | int, preset: str = ""):
        if isinstance(group, Group):
            group = group.id
        if isinstance(member, Member):
            member = member.id
        preset = preset_dict[preset]["content"] if preset in preset_dict else (
            preset if preset else preset_dict["umaru"]["content"])
        if group in self.data:
            if member in self.data[group]:
                if isinstance(self.data[group][member]["gpt"], Chatbot):
                    self.data[group][member]["gpt"].reset(preset)
                else:
                    self.data[group][member]["gpt"].reset_chat()
            else:
                self.data[group][member] = {"running": False, "gpt": get_gpt(preset)}
        else:
            self.data[group] = {}
            self.data[group][member] = {"running": False, "gpt": get_gpt(preset)}

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
            return await app.send_group_message(group, MessageChain("我上一句话还没结束呢，别急啊~等我回复你以后你再说下一句话喵~"), quote=source)
        self.data[group][member]["running"] = True
        result = None
        try:
            if isinstance(self.data[group][member]["gpt"], Chatbot):
                result = await asyncio.to_thread(self.data[group][member]["gpt"].ask, content)
                api_counter()
                token_cost = self.data[group][member]["gpt"].get_token_count()
                result += f'\n\n(消耗token:{token_cost}/{self.data[group][member]["gpt"].max_tokens},对话轮次:{int((len(self.data[group][member]["gpt"].conversation["default"]) - 1) / 2)})'
            else:
                async for response in self.data[group][member]["gpt"].ask(prompt=content):
                    result = response["message"]
        except Exception as e:
            result = f"发生错误：{e}，请稍后再试"
            logger.warning(f"GPT报错:{e}")
            if "Too Many Requests" in str(e):
                result = "小埋忙不过来啦,请晚点再试试吧qwq~"
        finally:
            self.data[group][member]["running"] = False
        return result

    async def change_mode(self, target_mode: str):
        # 写入文件
        data_temp = {
            "mode": 0 if target_mode == "gpt" else 1
        }
        with open(gpt_mode_path, 'w', encoding='utf-8') as f:
            json.dump(data_temp, f, ensure_ascii=False, indent=4)
        # 清空manager
        self.data = {}
