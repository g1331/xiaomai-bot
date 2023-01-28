import re
import random
import hashlib
from pathlib import Path
from typing import Union
from sqlalchemy import select

from creart import create
from graia.saya import Channel
from graia.ariadne.app import Ariadne
from graia.broadcast import Broadcast
from graia.broadcast.interrupt.waiter import Waiter
from graia.ariadne.message.chain import MessageChain
from graia.broadcast.interrupt import InterruptControl
from graia.ariadne.message.parser.twilight import Twilight
from graia.ariadne.event.lifecycle import ApplicationLaunched
from graia.saya.builtins.broadcast.schema import ListenerSchema
from graia.ariadne.event.message import Group, GroupMessage, Member
from graia.ariadne.message.element import Source, MultimediaElement, Plain
from graia.ariadne.message.parser.twilight import (
    FullMatch,
    RegexMatch,
    WildcardMatch,
    RegexResult,
)

from core.models import saya_model
from core.orm import orm
from core.orm.tables import KeywordReply
from core.control import (
    Permission,
    Function,
    FrequencyLimitation,
    Distribute
)
from utils.waiter import ConfirmWaiter
from utils.message_chain import message_chain_to_json, json_to_message_chain

module_controller = saya_model.get_module_controller()
channel = Channel.current()
channel.name("KeywordRespondent")
channel.author("SAGIRI-kawaii")
channel.description(
    "一个关键字回复插件，在群中发送已添加关键词可自动回复\n"
    "在群中发送 `添加回复关键词#{keyword}#{reply}` 可添加关键词\n"
    "在群中发送 `删除回复关键词#{keyword}` 可删除关键词"
)
channel.metadata = module_controller.get_metadata_from_path(Path(__file__))

inc = InterruptControl(create(Broadcast))
regex_list = []
parse_big_bracket = r"\{"
parse_mid_bracket = r"\["
parse_bracket = r"\("
reply_type_set = ["fullmatch", "regex", "fuzzy"]


class NumberWaiter(Waiter.create([GroupMessage])):
    """超时Waiter"""

    def __init__(
            self, group: Union[int, Group], member: Union[int, Member], max_length: int
    ):
        self.group = group if isinstance(group, int) else group.id
        self.member = (
            (member if isinstance(member, int) else member.id) if member else None
        )
        self.max_length = max_length

    async def detected_event(self, group: Group, member: Member, message: MessageChain):
        if group.id == self.group and member.id == self.member:
            display = message.display
            return (
                int(display)
                if display.isnumeric() and 0 < int(display) <= self.max_length
                else -1
            )


add_keyword_twilight = Twilight(
    [
        FullMatch(r"添加"),
        FullMatch("群", optional=True) @ "group_only",
        RegexMatch(r"(模糊|正则)", optional=True) @ "op_type",
        FullMatch("回复关键词#"),
        RegexMatch(r"[^\s]+") @ "keyword",
        FullMatch("#"),
        WildcardMatch().flags(re.DOTALL) @ "response",
    ]
)

delete_keyword_twilight = Twilight(
    [
        FullMatch(r"删除"),
        FullMatch("群", optional=True) @ "group_only",
        RegexMatch(r"(模糊|正则)", optional=True) @ "op_type",
        FullMatch("回复关键词#"),
        RegexMatch(r"[^\s]+") @ "keyword",
    ]
)


@channel.use(
    ListenerSchema(
        listening_events=[GroupMessage],
        inline_dispatchers=[add_keyword_twilight],
        decorators=[
            Distribute.require(),
            FrequencyLimitation.require(channel.module),
            Function.require(channel.module),
            Permission.user_require(Permission.GroupAdmin),
            Permission.group_require(channel.metadata.level),
        ],
    )
)
async def add_keyword(
        app: Ariadne,
        group: Group,
        sender: Member,
        source: Source,
        group_only: RegexResult,
        op_type: RegexResult,
        keyword: RegexResult,
        response: RegexResult,
):
    if (not group_only.matched) and (not await Permission.require_user_perm(group.id, sender.id, Permission.BotAdmin)):
        return await app.send_group_message(group, MessageChain(
            f"添加全局关键词需要权限:{Permission.BotAdmin}/你的权限:{await Permission.get_user_perm_byID(group.id, sender.id)}\n"
            f"添加群关键词请用:添加群回复关键词#关键词#回复"
        ), quote=source)
    op_type = (
        ("regex" if op_type.result.display == "正则" else "fuzzy")
        if op_type.matched
        else "fullmatch"
    )
    response = await message_chain_to_json(response.result)
    keyword: MessageChain = keyword.result.copy()
    for i in keyword.content:
        if isinstance(i, MultimediaElement):
            i.url = ""
    keyword: str = keyword.as_persistent_string()
    reply_md5 = get_md5(response + str(group.id))
    if await orm.fetch_one(
            select(KeywordReply).where(
                KeywordReply.keyword == keyword.strip(),
                KeywordReply.reply_type == op_type,
                KeywordReply.reply_md5 == reply_md5,
                KeywordReply.group == (group.id if group_only.matched else -1),
            )
    ):
        return await app.send_group_message(
            group, MessageChain("重复添加关键词！进程退出"), quote=source
        )
    await orm.add(
        KeywordReply,
        {
            "keyword": keyword,
            "group": group.id if group_only.matched else -1,
            "reply_type": op_type,
            "reply": response,
            "reply_md5": reply_md5,
        },
    )
    if op_type != "fullmatch":
        regex_list.append(
            (
                keyword
                if op_type == "regex"
                else f"(.*)"
                     f"{keyword.replace('[', parse_mid_bracket).replace('{', parse_big_bracket).replace('(', parse_bracket)}"
                     f"(.*)",
                reply_md5,
                group.id if group_only else -1,
            )
        )
    await app.send_group_message(group, MessageChain(f"{'群关键词回复' if group_only.matched else '全局关键词回复'}添加成功！"),
                                 quote=source)


