import re
from pathlib import Path
from typing import TypedDict

from EdgeGPT import Chatbot, ConversationStyle
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

from core.config import GlobalConfig
from core.control import (
    Permission,
    Function,
    FrequencyLimitation,
    Distribute
)
from core.models import saya_model, response_model
from utils.text2img import md2img, template2img

module_controller = saya_model.get_module_controller()
account_controller = response_model.get_acc_controller()

channel = Channel.current()
channel.name("EdgeGPT")
channel.description("一个与必应AI对话的插件")
channel.author("十三")
channel.metadata = module_controller.get_metadata_from_path(Path(__file__))

config = create(GlobalConfig)
proxy = config.proxy if config.proxy != "proxy" else None
cookie_path = Path(__file__).parent / "cookies.json"


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
                self.data[group][member] = {"running": False, "gpt": Chatbot(cookiePath=cookie_path)}
        else:
            self.data[group] = {}
            self.data[group][member] = {"running": False, "gpt": Chatbot(cookiePath=cookie_path)}

    async def send_message(
            self, group: Group | int, member: Member | int,
            content: str, app: Ariadne, source: Source, style: int, texted: bool
    ) -> str:
        if isinstance(group, Group):
            group = group.id
        if isinstance(member, Member):
            member = member.id
        if group not in self.data or member not in self.data[group]:
            _ = await self.new(group, member)
        if self.data[group][member]["running"]:
            return await app.send_group_message(group, MessageChain("我上一句话还没结束呢，别急阿~等我回复你以后你再说下一句话喵~"), quote=source)
        self.data[group][member]["running"] = True
        response = None
        try:
            if texted:
                result = []
            else:
                result = [f"问题:\n\n{content}\n\n必应:\n\n"]
            conversation_style = ConversationStyle.balanced if style == 1 else ConversationStyle.creative if style == 2 else ConversationStyle.precise
            response = (
                await self.data[group][member]["gpt"].ask(prompt=content, conversation_style=conversation_style)
            )
            if len(response["item"]["messages"]) != 1:
                result.append(response["item"]["messages"][1]["text"])
            else:
                logger.error(response)
                return "获取必应的回复失败!"

            maxNumUserMessagesInConversation = response["item"]["throttling"]["maxNumUserMessagesInConversation"]
            numUserMessagesInConversation = response["item"]["throttling"]["numUserMessagesInConversation"]

            if sourceAttributions := response["item"]["messages"][1].get("sourceAttributions"):
                result.append("引用:")
                for i, item in enumerate(sourceAttributions):
                    result.append(f"[{i + 1}]{item.get('providerDisplayName')}:{item.get('seeMoreUrl')}")

            if suggestedResponses := response["item"]["messages"][1].get("suggestedResponses"):
                result.append("猜你想问:")
                for item in suggestedResponses:
                    result.append(f"{item.get('text')}")

            result.append(f"(对话轮次:{numUserMessagesInConversation}/{maxNumUserMessagesInConversation})")

            if texted:
                result = "\n".join(result)
            else:
                result = "\n\n".join(result)
        except Exception as e:
            logger.error(response)
            if response:
                response = response.get("item", {}).get("result", {}).get("message", {})
            result = f"发生错误：{e}，response:{response}请稍后再试"
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
                ArgumentMatch("-s", "-style", type=int, choices=[1, 2, 3], default=1,
                              optional=True) @ "style",
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
async def edge_gpt(
        app: Ariadne,
        group: Group,
        member: Member,
        source: Source,
        new_thread: ArgResult,
        text: ArgResult,
        style: ArgResult,
        content: RegexResult
):
    if new_thread.matched:
        _ = await manager.new(group, member)
    response = await manager.send_message(
        group, member, content.result.display, app, source, style.result, text.matched
    )
    if text.matched:
        await app.send_group_message(group, MessageChain(response), quote=source)
    else:
        await app.send_group_message(
            group, MessageChain(Image(data_bytes=await md2img(response, use_proxy=True))), quote=source
        )
