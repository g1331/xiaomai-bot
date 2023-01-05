import asyncio
from pathlib import Path
from typing import Union

import yaml
from arclet.alconna import Alconna, CommandMeta
from arclet.alconna.graia import AlconnaDispatcher
from creart import create
from graia.ariadne.app import Ariadne
from graia.ariadne.event.message import GroupMessage, FriendMessage
from graia.ariadne.event.mirai import MemberJoinEvent, MemberLeaveEventQuit
from graia.ariadne.message.chain import MessageChain
from graia.ariadne.message.element import Image, Source
from graia.ariadne.message.parser.twilight import Twilight, UnionMatch, FullMatch, RegexMatch, RegexResult, SpacePolicy, \
    ParamMatch, PRESERVE
from graia.ariadne.model import Group, Friend, Member
from graia.ariadne.util.saya import listen, dispatch, decorate
from graia.broadcast.interrupt import InterruptControl
from graia.saya import Channel, Saya
from graia.saya.builtins.broadcast import ListenerSchema

from core.bot import Umaru
from core.config import GlobalConfig
from core.control import (
    Permission,
    Function,
    FrequencyLimitation,
    Distribute
)
from core.models import saya_model
from utils.UI import *
from utils.waiter import ConfirmWaiter

config = create(GlobalConfig)
core = create(Umaru)
module_controller = saya_model.get_module_data()

saya = Saya.current()
channel = Channel.current()
channel.name("SayaManager")
channel.description("负责插件管理(必须插件)")
channel.author("13")
channel.metadata = module_controller.get_metadata_from_file(Path(__file__))


# >=64可修改当前群的用户权限
@listen(GroupMessage)
@decorate(
    Permission.user_require(Permission.GroupOwner, if_noticed=True),
    Permission.group_require(channel.metadata.level, if_noticed=True),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Distribute.require()
)
@dispatch(Twilight([
    FullMatch("修改权限").space(SpacePolicy.FORCE),
    "group_id" @ ParamMatch(optional=True).space(SpacePolicy.FORCE),
    "member_id" @ ParamMatch().space(SpacePolicy.FORCE),
    "perm" @ UnionMatch("64", "32", "16", "0")
    # 示例: 修改权限 群号 qq 32
]))
async def change_user_perm(
        app: Ariadne, group: Group, sender: Member, message: MessageChain,event:GroupMessage,
        group_id: RegexResult,
        perm: RegexResult,
        member_id: RegexResult,
        source: Source
):
    """
    修改用户权限
    """
    if group_id.matched:
        group_id = int(group_id.result.display)
    else:
        group_id:int = group.id
    try:
        member_id = int(member_id.result.display.replace("@", ""))
    except:
        return await app.send_message(group, MessageChain(
            f"请检查输入的成员qq号"
        ), quote=source)
    try:
        perm = int(perm.result.display)
    except:
        return await app.send_message(group, MessageChain(
            f"请检查输入的权限(64/32/16/0)"
        ), quote=source)
    # 修改其他群组的权限判假
    if group_id != group.id:
        if (user_level := await Permission.get_user_perm(event)) < Permission.Admin:
            return await app.send_message(event.sender.group, MessageChain(
                f"权限不足!(你的权限:{user_level}/需要权限:{perm})"
            ), quote=source)

    if await app.get_member(group_id, member_id) is None:
        await app.send_message(group, MessageChain(
            f"没有找到群成员{member_id}"
        ), quote=message[Source][0])
        return False
    if (Permission.get_user_perm(await app.get_member(group, member_id)) >= 128) and (
            Permission.get_user_perm(sender) < 128):
        await app.send_message(group, MessageChain(
            f"错误!无法将bot管理者降级!"
        ), quote=message[Source][0])
        return False

    # 进行增删改
    path = f'./config/group/{group_id}'
    file_path = f'{path}/perm.yaml'
    if not Path.exists(file_path):
        await app.send_message(group, MessageChain(
            f"请先使用[-perm create group (group_id) <type>]创建权限组"
        ), quote=message[Source][0])
        return False
    with open(file_path, 'r', encoding="utf-8") as file1:
        file_before = yaml.load(file1, Loader=yaml.Loader)
        if file_before is None:
            file_before = {}
        file_before[int(str(member_id).replace("@", ""))] = int(str(level.result))
        with open(file_path, 'w', encoding="utf-8") as file2:
            yaml.dump(file_before, file2, allow_unicode=True)
            await app.send_message(group, MessageChain(
                f"群<{group.id}>设置成员<{str(member_id).replace('@', '')}>权限级<{level.result}>成功"
            ), quote=message[Source][0])
            return True


# 自动删除退群的权限
@channel.use(ListenerSchema(listening_events=[MemberLeaveEventQuit]))
async def auto_del_perm(app: Ariadne, group: Group, member: Member):
    group_id = group.id
    member_id = member.id
    # 进行增删改
    path = f'./config/group/{group_id}'
    file_path = f'{path}/perm.yaml'
    if not Path.exists(file_path):
        return False
    with open(file_path, 'r', encoding="utf-8") as file1:
        file_before = yaml.load(file1, Loader=yaml.Loader)
        if file_before is None:
            file_before = {}
        try:
            file_before.pop(int(str(member_id).replace("@", "")))
        except:
            return False
        with open(file_path, 'w', encoding="utf-8") as file2:
            yaml.dump(file_before, file2, allow_unicode=True)
            await app.send_message(group, MessageChain(
                f"成员{member.name}({member.id})退群,已自动删除其权限"
            ))
            return True


