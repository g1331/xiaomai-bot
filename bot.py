import asyncio
import os
import httpx
import yaml
from creart import create
from pathlib import Path
from datetime import time as time_datetime
from graia.ariadne.app import Ariadne
from graia.ariadne.connection.config import config
from graia.ariadne.event.message import ActiveGroupMessage, ActiveFriendMessage
from graia.ariadne.event.mirai import NudgeEvent
from graia.ariadne.message.chain import MessageChain
from graia.ariadne.model import Member, Stranger
from graia.broadcast import Broadcast
from graia.saya import Saya
from graia.saya.builtins.broadcast import BroadcastBehaviour
from graia.scheduler import GraiaScheduler
from launart import Launart
from loguru import logger

LOGPATH = Path("./logs")
LOGPATH.mkdir(exist_ok=True)

true = True
false = False
null = ''

log_related: dict = {
    # 保留时长
    "error_retention": 14,
    "common_retention": 7
}

logger.add(
    Path(os.getcwd()) / "logs" / "{time:YYYY-MM-DD}" / "common.log",
    level="INFO",
    retention=f"{log_related['common_retention']} days",
    encoding="utf-8",
    rotation=time_datetime(),
    compression="tar.xz",
    diagnose=True,
    backtrace=True,
)

logger.add(
    Path(os.getcwd()) / "logs" / "{time:YYYY-MM-DD}" / "error.log",
    level="ERROR",
    retention=f"{log_related['error_retention']} days",
    encoding="utf-8",
    rotation=time_datetime(),
    compression="tar.xz",
    diagnose=True,
    backtrace=True,
)
logs = []


def set_log(log_str: str):
    logs.append(log_str.strip())


logger.add(set_log)
logger.info("bot开始加载咯")

# 读取账号信息
with open('./config/config.yaml', 'r', encoding="utf-8") as bot_file:
    bot_data = yaml.load(bot_file, Loader=yaml.Loader)
    bot_list = bot_data["botinfo"]["bot"]
    verifyKey = bot_data["botinfo"]["verifyKey"]

loop = asyncio.get_event_loop()
saya = create(Saya)
bcc = create(Broadcast)
Ariadne.config(
    launch_manager=Launart(),
    default_account=bot_list[0],
    inject_bypass_listener=True,
)

app_list = []
for bot in bot_list:
    app = Ariadne(
        config(
            bot,
            verifyKey,
        ),
    )
    # 关闭日志记录
    app.log_config.clear()
    app_list.append(app)

saya.install_behaviours(
    Ariadne.create(GraiaScheduler),
    Ariadne.create(BroadcastBehaviour)
)

# )

ignore = ["__init__.py", "__pycache__"]
with saya.module_context():
    for module in os.listdir("modules"):
        if module in ignore:
            continue
        if os.path.isdir(module):
            saya.require(f"modules.{module}")
        else:
            saya.require(f"modules.{module.split('.')[0]}")
    logger.info("saya加载完成")

temp = []


@bcc.receiver("ActiveGroupMessage")
async def group_message_speaker(event: ActiveGroupMessage, _app: Ariadne):
    bot_member = await _app.get_friend(_app.account)
    message_text_log = event.message_chain.display.replace("\n", "\\n").strip()
    if bot_member is not None:
        logger.info(
            f"【{bot_member.nickname}({bot_member.id})】成功向群【{event.subject.name.strip()}({event.subject.id})】发送消息：{message_text_log}")
    else:
        logger.info(
            f"【{_app.account}】成功向群【{event.subject.name.strip()}({event.subject.id})】发送消息：{message_text_log}")


@bcc.receiver("ActiveFriendMessage")
async def friend_message_speaker(event: ActiveFriendMessage, _app: Ariadne):
    bot_member = await _app.get_friend(_app.account)
    message_text_log = event.message_chain.display.replace("\n", "\\n").strip()
    if bot_member is not None:
        logger.info(
            f"【{bot_member.nickname}({bot_member.id})】成功向好友【{event.subject.nickname.strip()}({event.subject.id})】发送消息：{message_text_log}")
    else:
        logger.info(
            f"【{_app.account}】成功向好友【{event.subject.name.strip()}({event.subject.id})】发送消息：{message_text_log}")


@bcc.receiver(NudgeEvent)
async def nudged_listener(_app: Ariadne, event: NudgeEvent):
    bot_member = await _app.get_friend(_app.account)
    if event.target != _app.account or event.supplicant == _app.account:
        return
    if event.group_id is None:
        return
    if not (member := await _app.get_member(event.group_id, event.supplicant)):
        return
    if bot_member is not None:
        logger.info(f"【{bot_member.nickname}({bot_member.id})】被群【{member.group.name}】中成员【{member.name}】戳了戳。")
    else:
        logger.info(f"【{_app.account}】被群【{member.group.name}】中成员【{member.name}】戳了戳。")


@bcc.receiver("TempMessage")
async def temp_message_listener(member: Member, message: MessageChain, _app: Ariadne):
    bot_member = await _app.get_friend(_app.account)
    message_text_log = message.display.replace("\n", "\\n").strip()
    if bot_member is not None:
        logger.info(
            f"【{bot_member.nickname}({bot_member.id})】收到群【{member.group.name.strip()}({member.group.id})】成员【{member.name.strip()}({member.id})】的临时消息：{message_text_log}")
    else:
        logger.info(
            f"【{_app.account}】收到群【{member.group.name.strip()}({member.group.id})】成员【{member.name.strip()}({member.id})】的临时消息：{message_text_log}")


@bcc.receiver("StrangerMessage")
async def stranger_message_listener(stranger: Stranger, message: MessageChain, _app: Ariadne):
    bot_member = await _app.get_friend(_app.account)
    message_text_log = message.display.replace("\n", "\\n").strip()
    if bot_member is not None:
        logger.info(
            f"【{bot_member.nickname}({bot_member.id})】收到来自陌生人【{stranger.nickname.strip()}({stranger.id})】的消息：{message_text_log})")
    else:
        logger.info(
            f"【{_app.account}】收到来自陌生人【{stranger.nickname.strip()}({stranger.id})】的消息：{message_text_log})")


if __name__ == "__main__":
    logger.info("正在检测 MAH 是否启动")
    while True:
        try:
            mah = httpx.get(bot_data["botinfo"]["mah"] + "/about")
            logger.info(f'mah.status_code:{mah.status_code}')
            if mah.status_code == 200:
                # app.launch_blocking()
                Ariadne.launch_blocking()
                # save_config() -工具类的函数
                break
            else:
                logger.critical("MAH 尚未启动，正在重试...")
        except httpx.HTTPError:
            logger.critical("MAH 尚未启动，请检查")
            break
        except KeyboardInterrupt:
            break
