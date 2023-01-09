import asyncio
from pathlib import Path

from creart import create
from graia.ariadne.app import Ariadne
from graia.ariadne.event import MiraiEvent
from graia.ariadne.event.message import GroupMessage, MessageEvent
from graia.ariadne.event.mirai import BotInvitedJoinGroupRequestEvent
from graia.ariadne.message.chain import MessageChain
from graia.ariadne.message.element import At, Source
from graia.ariadne.message.parser.twilight import Twilight, UnionMatch, SpacePolicy, ElementMatch
from graia.ariadne.model import Group, Member
from graia.ariadne.util.interrupt import FunctionWaiter
from graia.ariadne.util.saya import listen, decorate, dispatch
from graia.saya import Channel, Saya
from loguru import logger

from core.config import GlobalConfig
from core.control import (
    Permission,
    Function,
    FrequencyLimitation
)
from core.models import saya_model

module_controller = saya_model.get_module_controller()
global_config = create(GlobalConfig)

saya = Saya.current()
channel = Channel.current()
channel.name("QQ群管")
channel.description("简易的qq群管理功能")
channel.author("13")
channel.metadata = module_controller.get_metadata_from_path(Path(__file__))


@listen(BotInvitedJoinGroupRequestEvent)
async def invited_event(app: Ariadne, event: BotInvitedJoinGroupRequestEvent):
    """处理邀请
    """
    if Permission.require_user_perm(event.source_group, event.supplicant, Permission.BotAdmin):
        await event.accept('已同意您的邀请~')
        return await app.send_message(await app.get_group(global_config.test_group), MessageChain(
            f"成员{event.nickname}({event.supplicant})邀请bot加入群:\n{event.group_name}({event.source_group})\n"
            f'已自动同意该管理的邀请'
        ))
    group = await app.get_group(global_config.test_group)
    if group is None:
        member = await app.get_friend(global_config.Master)
        bot_message = await app.send_message(member, MessageChain(
            f"成员{event.nickname}({event.supplicant})邀请bot加入群:\n{event.group_name}({event.source_group})\n"
            f'是否同意该申请，请在1小时内回复“y”或“n”'
        ))
    else:
        bot_message = await app.send_message(group, MessageChain(
            f"成员{event.nickname}({event.supplicant})邀请bot加入群:\n{event.group_name}({event.source_group})\n"
            f'是否同意该申请，请在1小时内回复“y”或“n”'
        ))

    async def waiter(waiter_member: Member, waiter_message: MessageChain, waiter_group: Group,
                     event_waiter: GroupMessage):
        if await Permission.require_user_perm(waiter_group.id, waiter_member.id,
                                              Permission.GroupAdmin) and group.id == waiter_group.id \
                and eval(event_waiter.json())['message_chain'][1]['type'] == "Quote" and \
                eval(event_waiter.json())['message_chain'][1]['id'] == bot_message.id:
            saying = waiter_message.display
            if saying == 'y':
                return True, waiter_member.id
            elif saying == 'n':
                return False, waiter_member.id
            elif saying.startswith("n"):
                saying.replace("n", "")
                return False, waiter_member.id
            else:
                pass

    try:
        result, admin = await FunctionWaiter(waiter, [GroupMessage]).wait(timeout=3600)
    except asyncio.exceptions.TimeoutError:
        await app.send_message(group, MessageChain(
            f'处理 {event.nickname}({event.supplicant}) 的入群邀请已超时失效'),
                               )
        return

    if result:
        await event.accept('已同意您的邀请~')  # 同意入群
        await app.send_message(group, MessageChain(
            f'已同意 {event.nickname}({event.supplicant}) 的入群邀请'))
    else:
        await event.reject(f'BOT拒绝了你的入群邀请!')  # 拒绝
        await app.send_message(group, MessageChain(
            f'已拒绝 {event.nickname}({event.supplicant}) 的入群邀请'))


@listen(GroupMessage)
@decorate(
    Permission.user_require(Permission.GroupAdmin, if_noticed=True),
    Permission.group_require(channel.metadata.level, if_noticed=True),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
)
@dispatch(Twilight([
        "at" @ ElementMatch(At, optional=True).space(SpacePolicy.PRESERVE),
        "command" @ UnionMatch("加精", "设精")
]))
async def set_essence(app: Ariadne, group: Group, event: MessageEvent, src: Source):
    if event.quote:
        quote_id = event.quote.id
        bot_member = await app.get_member(group, app.account)
        if bot_member.permission.name == "Member":
            await app.send_message(group, MessageChain(
                f"bot权限不足!"
            ), quote=src)
            return
        try:
            await app.set_essence(quote_id)
        except Exception as e:
            logger.error(e)
            return await app.send_message(group, MessageChain(
                f"出错力~!"
            ), quote=src)

        return await app.send_message(group, MessageChain(
            f"加精成功"
        ), quote=src)
