import os
import random

from PIL import Image
from graia.ariadne.app import Ariadne
from graia.ariadne.event.message import Group, GroupMessage
from graia.ariadne.message.chain import MessageChain
from graia.ariadne.message.element import Image as Graia_Image
from graia.ariadne.message.element import Source
from graia.ariadne.message.parser.twilight import Twilight, FullMatch, PRESERVE, RegexMatch
from graia.saya import Saya, Channel
from graia.saya.builtins.broadcast.schema import ListenerSchema
from loguru import logger

from modules.self_contained.DuoQHandle import DuoQ
from modules.PermManager import Perm
from modules.self_contained.Switch import Switch

saya = Saya.current()
channel = Channel.current()

channel.name("Random_Dingzhen")
channel.author("13")
channel.description("发送随机丁真的插件")


@channel.use(ListenerSchema(listening_events=[GroupMessage],
                            decorators=[Perm.require(16),
                                        Switch.require("随机丁真"),
                                        DuoQ.require()],
                            inline_dispatchers=[
                                Twilight([RegexMatch(r"^(随机|一眼|来[点张])[顶丁钉][真针]|[Dd]ing[！!]?$")])
                            ]))
async def random_dingzhen(app: Ariadne, group: Group, source: Source):
    bqb_path = './modules/Random_Dingzhen/imgs'
    bqb_pic_list = os.listdir(bqb_path)
    pic = random.choice(bqb_pic_list)
    pic_path = f"{bqb_path}/{pic}"
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


@channel.use(ListenerSchema(listening_events=[GroupMessage],
                            decorators=[Perm.require(16),
                                        DuoQ.require()],
                            inline_dispatchers=[
                                Twilight(
                                    [FullMatch("-help 随机丁真").space(PRESERVE)]
                                )
                            ]))
async def bf1_help_xiaobiaoyu(app: Ariadne, group: Group, message: MessageChain):
    await app.send_message(group, MessageChain(
        f"1.发送随机丁真的插件，在群中发送 随机|一眼|来[点张])[顶丁钉][真针] "
    ), quote=message[Source][0])
