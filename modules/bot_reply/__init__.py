import asyncio
import json
import os
import random
import string

import zhconv
from graia.ariadne.app import Ariadne
from graia.ariadne.event.message import GroupMessage
from graia.ariadne.event.mirai import MemberHonorChangeEvent
from graia.ariadne.message.chain import MessageChain
from graia.ariadne.message.element import At, Source, Image
from graia.ariadne.message.parser.twilight import Twilight, SpacePolicy, RegexResult, \
    ElementMatch, FullMatch
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
async def at_reply(app: Ariadne, sender: Member, group: Group, at: RegexResult):
    try:
        at: At = at.result
        if at.target == app.account:
            bqb_path = './data/bqb'
            bqb_pic_list = os.listdir(bqb_path)
            pic = random.choice(bqb_pic_list)
            pic_path = f"{bqb_path}/{pic}"
            send = Image(path=pic_path)
            await app.send_group_message(
                group.id, MessageChain(
                    At(sender.id), '\n', send
                )
            )
    except Exception as e:
        logger.error(e)
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
async def fengkong_bqb(app: Ariadne, group: Group):
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
    await app.send_message(events.member.group, MessageChain(msg))


# 生成随机字符串
def random_string_generator(str_size, allowed_chars):
    return ''.join(random.choice(allowed_chars) for _ in range(str_size))


@channel.use(ListenerSchema(listening_events=[GroupMessage],
                            decorators=[
                                Perm.require(128),
                            ],
                            inline_dispatchers=[
                                Twilight(
                                    [
                                        FullMatch("-check bot")
                                    ],
                                )
                            ]))
async def check_bot(app: Ariadne, group: Group):
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

    async def waiter(waiter_member: Member, waiter_group: Group, waiter_message: MessageChain):
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