@channel.use(
    ListenerSchema(
        listening_events=[GroupMessage],
        inline_dispatchers=[delete_keyword_twilight],
        decorators=[
            Distribute.require(),
            FrequencyLimitation.require(channel.module),
            Function.require(channel.module),
            Permission.user_require(Permission.GroupAdmin),
            Permission.group_require(channel.metadata.level),
        ],
    )
)
async def delete_keyword(
        app: Ariadne,
        group: Group,
        sender: Member,
        member: Member,
        source: Source,
        group_only: RegexResult,
        op_type: RegexResult,
        keyword: RegexResult,
):
    if (not group_only.matched) and (not await Permission.require_user_perm(group.id, sender.id, Permission.BotAdmin)):
        return await app.send_group_message(group, MessageChain(
            f"删除全局关键词需要权限:{Permission.BotAdmin}/你的权限:{await Permission.get_user_perm_byID(group.id, sender.id)}\n"
            f"删除群关键词请用:删除群回复关键词#关键词"
        ), quote=source)
    op_type = (
        ("regex" if op_type.result.display == "正则" else "fuzzy")
        if op_type.matched
        else "fullmatch"
    )
    keyword: MessageChain = keyword.result.copy()
    for i in keyword.content:
        if isinstance(i, MultimediaElement):
            i.url = ""
    keyword = keyword.as_persistent_string()
    if results := await orm.fetch_all(
            select(
                KeywordReply.reply_type, KeywordReply.reply, KeywordReply.reply_md5
            ).where(KeywordReply.keyword == keyword)
    ):
        replies = list()
        for result in results:
            content_type = result[0]
            content = result[1]
            content_md5 = result[2]
            replies.append([content_type, content, content_md5])

        msg = [Plain(text=f"关键词{keyword}目前有以下数据：\n")]
        for i in range(len(replies)):
            msg.append(Plain(f"{i + 1}. "))
            msg.append(
                ("正则" if replies[i][0] == "regex" else "模糊")
                if replies[i][0] != "fullmatch"
                else "全匹配"
            )
            msg.append("匹配\n")
            msg.extend(json_to_message_chain(replies[i][1]).__root__)
            msg.append(Plain("\n"))
        msg.append(Plain(text="请发送你要删除的回复编号"))
        await app.send_group_message(group, MessageChain(msg))

        number = await inc.wait(NumberWaiter(group, member, len(replies)), timeout=30)
        if number == -1:
            await app.send_group_message(
                group, MessageChain("非预期回复，进程退出"), quote=source
            )
            return
        await app.send_group_message(
            group,
            MessageChain(
                [
                    Plain(text="你确定要删除下列回复吗(是/否)：\n"),
                    Plain(keyword),
                    Plain(text="\n->\n"),
                ]
            ).extend(json_to_message_chain(replies[number - 1][1])),
        )
        if await inc.wait(ConfirmWaiter(group, member), timeout=30):
            await orm.delete(
                KeywordReply,
                [
                    KeywordReply.keyword == keyword,
                    KeywordReply.reply_md5 == replies[number - 1][2],
                    KeywordReply.reply_type == replies[number - 1][0],
                    KeywordReply.group == (group.id if group_only.matched else -1),
                ],
            )
            temp_list = []
            global regex_list
            for i in regex_list:
                if all([
                    i[0] == keyword
                    if op_type == "regex"
                    else f"(.*){keyword.replace('[', parse_mid_bracket).replace('{', parse_big_bracket).replace('(', parse_bracket)}(.*)",
                    i[1] == replies[number - 1][2],
                    i[2] == (-1 if group_only.matched else group.id),
                ]):
                    continue
                temp_list.append(i)
            regex_list = temp_list
            await app.send_group_message(group, MessageChain(f"删除{'群关键词回复' if group_only.matched else '全局关键词回复'}成功"),
                                         quote=source)
        else:
            await app.send_group_message(
                group, MessageChain("非预期回复，进程退出"), quote=source
            )
    else:
        await app.send_group_message(group, MessageChain("未检测到此关键词数据"), quote=source)


