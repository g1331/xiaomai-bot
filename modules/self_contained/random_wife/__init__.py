import asyncio
import os
import random
import time
from pathlib import Path

import aiohttp
from creart import create
from graia.ariadne.app import Ariadne
from graia.ariadne.event.message import Group, GroupMessage
from graia.ariadne.message.chain import MessageChain
from graia.ariadne.message.element import Image, Source, At
from graia.ariadne.message.parser.twilight import Twilight, FullMatch, UnionMatch, SpacePolicy, ElementMatch, \
    ElementResult, ParamMatch, RegexResult
from graia.ariadne.model import Member
from graia.ariadne.util.interrupt import FunctionWaiter
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
from core.models import saya_model, response_model

account_controller = response_model.get_acc_controller()
module_controller = saya_model.get_module_controller()
global_config = create(GlobalConfig)

saya = Saya.current()
channel = Channel.current()
channel.name("RandomWife")
channel.author("13")
channel.description("生成随机老婆图片的插件，在群中发送 -随机<老婆/wife> ")
channel.metadata = module_controller.get_metadata_from_path(Path(__file__))


async def get_wife() -> str:
    wife_list = os.listdir(str(Path(__file__).parent / "wife"))
    wife_list = wife_list.remove("__init__.py")
    wife = random.choice(wife_list)
    return str(Path(__file__).parent / "wife") + f"/{wife}"


async def add_wife(file_name: str, img_url: str) -> bool:
    try:
        # 检查文件是否已存在
        with open(file_name, 'rb'):
            return True
    except FileNotFoundError:
        for i in range(3):
            async with aiohttp.ClientSession() as session:
                try:
                    async with session.get(img_url, timeout=5, verify_ssl=False) as resp:
                        # 读取图片数据
                        pic = await resp.read()
                        with open(file_name, 'wb') as fp:
                            fp.write(pic)
                            return True
                except Exception as e:
                    logger.error(e)
                    return False


@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level, if_noticed=True),
    Permission.user_require(Permission.GroupAdmin, if_noticed=True),
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
async def add_wife_handle(app: Ariadne, group: Group, source: Source, sender: Member,
                          img: ElementResult,
                          wife_name: RegexResult):
    img: Image = img.result
    img_url = img.url
    img_name = wife_name.result.display.replace("\n", '')
    img_type = img.dict()['imageId'][img.dict()['imageId'].rfind(".") + 1:]
    if img_name in ["\n", '']:
        return await app.send_message(
            group,
            MessageChain(f"请输入名字!"),
            quote=source
        )
    path = Path(__file__).parent / "wife"
    file_name = str(path / f"{img_name}.{img_type}")
    wife_list = os.listdir(path)
    for item in wife_list:
        if img_name in item:
            return await app.send_message(
                group,
                MessageChain(f"{img_name}已存在!"),
                quote=source
            )

    if await Permission.require_user_perm(group.id, sender.id, Permission.BotAdmin):
        result = await add_wife(file_name, img_url)
        if result:
            return await app.send_message(
                group,
                MessageChain(f"添加成功!"),
                quote=source
            )
        else:
            return await app.send_message(
                group,
                MessageChain(f"添加失败!"),
                quote=source
            )

    target_app, target_group = await account_controller.get_app_from_total_groups(group_id=global_config.test_group)
    if not (target_app and target_group):
        return await app.send_message(group, MessageChain(
            f"发送添加请求失败!"
        ), quote=source)
    else:
        await app.send_group_message(
            group,
            MessageChain(f"您的添加申请已经提交给管理员,审核通过后将会增加到老婆库中!"),
            quote=source
        )

    bot_msg = await app.send_group_message(
        target_group,
        MessageChain(
            f"收到来自群{group.name}({group.id})成员{sender.name}({sender.id})添加老婆{wife_name.result.display}的申请",
            Image(url=img_url),
            f"请在1小时内回复 y 可同意该请求,回复其他消息可拒绝"
        )
    )

    async def waiter(
            waiter_member: Member, waiter_message: MessageChain, waiter_group: Group,
            event_waiter: GroupMessage
    ):
        if waiter_group.id == global_config.test_group and event_waiter.quote and event_waiter.quote.id == bot_msg.id \
                and await Permission.require_user_perm(waiter_group.id, waiter_member.id,
                                                       Permission.GroupAdmin):
            saying = waiter_message.replace(At(app.account), "").display.strip()
            if saying == 'y':
                return True
            else:
                return False

    # 接收回复消息，如果为y则同意，如果不为y则以该消息拒绝
    try:
        return_info = await FunctionWaiter(waiter, [GroupMessage]).wait(timeout=3600)
    except asyncio.exceptions.TimeoutError:
        return await target_app.send_message(
            target_group,
            MessageChain(
                f'注意:由于超时未审核，处理{sender.name}({sender.id})添加老婆{wife_name.result.display}的申请已失效'
            )
        )

    if return_info:
        result = await add_wife(file_name, img_url)
        if result:
            await app.send_group_message(
                group,
                MessageChain(
                    At(sender), f"您添加老婆{wife_name.result.display}的申请已通过!"
                ),
                quote=source
            )
            return await target_app.send_message(
                target_group,
                MessageChain(f'已同意{sender.name}({sender.id})添加老婆{wife_name.result.display}')
            )
        else:
            await app.send_group_message(
                group,
                MessageChain(
                    At(sender), f"您添加老婆{wife_name.result.display}的申请失败了!"
                ),
                quote=source
            )
            return await target_app.send_message(
                target_group,
                MessageChain(f"添加失败!"),
                quote=source
            )
    else:
        await app.send_group_message(
            group,
            MessageChain(
                At(sender), f"您添加老婆{wife_name.result.display}的申请未通过!"
            ),
            quote=source
        )
        return await target_app.send_message(
            target_group,
            MessageChain(f'已拒绝{sender.name}({sender.id})添加老婆{wife_name.result.display}')
        )


@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level, if_noticed=True),
    Permission.user_require(Permission.BotAdmin, if_noticed=True),
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
    path = os.listdir(str(Path(__file__).parent / "wife"))
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
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module, 3),
    Permission.group_require(channel.metadata.level, if_noticed=True),
    Permission.user_require(Permission.User, if_noticed=True),
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
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module, 3),
    Permission.group_require(channel.metadata.level, if_noticed=True),
    Permission.user_require(Permission.User, if_noticed=True),
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
    wife_list = os.listdir(str(Path(__file__).parent / "wife"))
    wife_list = wife_list.remove("__init__.py")
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
