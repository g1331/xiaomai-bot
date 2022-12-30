# -*- coding: utf-8 -*-
from pathlib import Path

import httpx
from creart import create
from graia.ariadne import Ariadne
from graia.ariadne.event.lifecycle import AccountLaunch
from graia.ariadne.event.message import (
    ActiveFriendMessage,
    ActiveGroupMessage,
    StrangerMessage,
    TempMessage,
    GroupMessage,
    FriendMessage
)
from graia.ariadne.event.message import Member, MessageChain, Stranger
from graia.ariadne.event.mirai import NudgeEvent
from graia.ariadne.model import Friend, Group
from graia.broadcast import Broadcast
from graia.saya import Saya
from loguru import logger

from core.bot import Umaru
from core.config import GlobalConfig

config = create(GlobalConfig)
core = create(Umaru)
bcc = create(Broadcast)
saya = create(Saya)


@bcc.receiver(GroupMessage)
async def group_message_handler(app: Ariadne, message: MessageChain, group: Group, member: Member):
    core.received_count += 1
    # message_text_log = message.display.replace("\n", "\\n").strip()
    message_text_log = message.as_persistent_string().replace("\n", "\\n").strip()
    logger.info(
        f"收到来自 Bot <{app.account}> 群 <{group.name.strip()}> 中成员 <{member.name.strip()}> 的消息：{message_text_log}"
    )


@bcc.receiver(FriendMessage)
async def friend_message_listener(app: Ariadne, friend: Friend, message: MessageChain):
    core.received_count += 1
    message_text_log = message.display.replace("\n", "\\n").strip()
    logger.info(
        f"收到来自 Bot<{app.account}> 好友 <{friend.nickname.strip()}> 的消息：{message_text_log}")


@bcc.receiver(StrangerMessage)
async def stranger_message_listener(app: Ariadne, stranger: Stranger, message: MessageChain):
    core.received_count += 1
    message_text_log = message.display.replace("\n", "\\n").strip()
    logger.info(
        f"收到来自 Bot <{app.account}> 陌生人 <{stranger.nickname.strip()}> 的消息：{message_text_log}")


@bcc.receiver(ActiveGroupMessage)
async def group_message_speaker(event: ActiveGroupMessage, _app: Ariadne):
    core.sent_count += 1
    bot_member = await _app.get_friend(_app.account)
    message_text_log = event.message_chain.display.replace("\n", "\\n").strip()
    if bot_member is not None:
        logger.info(
            f"【{bot_member.nickname}({bot_member.id})】成功向群【{event.subject.name.strip()}({event.subject.id})】发送消息：{message_text_log}")
    else:
        logger.info(
            f"【{_app.account}】成功向群【{event.subject.name.strip()}({event.subject.id})】发送消息：{message_text_log}")


@bcc.receiver(ActiveFriendMessage)
async def friend_message_speaker(event: ActiveFriendMessage, _app: Ariadne):
    core.sent_count += 1
    bot_member = await _app.get_friend(_app.account)
    message_text_log = event.message_chain.display.replace("\n", "\\n").strip()
    if bot_member is not None:
        logger.info(
            f"【{bot_member.nickname}({bot_member.id})】成功向好友【{event.subject.nickname.strip()}({event.subject.id})】发送消息：{message_text_log}")
    else:
        logger.info(
            f"【{_app.account}】成功向好友【{event.subject.nickname.strip()}({event.subject.id})】发送消息：{message_text_log}")


@bcc.receiver(NudgeEvent)
async def nudged_listener(_app: Ariadne, event: NudgeEvent):
    core.sent_count += 1
    bot_member = await _app.get_friend(_app.account)
    if event.target != _app.account or event.supplicant == _app.account:
        return
    if event.group_id is None:
        return
    if not (member := await _app.get_member(event.group_id, event.supplicant)):
        return
    if bot_member is not None:
        logger.info(
            f"【{bot_member.nickname}({bot_member.id})】被群【{member.group.name}】中成员【{member.name}】戳了戳。")
    else:
        logger.info(
            f"【{_app.account}】被群【{member.group.name}】中成员【{member.name}】戳了戳。")


@bcc.receiver(TempMessage)
async def temp_message_listener(member: Member, message: MessageChain, _app: Ariadne):
    core.received_count += 1
    bot_member = await _app.get_friend(_app.account)
    message_text_log = message.display.replace("\n", "\\n").strip()
    if bot_member is not None:
        logger.info(
            f"【{bot_member.nickname}({bot_member.id})】收到群【{member.group.name.strip()}({member.group.id})】成员【{member.name.strip()}({member.id})】的临时消息：{message_text_log}")
    else:
        logger.info(
            f"【{_app.account}】收到群【{member.group.name.strip()}({member.group.id})】成员【{member.name.strip()}({member.id})】的临时消息：{message_text_log}")


@bcc.receiver(StrangerMessage)
async def stranger_message_listener(stranger: Stranger, message: MessageChain, _app: Ariadne):
    core.received_count += 1
    bot_member = await _app.get_friend(_app.account)
    message_text_log = message.display.replace("\n", "\\n").strip()
    if bot_member is not None:
        logger.info(
            f"【{bot_member.nickname}({bot_member.id})】收到来自陌生人【{stranger.nickname.strip()}({stranger.id})】的消息：{message_text_log})")
    else:
        logger.info(
            f"【{_app.account}】收到来自陌生人【{stranger.nickname.strip()}({stranger.id})】的消息：{message_text_log})")


@bcc.receiver(AccountLaunch)
async def init():
    _ = await core.initialize()


if __name__ == "__main__":
    if Path.cwd() != Path(__file__).parent:
        logger.critical(f"当前目录非项目所在目录！请进入{str(Path(__file__).parent)}后再运行!")
        exit(0)
    logger.info("正在检测 MAH 是否启动")
    while True:
        try:
            fl = 0
            mah = httpx.get(config.mirai_host + "/about")
            logger.info(f'mah.status_code:{mah.status_code}')
            if mah.status_code == 200:
                logger.success(f"成功检测到mirai")
                core.install_modules(Path("modules") / "required")
                core.install_modules(Path("modules") / "test_modules")
                core.launch()
                break
            elif fl >= 3:
                logger.critical("启动失败:请检查mirai是否正常启动/mah配置是否与bot配置一致")
                exit(0)
            else:
                fl += 1
                logger.critical("MAH 尚未启动，正在重试...")
        except httpx.HTTPError:
            logger.critical("MAH 尚未启动，请检查")
            break
        except KeyboardInterrupt:
            exit("--已手动退出--")