@channel.use(
    ListenerSchema(
        listening_events=[GroupMessage],
        decorators=[
            Distribute.require(),
            Function.require(channel.module, notice=False),
            Permission.user_require(Permission.User, if_noticed=False),
            Permission.group_require(channel.metadata.level, if_noticed=False),
        ],
    )
)
async def keyword_detect(app: Ariadne, message: MessageChain, group: Group):
    try:
        add_keyword_twilight.generate(message)
    except ValueError:
        try:
            delete_keyword_twilight.generate(message)
        except ValueError:
            copied_msg = message.copy()
            for i in copied_msg.__root__:
                if isinstance(i, MultimediaElement):
                    i.url = ""
            if result := list(
                    await orm.fetch_all(
                        select(KeywordReply.reply).where(
                            KeywordReply.keyword == copied_msg.as_persistent_string(),
                            KeywordReply.group.in_((-1, group.id)),
                        )
                    )
            ):
                reply = random.choice(result)
                await app.send_group_message(
                    group, json_to_message_chain(str(reply[0]))
                )
            else:
                response_md5 = [
                    i[1]
                    for i in regex_list
                    if (
                            re.match(i[0], copied_msg.as_persistent_string())
                            and i[2] in (-1, group.id)
                    )
                ]
                if response_md5:
                    await app.send_group_message(
                        group,
                        json_to_message_chain(
                            (
                                await orm.fetch_one(
                                    select(KeywordReply.reply).where(
                                        KeywordReply.reply_md5
                                        == random.choice(response_md5)
                                    )
                                )
                            )[0]
                        ),
                    )


@channel.use(
    ListenerSchema(
        listening_events=[GroupMessage],
        inline_dispatchers=[Twilight([
            FullMatch("查询"),
            FullMatch("群", optional=True) @ "group_only",
            FullMatch("回复关键词"),
        ])],
        decorators=[
            Distribute.require(),
            FrequencyLimitation.require(channel.module),
            Function.require(channel.module),
            Permission.user_require(Permission.GroupAdmin),
            Permission.group_require(channel.metadata.level),
        ],
    )
)
async def show_keywords(app: Ariadne, group: Group, sender: Member, group_only: RegexResult, source: Source):
    if (not group_only.matched) and (not await Permission.require_user_perm(group.id, sender.id, Permission.BotAdmin)):
        return await app.send_group_message(group, MessageChain(
            f"查询全局关键词需要权限:{Permission.BotAdmin}/你的权限:{await Permission.get_user_perm_byID(group.id, sender.id)}\n"
            f"查询群关键词请用:查询群回复关键词"
        ), quote=source)
    keywords = await orm.fetch_all(
        select(
            KeywordReply.keyword,
            KeywordReply.reply_type,
            KeywordReply.group,
        ).where(KeywordReply.group.in_((-1, group.id)))
    )
    global_keywords = filter(lambda x: x[2] == -1, keywords)
    local_keywords = filter(lambda x: x[2] == group.id, keywords)
    if group_only.matched:
        message = ["本群启用："]
        for ks in local_keywords:
            for reply_type in reply_type_set:
                t = set()
                for keyword in filter(lambda x: x[1] == reply_type, ks):
                    t.add(f"    {keyword[0]}")
                if t:
                    message.append(f"  {reply_type}:")
                    message.extend(t)
        return await app.send_group_message(group, "\n".join(message[:-1]))
    else:
        message = ["全局启用："]
        for ks in global_keywords:
            for reply_type in reply_type_set:
                t = set()
                for keyword in filter(lambda x: x[1] == reply_type, ks):
                    t.add(f"    {keyword[0]}")
                if t:
                    message.append(f"  {reply_type}:")
                    message.extend(t)
        return await app.send_group_message(group, "\n".join(message[:-1]))


@channel.use(ListenerSchema(listening_events=[ApplicationLaunched]))
async def regex_init():
    if result := await orm.fetch_all(
            select(
                KeywordReply.keyword,
                KeywordReply.reply_md5,
                KeywordReply.reply_type,
                KeywordReply.group,
            ).where(KeywordReply.reply_type.in_(("regex", "fuzzy")))
    ):
        regex_list.extend([
            (
                i[0]
                if i[2] == "regex"
                else f"(.*)"
                     f"{i[0].replace('[', parse_mid_bracket).replace('{', parse_big_bracket).replace('(', parse_bracket)}"
                     f"(.*)",
                i[1],
                i[3],
            )
            for i in result
        ])


def get_md5(data: str) -> str:
    m = hashlib.md5()
    m.update(data.encode("utf-8"))
    return m.hexdigest()
