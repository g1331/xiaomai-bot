import os
import random
from pathlib import Path

from PIL import Image
from graia.ariadne.app import Ariadne
from graia.ariadne.event.message import Group, GroupMessage
from graia.ariadne.message.chain import MessageChain
from graia.ariadne.message.element import Image as Graia_Image
from graia.ariadne.message.element import Source
from graia.ariadne.message.parser.twilight import Twilight, RegexMatch
from graia.ariadne.util.saya import listen, decorate, dispatch
from graia.saya import Saya, Channel
from loguru import logger

from core.control import Distribute, Permission, Function, FrequencyLimitation
from core.models import saya_model

module_controller = saya_model.get_module_controller()
saya = Saya.current()
channel = Channel.current()
channel.name("Random_Pic")
channel.author("13")
channel.description("发送随机图的插件")
channel.metadata = module_controller.get_metadata_from_path(Path(__file__))

# 图库映射名
pic_map = {
    "ding": "ding",
    "long": "long",
    "chai": "chai",
    "capoo": "capoo"
}


@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level),
    Permission.user_require(Permission.User),
)
@dispatch(
    Twilight([RegexMatch(r"^(随机|一眼|来[点张])[顶丁钉][真针]|[Dd]ing[！!]?$")])
)
async def random_ding(app: Ariadne, group: Group, source: Source):
    pic_path = Path(__file__).parent / "imgs" / pic_map["ding"]
    if not pic_path.exists():
        return await app.send_message(group, MessageChain(
            f"未找到图库 '{pic_map['ding']}'"
        ), quote=source)
    pic_list = os.listdir(pic_path)
    pic = random.choice(pic_list)
    pic_path = f"{pic_path}/{pic}"
    try:
        im = Image.open(pic_path)
        if im.mode == "RGBA":
            im.load()  # required for png.split()
            background = Image.new("RGB", im.size, (255, 255, 255))
            background.paste(im, mask=im.split()[3])
        save_name = pic_path.replace('webp', 'jpg')
        im.save('{}'.format(save_name), 'JPEG')
        await app.send_message(group, MessageChain(
            Graia_Image(path=save_name)
        ), quote=source)
        return
    except Exception as e:
        logger.error(f"发送{pic}失败")
        logger.error(e)
        return


@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level),
    Permission.user_require(Permission.User),
)
@dispatch(
    Twilight([RegexMatch(r"^(随机|来[点张])[龙][图]|🐉|[Ll]ong[！!]?$")])
)
async def random_long(app: Ariadne, group: Group, source: Source):
    pic_path = Path(__file__).parent / "imgs" / pic_map["long"]
    if not pic_path.exists():
        return await app.send_message(group, MessageChain(
            f"未找到图库 '{pic_map['long']}'"
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


@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level),
    Permission.user_require(Permission.User),
)
@dispatch(
    Twilight([RegexMatch(r"^(随机|来[点张])[柴][郡]|chai[！!]?$")])
)
async def random_chai(app: Ariadne, group: Group, source: Source):
    pic_path = Path(__file__).parent / "imgs" / pic_map["chai"]
    if not pic_path.exists():
        return await app.send_message(group, MessageChain(
            f"未找到图库 '{pic_map['chai']}'"
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


@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level),
    Permission.user_require(Permission.User),
)
@dispatch(
    Twilight([RegexMatch(r"^(随机|来[点张])[咖][波]|capoo[！!]?$")])
)
async def random_capoo(app: Ariadne, group: Group, source: Source):
    pic_path = Path(__file__).parent / "imgs" / pic_map["capoo"]
    if not pic_path.exists():
        return await app.send_message(group, MessageChain(
            f"未找到图库 '{pic_map['capoo']}'"
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
