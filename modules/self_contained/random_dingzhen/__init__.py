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
channel.name("Random_Dingzhen")
channel.author("13")
channel.description("发送随机丁真的插件")
channel.metadata = module_controller.get_metadata_from_path(Path(__file__))


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
async def main(app: Ariadne, group: Group, source: Source):
    pic_path = Path(__file__).parent / "imgs"
    if not pic_path.exists():
        return await app.send_message(group, MessageChain(
            "未找到图库"
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
