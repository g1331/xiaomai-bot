import os
import random
from pathlib import Path

from graia.ariadne.app import Ariadne
from graia.ariadne.event.message import Group, GroupMessage
from graia.ariadne.message.chain import MessageChain
from graia.ariadne.message.element import Image as Graia_Image
from graia.ariadne.message.element import Source
from graia.ariadne.message.parser.twilight import Twilight, RegexMatch
from graia.ariadne.util.saya import decorate, listen, dispatch
from graia.saya import Saya, Channel
from loguru import logger

from core.control import FrequencyLimitation, Permission, Function, Distribute
from core.models import saya_model

module_controller = saya_model.get_module_controller()
saya = Saya.current()
channel = Channel.current()
channel.name("RandomDragon")
channel.author("13")
channel.description("发送随机龙图的插件")
channel.metadata = module_controller.get_metadata_from_path(Path(__file__))


@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    Permission.user_require(Permission.User),
    Permission.group_require(channel.metadata.level),
    FrequencyLimitation.require(channel.module)
)
@dispatch(
    Twilight([RegexMatch(r"^(随机|来[点张])[龙🐉][图]|[Ll]ong[！!]?$")])
)
async def main(app: Ariadne, group: Group, source: Source):
    pic_path = Path(__file__) / "imgs"
    if not pic_path.exists():
        return await app.send_message(group, MessageChain(
            "未找到图库"
        ), quote=source)
    pic_list = os.listdir(pic_path)
    pic = random.choice(pic_list)
    pic_path = f"{pic_path}/{pic}"
    try:
        return await app.send_message(group, MessageChain(
            Graia_Image(path=pic_path)
        ), quote=source)

    except Exception as e:
        logger.error(f"发送{pic}失败")
        logger.error(e)
