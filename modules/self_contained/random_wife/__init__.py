import os
import random
import time
from pathlib import Path

import aiohttp
from creart import create
from graia.ariadne.app import Ariadne
from graia.ariadne.event.message import Group, GroupMessage
from graia.ariadne.message.chain import MessageChain
from graia.ariadne.message.element import Image, Source
from graia.ariadne.message.parser.twilight import Twilight, FullMatch, UnionMatch, SpacePolicy, ElementMatch, \
    ElementResult, ParamMatch, RegexResult
from graia.ariadne.model import Member
from graia.ariadne.util.saya import listen, decorate, dispatch
from graia.saya import Saya, Channel
from loguru import logger

from core.config import GlobalConfig
from core.control import (
    Permission,
    Function,
    FrequencyLimitation,
    Distribute
)
from core.models import saya_model

module_controller = saya_model.get_module_controller()
global_config = create(GlobalConfig)

saya = Saya.current()
channel = Channel.current()
channel.name("RandomWife")
channel.author("13")
channel.description("生成随机老婆图片的插件，在群中发送 -随机<老婆/wife> ")
channel.metadata = module_controller.get_metadata_from_path(Path(__file__))


async def get_wife() -> str:
    wife_list = os.listdir(str(Path(__file__).parent/"wife"))
    wife = random.choice(wife_list)
    return str(Path(__file__).parent/"wife")+f"/{wife}"


@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Permission.user_require(Permission.GroupAdmin, if_noticed=True),
    Permission.group_require(channel.metadata.level, if_noticed=True),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
)
@dispatch(
    Twilight(
        [
            "message" @ UnionMatch("-添加wife").space(SpacePolicy.PRESERVE),
            "wife_name" @ ParamMatch(optional=False).space(SpacePolicy.PRESERVE),
            FullMatch("\n", optional=True),
            "img" @ ElementMatch(Image, optional=False),
        ]
    )
)
async def add_wife(app: Ariadne, group: Group, source: Source,
                   img: ElementResult,
                   wife_name: RegexResult):
    img: Image = img.result
    img_url = img.url
    img_name = wife_name.result.display.replace("\n", '')
    img_type = img.dict()['imageId'][img.dict()['imageId'].rfind(".") + 1:]
    if img_name in ["\n", '']:
        await app.send_message(
            group,
            MessageChain(f"请输入名字!"),
            quote=source
        )
        return
    path = os.listdir(str(Path(__file__).parent/"wife"))
    file_name = f'{path}/{img_name}.{img_type}'
    wife_list = os.listdir(path)
    for item in wife_list:
        if img_name in item:
            await app.send_message(
                group,
                MessageChain(f"{img_name}已存在!"),
                quote=source
            )
            return
    # noinspection PyBroadException
    try:
        fp = open(file_name, 'rb')
        fp.close()
        return file_name
    except Exception as e:
        logger.warning(e)
        i = 0
        while i < 3:
            async with aiohttp.ClientSession() as session:
                # noinspection PyBroadException
                try:
                    async with session.get(img_url, timeout=5, verify_ssl=False) as resp:
                        pic = await resp.read()
                        fp = open(file_name, 'wb')
                        fp.write(pic)
                        fp.close()
                        await app.send_message(
                            group,
                            MessageChain(f"添加成功!"),
                            quote=source
                        )
                        return
                except Exception as e:
                    logger.error(e)
                    i += 1
    await app.send_message(
        group,
        MessageChain(f"添加失败!"),
        quote=source
    )
    return


@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Permission.user_require(Permission.BotAdmin, if_noticed=True),
    Permission.group_require(channel.metadata.level, if_noticed=True),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
)
@dispatch(
    Twilight(
        [
            "message" @ UnionMatch("-删除wife").space(SpacePolicy.PRESERVE),
            "wife_name" @ ParamMatch(optional=False).space(SpacePolicy.PRESERVE),
        ]
    )
)
async def del_wife(app: Ariadne, group: Group, source: Source,
                   wife_name: RegexResult):
    img_name = wife_name.result.display
    path = os.listdir(str(Path(__file__).parent/"wife"))
    wife_list = os.listdir(path)
    for item in wife_list:
        if img_name in item:
            try:
                os.remove(f"{path}/{item}")
                await app.send_message(
                    group,
                    MessageChain(f"删除成功!"),
                    quote=source
                )
                return
            except Exception as e:
                await app.send_message(
                    group,
                    MessageChain(f"删除失败{e}"),
                    quote=source
                )
                return
    await app.send_message(
        group,
        MessageChain(f"没有找到wife{img_name}"),
        quote=source
    )


wife_dict = {
    "wife_path": {
        "owner": {
            "qq": "qq_id",
            "name": "owner_name",
        },
        "wife_name": "wife_name"
    },
}
counter = {
    "qq": [],
    "time": time.time()
}