# 查询权限组-当权限>=128时 可以查询其他群的
@channel.use(ListenerSchema(listening_events=[GroupMessage],
                            decorators=[
                                Permission.user_require(Permission.GroupAdmin),
                                Distribute.require()
                            ],
                            inline_dispatchers=[
                                Twilight(
                                    [
                                        FullMatch("-perm list").space(SpacePolicy.PRESERVE)
                                        # 示例: -perm list
                                    ]
                                )
                            ]))
async def perm_list(app: Ariadne, group: Group, message: MessageChain):
    # 进行增删改
    path = f'./config/group/{group.id}'
    file_path = f'{path}/perm.yaml'
    if not os.path.exists(file_path):
        await app.send_message(group, MessageChain(
            f"请先使用[-perm create group (group_id) <type>]创建权限组"
        ), quote=message[Source][0])
        return False
    else:
        with open(file_path, 'r', encoding="utf-8") as file1:
            data = yaml.load(file1, Loader=yaml.Loader)
            if data is None:
                await app.send_message(group, MessageChain(
                    "当前权限组为空!"
                ), quote=message[Source][0])
                return
            level_64 = []
            level_32 = []
            level_else = []
            for key_id in list(data.keys()):
                try:
                    member = await app.get_member(group, int(key_id))
                    if data[key_id] == 64:
                        level_64.append(f"{member.name}({key_id})\n")
                    elif data[key_id] == 32:
                        level_32.append(f"{member.name}({key_id})\n")
                    elif data[key_id] == 16:
                        data.pop(key_id)
                    else:
                        level_else.append(f"{data[key_id]}-{member.name}({key_id})\n")
                except Exception as e:
                    data.pop(key_id)
            with open(file_path, 'w', encoding="utf-8") as file2:
                yaml.dump(data, file2, allow_unicode=True)
        message_send = MessageChain(
            f"64:\n", level_64,
            f"32(共{len(level_32)}人):\n", level_32,
            f"其他:\n" if len(level_else) != 0 else '', level_else if len(level_else) != 0 else ''
        )
        await app.send_message(group, message_send, quote=message[Source][0])
        return True


# 增删bot管理
@channel.use(ListenerSchema(listening_events=[GroupMessage],
                            decorators=[
                                Permission.user_require(Permission.Master),
                                Distribute.require()
                            ],
                            inline_dispatchers=[
                                Twilight(
                                    [
                                        FullMatch("-perm botAdmin").space(SpacePolicy.FORCE),
                                        "action" @ UnionMatch("add", "del").space(SpacePolicy.FORCE),
                                        "member_id" @ ParamMatch().space(SpacePolicy.PRESERVE),
                                        # 示例: -perm botAdmin add
                                    ]
                                )
                            ]))
async def change_botAdmin(app: Ariadne, group: Group, message: MessageChain,
                          action: RegexResult, member_id: RegexResult):
    with open('./config/config.yaml', 'r', encoding="utf-8") as bot_file:
        bot_data = yaml.load(bot_file, Loader=yaml.Loader)
        member_id = int(str(member_id.result).replace("@", ""))
        if str(action.result) == "add":
            if member_id in bot_data["botinfo"]["Admin"]:
                await app.send_message(group, MessageChain(
                    f"{member_id}已经是bot管理员了"
                ), quote=message[Source][0])
                return False
            else:
                bot_data["botinfo"]["Admin"].append(member_id)
                with open('./config/config.yaml', 'w', encoding="utf-8") as bot_file2:
                    yaml.dump(bot_data, bot_file2, allow_unicode=True)
                    await app.send_message(group, MessageChain(
                        f"添加{member_id}为bot管理员成功"
                    ), quote=message[Source][0])
        else:
            if member_id in bot_data["botinfo"]["Admin"]:
                bot_data["botinfo"]["Admin"].remove(member_id)
                with open('./config/config.yaml', 'w', encoding="utf-8") as bot_file2:
                    yaml.dump(bot_data, bot_file2, allow_unicode=True)
                    await app.send_message(group, MessageChain(
                        f"删除{member_id}bot管理员成功"
                    ), quote=message[Source][0])
            else:
                await app.send_message(group, MessageChain(
                    f"{member_id}不是bot管理员"
                ), quote=message[Source][0])
                return False


# 测试权限消息
@channel.use(ListenerSchema(listening_events=[GroupMessage],
                            decorators=[
                                Permission.user_require(Permission.User),
                                Distribute.require()
                            ],
                            inline_dispatchers=[
                                Twilight.from_command("-test perm")
                            ]
                            ))
async def check_perm(app: Ariadne, group: Group, sender: Member, message: MessageChain):
    await app.send_message(group, MessageChain(
        "这是一则测试内容\n"f"你的权限级:{Permission.get_user_perm(sender, group)}\n"
        f"你的群权限:{sender.permission}"
    ), quote=message[Source][0])
