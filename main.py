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
from graia.ariadne.event.mirai import NudgeEvent, BotJoinGroupEvent
from graia.ariadne.model import Friend, Group
from graia.broadcast import Broadcast
from graia.saya import Saya
from loguru import logger

from core.bot import Umaru
from core.config import GlobalConfig
from core.models import (
    frequency_model
)

config = create(GlobalConfig)
core = create(Umaru)
bcc = create(Broadcast)
saya = create(Saya)


@bcc.receiver(GroupMessage)
async def group_message_listener(app: Ariadne, message: MessageChain, group: Group, member: Member):
    core.received_count += 1
    if core.config.GroupMsg_log:
        bot_member = await app.get_bot_profile()
        message_text_log = message.display.replace("\n", "\\n").strip()
        logger.info(
            f"【{bot_member.nickname}({app.account})】成功收到群【{group.name.strip()}({group.id})】"
            f"成员【{member.name.strip()}({member.id})】的消息：{message_text_log}")


@bcc.receiver(FriendMessage)
async def friend_message_listener(app: Ariadne, friend: Friend, message: MessageChain):
    core.received_count += 1
    message_text_log = message.display.replace("\n", "\\n").strip()
    bot_member = await app.get_bot_profile()
    logger.info(
        f"【{bot_member.nickname}({app.account})】成功收到"
        f"好友【{friend.nickname.strip()}({friend.id})】的消息：{message_text_log}")


@bcc.receiver(ActiveGroupMessage)
async def group_message_speaker(app: Ariadne, event: ActiveGroupMessage):
    core.sent_count += 1
    message_text_log = event.message_chain.display.replace("\n", "\\n").strip()
    bot_member = await app.get_bot_profile()
    logger.info(
        f"【{bot_member.nickname}({app.account})】成功向群"
        f"【{event.subject.name.strip()}({event.subject.id})】发送消息：{message_text_log}")


@bcc.receiver(ActiveFriendMessage)
async def friend_message_speaker(app: Ariadne, event: ActiveFriendMessage):
    core.sent_count += 1
    bot_member = await app.get_bot_profile()
    message_text_log = event.message_chain.display.replace("\n", "\\n").strip()
    logger.info(
        f"【{bot_member.nickname}({app.account})】成功向"
        f"好友【{event.subject.nickname.strip()}({event.subject.id})】发送消息：{message_text_log}")


@bcc.receiver(NudgeEvent)
async def nudged_listener(app: Ariadne, event: NudgeEvent):
    bot_member = await app.get_bot_profile()
    if event.target != app.account or event.supplicant == app.account:
        return
    if event.group_id is None:
        return
    if not (member := await app.get_member(event.group_id, event.supplicant)):
        return
    logger.info(
        f"【{bot_member.nickname}({app.account})】被群【{member.group.name}】中"
        f"成员【{member.name}】({member.id})戳了戳。")


@bcc.receiver(TempMessage)
async def temp_message_listener(app: Ariadne, member: Member, message: MessageChain):
    core.received_count += 1
    bot_member = await app.get_bot_profile()
    message_text_log = message.display.replace("\n", "\\n").strip()
    logger.info(
        f"【{bot_member.nickname}({app.account})】收到群【{member.group.name.strip()}({member.group.id})】"
        f"成员【{member.name.strip()}({member.id})】的临时消息：{message_text_log}")


@bcc.receiver(StrangerMessage)
async def stranger_message_listener(app: Ariadne, stranger: Stranger, message: MessageChain):
    core.received_count += 1
    bot_member = await app.get_bot_profile()
    message_text_log = message.display.replace("\n", "\\n").strip()
    logger.info(
        f"【{bot_member.nickname}({app.account})】收到来自"
        f"陌生人【{stranger.nickname.strip()}({stranger.id})】的消息：{message_text_log})")


@bcc.receiver(AccountLaunch)
async def init():
    await core.initialize()
    await frequency_model.get_frequency_controller().limited()


# BOT加入新群时,进行初始化
@bcc.receiver(BotJoinGroupEvent)
async def init_join_group(app: Ariadne, event: BotJoinGroupEvent):
    await core.init_group(app, event.group)


if __name__ == "__main__":
    if Path.cwd() != Path(__file__).parent:
        logger.critical(f"当前目录非项目所在目录!请进入{str(Path(__file__).parent)}后再运行!")
        exit(0)
    logger.info("正在检测 Mirai 是否启动")
    for fl in range(3):
        try:
            mah = httpx.get(config.mirai_host + "/about", timeout=3)
            if mah.status_code == 200:
                logger.opt(colors=True).info(f'<blue>mah.status_code:{mah.status_code}</blue>')
                logger.opt(colors=True).info(f'<blue>mah.version:{eval(mah.text)["data"]["version"]}</blue>')
                logger.success(f"成功检测到 Mirai !")
                break
            elif fl >= 3:
                logger.critical("启动失败:请检查(mirai是否正常启动)/(mah端口是否被占用)/(mah配置是否与bot配置一致)")
                exit(0)
            else:
                fl += 1
                logger.warning("未检测到 Mirai ，正在重试...")
        except httpx.HTTPError:
            logger.error("Mirai 尚未启动，请检查")
            exit(0)
        except KeyboardInterrupt:
            exit("--已手动退出启动--")
    core.install_modules(Path("modules") / "required")
    core.install_modules(Path("modules") / "self_contained")
    core.launch()
    logger.info("UmaruBot 已关闭")
