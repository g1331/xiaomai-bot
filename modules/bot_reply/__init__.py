import asyncio
import json
import os
import random
import string
import time

import requests
import zhconv
from graia.ariadne.app import Ariadne
from graia.ariadne.event.message import GroupMessage
from graia.ariadne.event.mirai import MemberHonorChangeEvent, NudgeEvent
from graia.ariadne.message.chain import MessageChain
from graia.ariadne.message.element import At, Source, Image
from graia.ariadne.message.parser.twilight import Twilight, SpacePolicy, RegexResult, \
    ElementMatch, UnionMatch, FullMatch
from graia.ariadne.model import Group, Member
from graia.ariadne.util.interrupt import FunctionWaiter
from graia.saya import Channel, Saya
from graia.saya.builtins.broadcast.schema import ListenerSchema
# 权限判断
from loguru import logger

from modules.DuoQHandle import DuoQ
from modules.PermManager import Perm

# 开启判断

# 获取属于这个模组的实例

saya = Saya.current()
channel = Channel.current()
channel.name("at_reply")
channel.description("一些简单的回复")
channel.author("13")


@channel.use(ListenerSchema(listening_events=[GroupMessage],
                            decorators=[
                                Perm.require(16),
                                DuoQ.require()
                            ],
                            inline_dispatchers=[
                                Twilight(
                                    [
                                        "at" @ ElementMatch(At).space(SpacePolicy.PRESERVE),
                                    ],
                                )
                            ]))
async def at_reply(app: Ariadne, sender: Member, group: Group, message: MessageChain, at: RegexResult):
    try:
        if at.result.target == app.account:
            gl = random.randint(0, 99)
            if 0 <= gl <= 70:
                file_path = f"./data/battlefield/小标语/data.json"
                with open(file_path, 'r', encoding="utf-8") as file1:
                    data = json.load(file1)['result']
                    a = random.choice(data)['name']
                    send = zhconv.convert(a, 'zh-cn')
            elif 70 < gl < 95:
                bqb_path = './data/bqb'
                bqb_pic_list = os.listdir(bqb_path)
                pic = random.choice(bqb_pic_list)
                pic_path = f"{bqb_path}/{pic}"
                send = Image(path=pic_path)
            else:
                bf_dic = [
                    "你知道吗,小埋最初的灵感来自于胡桃-by水神",
                    f"当武器击杀达到40⭐图片会发出白光,60⭐时为蓝光,当达到100⭐之后会发出耀眼的金光~",
                ]
                send = random.choice(bf_dic)
            await app.send_group_message(
                group.id, MessageChain(
                    At(sender.id), '\n', send
                )
            )
    except Exception as e:
        logger.error(e)
        return


# TODO 被戳回复小标语
@channel.use(ListenerSchema(listening_events=[NudgeEvent],
                            decorators=[
                                # Switch.require("bf1战绩")
                            ]))
async def getup(app: Ariadne, event: NudgeEvent):
    if event.group_id is not None:
        if event.target == app.account:
            gl = random.randint(0, 99)
            if gl > 2:
                file_path = f"./data/battlefield/小标语/data.json"
                with open(file_path, 'r', encoding="utf-8") as file1:
                    data = json.load(file1)['result']
                    a = random.choice(data)['name']
                    send = zhconv.convert(a, 'zh-cn')
            else:
                bf_dic = [
                    "你知道吗,小埋最初的灵感来自于胡桃-by水神",
                    f"当武器击杀达到40⭐图片会发出白光,60⭐时为紫光,当达到100⭐之后会发出耀眼的金光~",
                ]
                send = random.choice(bf_dic)
            await app.send_group_message(
                event.group_id, MessageChain(
                    At(event.supplicant), '\n', send
                )
            )
            return


@channel.use(ListenerSchema(listening_events=[GroupMessage],
                            decorators=[
                                Perm.require(16),
                                # Switch.require("test"),
                                DuoQ.require()
                            ],
                            inline_dispatchers=[
                                Twilight(
                                    [
                                        FullMatch("风控")
                                    ],
                                )
                            ]))
async def fengkong_bqb(app: Ariadne, sender: Member, group: Group, message: MessageChain):
    try:
        bqb_path = './data/bqb'
        bqb_pic_list = os.listdir(bqb_path)
        pic = None
        for item in bqb_pic_list:
            if item.startswith("风控"):
                pic = item
        if pic is None:
            return
        pic_path = f"{bqb_path}/{pic}"
        await app.send_message(group, MessageChain(
            Image(path=pic_path)
        ))
        return
    except Exception as e:
        logger.error(e)
        return


@channel.use(ListenerSchema(listening_events=[MemberHonorChangeEvent]))
async def get_MemberHonorChangeEvent(events: MemberHonorChangeEvent, app: Ariadne):
    """
    有人群荣誉变动
    """
    msg = [
        At(events.member.id),
        f" {'获得了' if events.action == 'achieve' else '失去了'} 群荣誉 {events.honor}！"
    ]
    await app.send_message(events.member.group, MessageChain.create(msg))


# 生成随机字符串
def random_string_generator(str_size, allowed_chars):
    return ''.join(random.choice(allowed_chars) for x in range(str_size))


@channel.use(ListenerSchema(listening_events=[GroupMessage],
                            decorators=[
                                Perm.require(128),
                                # Distribute.distribute()
                                # Switch.require("test"),
                                # DuoQ.require()
                            ],
                            inline_dispatchers=[
                                Twilight(
                                    [
                                        FullMatch("-check bot")
                                    ],
                                )
                            ]))
async def check_bot(app: Ariadne, sender: Member, group: Group, message: MessageChain):
    chars = string.ascii_letters + string.punctuation
    a = random_string_generator(10, chars)
    await app.send_message(group, MessageChain(
        a
    ))


@channel.use(ListenerSchema(listening_events=[GroupMessage],
                            decorators=[
                                Perm.require(),
                                DuoQ.require()
                            ],
                            inline_dispatchers=[
                                Twilight(
                                    [
                                        FullMatch("-开摆")
                                    ],
                                )
                            ]))
async def kai_bai(app: Ariadne, group: Group, sender: Member, message: MessageChain):
    await app.send_message(group, MessageChain(
        f"你真的要开摆吗:[是|否]?"
    ), quote=message[Source][0])

    async def waiter(event: GroupMessage, waiter_member: Member, waiter_group: Group, waiter_message: MessageChain):
        if waiter_member.id == sender.id and waiter_group.id == group.id:
            saying = waiter_message.display
            if saying == "是":
                return True
            else:
                return False

    try:
        result = await FunctionWaiter(waiter, [GroupMessage], block_propagation=True).wait(timeout=5)
    except asyncio.exceptions.TimeoutError:
        await app.send_message(group, MessageChain(
            f'取消操作!'), quote=message[Source][0])
        return
    if result:
        await app.send_message(group, MessageChain(
            f"啊对对对!"
        ))
    else:
        await app.send_message(group, MessageChain(
            f"寄摆!"
        ))