async def judge(app: Ariadne, sender: Member, wife: str) -> MessageChain:
    global wife_dict, counter
    qq = sender.id
    name = (await app.get_member_profile(sender)).nickname
    wife_name = wife[wife.rfind('/') + 1:wife.rfind('.')]
    # 初始化字典
    if (time.time() - counter.get("time")) >= 60 * 3600 * 24:
        wife_dict = {
        }
        counter = {
            "time": time.time()
        }
    # 初始化老婆
    if wife not in wife_dict:
        wife_dict[wife] = {
            "owner": {
                "qq": None,
                "name": None
            },
            "wife_name": wife[wife.rfind('/') + 1:wife.rfind('.')]
        }
    # 初始化计数器
    if qq not in counter:
        counter[qq] = []
    del_wife_item = None
    for key in wife_dict:
        # 如果有老婆就返回信息
        if wife_dict[key]["owner"]["qq"] == qq:
            if os.path.exists(key):
                return MessageChain(
                    f"你的老婆是{wife_dict[key]['wife_name']}哦~可发送‘-离婚’来取消",
                    Image(path=key)
                )
            else:
                del_wife_item = key
                break
    if del_wife_item:
        wife_dict.pop(del_wife_item)
    # 如果没有老婆(先看wife是否有owner,如果没有则返回wife,有则判断counter(如果counter内没有这个wife则返回你抽到别人的老婆并计数，如果counter内有这个老婆则抢走别人的老婆))
    if wife_dict[wife]["owner"]["qq"] is None:
        wife_dict[wife] = {
            "owner": {
                "qq": qq,
                "name": name
            },
            "wife_name": wife_name
        }
        counter[qq] = []
        return MessageChain(
            f"你的老婆是{wife_name}哦~可发送‘-离婚’来取消",
            Image(path=wife)
        )
    else:
        if wife not in counter[qq]:
            if len(counter[qq]) >= 10:
                counter[qq] = [wife]
            else:
                counter[qq].append(wife)
            return MessageChain(
                f"你抽到了{wife_name},是【{wife_dict[wife]['owner']['name']}】的老婆哦~",
                Image(path=wife)
            )
        if counter[qq].count(wife) >= 2:
            counter[qq] = []
            msg = MessageChain(
                f"你抢走了【{wife_dict[wife]['owner']['name']}】的老婆{wife_name}~",
                Image(path=wife),
                "\n达成成就【NTR】"
            )
            wife_dict[wife] = {
                "owner": {
                    "qq": qq,
                    "name": name
                },
                "wife_name": wife_name
            }
            return msg
    return MessageChain(f"没有抽到老婆哦~")


@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Permission.user_require(Permission.User, if_noticed=True),
    Permission.group_require(channel.metadata.level, if_noticed=True),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module, 3),
)
@dispatch(
    Twilight(
        ["message" @ UnionMatch(
            "-离婚"
        ).space(SpacePolicy.PRESERVE)]
    )
)
async def give_up_wife(app: Ariadne, sender: Member, group: Group, source: Source):
    global wife_dict
    wife_name = None
    wife = None
    for item in wife_dict:
        if wife_dict.get(item).get("owner").get("qq") == sender.id:
            wife_name = item[item.rfind('/') + 1:item.rfind('.')]
            wife = item
    if not wife_name:
        await app.send_message(
            group,
            MessageChain(
                f"你还没有抽到老婆,请先使用'抽老婆'抽一个哦~"
            ),
            quote=source
        )
        return
    if wife_name:
        wife_dict[wife] = {
            "owner": {
                "qq": None,
                "name": None
            },
            "wife_name": wife[wife.rfind('/') + 1:wife.rfind('.')]
        }
        await app.send_message(
            group,
            MessageChain(
                f"你已和{wife_name}离婚了哦~"
            ),
            quote=source
        )
        return


@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Permission.user_require(Permission.User, if_noticed=True),
    Permission.group_require(channel.metadata.level, if_noticed=True),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module, 3),
)
@dispatch(
    Twilight(
        ["message" @ UnionMatch(
            "随机老婆", "随机wife", "抽老婆"
        ).space(SpacePolicy.PRESERVE)]
    )
)
async def random_wife(app: Ariadne, sender: Member, group: Group, source: Source):
    """
    TODO:1.抽到没人要的就建立所属权力 2.抽到别人就返回:你抽到了xxx是xxx的老婆哦~ 3.连续抽到两次别人的wife就变成你的了
    """
    wife_list = os.listdir(str(Path(__file__).parent/"wife"))
    if len(wife_list) != 0:
        wife = await get_wife()
        await app.send_message(
            group,
            await judge(app, sender, wife),
            quote=source
        )
    else:
        await app.send_message(
            group,
            MessageChain("当前没有老婆哦~"),
            quote=source
        )
