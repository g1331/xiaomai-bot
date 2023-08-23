import asyncio
import difflib
import json
import os
import random
import time
from datetime import timedelta
from pathlib import Path
from typing import Union

import aiohttp
import zhconv
from PIL import Image as PIL_Image
from PIL import ImageFont, ImageDraw, ImageFilter, ImageEnhance
from creart import create
from graia.ariadne.app import Ariadne
from graia.ariadne.event.message import GroupMessage, FriendMessage
from graia.ariadne.message.chain import MessageChain
from graia.ariadne.message.element import Image as GraiaImage, At
from graia.ariadne.message.element import Source, ForwardNode, Forward
from graia.ariadne.message.parser.twilight import (
    Twilight, FullMatch, ParamMatch, RegexResult, SpacePolicy, MatchResult,
    UnionMatch, WildcardMatch, RegexMatch
)
from graia.ariadne.model import Group, Member, Friend
from graia.ariadne.util.interrupt import FunctionWaiter
from graia.ariadne.util.saya import listen, decorate, dispatch
from graia.saya import Channel, Saya
from graia.scheduler import timers
from graia.scheduler.saya import SchedulerSchema
from loguru import logger

from core.config import GlobalConfig
from core.control import (
    Permission,
    Function,
    FrequencyLimitation,
    Distribute
)
from core.models import saya_model, response_model
from utils.UI import *
from utils.bf1.bf_utils import BF1GROUP, BF1ManagerAccount, get_playerList_byGameid, bf1_perm_check, BF1GROUPPERM, \
    get_personas_by_name, perm_judge, BF1Log, dummy_coroutine, BF1ServerVipManager
from utils.bf1.database import BF1DB
from utils.bf1.default_account import BF1DA
from utils.parse_messagechain import get_targets
from utils.string import generate_random_str
from utils.timeutils import DateTimeUtils
from .api_gateway import refresh_api_client, get_player_stat_data
from .bfgroups_log import rsp_log
from .main_session_auto_refresh import auto_refresh_account
from .map_team_info import MapData
from .utils import getPid_byName, server_playing, app_blocked

module_controller = saya_model.get_module_controller()
account_controller = response_model.get_acc_controller()
global_config = create(GlobalConfig)
saya = Saya.current()
channel = Channel.current()
channel.name("BF1服管")
channel.description("战地1服务器管理插件")
channel.author("13")
channel.metadata = module_controller.get_metadata_from_path(Path(__file__))


#  1.创建群组，增删改查，群组名为唯一标识，且不区分大小写，即若ABC存在,则abc无法创建,
#    群组权限分为为拥有者和管理者,表1:群组表,表2:权限表                              [√]
#  2.群组绑定服务器,搜索服务器信息并绑定gameid和serverid,绑定服管账号pid             [√]
#  3.群组绑定群,绑定后自动添加群主为群组拥有者，群管理员为群组管理者，                 [√]
#  4.添加/删除/修改 BF1群组成员权限,查询群组权限信息                               [√]
#  5.服管账号，增删改查，登录                                                   [√]
#  6.踢人，日志记录                                                           [√]
#  7.封禁，日志记录                                                           [√]
#  8.解封，日志记录                                                           [√]
#  9.banall，日志记录                                                        [√]
#  10.unbanall，日志记录                                                     [√]
#  11.换边，日志记录                                                         [√]
#  12.换图，日志记录                                                         [√]
#  13.vip，日志记录                                                         [√]

# TODO:
#  14.群组操作日志查询
#  15.服务器配置修改，日志记录
#  16.玩家列表pic版重构
#  17.Vban重构 (?真的有人在用么(


# 创建bf群组
@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level),
    Permission.user_require(Permission.BotAdmin, if_noticed=True),
)
@dispatch(
    Twilight(
        [
            UnionMatch("-bf群组", "-bfg").space(SpacePolicy.FORCE),
            UnionMatch("新建", "new", "删除", "del", "信息", "info").space(SpacePolicy.FORCE) @ "action",
            ParamMatch(optional=True) @ "group_name"
        ]
    )
)
async def bfgroup_manager(app: Ariadne, group: Group, group_name: RegexResult, source: Source, action: RegexResult):
    if not group_name.result:
        return await app.send_message(group, MessageChain(
            "请输入bf群组名称"
        ), quote=source)
    group_name = group_name.result.display
    action = action.result.display
    if action in ["信息", "info"]:
        result = await BF1GROUP.get_info(group_name)
        if isinstance(result, str):
            return await app.send_message(group, MessageChain(result), quote=source)
        id_info = [f"群组{group_name}信息:"]
        for id_item in result["bind_ids"]:
            if not id_item:
                continue
            id_info.extend(
                (
                    f"{result['bind_ids'].index(id_item) + 1}.GameID:{id_item['gameId']}",
                    f"ServerID:{id_item['serverId']}",
                    f"Guid:{id_item['guid']}",
                )
            )
            if id_item['account']:
                account_info = await BF1DB.bf1account.get_bf1account_by_pid(int(id_item['account']))
                display_name = account_info.get("displayName") if account_info else ""
                id_info.append(f"服管账号:{display_name}({id_item['account']})")
            else:
                id_info.append("服管账号:未绑定")
            id_info.append("=" * 20)
        if len(id_info) == 1:
            return await app.send_message(group, MessageChain(f"群组[{group_name}]信息为空!请绑定服务器!"), quote=source)
        result = "\n".join(id_info)
        return await app.send_message(group, MessageChain(result), quote=source)
    elif action in ["删除", "del"]:
        result = await BF1GROUP.delete(group_name)
        return await app.send_message(group, MessageChain(result), quote=source)
    elif action in ["新建", "new"]:
        result = await BF1GROUP.create(group_name)
        return await app.send_message(group, MessageChain(result), quote=source)


@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level),
    Permission.user_require(Permission.BotAdmin, if_noticed=True),
)
@dispatch(
    Twilight(
        [
            UnionMatch("-bf群组", "-bfg").space(SpacePolicy.FORCE),
            UnionMatch("改名", "rename").space(SpacePolicy.FORCE),
            ParamMatch().space(SpacePolicy.FORCE) @ "group_name",
            ParamMatch() @ "new_name",
        ]
    )
)
async def bfgroup_rename(app: Ariadne, group: Group, group_name: RegexResult, new_name: RegexResult, source: Source):
    group_name = group_name.result.display
    new_name = new_name.result.display
    result = await BF1GROUP.rename(group_name, new_name)
    return await app.send_message(group, MessageChain(result), quote=source)


# bf群组名单
@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level),
    Permission.user_require(Permission.BotAdmin, if_noticed=True),
)
@dispatch(
    Twilight(
        [
            UnionMatch("-bf群组列表", "-bfgl")
        ]
    )
)
async def bfgroup_list_info(app: Ariadne, group: Group, source: Source):
    bf1_group_info = await BF1DB.bf1group.get_all_bf1_group_info()
    if not bf1_group_info:
        return await app.send_message(group, MessageChain("当前没有BF1群组"), quote=source)
    result = [f"当前共{len(bf1_group_info)}个群组:"]
    group_names = [group_info['group_name'] for group_info in bf1_group_info]
    group_count = len(group_names)
    line_count = group_count // 4

    for i in range(line_count):
        group_line = " ".join(group_names[i * 4:(i + 1) * 4])
        result.append(group_line)

    if group_count % 4 != 0:
        remaining_group_line = " ".join(group_names[line_count * 4:])
        result.append(remaining_group_line)

    result = "\n".join(result)
    return await app.send_message(group, MessageChain(result), quote=source)


# 2:服务器绑定 增删改查

# 群组绑服服务器-增改
@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level),
    Permission.user_require(Permission.BotAdmin, if_noticed=True),
)
@dispatch(
    Twilight(
        [
            UnionMatch("-bf群组", "-bfg").space(SpacePolicy.PRESERVE),
            ParamMatch(optional=False).space(SpacePolicy.FORCE) @ "group_name",
            UnionMatch("绑服#", "bind#").space(SpacePolicy.NOSPACE),
            ParamMatch(optional=False).space(SpacePolicy.FORCE) @ "server_rank",
            ParamMatch(optional=False).space(SpacePolicy.PRESERVE) @ "server_gameid",
            # 示例: -bf群组 skl 绑服#1 gameid
        ]
    )
)
async def bf1group_bind_server(
        app: Ariadne, group: Group,
        group_name: RegexResult, server_rank: RegexResult,
        server_gameid: RegexResult, source: Source
):
    group_name = group_name.result.display
    server_gameid = server_gameid.result.display
    if not server_rank.result.display.isdigit():
        return
    server_rank = int(server_rank.result.display)
    if server_rank < 1 or server_rank > 30:
        return await app.send_message(group, MessageChain(
            "服务器序号只能在1~30内"
        ), quote=source)
    # 检查是否有bf群组
    if not await BF1DB.bf1group.check_bf1_group(group_name):
        return await app.send_message(group, MessageChain(
            f"bf群组[{group_name}]不存在"
        ), quote=source)

    # 检查gameId是否正确
    server_info = await (await BF1DA.get_api_instance()).getFullServerDetails(server_gameid)
    if isinstance(server_info, str):
        return await app.send_message(
            group,
            MessageChain(f"查询出错!{server_info}"),
            quote=source
        )
    server_info = server_info["result"]
    gameId = server_info.get("serverInfo").get("gameId")
    guid = server_info.get("serverInfo").get("guid")
    ServerId = server_info.get("rspInfo").get('server').get('serverId')

    # 获取群组信息,遍历检查guid是否已经绑定过了
    # group_info = await BF1DB.bf1group.get_bf1_group_info(group_name)
    # 感觉检测重复绑定比较多余
    # if group_info:
    #     for server in group_info["bind_ids"]:
    #         if server and server["guid"] == guid and server["gameId"] == gameId:
    #             return await app.send_message(
    #                 group,
    #                 MessageChain(f"群组[{group_name}]已经绑定过该服务器在序号{group_info['bind_ids'].index(server) + 1}"),
    #                 quote=source
    #             )

    # 获取管理pid列表，如果服管账号pid在里面则绑定
    admin_list = [f"{item['personaId']}" for item in server_info["rspInfo"]["adminList"]]
    admin_list.append(f"{server_info['rspInfo']['owner']['personaId']}")
    # 获取服管账号列表
    account_list = await BF1ManagerAccount.get_accounts()
    account_pid_list = [f"{account['pid']}" for account in account_list]
    # 获取绑定的服管账号
    bind_account = list(set(admin_list) & set(account_pid_list))
    manager_account = bind_account[0] if bind_account else None

    # 绑定
    result = await BF1GROUP.bind_ids(
        group_name, server_rank, guid, gameId, ServerId, manager_account
    )
    return await app.send_message(group, MessageChain(result), quote=source)


# 群组解绑服务器
@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level),
    Permission.user_require(Permission.BotAdmin, if_noticed=True),
)
@dispatch(
    Twilight(
        [
            UnionMatch("-bf群组", "-bfg").space(SpacePolicy.PRESERVE),
            ParamMatch(optional=False).space(SpacePolicy.FORCE) @ "group_name",
            UnionMatch("解绑#").space(SpacePolicy.NOSPACE),
            ParamMatch(optional=False).space(SpacePolicy.PRESERVE) @ "server_rank"
            # 示例: -bf群组 skl 解绑#1
        ]
    )
)
async def bf1group_unbind_server(
        app: Ariadne, group: Group,
        group_name: RegexResult, server_rank: RegexResult, source: Source
):
    group_name = group_name.result.display
    if not server_rank.result.display.isdigit():
        return await app.send_message(group, MessageChain(
            "服务器序号只能为数字\n例: -bf群组 sakula 解绑#1"
        ), quote=source)
    server_rank = int(server_rank.result.display)
    if server_rank < 1 or server_rank > 30:
        return await app.send_message(group, MessageChain(
            "服务器序号只能在1~30内"
        ), quote=source)
    # 检查是否有bf群组
    if not await BF1DB.bf1group.check_bf1_group(group_name):
        return await app.send_message(group, MessageChain(
            f"bf群组[{group_name}]不存在"
        ), quote=source)

    if not await BF1GROUP.get_bindInfo_byIndex(group_name, server_rank - 1):
        return await app.send_message(group, MessageChain(
            f"bf群组[{group_name}]未绑定服务器{server_rank}"
        ), quote=source)

    result = await BF1GROUP.unbind_ids(group_name, server_rank)
    return await app.send_message(group, MessageChain(result), quote=source)


# ======================================================================================================================
# TODO: vban重构
#
# # 群组创建vban
# @listen(GroupMessage)
# @decorate(
#     Distribute.require(),
#     Function.require(channel.module),
#     FrequencyLimitation.require(channel.module),
#     Permission.group_require(channel.metadata.level),
#     Permission.user_require(Permission.BotAdmin, if_noticed=True),
# )
# @dispatch(
#     Twilight(
#         [
#             UnionMatch("-bf群组", "-bfg").space(SpacePolicy.PRESERVE),
#             "group_name" @ ParamMatch(optional=False).space(SpacePolicy.FORCE),
#             FullMatch("创建vban#").space(SpacePolicy.NOSPACE),
#             "vban_rank" @ ParamMatch(optional=False).space(SpacePolicy.PRESERVE),
#             # 示例: -bf群组 skl 创建vban
#         ]
#     )
# )
# async def bfgroup_create_vban(
#         app: Ariadne, group: Group,
#         group_name: RegexResult, vban_rank: RegexResult, source: Source
# ):
#     group_name = str(group_name.result)
#     # 检查是否有bf群组
#     group_path = f"./data/battlefield/binds/bfgroups/{group_name}"
#     if not os.path.exists(group_path):
#         await app.send_message(group, MessageChain(
#             f"群组{group_name}不存在"
#         ), quote=source)
#         return False
#     try:
#         vban_rank = int(str(vban_rank.result))
#         if vban_rank < 1 or vban_rank > 10:
#             raise Exception
#         if vban_rank == 1:
#             vban_rank = ''
#     except:
#         await app.send_message(group, MessageChain(
#             "请检查vban序号:1~10"
#         ), quote=source)
#         return False
#     # 是否有vban的文件
#     vban_file_path = f'./data/battlefield/binds/bfgroups/{group_name}/vban{vban_rank}.json'
#     if os.path.isfile(vban_file_path):
#         await app.send_message(group, MessageChain(
#             "vban配置已存在,请勿重复创建"
#         ), quote=source)
#         return False
#     else:
#         open(f'./data/battlefield/binds/bfgroups/{group_name}/vban{vban_rank}.json', 'w', encoding="utf-8")
#         await app.send_message(group, MessageChain(
#             f"群组{group_name}创建vban配置文件成功,请手动配置groupid和token"
#         ), quote=source)
#         return True
#
#
# # 群组查询vban
# @listen(GroupMessage)
# @decorate(
#     Distribute.require(),
#     Function.require(channel.module),
#     FrequencyLimitation.require(channel.module),
#     Permission.group_require(channel.metadata.level),
#     Permission.user_require(Permission.GroupAdmin, if_noticed=True),
# )
# @dispatch(
#     Twilight(
#         [
#             UnionMatch("-bf群组", "-bfg").space(SpacePolicy.PRESERVE),
#             "group_name" @ ParamMatch(optional=False).space(SpacePolicy.FORCE),
#             FullMatch("vban信息").space(SpacePolicy.PRESERVE),
#             # 示例: -bf群组 skl vban信息
#         ]
#     )
# )
# async def bfgroup_get_vban(
#         app: Ariadne, group: Group,
#         group_name: RegexResult, source: Source
# ):
#     group_name = str(group_name.result)
#     # 检查是否有bf群组
#     group_path = f"./data/battlefield/binds/bfgroups/{group_name}"
#     if not os.path.exists(group_path):
#         await app.send_message(group, MessageChain(
#             f"群组{group_name}不存在"
#         ), quote=source)
#         return False
#     send_temp = []
#     # 是否有vban的文件
#     vban_file_path = f'./data/battlefield/binds/bfgroups/{group_name}'
#     file_list = os.listdir(vban_file_path)
#     for file in file_list:
#         if "vban" in file:
#             with open(f"{vban_file_path}/{file}", 'r', encoding='utf-8') as file1:
#                 try:
#                     data = json.load(file1)["groupid"]
#                     send_temp.append(f"{data}\n")
#                 except:
#                     await app.send_message(group, MessageChain(
#                         f"群组{group_name}vban信息为空!"
#                     ), quote=source)
#                     return False
#     if len(send_temp) == 0:
#         await app.send_message(group, MessageChain(
#             f"群组{group_name}没有找到vban信息"
#         ), quote=source)
#         return True
#     else:
#         await app.send_message(group, MessageChain(
#             f"群组{group_name}vban有:\n", send_temp
#         ), quote=source)
#         return True
#
#
# # 群组删除vban
# @listen(GroupMessage)
# @decorate(
#     Distribute.require(),
#     Function.require(channel.module),
#     FrequencyLimitation.require(channel.module),
#     Permission.group_require(channel.metadata.level),
#     Permission.user_require(Permission.BotAdmin, if_noticed=True),
# )
# @dispatch(
#     Twilight(
#         [
#             UnionMatch("-bf群组", "-bfg").space(SpacePolicy.PRESERVE),
#             "group_name" @ ParamMatch(optional=False).space(SpacePolicy.FORCE),
#             FullMatch("删除vban#").space(SpacePolicy.NOSPACE),
#             "vban_rank" @ ParamMatch(optional=False).space(SpacePolicy.PRESERVE),
#             # 示例: -bf群组 skl 删除vban#1
#         ]
#     )
# )
# async def bfgroup_del_vban(
#         app: Ariadne, group: Group,
#         group_name: RegexResult, vban_rank: RegexResult, source: Source
# ):
#     group_name = str(group_name.result)
#     # 检查是否有bf群组
#     group_path = f"./data/battlefield/binds/bfgroups/{group_name}"
#     if not os.path.exists(group_path):
#         await app.send_message(group, MessageChain(
#             f"群组{group_name}不存在"
#         ), quote=source)
#         return False
#     try:
#         vban_rank = int(str(vban_rank.result))
#         if vban_rank < 1 or vban_rank > 10:
#             raise Exception
#         if vban_rank == 1:
#             vban_rank = ''
#     except:
#         await app.send_message(group, MessageChain(
#             "请检查vban序号:1~10"
#         ), quote=source)
#         return False
#     # 是否有vban的文件
#     vban_file_path = f'./data/battlefield/binds/bfgroups/{group_name}/vban{vban_rank}.json'
#     if not os.path.isfile(vban_file_path):
#         await app.send_message(group, MessageChain(
#             f"vban{vban_rank}配置不存在!"
#         ), quote=source)
#         return False
#     else:
#         os.remove(vban_file_path)
#         await app.send_message(group, MessageChain(
#             f"群组{group_name}删除vban{vban_rank}成功!"
#         ), quote=source)
#         return True
#
#
# # 配置vban的群组id和token
# @listen(GroupMessage, FriendMessage)
# @decorate(
#     Distribute.require(),
#     Function.require(channel.module),
#     FrequencyLimitation.require(channel.module),
#     Permission.group_require(channel.metadata.level),
#     Permission.user_require(Permission.BotAdmin, if_noticed=True),
# )
# @dispatch(
#     Twilight(
#         [
#             UnionMatch("-bf群组", "-bfg").space(SpacePolicy.FORCE),
#             "group_name" @ ParamMatch(optional=False).space(SpacePolicy.FORCE),
#             FullMatch("配置vban#").space(SpacePolicy.NOSPACE),
#             "vban_rank" @ ParamMatch(optional=False).space(SpacePolicy.FORCE),
#             FullMatch("gid=").space(SpacePolicy.NOSPACE),
#             "group_id" @ ParamMatch(optional=False).space(SpacePolicy.NOSPACE),
#             FullMatch(",token=").space(SpacePolicy.NOSPACE),
#             "token" @ ParamMatch(optional=False).space(SpacePolicy.PRESERVE),
#             # 示例: -bf群组 skl 配置vban#n gid=xxx,token=xxx
#         ]
#     )
# )
# async def bfgroup_config_vban(
#         app: Ariadne, group: Group,
#         group_name: RegexResult, group_id: RegexResult,
#         token: RegexResult, vban_rank: RegexResult, source: Source
# ):
#     group_name = str(group_name.result)
#     # 检查是否有bf群组
#     group_path = f"./data/battlefield/binds/bfgroups/{group_name}"
#     if not os.path.exists(group_path):
#         await app.send_message(group, MessageChain(
#             f"群组{group_name}不存在"
#         ), quote=source)
#         return False
#     try:
#         vban_rank = int(str(vban_rank.result))
#         if vban_rank < 1 or vban_rank > 10:
#             raise Exception
#         if vban_rank == 1:
#             vban_rank = ''
#     except:
#         await app.send_message(group, MessageChain(
#             "请检查vban序号:1~10"
#         ), quote=source)
#         return False
#     # 是否有vban的文件
#     vban_file_path = f'./data/battlefield/binds/bfgroups/{group_name}/vban{vban_rank}.json'
#     if not os.path.isfile(vban_file_path):
#         await app.send_message(group, MessageChain(
#             f"没有找到群组vban{vban_rank}文件,请先为群组创建vban{vban_rank}"
#         ), quote=source)
#         return False
#     # 有的话就写入数据
#     else:
#         data = {
#             "groupid": group_id.result.display.replace("\n", ""),
#             "token": token.result.display.replace("\n", "")
#         }
#         with open(vban_file_path, 'w', encoding="utf-8") as file1:
#             json.dump(data, file1, indent=4)
#             await app.send_message(group, MessageChain(
#                 f"群组{group_name}写入vban{vban_rank}配置成功!"
#             ), quote=source)
#             return True


# ======================================================================================================================

# qq群绑定群组
@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level),
    Permission.user_require(Permission.BotAdmin, if_noticed=True),
)
@dispatch(
    Twilight(
        [
            UnionMatch("-bf群组", "-bfg").space(SpacePolicy.PRESERVE),
            ParamMatch(optional=False).space(SpacePolicy.FORCE) @ "group_name",
            FullMatch("绑群").space(SpacePolicy.PRESERVE),
            ParamMatch(optional=False).space(SpacePolicy.PRESERVE) @ "qqgroup_id",
            # 示例: -bf群组 skl 绑群 123
        ]
    )
)
async def bfgroup_bind_qqgroup(
        app: Ariadne, group: Group, source: Source,
        group_name: RegexResult, qqgroup_id: RegexResult
):
    group_name = group_name.result.display
    qqgroup_id = qqgroup_id.result.display
    if not qqgroup_id.isdigit():
        return await app.send_message(group, MessageChain(
            "QQ群号必须是数字!"
        ), quote=source)
    qqgroup_id = int(qqgroup_id)
    target_app, target_group = await account_controller.get_app_from_total_groups(qqgroup_id)
    if not (target_app and target_group):
        return await app.send_message(group, MessageChain(
            f"没有找到目标群:{qqgroup_id}"
        ), quote=source)
    # 绑定群组
    result = await BF1GROUP.bind_qq_group(group_name, qqgroup_id)
    # 绑定权限组
    perm_result = await BF1GROUPPERM.bind_group(group_name, qqgroup_id)
    # 自动添加群主为拥有着 1
    # 自动添加群管为管理员 0
    member_list = await target_app.get_member_list(target_group)
    for member in member_list:
        member: Member
        if member.permission.name == "Owner":
            await BF1GROUPPERM.add_permission(group_name, member.id, 1)
        elif member.permission.name == "Administrator":
            await BF1GROUPPERM.add_permission(group_name, member.id, 0)
    return await app.send_message(
        group,
        MessageChain(f"{result}\n权限组绑定成功" if perm_result else "权限组绑定失败!"),
        quote=source,
    )


@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level),
)
@dispatch(
    Twilight(
        [
            UnionMatch("-bf群组", "-bfg").space(SpacePolicy.PRESERVE),
            ParamMatch(optional=False).space(SpacePolicy.FORCE) @ "group_name",
            UnionMatch("aa", "ao", "del").space(SpacePolicy.FORCE) @ "action",
            WildcardMatch() @ "qq_id"
            # 示例: -bf群组 skl aa 123
        ]
    )
)
async def bfgroup_change_perm(
        app: Ariadne, group: Group, source: Source, member: Member,
        action: RegexResult, qq_id: RegexResult, group_name: RegexResult
):
    group_name = group_name.result.display
    # 检查是否有bf群组
    if not await BF1DB.bf1group.check_bf1_group(group_name):
        return await app.send_message(group, MessageChain(
            f"bf群组[{group_name}]不存在"
        ), quote=source)
    action = action.result.display
    action_perm = await BF1GROUPPERM.get_permission(group_name, member.id)
    group_perm = await Permission.get_user_perm_byID(group.id, member.id)
    if ((not action_perm) or (action_perm == 0)) and (group_perm < Permission.BotAdmin):
        return await app.send_message(group, MessageChain(
            "你没有权限执行此操作!"
        ), quote=source)
    targets = get_targets(qq_id.result)
    error_targets = []
    for qq in targets:
        if action == "aa":
            if await BF1GROUPPERM.get_permission(group_name, qq) == 0:
                error_targets.append((qq, "已经是管理员了"))
                continue
            if not await BF1GROUPPERM.add_permission(group_name, qq, 0):
                error_targets.append((qq, "添加失败"))
        elif action == "ao":
            if await BF1GROUPPERM.get_permission(group_name, qq) == 1:
                error_targets.append((qq, "已经是服主了"))
                continue
            if not await BF1GROUPPERM.add_permission(group_name, qq, 1):
                error_targets.append((qq, "添加失败"))
        elif action == "del":
            if await BF1GROUPPERM.get_permission(group_name, qq) is None:
                error_targets.append((qq, "非群组成员"))
                continue
            if not await BF1GROUPPERM.del_permission(group_name, qq):
                error_targets.append((qq, "删除失败"))
    response_text = f"共解析{len(targets)}个目标\n其中{len(targets) - len(error_targets)}个执行成功,{len(error_targets)}个失败"
    if error_targets:
        response_text += "\n\n失败目标:"
        for i in error_targets:
            response_text += f"\n{i[0]}-{i[1]}"
    return await app.send_message(group, response_text, quote=source)


@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level),
)
@dispatch(
    Twilight(
        [
            UnionMatch("-bf群组", "-bfg").space(SpacePolicy.PRESERVE),
            ParamMatch(optional=False).space(SpacePolicy.FORCE) @ "group_name",
            UnionMatch("权限列表", "permlist").space(SpacePolicy.PRESERVE),
            # 示例: -bf群组 skl 权限列表
        ]
    )
)
async def bfgroup_perm_list(
        app: Ariadne, group: Group, source: Source, group_name: RegexResult
):
    group_name = group_name.result.display
    # 检查是否有bf群组
    if not await BF1DB.bf1group.check_bf1_group(group_name):
        return await app.send_message(group, MessageChain(
            f"bf群组[{group_name}]不存在"
        ), quote=source)
    perminfo = await BF1GROUPPERM.get_permission_group(group_name)
    if not perminfo:
        return await app.send_message(group, MessageChain(
            f"bf群组[{group_name}]权限列表为空"
        ), quote=source)
    result = [f"群组[{group_name}]权限列表({len(perminfo.keys())}):"]
    owner = [f"服主:({len([i for i in perminfo if perminfo[i] == 1])})"]
    admin = [f"管理员:({len([i for i in perminfo if perminfo[i] == 0])})"]
    for qq in perminfo:
        if perminfo[qq] == 1:
            owner.append(f" {qq}")
        elif perminfo[qq] == 0:
            admin.append(f" {qq}")
    result = result + owner + admin
    return await app.send_message(group, MessageChain(
        "\n".join(result)
    ), quote=source)


# TODO 通过bf1_server表自动更新gameid


# 绑定过群组的群-查服务器
@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level),
    Permission.user_require(Permission.User, if_noticed=True),
)
@dispatch(
    Twilight(
        [
            UnionMatch("-服务器", "-fwq", "-FWQ", "-服", "-f", "-狐务器", "-负无穷")
            # 示例: -服务器
        ]
    )
)
async def check_server(app: Ariadne, group: Group, source: Source):
    # 获取绑定的群组
    bf1_group_info = await BF1GROUP.get_bf1Group_byQQ(group.id)
    if not bf1_group_info:
        return await app.send_message(group, MessageChain(
            "请先绑定BF1群组"
        ), quote=source)
    bfgroups_name = bf1_group_info["group_name"]
    server_list = [i["gameId"] if i else None for i in bf1_group_info["bind_ids"]]
    # 并发查找
    tasks = [(await BF1DA.get_api_instance()).getFullServerDetails(gameid) for gameid in server_list if gameid]
    tasks = asyncio.gather(*tasks)
    try:
        tasks = await tasks
        logger.info(f"查询{bfgroups_name}服务器ing")
    except Exception as e:
        logger.error(f"查询{bfgroups_name}服务器失败{e}")
        await app.send_message(group, MessageChain(
            GraiaImage(path='./data/bqb/狐务器无响应.jpg')
        ), quote=source)
        return False
    result = [f"所属群组:{bfgroups_name}\n" + "=" * 18]
    servers = 0
    for server_info in tasks:
        if isinstance(server_info, dict):
            server_info = server_info.get("result").get("serverInfo")
            result.append(f'\n{server_list.index(server_info["gameId"]) + 1}#:{server_info["name"][:20]}\n')
            人数 = f'人数:{server_info["slots"]["Soldier"]["current"]}/{server_info["slots"]["Soldier"]["max"]}[{server_info["slots"]["Queue"]["current"]}]({server_info["slots"]["Spectator"]["current"]})'
            result.extend(
                (
                    人数,
                    f"  收藏:{server_info['serverBookmarkCount']}\n",
                    f'地图:{server_info["mapModePretty"]}-{server_info["mapNamePretty"]}\n'.replace(
                        "流血", "流\u200b血"
                    ).replace("战争", "战\u200b争"),
                    "=" * 18,
                )
            )
            servers += 1
        # result.append(f"\n{server_list.index(server_info) + 1}#:{server_info}")
    if len(result) == 1:
        pic_path = Path("./data/bqb/狐务器无响应.jpg")
        if pic_path.exists():
            return await app.send_message(group, MessageChain(
                GraiaImage(path='./data/bqb/狐务器无响应.jpg')
            ), quote=source)
        else:
            return await app.send_message(group, MessageChain(
                "服务器无响应!"
            ), quote=source)
    result.append(f"\n({generate_random_str(20)})")

    server_list_column = [
        ColumnTitle(title=f"所属群组:{bfgroups_name}"),
        ColumnTitle(title="可使用-f#n获取服务器详细信息"),
    ]
    for index, server_info in enumerate(tasks):
        if not isinstance(server_info, dict):
            continue
        server_info = server_info.get("result").get("serverInfo")
        server_list_column.append(
            ColumnUserInfo(
                name=f"{index + 1}:{server_info['name'][:15]}",
                description=f"{server_info['name']}",
                avatar=server_info["mapImageUrl"].replace("[BB_PREFIX]",
                                                          "https://eaassets-a.akamaihd.net/battlelog/battlebinary")
            )
        )
        server_list_column.append(
            ColumnList(
                rows=[
                    ColumnListItem(
                        subtitle=f"当前人数："
                                 f'{server_info["slots"]["Soldier"]["current"]}/{server_info["slots"]["Soldier"]["max"]}'
                                 f'[{server_info["slots"]["Queue"]["current"]}]'
                                 f'({server_info["slots"]["Spectator"]["current"]})'
                    ),
                    ColumnListItem(
                        subtitle=f"地图模式：{server_info['mapNamePretty']}--{server_info['mapModePretty']}"
                    ),
                    ColumnListItem(
                        subtitle=f"当前收藏：{server_info['serverBookmarkCount']}"
                    )
                ]
            )
        )
    server_list_column = [Column(elements=server_list_column[i: i + 6]) for i in range(0, len(server_list_column), 6)]
    if await app_blocked(app.account) or servers > 5:
        return await app.send_message(
            group,
            MessageChain(
                GraiaImage(data_bytes=await OneMockUI.gen(
                    GenForm(columns=server_list_column, color_type=get_color_type_follow_time())
                ))
            ),
            quote=source)

    return await app.send_message(group, MessageChain(
        result
    ), quote=source)


@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level),
    Permission.user_require(Permission.User, if_noticed=True),
)
@dispatch(
    Twilight(
        [
            UnionMatch("-服务器", "-fwq", "-FWQ", "-服", "-f", "-狐务器", "-负无穷").space(SpacePolicy.PRESERVE),
            ParamMatch(optional=True).space(SpacePolicy.NOSPACE) @ "bf_group_name",
            ParamMatch(optional=False) @ "server_index",
            # 示例: -服务器#1
        ]
    )
)
async def check_server_by_index(
        app: Ariadne, group: Group, source: Source,
        server_index: RegexResult, bf_group_name: RegexResult
):
    # 服务器序号检查
    server_index = server_index.result.display
    if not server_index.isdigit():
        return await app.send_message(group, MessageChain(
            "请输入正确的服务器序号"
        ), quote=source)
    server_index = int(server_index)
    if server_index < 1 or server_index > 30:
        return await app.send_message(group, MessageChain(
            "服务器序号只能在1~30内"
        ), quote=source)

    # 获取群组信息
    bf_group_name = bf_group_name.result.display if bf_group_name.matched else None
    if not bf_group_name:
        bf1_group_info = await BF1GROUP.get_bf1Group_byQQ(group.id)
        if not bf1_group_info:
            return await app.send_message(group, MessageChain(
                "请先绑定BF1群组/指定群组名"
            ), quote=source)
        bf_group_name = bf1_group_info.get("group_name")
    server_info = await BF1GROUP.get_bindInfo_byIndex(bf_group_name, server_index)
    if not server_info:
        return await app.send_message(group, MessageChain(
            f"群组[{bf_group_name}]未绑定服务器{server_index}"
        ), quote=source)
    elif isinstance(server_info, str):
        return await app.send_message(group, MessageChain(server_info), quote=source)

    game_id = server_info.get("gameId")

    # 调用接口获取数据
    server_info = await (await BF1DA.get_api_instance()).getFullServerDetails(game_id)
    if isinstance(server_info, str):
        return await app.send_message(
            group,
            MessageChain(f"查询出错!{server_info}"),
            quote=source
        )
    server_info = server_info["result"]

    # 处理数据
    # 第一部分为serverInfo,其下:包含服务器名、简介、人数、地图、模式、gameId、guid、收藏数serverBookmarkCount
    # 第二部分为rspInfo,其下包含owner（名字和pid）、serverId、createdDate、expirationDate、updatedDate
    # 第三部分为platoonInfo，其下包含战队名、tag、人数、description
    result = [f"所属群组: {bf_group_name} -- {server_index}#\n" + "=" * 18]
    Info = server_info["serverInfo"]
    result.append(
        f"服务器名: {Info.get('name')}\n"
        f"人数: {Info.get('slots').get('Soldier').get('current')}/{Info.get('slots').get('Soldier').get('max')}"
        f"[{Info.get('slots').get('Queue').get('current')}]({Info.get('slots').get('Spectator').get('current')})\n"
        f"地图: {Info.get('mapNamePretty')}-{Info.get('mapModePretty')}\n"
        + "=" * 20 + "\n" +
        f"简介: {Info.get('description')}\n"
        f"GameId: {Info.get('gameId')}\n"
        f"Guid: {Info.get('guid')}\n"
        + "=" * 20
    )
    if rspInfo := server_info.get("rspInfo"):
        result.append(
            f"ServerId:{rspInfo.get('server').get('serverId')}\n"
            f"创建时间: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(int(rspInfo['server']['createdDate']) / 1000))}\n"
            f"到期时间: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(int(rspInfo['server']['expirationDate']) / 1000))}\n"
            f"更新时间: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(int(rspInfo['server']['updatedDate']) / 1000))}\n"
            f"服务器拥有者: {rspInfo.get('owner').get('displayName')}\n"
            f"Pid: {rspInfo.get('owner').get('personaId')}\n"
            + "=" * 20
        )
    if platoonInfo := server_info.get("platoonInfo"):
        result.append(
            f"战队: [{platoonInfo.get('tag')}]{platoonInfo.get('name')}\n"
            f"人数: {platoonInfo.get('size')}\n"
            f"简介: {platoonInfo.get('description')}\n"
            + "=" * 20
        )
    result = "\n".join(result)
    return await app.send_message(
        group,
        MessageChain(result),
        quote=source
    )


# 谁在玩功能
@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Function.require("modules.self_contained.bf1_info"),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level),
    Permission.user_require(Permission.User, if_noticed=True),
)
@dispatch(
    Twilight(
        [
            UnionMatch("-谁在玩", "-谁在捞").space(SpacePolicy.PRESERVE),
            ParamMatch(optional=True).space(SpacePolicy.NOSPACE) @ "bf_group_name",
            FullMatch("#", optional=True).space(SpacePolicy.NOSPACE),
            ParamMatch(optional=False).space(SpacePolicy.PRESERVE) @ "server_rank",
            # 示例: -谁在玩 SAKULA#1
        ]
    )
)
async def who_are_playing(
        app: Ariadne, group: Group, source: Source, message: MessageChain,
        server_rank: RegexResult, bf_group_name: RegexResult
):
    # 服务器序号检查
    server_rank = server_rank.result.display
    if not server_rank.isdigit():
        return await app.send_message(group, MessageChain("请输入正确的服务器序号"), quote=source)
    server_rank = int(server_rank)
    if server_rank < 1 or server_rank > 30:
        return await app.send_message(group, MessageChain("服务器序号只能在1~30内"), quote=source)

    # 获取群组信息
    bf_group_name = bf_group_name.result.display if bf_group_name and bf_group_name.matched else None
    if not bf_group_name:
        bf1_group_info = await BF1GROUP.get_bf1Group_byQQ(group.id)
        if not bf1_group_info:
            return await app.send_message(group, MessageChain("请先绑定BF1群组/指定群组名"), quote=source)
        bf_group_name = bf1_group_info.get("group_name")

    server_info = await BF1GROUP.get_bindInfo_byIndex(bf_group_name, server_rank)
    if not server_info:
        return await app.send_message(group, MessageChain(
            f"群组[{bf_group_name}]未绑定服务器{server_rank}"
        ), quote=source)
    elif isinstance(server_info, str):
        return await app.send_message(group, MessageChain(server_info), quote=source)

    server_gameid = server_info.get("gameId")

    await app.send_message(group, MessageChain(
        "查询ing"
    ), quote=source)

    # 获取绑定的成员列表
    group_member_list = await BF1GROUP.get_group_bindList(app, group)

    # 获取服务器信息-fullInfo
    server_fullInfo = await (await BF1DA.get_api_instance()).getFullServerDetails(server_gameid)
    if isinstance(server_fullInfo, str):
        return await app.send_message(
            group,
            MessageChain(f"查询出错!{server_fullInfo}"),
            quote=source
        )
    server_fullInfo = server_fullInfo["result"]
    admin_list = [
        f"{item['displayName']}".upper()
        for item in server_fullInfo["rspInfo"]["adminList"]
    ]
    vip_list = [
        f"{item['displayName']}".upper()
        for item in server_fullInfo["rspInfo"]["vipList"]
    ]
    # # gt接口获取玩家列表
    # url = "https://api.gametools.network/bf1/players/?gameid=" + str(server_gameid)
    # try:
    #     async with httpx.AsyncClient() as client:
    #         response = await client.get(url, timeout=10)
    # except:
    #     await app.send_message(group, MessageChain(
    #         "网络出错，请稍后再试!"
    #     ), quote=message[Source][0])
    #     return False
    # end_time = time.time()
    # logger.info(f"获取玩家列表和服务器信息耗时:{end_time - start_time}秒")
    # html = response.text
    # # 处理网页超时
    # if html == "timed out":
    #     await app.send_message(group, MessageChain(
    #         'timed out'
    #     ), quote=message[Source][0])
    # elif html == {}:
    #     await app.send_message(group, MessageChain(
    #         'timed out'
    #     ), quote=message[Source][0])
    # elif html == 404:
    #     await app.send_message(group, MessageChain(
    #         "未找到服务器或接口出错"
    #     ), quote=message[Source][0])
    # html = eval(html)
    # if "errors" in html:
    #     await app.send_message(group, MessageChain(
    #         "接口出错，请稍后再试!"
    #     ), quote=message[Source][0])
    #     return False
    # try:
    #     update_time = time.strftime('更新时间:%Y-%m-%d %H:%M:%S', time.localtime(int(html["update_timestamp"])))
    # except:
    #     await app.send_message(group, MessageChain(
    #         "接口出错，请稍后再试!"
    #     ), quote=message[Source][0])
    #     return False

    # easb接口:
    playerlist_data = await get_playerList_byGameid(server_gameid=server_gameid)
    if type(playerlist_data) != dict:
        return await app.send_message(group, MessageChain(
            "服务器信息为空" if playerlist_data is None else playerlist_data
        ), quote=source)
    playerlist_data["teams"] = {
        0: [item for item in playerlist_data["players"] if item["team"] == 0],
        1: [item for item in playerlist_data["players"] if item["team"] == 1]
    }
    update_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(playerlist_data["time"]))
    team1_num = len(playerlist_data["teams"][0])
    team2_num = len(playerlist_data["teams"][1])

    # 用来装服务器玩家
    player_list1 = {}
    player_list2 = {}
    i = 0
    while i < team1_num:
        player_list1[
            f'[{playerlist_data["teams"][0][i]["rank"]}]{playerlist_data["teams"][0][i]["display_name"]}'
        ] = f'{playerlist_data["teams"][0][i]["time"]}'
        i += 1
    i = 0
    while i < team2_num:
        player_list2[
            f'[{playerlist_data["teams"][1][i]["rank"]}]{playerlist_data["teams"][1][i]["display_name"]}'
        ] = f'{playerlist_data["teams"][1][i]["time"]}'
        i += 1
    player_dict_all = player_list1 | player_list2
    # 按照加入时间排序
    player_list_all = sorted(player_dict_all.items(), key=lambda kv: ([kv[1]], kv[0]))
    player_list = [item[0] for item in player_list_all]
    if not player_list:
        await app.send_message(group, MessageChain("获取到服务器内玩家数为0"), quote=source)
        return
    # 过滤人员
    player_list_filter = []
    for item in group_member_list:
        for i in player_list:
            if i[i.rfind("]") + 1:].upper() in item.upper():
                player_list_filter.append(i + "\n")
    player_list_filter = list(set(player_list_filter))
    i = 0
    for player in player_list_filter:
        if player[player.rfind("]") + 1:].upper().replace("\n", '') in admin_list:
            player_list_filter[i] = f"{player}".replace("\n", "(管理员)\n")
            i += 1
            continue
        elif player[player.rfind("]") + 1:].upper().replace("\n", '') in vip_list:
            player_list_filter[i] = f"{player}".replace("\n", "(vip)\n")
        i += 1
    player_num = len(player_list_filter)

    if player_num != 0:
        player_list_filter[-1] = player_list_filter[-1].replace("\n", '')
        await app.send_message(group, MessageChain(
            f"服内群友数:{player_num}\n" if "捞" not in message.display else f"服内捞b数:{player_num}\n", player_list_filter,
            f"\n{update_time}"
        ), quote=source)
    else:
        await app.send_message(
            group, MessageChain("服内群友数:0", f"\n{update_time}"), quote=source
        )


# 玩家列表
@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Function.require("modules.self_contained.bf1_info"),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level),
    Permission.user_require(Permission.User, if_noticed=True),
)
@dispatch(
    Twilight(
        [
            UnionMatch("-ppl").space(SpacePolicy.PRESERVE),
            ParamMatch(optional=True).space(SpacePolicy.NOSPACE) @ "bf_group_name",
            FullMatch("#", optional=True).space(SpacePolicy.NOSPACE),
            ParamMatch(optional=False).space(SpacePolicy.PRESERVE) @ "server_rank",
            # 示例: -ppl#1
        ]
    )
)
@bf1_perm_check()
async def get_server_playerList(
        app: Ariadne, group: Group, source: Source, sender: Member,
        bf_group_name: RegexResult, server_rank: RegexResult
):
    # 服务器序号检查
    server_rank = server_rank.result.display
    if not server_rank.isdigit():
        return await app.send_message(group, MessageChain("请输入正确的服务器序号"), quote=source)
    server_rank = int(server_rank)
    if server_rank < 1 or server_rank > 30:
        return await app.send_message(group, MessageChain("服务器序号只能在1~30内"), quote=source)

    # 获取群组信息
    bf_group_name = bf_group_name.result.display if bf_group_name and bf_group_name.matched else None
    if not bf_group_name:
        bf1_group_info = await BF1GROUP.get_bf1Group_byQQ(group.id)
        if not bf1_group_info:
            return await app.send_message(group, MessageChain("请先绑定BF1群组/指定群组名"), quote=source)
        bf_group_name = bf1_group_info.get("group_name")

    if not await perm_judge(bf_group_name, group, sender):
        return await app.send_message(
            group,
            MessageChain(f"您不是群组[{bf_group_name}]的成员"),
            quote=source,
        )
    server_info = await BF1GROUP.get_bindInfo_byIndex(bf_group_name, server_rank)
    if not server_info:
        return await app.send_message(group, MessageChain(
            f"群组[{bf_group_name}]未绑定服务器{server_rank}"
        ), quote=source)
    elif isinstance(server_info, str):
        return await app.send_message(group, MessageChain(server_info), quote=source)
    server_id = server_info["serverId"]
    server_gameid = server_info["gameId"]
    server_guid = server_info["guid"]

    data = await get_playerList_byGameid(server_gameid=server_gameid)
    if not isinstance(data, dict):
        return await app.send_message(group, MessageChain(
            "服务器信息为空" if data is None else data
        ), quote=source)

    dt = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(data['time']))
    message_servername = f'服务器名:{data["server_name"]}\n获取时间:{dt}'
    bot_member = await app.get_member(group, app.account)
    fwd_nodeList = [ForwardNode(
        target=bot_member,
        time=datetime.now(),
        message=MessageChain(message_servername),
    )]
    players = data["players"]
    message0 = f"队伍1信息:\n"
    message1 = f"队伍2信息:\n"
    for item in players:
        if item["team"] == 0:
            # 时间戳转日期
            dt = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(item['time']))
            message_temp = f"玩家名字:[{item['rank']}]{item['display_name']}\n加入时间:{dt}\n" + "=" * 20 + "\n"
            message0 += message_temp
        else:
            # 时间戳转日期
            dt = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(item['time']))
            message_temp = f"玩家名字:[{item['rank']}]{item['display_name']}\n加入时间:{dt}\n" + "=" * 20 + "\n"
            message1 += message_temp
    if message0 != f"队伍1信息:\n":
        fwd_nodeList.append(ForwardNode(
            target=bot_member,
            time=datetime.now(),
            message=MessageChain(message0),
        ))
    if message1 != f"队伍2信息:\n":
        fwd_nodeList.append(ForwardNode(
            target=bot_member,
            time=datetime.now(),
            message=MessageChain(message1),
        ))
    message_send = MessageChain(Forward(nodeList=fwd_nodeList))
    return await app.send_message(group, message_send)


async def download_serverMap_pic(url: str) -> str:
    file_name = './data/battlefield/pic/map/' + url[url.rfind('/') + 1:]
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
                    async with session.get(url, timeout=5, verify_ssl=False) as resp:
                        pic = await resp.read()
                        with open(file_name, 'wb') as fp:
                            fp.write(pic)
                        return file_name
                except Exception as e:
                    logger.error(e)
                    i += 1
        return None


async def get_server_map_pic(map_name: str) -> str:
    file_path = "./data/battlefield/游戏模式/data.json"
    with open(file_path, 'r', encoding="utf-8") as file1:
        data = json.load(file1)["result"]["maps"]
    for item in data:
        if item["assetName"] == map_name:
            try:
                return await download_serverMap_pic(
                    item["images"]["JpgAny"].replace(
                        "[BB_PREFIX]",
                        "https://eaassets-a.akamaihd.net/battlelog/battlebinary",
                    )
                )
            except Exception:
                return None


def get_team_pic(team_name: str) -> str:
    team_pic_list = os.listdir("./data/battlefield/pic/team/")
    for item in team_pic_list:
        if team_name in item:
            return f"./data/battlefield/pic/team/{item}"


def get_width(o):
    """Return the screen column width for unicode ordinal o."""
    if o in [0xE, 0xF]:
        return 0
    widths = [
        (126, 1), (159, 0), (687, 1), (710, 0), (711, 1),
        (727, 0), (733, 1), (879, 0), (1154, 1), (1161, 0),
        (4347, 1), (4447, 2), (7467, 1), (7521, 0), (8369, 1),
        (8426, 0), (9000, 1), (9002, 2), (11021, 1), (12350, 2),
        (12351, 1), (12438, 2), (12442, 0), (19893, 2), (19967, 1),
        (55203, 2), (63743, 1), (64106, 2), (65039, 1), (65059, 0),
        (65131, 2), (65279, 1), (65376, 2), (65500, 1), (65510, 2),
        (120831, 1), (262141, 2), (1114109, 1),
    ]
    return next((wid for num, wid in widths if o <= num), 1)


# 图片版玩家列表
@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Function.require("modules.self_contained.bf1_info"),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level),
    Permission.user_require(Permission.User, if_noticed=True),
)
@dispatch(
    Twilight(
        [
            UnionMatch("-玩家列表", "-playerlist", "-pl", "-lb").space(
                SpacePolicy.PRESERVE),
            ParamMatch(optional=True).space(SpacePolicy.NOSPACE) @ "bf_group_name",
            FullMatch("#", optional=True).space(SpacePolicy.NOSPACE),
            ParamMatch(optional=False).space(SpacePolicy.PRESERVE) @ "server_rank",
            # 示例: -玩家列表 sakula#1
        ]
    )
)
async def get_server_playerList_pic(
        app: Ariadne, sender: Member, group: Group, source: Source,
        server_rank: MatchResult, bf_group_name: MatchResult
):
    # 服务器序号检查
    server_rank = server_rank.result.display
    if not server_rank.isdigit():
        return await app.send_message(group, MessageChain("请输入正确的服务器序号"), quote=source)
    server_rank = int(server_rank)
    if server_rank < 1 or server_rank > 30:
        return await app.send_message(group, MessageChain("服务器序号只能在1~30内"), quote=source)

    # 获取群组信息
    bf_group_name = bf_group_name.result.display if bf_group_name and bf_group_name.matched else None
    if not bf_group_name:
        bf1_group_info = await BF1GROUP.get_bf1Group_byQQ(group.id)
        if not bf1_group_info:
            return await app.send_message(group, MessageChain("请先绑定BF1群组/指定群组名"), quote=source)
        bf_group_name = bf1_group_info.get("group_name")

    server_info_temp = await BF1GROUP.get_bindInfo_byIndex(bf_group_name, server_rank)
    if not server_info_temp:
        return await app.send_message(group, MessageChain(
            f"群组[{bf_group_name}]未绑定服务器{server_rank}"
        ), quote=source)
    elif isinstance(server_info_temp, str):
        return await app.send_message(group, MessageChain(server_info_temp), quote=source)
    server_id = server_info_temp["serverId"]
    server_gameid = server_info_temp["gameId"]
    server_guid = server_info_temp["guid"]

    await app.send_message(group, MessageChain(
        f"查询ing"
    ), quote=source)
    time_start = time.time()
    try:
        server_info = await (await BF1DA.get_api_instance()).getFullServerDetails(server_gameid)
        if isinstance(server_info, str):
            return await app.send_message(group, MessageChain(
                f"查询失败!{server_info}"
            ), quote=source)
        server_info = server_info["result"]
    except:
        await app.send_message(group, MessageChain(
            GraiaImage(path='./data/bqb/狐务器无响应.jpg')
        ), quote=source)
        return False
    admin_pid_list = [str(item['personaId']) for item in server_info["rspInfo"]["adminList"]]
    admin_counter = 0
    admin_color = (0, 255, 127)
    vip_pid_list = [str(item['personaId']) for item in server_info["rspInfo"]["vipList"]]
    vip_counter = 0
    vip_color = (255, 99, 71)
    bind_pid_list = await BF1GROUP.get_group_bindList(app, group)
    bind_color = (179, 244, 255)
    bind_counter = 0
    max_level_counter = 0

    # # gt接口获取玩家列表
    # url = "https://api.gametools.network/bf1/players/?gameid=" + str(server_gameid)
    # # url = "https://api.gametools.network/bf1/players/?gameid=" + str(7525683910896)
    # try:
    #     async with httpx.AsyncClient() as client:
    #         response = await client.get(url, timeout=10)
    # except:
    #     await app.send_message(group, MessageChain(
    #         "网络出错，请稍后再试!"
    #     ), quote=message[Source][0])
    #     return False
    # response_data = eval(response.text)
    # if "errors" in response_data:
    #     await app.send_message(group, MessageChain(
    #         "接口出错，请稍后再试!"
    #     ), quote=message[Source][0])
    #     return False
    # # 获取时间
    # try:
    #     update_time = time.strftime('更新时间:%Y-%m-%d %H:%M:%S', time.localtime(int(response_data["update_timestamp"])))
    # except:
    #     await app.send_message(group, MessageChain(
    #         "接口出错，请稍后再试!"
    #     ), quote=message[Source][0])
    #     return False

    # easb接口:
    playerlist_data = await get_playerList_byGameid(server_gameid=server_gameid)
    if type(playerlist_data) != dict:
        return await app.send_message(group, MessageChain(
            "服务器信息为空" if playerlist_data is None else playerlist_data
        ), quote=source)

    playerlist_data["teams"] = {
        0: [item for item in playerlist_data["players"] if item["team"] == 0],
        1: [item for item in playerlist_data["players"] if item["team"] == 1]
    }
    update_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(playerlist_data["time"]))

    # 获取玩家生涯战绩
    # 队伍1
    scrape_index_tasks_t1 = [asyncio.ensure_future(get_player_stat_data(player_item['pid'])) for
                             player_item in playerlist_data["teams"][0]]
    tasks = asyncio.gather(*scrape_index_tasks_t1)
    try:
        await tasks
    except:
        pass

    # 队伍2
    scrape_index_tasks_t2 = [asyncio.ensure_future(get_player_stat_data(player_item['pid'])) for
                             player_item in playerlist_data["teams"][1]]
    tasks = asyncio.gather(*scrape_index_tasks_t2)
    try:
        await tasks
    except:
        pass

    # 服务器名
    server_name = server_info["serverInfo"]["name"]
    # MP_xxx
    server_mapName = server_info["serverInfo"]["mapName"]

    team1_name = MapData.Map_Team_dict[server_info["serverInfo"]["mapName"]]["Team1"]
    team1_pic = get_team_pic(team1_name)
    team1_pic = PIL_Image.open(team1_pic).convert('RGBA')
    team1_pic = team1_pic.resize((40, 40), PIL_Image.ANTIALIAS)
    team2_name = MapData.Map_Team_dict[server_info["serverInfo"]["mapName"]]["Team2"]
    team2_pic = get_team_pic(team2_name)
    team2_pic = PIL_Image.open(team2_pic).convert('RGBA')
    team2_pic = team2_pic.resize((40, 40), PIL_Image.ANTIALIAS)

    # 地图路径
    server_map_pic = await get_server_map_pic(server_mapName)
    # 地图作为画布底图并且高斯模糊化
    if server_map_pic is None:
        logger.warning(f"获取地图{server_mapName}图片出错")
        await app.send_message(group, MessageChain(
            "网络出错，请稍后再试!"
        ), quote=source)
        return False
    IMG = PIL_Image.open(server_map_pic)
    # 高斯模糊
    IMG = IMG.filter(ImageFilter.GaussianBlur(radius=12))
    # 调低亮度
    IMG = ImageEnhance.Brightness(IMG).enhance(0.7)
    # 裁剪至1920x1080
    box = (0, 70, 1920, 1150)  # 将要裁剪的图片块距原图左边界距左边距离，上边界距上边距离，右边界距左边距离，下边界距上边的距离。
    IMG = IMG.crop(box)

    # 延迟 5:小于50 4:50< <100 3: 150< < 100 2: 150<  <200 1: 250< <300 0:300+
    Ping1 = PIL_Image.open(f"./data/battlefield/pic/ping/4.png").convert('RGBA')
    Ping1 = Ping1.resize((int(Ping1.size[0] * 0.04), int(Ping1.size[1] * 0.04)), PIL_Image.ANTIALIAS)
    Ping2 = PIL_Image.open(f"./data/battlefield/pic/ping/3.png").convert('RGBA')
    Ping2 = Ping2.resize((int(Ping2.size[0] * 0.04), int(Ping2.size[1] * 0.04)), PIL_Image.ANTIALIAS)
    Ping3 = PIL_Image.open(f"./data/battlefield/pic/ping/2.png").convert('RGBA')
    Ping3 = Ping3.resize((int(Ping3.size[0] * 0.04), int(Ping3.size[1] * 0.04)), PIL_Image.ANTIALIAS)
    Ping4 = PIL_Image.open(f"./data/battlefield/pic/ping/1.png").convert('RGBA')
    Ping4 = Ping4.resize((int(Ping4.size[0] * 0.04), int(Ping4.size[1] * 0.04)), PIL_Image.ANTIALIAS)
    Ping5 = PIL_Image.open(f"./data/battlefield/pic/ping/0.png").convert('RGBA')
    Ping5 = Ping5.resize((int(Ping5.size[0] * 0.04), int(Ping5.size[1] * 0.04)), PIL_Image.ANTIALIAS)

    draw = ImageDraw.Draw(IMG)
    # 字体路径
    font_path = './data/battlefield/font/BFText-Regular-SC-19cf572c.ttf'
    title_font = ImageFont.truetype(font_path, 40)
    team_font = ImageFont.truetype(font_path, 25)
    title_font_small = ImageFont.truetype(font_path, 22)
    player_font = ImageFont.truetype(font_path, 20)
    rank_font = ImageFont.truetype(font_path, 15)
    info_font = ImageFont.truetype(font_path, 22)
    # 服务器名字
    draw.text((97, 30), f"服务器名:{server_name}", fill='white', font=title_font)
    # 更新时间
    draw.text((100, 80), update_time, fill="white", font=rank_font)
    max_level_color = (255, 132, 0)

    KD_counter1 = 0
    KPM_counter1 = 0
    RANK_counter1 = 0
    TIME_counter1 = 0
    WIN_counter1 = 0
    # 队伍1
    # 队伍1图片
    IMG.paste(team1_pic, (100, 101))
    # 队伍1名
    draw.text((152, 105), team1_name, fill='white', font=team_font)
    draw.text((520, 113), f"胜率", fill='white', font=title_font_small)
    draw.text((610, 113), f"K/D", fill='white', font=title_font_small)
    draw.text((700, 113), f"KPM", fill='white', font=title_font_small)
    draw.text((790, 113), f"时长(h)", fill='white', font=title_font_small)
    draw.text((890, 113), f"延迟", fill='white', font=title_font_small)
    # 队伍1横线
    draw.line([100, 141, 950, 141], fill=(114, 114, 114), width=2, joint=None)
    # 队伍1竖线
    draw.line([100, 155, 100, 915], fill=(114, 114, 114), width=2, joint=None)
    leve_position_1 = None
    for i, player_item in enumerate(playerlist_data["teams"][0]):
        # 序号
        draw.text((135, 156 + i * 23), f"{i + 1}", anchor="ra", fill='white', font=player_font)

        # 等级框 30*15  等级 居中显示
        draw.rectangle([155, 159 + i * 23, 185, 173.5 + i * 23],
                       fill=max_level_color if player_item['rank'] == 150 else None, outline=None, width=1)
        RANK_counter1 += player_item['rank']
        if player_item['rank'] == 150:
            max_level_counter += 1
        rank_font_temp = ImageFont.truetype(font_path, 15)
        ascent, descent = rank_font_temp.getsize(f"{player_item['rank']}")
        leve_position_1 = 170 - ascent / 2, 165.5 + i * 23 - descent / 2
        draw.text(leve_position_1, f"{player_item['rank']}",
                  fill="white",
                  font=rank_font)
        # 战队 名字
        color_temp = 'white'
        if str(player_item["display_name"]).upper() in bind_pid_list:
            color_temp = bind_color
            bind_counter += 1
        if str(player_item["pid"]) in vip_pid_list:
            color_temp = vip_color
            vip_counter += 1
        if str(player_item["pid"]) in admin_pid_list:
            color_temp = admin_color
            admin_counter += 1
        # if player_item["platoon"] != "":
        #     draw.text((195, 155 + i * 23), f"[{player_item['platoon']}]{player_item['name']}", fill=color_temp,
        #               font=player_font)
        # else:
        draw.text((195, 155 + i * 23), player_item["display_name"], fill=color_temp, font=player_font)

        # 延迟 靠右显示
        ping_pic = Ping5
        if player_item['ping'] <= 50:
            ping_pic = Ping1
        elif 50 < player_item['ping'] <= 100:
            ping_pic = Ping2
        elif 100 < player_item['ping'] <= 150:
            ping_pic = Ping3
        elif 150 < player_item['ping']:
            ping_pic = Ping4
        IMG.paste(ping_pic, (880, 158 + i * 23), ping_pic)
        draw.text((930, 155 + i * 23), f"{player_item['ping']}", anchor="ra", fill='white', font=player_font)

        # KD KPM 时长
        try:
            player_stat_data = scrape_index_tasks_t1[i].result()["result"]
            # 胜率
            win_p = int(player_stat_data['basicStats']['wins'] / (
                    player_stat_data['basicStats']['losses'] + player_stat_data['basicStats']['wins']) * 100)
            WIN_counter1 += win_p
            draw.text((565, 155 + i * 23), f'{win_p}%', anchor="ra", fill=max_level_color if win_p >= 70 else 'white',
                      font=player_font)
            # kd
            kd = player_stat_data['kdr']
            KD_counter1 += kd
            draw.text((645, 155 + i * 23), f'{kd}', anchor="ra", fill=max_level_color if kd >= 3 else 'white',
                      font=player_font)
            # kpm
            kpm = player_stat_data['basicStats']["kpm"]
            KPM_counter1 += kpm
            draw.text((740, 155 + i * 23), f'{kpm}', fill=max_level_color if kpm >= 2 else 'white', anchor="ra",
                      font=player_font)
            # 时长
            time_played = "{:.1f}".format(player_stat_data['basicStats']["timePlayed"] / 3600)
            TIME_counter1 += float(time_played)
            draw.text((850, 155 + i * 23), f"{time_played}", anchor="ra",
                      fill=max_level_color if float(time_played) >= 1000 else 'white',
                      font=player_font)
        except:
            pass

    # x相差860

    KD_counter2 = 0
    KPM_counter2 = 0
    RANK_counter2 = 0
    TIME_counter2 = 0
    WIN_counter2 = 0
    # 队伍2
    # 队伍2图片
    IMG.paste(team2_pic, (960, 101))
    # 队伍2名
    draw.text((1012, 105), team2_name, fill='white', font=team_font)
    draw.text((1380, 113), f"胜率", fill='white', font=title_font_small)
    draw.text((1470, 113), f"K/D", fill='white', font=title_font_small)
    draw.text((1560, 113), f"KPM", fill='white', font=title_font_small)
    draw.text((1650, 113), f"时长(h)", fill='white', font=title_font_small)
    draw.text((1750, 113), f"延迟", fill='white', font=title_font_small)
    # 队伍2横线
    draw.line([960, 141, 1810, 141], fill=(114, 114, 114), width=2, joint=None)
    # 队伍2竖线
    draw.line([960, 155, 960, 915], fill=(114, 114, 114), width=2, joint=None)
    leve_position_2 = None
    for i, player_item in enumerate(playerlist_data["teams"][1]):
        # 序号
        draw.text((995, 156 + i * 23), f"{int(i + 1 + server_info['serverInfo']['slots']['Soldier']['max'] / 2)}",
                  anchor="ra", fill='white', font=player_font)
        # 等级框 30*15 等级居中显示
        draw.rectangle([1015, 159 + i * 23, 1045, 173.5 + i * 23],
                       fill=max_level_color if player_item['rank'] == 150 else None, outline=None, width=1)
        RANK_counter2 += player_item['rank']
        if player_item['rank'] == 150:
            max_level_counter += 1
        rank_font_temp = ImageFont.truetype(font_path, 15)
        ascent, descent = rank_font_temp.getsize(f"{player_item['rank']}")
        leve_position_2 = 1030 - ascent / 2, 165.5 + i * 23 - descent / 2
        draw.text(leve_position_2, f"{player_item['rank']}",
                  fill="white",
                  font=rank_font)
        # 战队 名字
        color_temp = 'white'
        if str(player_item["display_name"]).upper() in bind_pid_list:
            color_temp = bind_color
            bind_counter += 1
        if str(player_item["pid"]) in vip_pid_list:
            color_temp = vip_color
            vip_counter += 1
        if str(player_item["pid"]) in admin_pid_list:
            color_temp = admin_color
            admin_counter += 1
        # if player_item["platoon"] != "":
        #     draw.text((1055, 155 + i * 23), f"[{player_item['platoon']}]{player_item['name']}", fill=color_temp,
        #               font=player_font)
        # else:
        draw.text((1055, 155 + i * 23), player_item["display_name"], fill=color_temp, font=player_font)
        # 延迟 靠右显示
        ping_pic = Ping5
        if player_item['ping'] <= 50:
            ping_pic = Ping1
        elif 50 < player_item['ping'] <= 100:
            ping_pic = Ping2
        elif 100 < player_item['ping'] <= 150:
            ping_pic = Ping3
        elif 150 < player_item['ping']:
            ping_pic = Ping4
        IMG.paste(ping_pic, (1740, 158 + i * 23), ping_pic)
        draw.text((1790, 155 + i * 23), f"{player_item['ping']}", anchor="ra", fill='white', font=player_font)
        # 生涯数据
        try:
            player_stat_data = scrape_index_tasks_t2[i].result()["result"]
            # 胜率
            win_p = int(player_stat_data['basicStats']['wins'] / (
                    player_stat_data['basicStats']['losses'] + player_stat_data['basicStats']['wins']) * 100)
            WIN_counter2 += win_p
            draw.text((1425, 155 + i * 23), f'{win_p}%', anchor="ra", fill=max_level_color if win_p >= 70 else 'white',
                      font=player_font)
            # kd
            kd = player_stat_data['kdr']
            KD_counter2 += kd
            draw.text((1505, 155 + i * 23), f'{kd}', anchor="ra", fill=max_level_color if kd >= 3 else 'white',
                      font=player_font)
            # kpm
            kpm = player_stat_data['basicStats']["kpm"]
            KPM_counter2 += kpm
            draw.text((1600, 155 + i * 23), f'{kpm}', fill=max_level_color if kpm >= 2 else 'white', anchor="ra",
                      font=player_font)
            # 时长
            time_played = "{:.1f}".format(player_stat_data['basicStats']["timePlayed"] / 3600)
            TIME_counter2 += float(time_played)
            draw.text((1710, 155 + i * 23), f"{time_played}", anchor="ra",
                      fill=max_level_color if float(time_played) >= 1000 else 'white',
                      font=player_font)
        except:
            pass

    i_temp = len(playerlist_data['teams'][0]) if len(playerlist_data['teams'][0]) >= len(
        playerlist_data['teams'][1]) else len(playerlist_data['teams'][1])
    avg_color = (250, 183, 39)
    avg_1_1 = 0
    avg_1_2 = 0
    avg_1_3 = 0
    avg_1_4 = 0
    avg_1_5 = 0
    if len(playerlist_data['teams'][0]) != 0:
        avg_1_1 = int(RANK_counter1 / len(playerlist_data['teams'][0]))
        avg_1_2 = KD_counter1 / len(playerlist_data['teams'][0])
        avg_1_3 = KPM_counter1 / len(playerlist_data['teams'][0])
        avg_1_4 = TIME_counter1 / len(playerlist_data['teams'][0])
        avg_1_5 = int(WIN_counter1 / len(playerlist_data['teams'][0]))
    avg_2_1 = 0
    avg_2_2 = 0
    avg_2_3 = 0
    avg_2_4 = 0
    avg_2_5 = 0
    if len(playerlist_data['teams'][1]) != 0:
        avg_2_1 = int(RANK_counter2 / len(playerlist_data['teams'][1]))
        avg_2_2 = KD_counter2 / len(playerlist_data['teams'][1])
        avg_2_3 = KPM_counter2 / len(playerlist_data['teams'][1])
        avg_2_4 = TIME_counter2 / len(playerlist_data['teams'][1])
        avg_2_5 = int(WIN_counter2 / len(playerlist_data['teams'][1]))

    if leve_position_1:
        rank_font_temp = ImageFont.truetype(font_path, 15)
        ascent, descent = rank_font_temp.getsize(f"{int(RANK_counter1 / len(playerlist_data['teams'][0]))}")
        leve_position_1 = 168 - ascent / 2, 156 + i_temp * 23
        draw.text((115, 156 + i_temp * 23), f"平均:",
                  fill="white",
                  font=player_font)
        if RANK_counter1 != 0:
            draw.text(leve_position_1, f"{int(RANK_counter1 / len(playerlist_data['teams'][0]))}",
                      fill=avg_color if avg_1_1 > avg_2_1 else "white",
                      font=player_font)
        if WIN_counter1 != 0:
            draw.text((565, 156 + i_temp * 23), f"{int(WIN_counter1 / len(playerlist_data['teams'][0]))}%",
                      anchor="ra",
                      fill=avg_color if avg_1_5 > avg_2_5 else "white",
                      font=player_font)
        if KD_counter1 != 0:
            draw.text((645, 156 + i_temp * 23),
                      "{:.2f}".format(KD_counter1 / len(playerlist_data['teams'][0])),
                      anchor="ra",
                      fill=avg_color if avg_1_2 > avg_2_2 else "white",
                      font=player_font)
        if KPM_counter1 != 0:
            draw.text((740, 156 + i_temp * 23),
                      "{:.2f}".format(KPM_counter1 / len(playerlist_data['teams'][0])),
                      anchor="ra",
                      fill=avg_color if avg_1_3 > avg_2_3 else "white",
                      font=player_font)
        if TIME_counter1 != 0:
            draw.text((850, 156 + i_temp * 23),
                      "{:.1f}".format(TIME_counter1 / len(playerlist_data['teams'][0])),
                      anchor="ra",
                      fill=avg_color if avg_1_4 > avg_2_4 else "white",
                      font=player_font)

    if leve_position_2:
        rank_font_temp = ImageFont.truetype(font_path, 15)
        ascent, descent = rank_font_temp.getsize(f"{int(RANK_counter1 / len(playerlist_data['teams'][1]))}")
        leve_position_2 = 1028 - ascent / 2, 156 + i_temp * 23
        draw.text((975, 156 + i_temp * 23), f"平均:",
                  fill="white",
                  font=player_font)
        if RANK_counter2 != 0:
            draw.text(leve_position_2, f"{int(RANK_counter2 / len(playerlist_data['teams'][1]))}",
                      fill=avg_color if avg_1_1 < avg_2_1 else "white",
                      font=player_font)
        if WIN_counter2 != 0:
            draw.text((1425, 156 + i_temp * 23), f"{int(WIN_counter2 / len(playerlist_data['teams'][1]))}%",
                      anchor="ra",
                      fill=avg_color if avg_1_5 < avg_2_5 else "white",
                      font=player_font)
        if KD_counter2 != 0:
            draw.text((1505, 156 + i_temp * 23),
                      "{:.2f}".format(KD_counter2 / len(playerlist_data['teams'][1])),
                      anchor="ra",
                      fill=avg_color if avg_1_2 < avg_2_2 else "white",
                      font=player_font)
        if KPM_counter2 != 0:
            draw.text((1600, 156 + i_temp * 23),
                      "{:.2f}".format(KPM_counter2 / len(playerlist_data['teams'][1])),
                      anchor="ra",
                      fill=avg_color if avg_1_3 < avg_2_3 else "white",
                      font=player_font)
        if TIME_counter2 != 0:
            draw.text((1710, 156 + i_temp * 23),
                      "{:.1f}".format(TIME_counter2 / len(playerlist_data['teams'][1])),
                      anchor="ra",
                      fill=avg_color if avg_1_4 < avg_2_4 else "white",
                      font=player_font)

    # 服务器信息
    server_info_text = f'服务器状态:{server_info["serverInfo"]["mapModePretty"]}-{server_info["serverInfo"]["mapNamePretty"]}  ' \
                       f'在线人数:{server_info["serverInfo"]["slots"]["Soldier"]["current"]}/{server_info["serverInfo"]["slots"]["Soldier"]["max"]}' \
                       f'[{server_info["serverInfo"]["slots"]["Queue"]["current"]}]({server_info["serverInfo"]["slots"]["Spectator"]["current"]})  ' \
                       f"收藏:{server_info['serverInfo']['serverBookmarkCount']}"

    draw.text((240, 925), server_info_text, fill="white", font=info_font)

    # 服务器简介
    server_dscr = f'        {server_info["serverInfo"]["description"]}'
    test_temp = ""
    i = 0
    for letter in server_dscr:
        if i * 11 % 125 == 0 or (i + 1) * 11 % 125 == 0:
            test_temp += '\n'
            i = 0
        i += get_width(ord(letter))
        test_temp += letter
    draw.text((240, 955), f"服务器简介:{test_temp}", fill="white", font=info_font)

    # 颜色标识
    # 管理
    draw.rectangle([1100, 925, 1120, 945], fill=admin_color, outline=None, width=1)
    draw.text((1130, 925), f"在线管理:{admin_counter}", fill="white", font=player_font)
    # vip
    draw.rectangle([1250, 925, 1270, 945], fill=vip_color, outline=None, width=1)
    draw.text((1280, 925), f"在线VIP:{vip_counter}", fill="white", font=player_font)
    # 群友
    draw.rectangle([1400, 925, 1420, 945], fill=bind_color, outline=None, width=1)
    draw.text((1430, 925), f"在线群友:{bind_counter}", fill="white", font=player_font)
    # 150数量
    draw.rectangle([1550, 925, 1570, 945], fill=max_level_color, outline=None, width=1)
    draw.text((1580, 925), f"150数量:{max_level_counter}", fill="white", font=player_font)

    # 水印
    draw.text((1860, 1060), f"by.13", fill=(114, 114, 114), font=player_font)

    # IMG.show()
    SavePic = f"./data/battlefield/Temp/{time.time()}.png"
    SavePic = SavePic.replace(".png", ".jpg")
    IMG.save(SavePic, quality=100)
    logger.info(f"玩家列表pic耗时:{(time.time() - time_start):.2f}秒")
    message_send = MessageChain(
        GraiaImage(path=SavePic),
        "\n回复'-k 序号 原因'可踢出玩家(120秒内有效)"
    )
    bot_message = await app.send_group_message(group, message_send, quote=source)
    os.remove(SavePic)

    # TODO 待重构的回复踢出
    async def waiter(event: GroupMessage, waiter_member: Member, waiter_group: Group, waiter_message: MessageChain):
        if (await perm_judge(bf_group_name, waiter_group, waiter_member)) and waiter_group.id == group.id and (
                event.quote and event.quote.id == bot_message.id):
            saying = waiter_message.display.replace(f"@{app.account} ", "").replace(f"@{app.account}", "")
            return saying

    try:
        result = await FunctionWaiter(waiter, [GroupMessage]).wait(120)
    except asyncio.exceptions.TimeoutError:
        return
    if not result:
        return

    kick_action = result.split(' ')

    kick_action = list(filter(lambda x: x != '', kick_action))
    if kick_action[0] != "-k":
        return
    ending = None
    for i, item in enumerate(kick_action):
        if i == 0:
            continue
        if item.isnumeric():
            pass
        else:
            ending = i
    if ending is not None:
        index_list = kick_action[1:ending]
        reason = ''
        for r in kick_action[ending:]:
            reason += r
    else:
        index_list = kick_action[1:]
        reason = "违反规则"
    reason = reason.replace("ADMINPRIORITY", "违反规则")
    # 获取服管帐号实例
    if not server_info_temp["account"]:
        return await app.send_message(group, MessageChain(
            f"群组{bf_group_name}服务器{server_rank}未绑定服管账号，请先绑定服管账号!"
        ), quote=source)
    account_instance = await BF1ManagerAccount.get_manager_account_instance(server_info_temp["account"])
    # 并发踢出
    scrape_index_tasks = []
    name_temp = []
    for index in index_list:
        index = int(index)
        try:
            if index <= (int(server_info["serverInfo"]["slots"]["Soldier"]["max"]) / 2):
                index = index - 1
                scrape_index_tasks.append(asyncio.ensure_future(
                    account_instance.kickPlayer(gameId=server_gameid,
                                                personaId=playerlist_data["teams"][0][index]["pid"], reason=reason)
                ))
                name_temp.append(playerlist_data["teams"][0][index]["display_name"])
            else:
                index = index - 1 - int((int(server_info["serverInfo"]["slots"]["Soldier"]["max"]) / 2))
                scrape_index_tasks.append(asyncio.ensure_future(
                    account_instance.kickPlayer(gameId=server_gameid,
                                                personaId=playerlist_data["teams"][0][index]["pid"], reason=reason)
                ))
                name_temp.append(playerlist_data["teams"][1][index]["display_name"])
        except:
            await app.send_message(group, MessageChain(
                f"无效序号:{index}"
            ), quote=source)
            return False
    tasks = asyncio.gather(*scrape_index_tasks)
    try:
        await tasks
    except Exception as e:
        await app.send_message(group, MessageChain(
            f"执行中出现了一个错误!{e}"
        ), quote=source)
        return False
    kick_result = []
    suc = 0
    suc_list = []
    fal = 0
    fal_list = []
    for i, result in enumerate(scrape_index_tasks):
        result = result.result()
        if type(result) == dict:
            suc += 1
            suc_list.append(
                f"{name_temp[i]},"
            )
            await BF1Log.record(
                operator_qq=sender.id,
                serverId=server_id,
                persistedGameId=server_guid,
                gameId=server_gameid,
                pid=0000,
                display_name=name_temp[i],
                action="kick",
                info=reason,
            )
        else:
            fal += 1
            fal_list.append(
                f"踢出玩家{name_temp[i]}失败\n原因:{result}\n"
            )
    if 0 < suc <= 3:
        kick_result = [f"{name}" for name in suc_list]
        kick_result.insert(0, "成功踢出:")
        kick_result.append(f"\n原因:{reason}")
    elif suc != 0:
        kick_result.append(f"成功踢出{suc}位玩家\n原因:{reason}\n")
    if fal != 0:
        try:
            fal_list[-1] = fal_list[-1].replace("\n", "")
        except:
            pass
        kick_result.append(fal_list)
    try:
        kick_result[-1] = kick_result[-1].replace("\n", "")
    except:
        pass
    await app.send_message(group, MessageChain(
        kick_result
    ), quote=source)


# 3.服管账号相关-查增改、删、绑定到bfgroups-servers里的managerAccount
@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level),
    Permission.user_require(Permission.User, if_noticed=True),
)
@dispatch(
    Twilight(
        [
            UnionMatch("-bf服管账号列表", "-bfal").space(SpacePolicy.PRESERVE)
        ]
    )
)
async def managerAccount_list(app: Ariadne, group: Group, source: Source):
    # 检测bf1_account账号表中有cookie的->有session的
    manager_account_list = await BF1ManagerAccount.get_accounts()
    if not manager_account_list:
        return await app.send_message(group, MessageChain(
            "当前没有服管账号!"
        ), quote=source)
    tasks = []
    for manager_account in manager_account_list:
        account_pid = manager_account.get("pid")
        tasks.append(asyncio.ensure_future(
            BF1DB.server.get_playerAdminServerList(account_pid)
        ))
    try:
        await asyncio.gather(*tasks)
    except Exception:
        return await app.send_message(group, MessageChain(
            "查询数据库信息时出错!"
        ), quote=source)
    result = []
    for i, manager_account in enumerate(manager_account_list):
        result.append(
            f"⚪{manager_account.get('display_name')} ({len(tasks[i].result())})\n  {manager_account.get('pid')}")
    send = "\n".join(result)
    return await app.send_message(group, MessageChain(
        f"当前共有{len(manager_account_list)}个服管账号:\n{send}"
    ), quote=source)


# 传入remid和sid信息-登录 如果没有该帐号就创建写入
@listen(GroupMessage, FriendMessage)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level),
    Permission.user_require(Permission.BotAdmin, if_noticed=True),
)
@dispatch(
    Twilight(
        [
            UnionMatch("-bf服管账号", "-bfga").space(SpacePolicy.FORCE),
            UnionMatch("登录", "login").space(SpacePolicy.FORCE),
            ParamMatch(optional=False).space(SpacePolicy.FORCE) @ "player_name",
            FullMatch("remid=").space(SpacePolicy.NOSPACE),
            ParamMatch(optional=False).space(SpacePolicy.NOSPACE) @ "remid",
            FullMatch(",sid=").space(SpacePolicy.NOSPACE),
            ParamMatch(optional=False) @ "sid",
            # 示例: -bf服管账号 登录 xmmxml remid=xxx,sid=xxx
        ]
    )
)
async def managerAccount_login(
        app: Ariadne, group: Union[Group, Friend],
        player_name: RegexResult, remid: RegexResult, sid: RegexResult, source: Source
):
    player_name = player_name.result.display
    player_info = await get_personas_by_name(player_name)
    if isinstance(player_info, str):
        return await app.send_message(
            group,
            MessageChain(f"查询出错!{player_info}"),
            quote=source
        )
    if not player_info:
        return await app.send_message(
            group,
            MessageChain(f"玩家 {player_name} 不存在"),
            quote=source
        )
    player_pid = player_info["personas"]["persona"][0]["personaId"]
    display_name = player_info["personas"]["persona"][0]["displayName"]
    remid = remid.result.display
    sid = sid.result.display
    await BF1DB.bf1account.update_bf1account(pid=player_pid, display_name=display_name, remid=remid, sid=sid)
    account_instance = await BF1ManagerAccount.login(player_pid, remid, sid)
    if not await account_instance.check_session_expire():
        return await app.send_message(group, MessageChain(
            f"账号{player_name}({player_pid})登录成功!"
        ), quote=source)
    else:
        return await app.send_message(group, MessageChain(
            f"账号{player_name}({player_pid})登录失败!"
        ), quote=source)


# 删除服管账号
@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level),
    Permission.user_require(Permission.BotAdmin, if_noticed=True),
)
@dispatch(
    Twilight(
        [
            UnionMatch("-bf服管账号", "-bfga").space(SpacePolicy.FORCE),
            UnionMatch("删除", "del").space(SpacePolicy.PRESERVE),
            ParamMatch(optional=False).space(SpacePolicy.PRESERVE) @ "account_pid"
            # 示例: -bf服管账号 删除 123
        ]
    )
)
async def managerAccount_del(
        app: Ariadne, group: Group,
        account_pid: RegexResult, source: Source
):
    account_pid = account_pid.result.display
    account_info = await BF1ManagerAccount.get_account(account_pid)
    if not account_info:
        return await app.send_message(group, MessageChain(
            "未找到该服管账号!"
        ), quote=source)
    result = await BF1ManagerAccount.del_account(account_pid)
    if result:
        return await app.send_message(group, MessageChain(
            "删除成功!"
        ), quote=source)
    return await app.send_message(group, MessageChain(
        "删除失败,请检查后台数据库!"
    ), quote=source)


# 查询服管账号管理服务器
@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Function.require("modules.self_contained.bf1_info"),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level),
    Permission.user_require(Permission.BotAdmin, if_noticed=True),
)
@dispatch(
    Twilight(
        [
            UnionMatch("-bf服管账号", "-bfga").space(SpacePolicy.FORCE),
            UnionMatch("信息", "info").space(SpacePolicy.PRESERVE),
            ParamMatch(optional=False) @ "account_pid",
            # 示例: -bf服管账号 信息
        ]
    )
)
async def managerAccount_info(
        app: Ariadne, group: Group,
        account_pid: RegexResult, source: Source
):
    account_pid = account_pid.result.display
    account_info = await BF1ManagerAccount.get_account(account_pid)
    if not account_info:
        return await app.send_message(group, MessageChain(
            "未找到该服管账号!"
        ), quote=source)
    return await app.send_message(group, MessageChain(
        f"帐号名: {account_info['display_name']}\n"
        f"pid: {account_info['pid']}\n"
        f"uid: {account_info['uid']}\n"
        f"remid: {account_info['remid']}\n"
        f"sid: {account_info['sid']}\n"
        f"session: {account_info['session']}\n"
    ), quote=source)


# 群组服务器绑定服管账号
@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level),
    Permission.user_require(Permission.BotAdmin, if_noticed=True),
)
@dispatch(
    Twilight(
        [
            UnionMatch("-bf群组", "-bfg").space(SpacePolicy.PRESERVE),
            ParamMatch(optional=False).space(SpacePolicy.NOSPACE) @ "group_name",
            FullMatch("#", optional=False).space(SpacePolicy.NOSPACE),
            ParamMatch(optional=False).space(SpacePolicy.FORCE) @ "server_rank",
            UnionMatch("使用服管", "use").space(SpacePolicy.PRESERVE),
            ParamMatch(optional=False).space(SpacePolicy.PRESERVE) @ "account_pid",
            # 示例: -bf群组 sakula#1 使用服管pid
        ]
    )
)
async def bfgroup_bind_managerAccount(
        app: Ariadne, group: Group, source: Source,
        server_rank: RegexResult, account_pid: RegexResult, group_name: RegexResult
):
    group_name = group_name.result.display
    if not server_rank.result.display.isdigit():
        return await app.send_message(group, MessageChain(
            "服务器序号只能为数字\n例: -bf群组 sakula#1 使用服管pid"
        ), quote=source)
    server_rank = int(server_rank.result.display)
    if server_rank < 1 or server_rank > 30:
        return await app.send_message(group, MessageChain(
            "服务器序号只能在1~30内"
        ), quote=source)
    # 检查服务器信息
    group_info = await BF1GROUP.get_info(group_name)
    if isinstance(group_info, str):
        return await app.send_message(group, MessageChain(group_info), quote=source)
    if not group_info["bind_ids"][server_rank - 1]:
        return await app.send_message(group, MessageChain(
            f"群组[{group_name}]未绑定服务器序号 {server_rank} 的服务器"
        ), quote=source)

    # 检查帐号信息
    account_pid = account_pid.result.display
    account_info = await BF1ManagerAccount.get_account(account_pid)
    if not account_info:
        return await app.send_message(group, MessageChain(
            "未找到该服管账号!"
        ), quote=source)
    # {"guid": "1a9f5032-0cc0-4c0a-a83b-f229463ea39e", "gameId": "8460032230118", "serverId": "10667817", "account": null}
    group_guid = group_info["bind_ids"][server_rank - 1]["guid"]
    group_gameid = group_info["bind_ids"][server_rank - 1]["gameId"]
    group_serverid = group_info["bind_ids"][server_rank - 1]["serverId"]

    result = await BF1GROUP.bind_ids(
        group_name=group_name,
        index=server_rank,
        guid=group_guid,
        gameId=group_gameid,
        serverId=group_serverid,
        account_pid=account_pid
    )

    return await app.send_message(group, MessageChain(result), quote=source)


# 群组服务器绑定全部服管账号
@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level),
    Permission.user_require(Permission.BotAdmin, if_noticed=True),
)
@dispatch(
    Twilight(
        [
            UnionMatch("-bf群组", "-bfg").space(SpacePolicy.PRESERVE),
            ParamMatch(optional=False).space(SpacePolicy.FORCE) @ "group_name",
            UnionMatch("使用服管", "use").space(SpacePolicy.PRESERVE),
            ParamMatch(optional=False).space(SpacePolicy.PRESERVE) @ "account_pid",
            # 示例: -bf群组 sakula 使用服管pid
        ]
    )
)
async def bfgroup_bind_managerAccount_all(
        app: Ariadne, group: Group, source: Source,
        account_pid: RegexResult, group_name: RegexResult
):
    group_name = group_name.result.display
    if "#" in group_name:
        return
    # 检查服务器信息
    group_info = await BF1GROUP.get_info(group_name)
    if isinstance(group_info, str):
        return await app.send_message(group, MessageChain(group_info), quote=source)

    # 检查帐号信息
    account_pid = account_pid.result.display
    account_info = await BF1ManagerAccount.get_account(account_pid)
    if not account_info:
        return await app.send_message(group, MessageChain(
            "未找到该服管账号!"
        ), quote=source)

    # await BF1DB.bf1group.bind_bf1_group_id(group_name, 下标, guid, gameId, serverId, account_pid)
    for i, server in enumerate(group_info["bind_ids"]):
        if server:
            _ = await BF1GROUP.bind_ids(
                group_name=group_name,
                index=i,
                guid=server["guid"],
                gameId=server["gameId"],
                serverId=server["serverId"],
                account_pid=account_pid
            )

    return await app.send_message(group, MessageChain(f"群组[{group_name}]绑定服管帐号{account_pid}成功"), quote=source)


# 群组服务器解绑服管账号
@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level),
    Permission.user_require(Permission.BotAdmin, if_noticed=True),
)
@dispatch(
    Twilight(
        [
            UnionMatch("-bf群组", "-bfg").space(SpacePolicy.PRESERVE),
            ParamMatch(optional=False).space(SpacePolicy.FORCE) @ "group_name",
            FullMatch("#").space(SpacePolicy.NOSPACE),
            ParamMatch(optional=False).space(SpacePolicy.FORCE) @ "server_rank",
            FullMatch("解绑服管").space(SpacePolicy.PRESERVE),
            # 示例: -bf群组 sakula #1 解绑服管
        ]
    )
)
async def bfgroup_del_managerAccount(
        app: Ariadne, group: Group, source: Source,
        server_rank: RegexResult, group_name: RegexResult
):
    group_name = group_name.result.display
    if not server_rank.result.display.isdigit():
        return await app.send_message(group, MessageChain(
            "服务器序号只能为数字\n例: -bf群组 skl 绑服#1 gameid"
        ), quote=source)
    server_rank = int(server_rank.result.display)
    if server_rank < 1 or server_rank > 30:
        return await app.send_message(group, MessageChain(
            "服务器序号只能在1~30内"
        ), quote=source)
    # 检查服务器信息
    group_info = await BF1GROUP.get_info(group_name)
    if isinstance(group_info, str):
        return await app.send_message(group, MessageChain(group_info), quote=source)
    if not group_info["bind_ids"][server_rank - 1]:
        return await app.send_message(group, MessageChain(
            f"群组[{group_name}]未绑定服务器序号 {server_rank} 的服务器"
        ), quote=source)

    guid = group_info["bind_ids"][server_rank - 1]["guid"]
    gameId = group_info["bind_ids"][server_rank - 1]["gameId"]
    ServerId = group_info["bind_ids"][server_rank - 1]["serverId"]
    manager_account = None

    # 绑定
    _ = await BF1GROUP.bind_ids(
        group_name, server_rank, guid, gameId, ServerId, manager_account
    )
    return await app.send_message(group, MessageChain(f"群组[{group_name}]成功解绑服#{server_rank}服管"), quote=source)


# 解绑全部服管账号
@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level),
    Permission.user_require(Permission.BotAdmin, if_noticed=True),
)
@dispatch(
    Twilight(
        [
            UnionMatch("-bf群组", "-bfg").space(SpacePolicy.PRESERVE),
            ParamMatch(optional=False).space(SpacePolicy.FORCE) @ "group_name",
            FullMatch("解绑服管").space(SpacePolicy.PRESERVE),
            # 示例: -bf群组 sakula 解绑服管
        ]
    )
)
async def bfgroup_del_managerAccount_all(
        app: Ariadne, group: Group, source: Source,
        group_name: RegexResult
):
    group_name = group_name.result.display
    # 检查服务器信息
    group_info = await BF1GROUP.get_info(group_name)
    if isinstance(group_info, str):
        return await app.send_message(group, MessageChain(group_info), quote=source)
    for i, server in enumerate(group_info["bind_ids"]):
        if server:
            guid = server["guid"]
            gameId = server["gameId"]
            ServerId = server["serverId"]
            manager_account = None
            # 绑定
            _ = await BF1GROUP.bind_ids(
                group_name, i + 1, guid, gameId, ServerId, manager_account
            )
    return await app.send_message(group, MessageChain(f"群组[{group_name}]成功解绑服管"), quote=source)


# 查日志
@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level),
    Permission.user_require(Permission.User, if_noticed=True),
)
@dispatch(
    Twilight(
        [
            FullMatch("-bflog").space(SpacePolicy.PRESERVE),
            ParamMatch(optional=True).space(SpacePolicy.NOSPACE) @ "bf_group_name",
            RegexMatch(r"[0-9]+", optional=True).space(SpacePolicy.PRESERVE) @ "member_id",
            UnionMatch(
                "踢出", "封禁", "解封", "上v", "下v", "换图", "玩家", optional=True
            ).space(SpacePolicy.PRESERVE) @ "action",
            ParamMatch(optional=True).space(SpacePolicy.PRESERVE) @ "action_object"
            # 示例: -bf群组 sakula 日志 1257661006 踢出 shlsan13
        ]
    )
)
async def bfgroup_search_log(
        app: Ariadne, sender: Member, group: Group, source: Source,
        group_name: RegexResult, member_id: RegexResult, action: RegexResult,
        action_object: RegexResult
):
    # TODO: 重构为数据库查询
    ...


# 刷新session
@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level),
    Permission.user_require(Permission.GroupAdmin, if_noticed=True),
)
@dispatch(
    Twilight(
        [
            FullMatch("-refresh").space(SpacePolicy.PRESERVE),
            ParamMatch(optional=True).space(SpacePolicy.NOSPACE) @ "bf_group_name",
            FullMatch("#", optional=True).space(SpacePolicy.NOSPACE),
            ParamMatch(optional=False) @ "server_rank",
            # 示例: -refresh
        ]
    )
)
async def bfgroup_refresh(
        app: Ariadne, group: Group, sender: Member, source: Source,
        server_rank: RegexResult, bf_group_name: RegexResult
):
    # 服务器序号检查
    if server_rank.matched:
        server_rank = server_rank.result.display
        if not server_rank.isdigit():
            return await app.send_message(group, MessageChain("请输入正确的服务器序号"), quote=source)
        server_rank = int(server_rank)
        if server_rank < 1 or server_rank > 30:
            return await app.send_message(group, MessageChain("服务器序号只能在1~30内"), quote=source)
    else:
        server_rank = 1

    # 获取群组信息
    bf_group_name = bf_group_name.result.display if bf_group_name and bf_group_name.matched else None
    if not bf_group_name:
        bf1_group_info = await BF1GROUP.get_bf1Group_byQQ(group.id)
        if not bf1_group_info:
            return await app.send_message(group, MessageChain("请先绑定BF1群组/指定群组名"), quote=source)
        bf_group_name = bf1_group_info.get("group_name")

    if not await perm_judge(bf_group_name, group, sender):
        return await app.send_message(
            group,
            MessageChain(f"您不是群组[{bf_group_name}]的成员"),
            quote=source,
        )
    server_info = await BF1GROUP.get_bindInfo_byIndex(bf_group_name, server_rank)
    if not server_info:
        return await app.send_message(group, MessageChain(
            f"群组[{bf_group_name}]未绑定服务器{server_rank}"
        ), quote=source)
    elif isinstance(server_info, str):
        return await app.send_message(group, MessageChain(server_info), quote=source)
    if not server_info["account"]:
        return await app.send_message(group, MessageChain(
            f"群组{bf_group_name}服务器{server_rank}未绑定服管账号，请先绑定服管账号！"
        ), quote=source)
    account_instance = await BF1ManagerAccount.get_manager_account_instance(server_info["account"])
    no_valid = await account_instance.check_session_expire()
    if no_valid:
        await account_instance.login(account_instance.remid, account_instance.sid)
    return await app.send_message(group, MessageChain(
        f"群组{bf_group_name}服务器{server_rank}服管号登录成功" if account_instance.check_login else f"群组{bf_group_name}服务器{server_rank}服管号登录失败"
    ), quote=source)


# 服管功能:  指定服务器序号版 1.踢人 2.封禁/解封 3.换边 4.换图 5.vip

# 踢人
@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Permission.group_require(channel.metadata.level),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.user_require(Permission.User, if_noticed=True),
)
@dispatch(
    Twilight(
        [
            UnionMatch("-kick", "-踢", "-k", "-滚出").space(SpacePolicy.PRESERVE),
            ParamMatch(optional=True).space(SpacePolicy.NOSPACE) @ "bf_group_name",
            FullMatch("#", optional=True).space(SpacePolicy.NOSPACE),
            ParamMatch(optional=False).space(SpacePolicy.FORCE) @ "server_rank",
            ParamMatch(optional=False).space(SpacePolicy.PRESERVE) @ "player_name",
            WildcardMatch(optional=True) @ "reason",
            # 示例: -k sakula#1 xiao7xiao test
        ]
    )
)
async def kick(
        app: Ariadne, sender: Member, group: Group, source: Source,
        bf_group_name: RegexResult, server_rank: RegexResult, player_name: RegexResult, reason: RegexResult
):
    # 服务器序号检查
    server_rank = server_rank.result.display
    if not server_rank.isdigit():
        return await app.send_message(group, MessageChain("请输入正确的服务器序号"), quote=source)
    server_rank = int(server_rank)
    if server_rank < 1 or server_rank > 30:
        return await app.send_message(group, MessageChain("服务器序号只能在1~30内"), quote=source)

    # 获取群组信息
    bf_group_name = bf_group_name.result.display if bf_group_name and bf_group_name.matched else None
    if not bf_group_name:
        bf1_group_info = await BF1GROUP.get_bf1Group_byQQ(group.id)
        if not bf1_group_info:
            return await app.send_message(group, MessageChain("请先绑定BF1群组/指定群组名"), quote=source)
        bf_group_name = bf1_group_info.get("group_name")

    if not await perm_judge(bf_group_name, group, sender):
        return await app.send_message(
            group,
            MessageChain(f"您不是群组[{bf_group_name}]的成员"),
            quote=source,
        )
    server_info = await BF1GROUP.get_bindInfo_byIndex(bf_group_name, server_rank)
    if not server_info:
        return await app.send_message(group, MessageChain(
            f"群组[{bf_group_name}]未绑定服务器{server_rank}"
        ), quote=source)
    elif isinstance(server_info, str):
        return await app.send_message(group, MessageChain(server_info), quote=source)
    server_id = server_info["serverId"]
    server_gameid = server_info["gameId"]
    server_guid = server_info["guid"]

    # 原因检测
    if (not reason.matched) or (reason.result.display == ""):
        reason = "违反规则"
    else:
        reason = reason.result.display.replace("ADMINPRIORITY", "违反规则")
    reason = zhconv.convert(reason, 'zh-tw')
    if ("空間" or "寬帶" or "帶寬" or "網絡" or "錯誤代碼" or "位置") in reason:
        await app.send_message(group, MessageChain(
            "操作失败:踢出原因包含违禁词"
        ), quote=source)
        return False
    # 字数检测
    if 30 < len(reason.encode("utf-8")):
        return await app.send_message(group, MessageChain(
            "原因字数过长(汉字10个以内)"
        ), quote=source)

    # 查验玩家是否存在
    player_name = player_name.result.display
    player_info = await get_personas_by_name(player_name)
    if isinstance(player_info, str):
        return await app.send_message(
            group,
            MessageChain(f"查询出错!{player_info}"),
            quote=source
        )
    if not player_info:
        return await app.send_message(
            group,
            MessageChain(f"玩家 {player_name} 不存在"),
            quote=source
        )
    pid = player_info["personas"]["persona"][0]["personaId"]
    # uid = player_info["personas"]["persona"][0]["pidId"]
    player_name = player_info["personas"]["persona"][0]["displayName"]

    # 获取服管账号实例
    if not server_info["account"]:
        return await app.send_message(group, MessageChain(
            f"群组{bf_group_name}服务器{server_rank}未绑定服管账号，请先绑定服管账号!"
        ), quote=source)
    account_instance = await BF1ManagerAccount.get_manager_account_instance(server_info["account"])

    # 踢出玩家
    star_time = time.time()
    result = await account_instance.kickPlayer(gameId=server_gameid, personaId=pid, reason=reason)
    end_time = time.time()
    logger.debug(f"踢人耗时:{(end_time - star_time):.2f}秒")

    if isinstance(result, dict):
        await app.send_message(group, MessageChain(
            f"踢出成功!原因:{reason}"
        ), quote=source)
        # 日志记录
        await BF1Log.record(
            operator_qq=sender.id,
            serverId=server_id,
            persistedGameId=server_guid,
            gameId=server_gameid,
            pid=pid,
            display_name=player_name,
            action="kick",
            info=reason,
        )
        return
    return await app.send_message(group, MessageChain(
        f"执行出错!{result}"
    ), quote=source)


# TODO: 待重构
@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level),
    Permission.user_require(Permission.User, if_noticed=True),
)
@dispatch(
    Twilight(
        [
            UnionMatch("-sk").space(SpacePolicy.FORCE),
            ParamMatch(optional=False).space(SpacePolicy.PRESERVE) @ "player_name",
            WildcardMatch(optional=True) @ "reason",
            # 示例: -sk xiao7xiao test
        ]
    )
)
async def kick_by_searched(
        app: Ariadne, sender: Member, group: Group, source: Source,
        action: RegexResult, player_name: RegexResult, reason: RegexResult
):
    return


# 封禁
@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level),
    Permission.user_require(Permission.User, if_noticed=True),
)
@dispatch(
    Twilight(
        [
            UnionMatch("-ban", "-封禁").space(SpacePolicy.PRESERVE),
            ParamMatch(optional=True).space(SpacePolicy.NOSPACE) @ "bf_group_name",
            FullMatch("#", optional=True).space(SpacePolicy.NOSPACE),
            ParamMatch(optional=False).space(SpacePolicy.FORCE) @ "server_rank",
            ParamMatch(optional=False).space(SpacePolicy.PRESERVE) @ "player_name",
            WildcardMatch(optional=True) @ "reason",
            # 示例: -b#1 xiao7xiao test
        ]
    )
)
async def add_ban(
        app: Ariadne, sender: Member, group: Group, source: Source,
        bf_group_name: RegexResult, server_rank: RegexResult, player_name: RegexResult, reason: RegexResult
):
    # 指令冲突相应
    if bf_group_name.matched and bf_group_name.result.display in ["list", "列表", "l", "列", "lis", "li"]:
        return
    if bf_group_name.matched:
        if bf_group_name.result.display.startswith("f群"):
            return
        elif bf_group_name.result.display in ["al"]:
            return
        elif bf_group_name.result.display.startswith("in"):
            return
        elif bf_group_name.result.display.startswith("f1百"):
            return
        logger.debug(f"群组名:{bf_group_name.result.display}")

    # 服务器序号检查
    server_rank = server_rank.result.display
    if not server_rank.isdigit():
        return await app.send_message(group, MessageChain("请输入正确的服务器序号"), quote=source)
    server_rank = int(server_rank)
    if server_rank < 1 or server_rank > 30:
        return await app.send_message(group, MessageChain("服务器序号只能在1~30内"), quote=source)

    # 获取群组信息
    bf_group_name = bf_group_name.result.display if bf_group_name and bf_group_name.matched else None
    if not bf_group_name:
        bf1_group_info = await BF1GROUP.get_bf1Group_byQQ(group.id)
        if not bf1_group_info:
            return await app.send_message(group, MessageChain("请先绑定BF1群组/指定群组名"), quote=source)
        bf_group_name = bf1_group_info.get("group_name")

    if not await perm_judge(bf_group_name, group, sender):
        return await app.send_message(
            group,
            MessageChain(f"您不是群组[{bf_group_name}]的成员"),
            quote=source,
        )
    server_info = await BF1GROUP.get_bindInfo_byIndex(bf_group_name, server_rank)
    if not server_info:
        return await app.send_message(group, MessageChain(
            f"群组[{bf_group_name}]未绑定服务器{server_rank}"
        ), quote=source)
    elif isinstance(server_info, str):
        return await app.send_message(group, MessageChain(server_info), quote=source)
    server_id = server_info["serverId"]
    server_gameid = server_info["gameId"]
    server_guid = server_info["guid"]

    # 原因检测
    if (not reason.matched) or (reason.result.display == ""):
        reason = "违反规则"
    else:
        reason = reason.result.display
    reason = zhconv.convert(reason, 'zh-tw')
    # 字数检测
    if 150 < len(reason.encode("utf-8")):
        return await app.send_message(group, MessageChain(
            "原因字数过长(汉字50个以内)"
        ), quote=source)

    # 查验玩家是否存在
    player_name = player_name.result.display
    player_info = await get_personas_by_name(player_name)
    if isinstance(player_info, str):
        return await app.send_message(
            group,
            MessageChain(f"查询出错!{player_info}"),
            quote=source
        )
    if not player_info:
        return await app.send_message(
            group,
            MessageChain(f"玩家 {player_name} 不存在"),
            quote=source
        )
    pid = player_info["personas"]["persona"][0]["personaId"]
    # uid = player_info["personas"]["persona"][0]["pidId"]
    player_name = player_info["personas"]["persona"][0]["displayName"]

    # 获取服管账号实例
    if not server_info["account"]:
        return await app.send_message(group, MessageChain(
            f"群组{bf_group_name}服务器{server_rank}未绑定服管账号，请先绑定服管账号!"
        ), quote=source)
    account_instance = await BF1ManagerAccount.get_manager_account_instance(server_info["account"])

    # 获取封禁列表查询玩家是否已经在封禁列表了
    server_info = await account_instance.getFullServerDetails(server_gameid)
    if isinstance(server_info, str):
        return await app.send_message(
            group,
            MessageChain(f"查询封禁信息时出错!{server_info}"),
            quote=source
        )
    server_info = server_info["result"]
    ban_list = [f"{item['personaId']}" for item in server_info["rspInfo"]["bannedList"]]
    if str(pid) in ban_list:
        return await app.send_message(group, MessageChain(
            f"玩家 {player_name} 已经在封禁列表中了!",
        ), quote=source)

    # 封禁玩家
    star_time = time.time()
    result = await account_instance.addServerBan(personaId=pid, serverId=server_id)
    end_time = time.time()
    logger.debug(f"封禁耗时:{(end_time - star_time):.2f}秒")

    if isinstance(result, dict):
        await app.send_message(group, MessageChain(
            f"封禁成功!原因:{reason}"
        ), quote=source)
        # 日志记录
        await BF1Log.record(
            operator_qq=sender.id,
            serverId=server_id,
            persistedGameId=server_guid,
            gameId=server_gameid,
            pid=pid,
            display_name=player_name,
            action="ban",
            info=reason,
        )
        return
    return await app.send_message(group, MessageChain(
        f"执行出错!{result}"
    ), quote=source)


# 解封
@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level),
    Permission.user_require(Permission.User, if_noticed=True),
)
@dispatch(
    Twilight(
        [
            UnionMatch("-unban", "-uban", "-解封").space(SpacePolicy.PRESERVE),
            ParamMatch(optional=True).space(SpacePolicy.NOSPACE) @ "bf_group_name",
            FullMatch("#", optional=True).space(SpacePolicy.NOSPACE),
            ParamMatch(optional=False).space(SpacePolicy.FORCE) @ "server_rank",
            ParamMatch(optional=False).space(SpacePolicy.PRESERVE) @ "player_name",
            # 示例: -unban all1 shlsan13
        ]
    )
)
async def del_ban(
        app: Ariadne, sender: Member, group: Group, source: Source,
        bf_group_name: RegexResult, server_rank: RegexResult, player_name: RegexResult
):
    # 服务器序号检查
    server_rank = server_rank.result.display
    if not server_rank.isdigit():
        return await app.send_message(group, MessageChain("请输入正确的服务器序号"), quote=source)
    server_rank = int(server_rank)
    if server_rank < 1 or server_rank > 30:
        return await app.send_message(group, MessageChain("服务器序号只能在1~30内"), quote=source)

    # 获取群组信息
    bf_group_name = bf_group_name.result.display if bf_group_name and bf_group_name.matched else None
    if not bf_group_name:
        bf1_group_info = await BF1GROUP.get_bf1Group_byQQ(group.id)
        if not bf1_group_info:
            return await app.send_message(group, MessageChain("请先绑定BF1群组/指定群组名"), quote=source)
        bf_group_name = bf1_group_info.get("group_name")

    if not await perm_judge(bf_group_name, group, sender):
        return await app.send_message(
            group,
            MessageChain(f"您不是群组[{bf_group_name}]的成员"),
            quote=source,
        )
    server_info = await BF1GROUP.get_bindInfo_byIndex(bf_group_name, server_rank)
    if not server_info:
        return await app.send_message(group, MessageChain(
            f"群组[{bf_group_name}]未绑定服务器{server_rank}"
        ), quote=source)
    elif isinstance(server_info, str):
        return await app.send_message(group, MessageChain(server_info), quote=source)
    server_id = server_info["serverId"]
    server_gameid = server_info["gameId"]
    server_guid = server_info["guid"]

    # 查验玩家是否存在
    player_name = player_name.result.display
    player_info = await get_personas_by_name(player_name)
    if isinstance(player_info, str):
        return await app.send_message(
            group,
            MessageChain(f"查询出错!{player_info}"),
            quote=source
        )
    if not player_info:
        return await app.send_message(
            group,
            MessageChain(f"玩家 {player_name} 不存在"),
            quote=source
        )
    pid = player_info["personas"]["persona"][0]["personaId"]
    # uid = player_info["personas"]["persona"][0]["pidId"]
    player_name = player_info["personas"]["persona"][0]["displayName"]

    # 获取服管账号实例
    if not server_info["account"]:
        return await app.send_message(group, MessageChain(
            f"群组{bf_group_name}服务器{server_rank}未绑定服管账号，请先绑定服管账号!"
        ), quote=source)
    account_instance = await BF1ManagerAccount.get_manager_account_instance(server_info["account"])

    # 获取封禁列表查询玩家是否已经在封禁列表了
    server_info = await account_instance.getFullServerDetails(server_gameid)
    if isinstance(server_info, str):
        return await app.send_message(
            group,
            MessageChain(f"查询封禁信息时出错!{server_info}"),
            quote=source
        )
    server_info = server_info["result"]
    ban_list = [f"{item['personaId']}" for item in server_info["rspInfo"]["bannedList"]]
    if str(pid) not in ban_list:
        return await app.send_message(group, MessageChain(
            f"玩家 {player_name} 不在封禁列表中!",
        ), quote=source)

    # 封禁玩家
    star_time = time.time()
    result = await account_instance.removeServerBan(personaId=pid, serverId=server_id)
    end_time = time.time()
    logger.debug(f"解封耗时:{(end_time - star_time):.2f}秒")

    if isinstance(result, dict):
        await app.send_message(group, MessageChain(
            f"解封成功!"
        ), quote=source)
        # 日志记录
        await BF1Log.record(
            operator_qq=sender.id,
            serverId=server_id,
            persistedGameId=server_guid,
            gameId=server_gameid,
            pid=pid,
            display_name=player_name,
            action="ban",
            info="解封",
        )
        return
    return await app.send_message(group, MessageChain(
        f"执行出错!{result}"
    ), quote=source)


# banall
@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level),
    Permission.user_require(Permission.User, if_noticed=True),
)
@dispatch(
    Twilight(
        [
            UnionMatch("-banall", "-ba").space(SpacePolicy.FORCE),
            ParamMatch(optional=False).space(SpacePolicy.FORCE) @ "bf_group_name",
            ParamMatch(optional=False).space(SpacePolicy.PRESERVE) @ "player_name",
            WildcardMatch(optional=True) @ "reason",
            # 示例: -banall (sakula) xiaoxiao test
        ]
    )
)
async def add_banall(
        app: Ariadne, sender: Member, group: Group, source: Source,
        bf_group_name: RegexResult, player_name: RegexResult, reason: RegexResult
):
    # 获取群组信息
    bf_group_name = bf_group_name.result.display if bf_group_name and bf_group_name.matched else None
    if not bf_group_name:
        bf1_group_info = await BF1GROUP.get_bf1Group_byQQ(group.id)
        if not bf1_group_info:
            return await app.send_message(group, MessageChain("请先绑定BF1群组/指定群组名"), quote=source)
        bf_group_name = bf1_group_info.get("group_name")

    if not await perm_judge(bf_group_name, group, sender):
        return await app.send_message(
            group,
            MessageChain(f"您不是群组[{bf_group_name}]的成员"),
            quote=source,
        )
    server_info = await BF1GROUP.get_info(bf_group_name)
    if isinstance(server_info, str):
        return await app.send_message(group, MessageChain(f"{server_info} 使用banall时必须指定群组名且不加服务器序号!"), quote=source)
    task_list = []
    for i, id_item in enumerate(server_info["bind_ids"]):
        if not id_item:
            task_list.append(None)
            continue
        if not id_item['account']:
            task_list.append("未绑定服管账号")
            continue
        task_list.append({
            "guid": id_item['guid'],
            "sid": id_item['serverId'],
            "gid": id_item['gameId'],
            "account:": id_item['account'],
            "instance": await BF1ManagerAccount.get_manager_account_instance(id_item["account"]),
            "result": None,
        })

    # 原因检测
    if (not reason.matched) or (reason.result.display == ""):
        reason = "违反规则"
    else:
        reason = reason.result.display
    # 字数检测
    if 300 < len(reason.encode("utf-8")):
        return await app.send_message(group, MessageChain(
            "原因字数过长(汉字100个以内)"
        ), quote=source)

    # 查验玩家是否存在
    player_name = player_name.result.display
    player_info = await get_personas_by_name(player_name)
    if isinstance(player_info, str):
        return await app.send_message(
            group,
            MessageChain(f"查询出错!{player_info}"),
            quote=source
        )
    if not player_info:
        return await app.send_message(
            group,
            MessageChain(f"玩家 {player_name} 不存在"),
            quote=source
        )
    pid = player_info["personas"]["persona"][0]["personaId"]
    # uid = player_info["personas"]["persona"][0]["pidId"]
    player_name = player_info["personas"]["persona"][0]["displayName"]

    # 将有实例的任务进行并发并把结果写入对应的result的位置

    start_time = time.time()
    # 获取封禁列表查询玩家是否已经在封禁列表中
    server_info_task = []
    for i, item in enumerate(task_list):
        if isinstance(item, dict):
            server_info_task.append((i, item["instance"].RSPgetServerDetails(item["sid"])))
        else:
            server_info_task.append((i, asyncio.ensure_future(dummy_coroutine())))
    server_info_task_results = await asyncio.gather(*[task for _, task in server_info_task])
    logger.debug(f"查询任务信息耗时: {time.time() - start_time}")
    # 循环依次把结果写入到对应的result的位置
    for index, result in enumerate(server_info_task_results):
        if isinstance(server_info_task_results[index], dict):
            server_info_temp = server_info_task_results[index]["result"]
            if not server_info_temp:
                task_list[index] = "服务器信息为空!"
            else:
                ban_list = [f"{item['personaId']}" for item in server_info_temp["bannedList"]]
                if str(pid) in ban_list:
                    task_list[index] = "该玩家已经在封禁列表中"
        elif server_info_task_results[index] is not None:
            task_list[index] = result
            logger.debug(f"{index} {result}")
    # 处理封禁逻辑
    ban_task = []
    for i, item in enumerate(task_list):
        if isinstance(item, dict) and not item["result"]:
            ban_task.append((i, item["instance"].addServerBan(personaId=pid, serverId=item["sid"])))
        else:
            ban_task.append((i, asyncio.ensure_future(dummy_coroutine())))
    ban_task_results = await asyncio.gather(*[task for _, task in ban_task])
    # 循环依次把结果写入到对应的result的位置
    for index, result in enumerate(ban_task_results):
        if isinstance(ban_task_results[index], dict):
            task_list[index]["result"] = result
        elif ban_task_results[index] is not None:
            task_list[index] = result

    # 封禁玩家
    end_time = time.time()
    logger.debug(f"封禁耗时:{(end_time - start_time):.2f}秒")

    send = []
    for i, result in enumerate(task_list):
        if isinstance(result, dict) and isinstance(result["result"], dict):
            send.append(f"{i + 1}服: 封禁成功!")
            # 日志记录
            await BF1Log.record(
                operator_qq=sender.id,
                serverId=result["sid"],
                persistedGameId=result["guid"],
                gameId=result["gid"],
                pid=pid,
                display_name=player_name,
                action="ban",
                info=reason,
            )
        elif isinstance(result, str):
            send.append(f"{i + 1}服: {result}")
    send.append(f"封禁原因: {reason}")
    send = "\n".join(send)
    if not send:
        return await app.send_message(group, MessageChain(
            "封禁出现未知错误!(查询服务器失败/服管号失效)"
        ), quote=source)
    await app.send_message(group, MessageChain(
        send
    ), quote=source)


# unbanll
@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level),
    Permission.user_require(Permission.User, if_noticed=True),
)
@dispatch(
    Twilight(
        [
            UnionMatch("-unbanall", "-uba").space(SpacePolicy.FORCE),
            ParamMatch(optional=False).space(SpacePolicy.FORCE) @ "bf_group_name",
            ParamMatch(optional=False) @ "player_name",
            # 示例: -unbanall xiaoxiao
        ]
    )
)
async def del_banall(
        app: Ariadne, sender: Member, group: Group, source: Source,
        bf_group_name: RegexResult, player_name: RegexResult
):
    # 获取群组信息
    bf_group_name = bf_group_name.result.display if bf_group_name and bf_group_name.matched else None
    if not bf_group_name:
        bf1_group_info = await BF1GROUP.get_bf1Group_byQQ(group.id)
        if not bf1_group_info:
            return await app.send_message(group, MessageChain("请先绑定BF1群组/指定群组名"), quote=source)
        bf_group_name = bf1_group_info.get("group_name")

    if not await perm_judge(bf_group_name, group, sender):
        return await app.send_message(
            group,
            MessageChain(f"您不是群组[{bf_group_name}]的成员"),
            quote=source,
        )
    server_info = await BF1GROUP.get_info(bf_group_name)
    if isinstance(server_info, str):
        return await app.send_message(group, MessageChain(f"{server_info} 使用unbanall时必须指定群组名且不加服务器序号!"), quote=source)
    task_list = []
    for i, id_item in enumerate(server_info["bind_ids"]):
        if not id_item:
            task_list.append(None)
            continue
        if not id_item['account']:
            task_list.append("未绑定服管账号")
            continue
        task_list.append({
            "guid": id_item['guid'],
            "sid": id_item['serverId'],
            "gid": id_item['gameId'],
            "account:": id_item['account'],
            "instance": await BF1ManagerAccount.get_manager_account_instance(id_item["account"]),
            "result": None,
        })

    # 查验玩家是否存在
    player_name = player_name.result.display
    player_info = await get_personas_by_name(player_name)
    if isinstance(player_info, str):
        return await app.send_message(
            group,
            MessageChain(f"查询出错!{player_info}"),
            quote=source
        )
    if not player_info:
        return await app.send_message(
            group,
            MessageChain(f"玩家 {player_name} 不存在"),
            quote=source
        )
    pid = player_info["personas"]["persona"][0]["personaId"]
    # uid = player_info["personas"]["persona"][0]["pidId"]
    player_name = player_info["personas"]["persona"][0]["displayName"]

    # 将有实例的任务进行并发并把结果写入对应的result的位置

    start_time = time.time()
    # 获取封禁列表查询玩家是否已经在封禁列表中
    server_info_task = []
    for i, item in enumerate(task_list):
        if isinstance(item, dict):
            server_info_task.append((i, item["instance"].RSPgetServerDetails(item["sid"])))
        else:
            server_info_task.append((i, asyncio.ensure_future(dummy_coroutine())))
    server_info_task_results = await asyncio.gather(*[task for _, task in server_info_task])
    logger.debug(f"查询任务信息耗时: {time.time() - start_time}")
    # 循环依次把结果写入到对应的result的位置
    for index, result in enumerate(server_info_task_results):
        if isinstance(server_info_task_results[index], dict):
            server_info_temp = server_info_task_results[index]["result"]
            if not server_info_temp:
                task_list[index] = "服务器信息为空!"
            else:
                ban_list = [f"{item['personaId']}" for item in server_info_temp["bannedList"]]
                if str(pid) not in ban_list:
                    task_list[index] = "该玩家不在封禁列表中"
        elif server_info_task_results[index] is not None:
            task_list[index] = result
            logger.debug(f"{index} {result}")
    # 处理封禁逻辑
    ban_task = []
    for i, item in enumerate(task_list):
        if isinstance(item, dict) and not item["result"]:
            ban_task.append((i, item["instance"].removeServerBan(personaId=pid, serverId=item["sid"])))
        else:
            ban_task.append((i, asyncio.ensure_future(dummy_coroutine())))
    ban_task_results = await asyncio.gather(*[task for _, task in ban_task])
    # 循环依次把结果写入到对应的result的位置
    for index, result in enumerate(ban_task_results):
        if isinstance(ban_task_results[index], dict):
            task_list[index]["result"] = result
        elif ban_task_results[index] is not None:
            task_list[index] = result

    # 封禁玩家
    end_time = time.time()
    logger.debug(f"解封耗时:{(end_time - start_time):.2f}秒")

    send = []
    for i, result in enumerate(task_list):
        if isinstance(result, dict) and isinstance(result["result"], dict):
            send.append(f"{i + 1}服: 解封成功!")
            # 日志记录
            await BF1Log.record(
                operator_qq=sender.id,
                serverId=result["sid"],
                persistedGameId=result["guid"],
                gameId=result["gid"],
                pid=pid,
                display_name=player_name,
                action="unban",
                info="解封",
            )
        elif isinstance(result, str):
            send.append(f"{i + 1}服: {result}")
    send = "\n".join(send)
    if not send:
        return await app.send_message(group, MessageChain(
            "解封出现未知错误!(查询服务器失败/服管号失效)"
        ), quote=source)
    await app.send_message(group, MessageChain(
        send
    ), quote=source)


# checkban
@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level),
    Permission.user_require(Permission.GroupAdmin, if_noticed=True),
)
@dispatch(
    Twilight(
        [
            UnionMatch("-checkban").space(SpacePolicy.PRESERVE),
            ParamMatch(optional=True).space(SpacePolicy.FORCE) @ "bf_group_name",
            ParamMatch(optional=True).space(SpacePolicy.PRESERVE) @ "player_name"
            # 示例: -checkban sakula xiaoxiao
        ]
    )
)
async def check_ban(
        app: Ariadne, sender: Member, group: Group, source: Source,
        bf_group_name: RegexResult, player_name: RegexResult
):
    # 获取群组信息
    bf_group_name = bf_group_name.result.display if bf_group_name and bf_group_name.matched else None
    if not bf_group_name:
        bf1_group_info = await BF1GROUP.get_bf1Group_byQQ(group.id)
        if not bf1_group_info:
            return await app.send_message(group, MessageChain("请先绑定BF1群组/指定群组名"), quote=source)
        bf_group_name = bf1_group_info.get("group_name")

    if not await perm_judge(bf_group_name, group, sender):
        return await app.send_message(
            group,
            MessageChain(f"您不是群组[{bf_group_name}]的成员"),
            quote=source,
        )
    server_info = await BF1GROUP.get_info(bf_group_name)
    if isinstance(server_info, str):
        return await app.send_message(group, MessageChain(f"{server_info} 使用unbanall时必须指定群组名且不加服务器序号!"), quote=source)
    id_list = []
    for i, id_item in enumerate(server_info["bind_ids"]):
        if not id_item:
            id_list.append(None)
            continue
        id_list.append({
            "guid": id_item['guid'],
            "sid": id_item['serverId'],
            "gid": id_item['gameId'],
            "account:": id_item['account'],
            "result": None,
        })

    # 查验玩家是否存在
    player_name = player_name.result.display
    player_info = await get_personas_by_name(player_name)
    if isinstance(player_info, str):
        return await app.send_message(
            group,
            MessageChain(f"查询出错!{player_info}"),
            quote=source
        )
    if not player_info:
        return await app.send_message(
            group,
            MessageChain(f"玩家 {player_name} 不存在"),
            quote=source
        )
    pid = player_info["personas"]["persona"][0]["personaId"]
    # uid = player_info["personas"]["persona"][0]["pidId"]
    player_name = player_info["personas"]["persona"][0]["displayName"]

    server_info_task = []
    for i, item in enumerate(id_list):
        if isinstance(item, dict):
            server_info_task.append((i, (await BF1DA.get_api_instance()).getFullServerDetails(item["gid"])))
        else:
            server_info_task.append((i, asyncio.ensure_future(dummy_coroutine())))
    server_info_task_results = await asyncio.gather(*[task for _, task in server_info_task])
    # 循环依次把结果写入到对应的result的位置
    for index, result in enumerate(server_info_task_results):
        if isinstance(server_info_task_results[index], dict):
            server_info_temp = server_info_task_results[index]["result"]
            if not isinstance(server_info_temp, dict):
                id_list[index]["result"] = f"查询失败{server_info_temp}"
            else:
                ban_pid_list = [f"{item['personaId']}" for item in server_info_temp["rspInfo"]["bannedList"]]
                if str(pid) in ban_pid_list:
                    id_list[index]["result"] = f"已封禁"
                else:
                    id_list[index]["result"] = f"未封禁"
    send = []
    for i, item in enumerate(id_list):
        if isinstance(item, dict):
            send.append(f"{i + 1}服: {item['result']}")
    send = "\n".join(send)
    if not send:
        return await app.send_message(group, MessageChain(
            "查询出现未知错误!(查询服务器失败/服务器未绑定)"
        ), quote=source)
    await app.send_message(group, MessageChain(
        send
    ), quote=source)


# 清理ban位
@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level),
    Permission.user_require(Permission.User, if_noticed=True),
)
@dispatch(
    Twilight(
        [
            UnionMatch("-清理ban位", "-清ban").space(SpacePolicy.PRESERVE),
            ParamMatch(optional=True).space(SpacePolicy.NOSPACE) @ "bf_group_name",
            FullMatch("#", optional=True).space(SpacePolicy.NOSPACE),
            ParamMatch(optional=False).space(SpacePolicy.FORCE) @ "server_rank",
            ParamMatch(optional=True).space(SpacePolicy.PRESERVE) @ "clear_num",
            # 示例: -清ban#
        ]
    )
)
async def clear_ban(
        app: Ariadne, sender: Member, group: Group, source: Source,
        bf_group_name: RegexResult, server_rank: RegexResult, clear_num: RegexResult
):
    # 数量检查
    if clear_num.matched:
        clear_num = clear_num.result.display
        if not clear_num.isdigit():
            return await app.send_message(group, MessageChain("请输入正确的数量(1~200)!"), quote=source)
        clear_num = int(clear_num)
        if clear_num < 1 or clear_num > 200:
            return await app.send_message(group, MessageChain("请输入正确的数量(1~200)!"), quote=source)
    else:
        clear_num = 200

    # 服务器序号检查
    server_rank = server_rank.result.display
    if not server_rank.isdigit():
        return await app.send_message(group, MessageChain("请输入正确的服务器序号"), quote=source)
    server_rank = int(server_rank)
    if server_rank < 1 or server_rank > 30:
        return await app.send_message(group, MessageChain("服务器序号只能在1~30内"), quote=source)

    # 获取群组信息
    bf_group_name = bf_group_name.result.display if bf_group_name and bf_group_name.matched else None
    if not bf_group_name:
        bf1_group_info = await BF1GROUP.get_bf1Group_byQQ(group.id)
        if not bf1_group_info:
            return await app.send_message(group, MessageChain("请先绑定BF1群组/指定群组名"), quote=source)
        bf_group_name = bf1_group_info.get("group_name")

    if not await perm_judge(bf_group_name, group, sender):
        return await app.send_message(
            group,
            MessageChain(f"您不是群组[{bf_group_name}]的成员"),
            quote=source,
        )

    server_info = await BF1GROUP.get_bindInfo_byIndex(bf_group_name, server_rank)
    if not server_info:
        return await app.send_message(group, MessageChain(
            f"群组[{bf_group_name}]未绑定服务器{server_rank}"
        ), quote=source)
    elif isinstance(server_info, str):
        return await app.send_message(group, MessageChain(server_info), quote=source)
    server_id = server_info["serverId"]
    server_gameid = server_info["gameId"]
    server_guid = server_info["guid"]

    # 获取服管账号实例
    if not server_info["account"]:
        return await app.send_message(group, MessageChain(
            f"群组{bf_group_name}服务器{server_rank}未绑定服管账号，请先绑定服管账号!"
        ), quote=source)
    account_instance = await BF1ManagerAccount.get_manager_account_instance(server_info["account"])

    # 获取服务器信息-fullInfo
    server_fullInfo = await account_instance.getFullServerDetails(server_gameid)
    if isinstance(server_fullInfo, str):
        return await app.send_message(group, MessageChain(
            f"获取服务器信息出错!{server_fullInfo}"
        ), quote=source)
    server_fullInfo = server_fullInfo["result"]
    ban_list = []
    for item in server_fullInfo["rspInfo"]["bannedList"]:
        ban_list.append(item)
    if not ban_list:
        return await app.send_message(group, MessageChain(
            "当前BAN位为空!"
        ), quote=source)
    if clear_num > len(ban_list):
        clear_num = len(ban_list)
    await app.send_message(group, MessageChain(
        f"当前BAN位{len(ban_list)}人,预计清理{clear_num}个~"
    ), quote=source)

    success_num = 0
    fail_num = 0
    del_tasks = []
    index_list = []
    # 从ban_list随机选取clear_num个pid
    for item in random.sample(ban_list, clear_num):
        del_tasks.append(account_instance.removeServerBan(personaId=item["personaId"], serverId=server_id))
        index_list.append(item)
    # 执行删除
    del_results = await asyncio.gather(*del_tasks)
    # 检查结果
    for i, result in enumerate(del_results):
        if isinstance(result, dict):
            success_num += 1
            await BF1Log.record(
                operator_qq=sender.id,
                serverId=server_id,
                persistedGameId=server_guid,
                gameId=server_gameid,
                pid=index_list[i]["personaId"],
                display_name=index_list[i]["displayName"],
                action="unban",
                info="批量清BAN",
            )
        else:
            fail_num += 1
    return await app.send_message(group, MessageChain(
        f"清理完成!成功{success_num}个，失败{fail_num}个"
    ), quote=source)


# =======================================================================================================================
# TODO 重构VBAN
# 加vban
# @listen(GroupMessage)
# @decorate(
#     Distribute.require(),
#     Function.require(channel.module),
#     FrequencyLimitation.require(channel.module),
#     Permission.group_require(channel.metadata.level),
#     Permission.user_require(Permission.GroupAdmin, if_noticed=True),
# )
# @dispatch(
#     Twilight(
#         [
#             "action" @ UnionMatch("-vban", "-加vban", "-vb").space(SpacePolicy.NOSPACE),
#             FullMatch("#", optional=True).space(SpacePolicy.NOSPACE),
#             "vban_rank" @ ParamMatch(optional=False).space(SpacePolicy.FORCE),
#             "player_name" @ ParamMatch(optional=False).space(SpacePolicy.PRESERVE),
#             "reason" @ ParamMatch(optional=True).space(SpacePolicy.PRESERVE),
#             # 示例: -vban xiaoxiao test 1
#         ]
#     )
# )
# async def add_vban(app: Ariadne, group: Group, player_name: RegexResult, reason: RegexResult, vban_rank: RegexResult,
#                    source: Source):
#     if not reason.matched:
#         reason = "违反规则"
#     else:
#         reason = str(reason.result)
#     # 寻找vban配置
#     try:
#         vban_rank = int(str(vban_rank.result))
#         if vban_rank < 1 or vban_rank > 10:
#             raise Exception
#         if vban_rank == 1:
#             vban_rank = ''
#     except:
#         await app.send_message(group, MessageChain(
#             "请检查vban序号:1~10"
#         ), quote=source)
#         return False
#     # 先检查绑定群组没
#     group_path = f'./data/battlefield/binds/groups/{group.id}'
#     file_path = group_path + "/bfgroups.yaml"
#     if not (os.path.exists(group_path) or os.path.isfile(file_path)):
#         await app.send_message(group, MessageChain(
#             f'请先绑定bf群组'
#         ), quote=source)
#         return False
#     # 打开绑定的文件
#     with open(file_path, 'r', encoding="utf-8") as file1:
#         data = yaml.load(file1, yaml.Loader)
#         try:
#             bfgroups_name = data["bfgroups"]
#         except:
#             await app.send_message(group, MessageChain(
#                 f'未识别到群组，请重新绑定bf群组'
#             ), quote=source)
#     # 根据bf群组名字找到群组绑定服务器文件-获取vban配置
#     group_path = f"./data/battlefield/binds/bfgroups/{bfgroups_name}"
#     if not os.path.exists(group_path):
#         await app.send_message(group, MessageChain(
#             f"群组{bfgroups_name}不存在"
#         ), quote=source)
#         return False
#     # 是否有vban的文件
#     vban_file_path = f'./data/battlefield/binds/bfgroups/{bfgroups_name}/vban{vban_rank}.json'
#     if not os.path.isfile(vban_file_path):
#         await app.send_message(group, MessageChain(
#             f"没有找到群组vban{vban_rank}文件,请先为群组创建vban"
#         ), quote=source)
#         return False
#     else:
#         with open(vban_file_path, 'r', encoding="utf-8") as file1:
#             data = json.load(file1)
#             if data is None:
#                 await app.send_message(group, MessageChain(
#                     f"群组vban{vban_rank}配置为空,请先配置"
#                 ), quote=source)
#                 return False
#             else:
#                 group_id = data["groupid"]
#                 token = data["token"]
#
#     # 调用接口
#     headers = {
#         'accept': 'application/json',
#         'token': token,
#     }
#     json_data = {
#         'groupid': group_id,
#         'reason': '%s' % reason,
#         'playername': '%s' % str(player_name.result),
#         'time': 0
#     }
#     try:
#         async with httpx.AsyncClient() as client:
#             response = await client.post('https://manager-api.gametools.network/api/addautoban', headers=headers,
#                                          json=json_data)
#     except:
#         await app.send_message(group, MessageChain(
#             f"网络出错,请稍后再试!"
#         ), quote=source)
#         return False
#     try:
#         if "message" in eval(response.text):
#             await app.send_message(group, MessageChain(
#                 f"vban封禁成功!原因:{reason}"
#             ), quote=source)
#             return True
#         else:
#             raise Exception("封禁出错")
#     except Exception as e:
#         logger.warning(e)
#         try:
#             result = eval(response.text)["error"]["code"]
#             if result == -9960:
#                 if eval(response.text)["error"]["message"] == "Player already in autoban for this group":
#                     await app.send_message(group, MessageChain(
#                         f"该玩家已在vban"
#                     ), quote=source)
#                     return False
#                 elif eval(response.text)["error"]["message"] == "Player not found":
#                     await app.send_message(group, MessageChain(
#                         f"无效的玩家名字"
#                     ), quote=source)
#                     return False
#                 else:
#                     error_message = eval(response.text)["error"]["message"]
#                     await app.send_message(group, MessageChain(
#                         f"token无效/参数错误\n错误信息:{error_message}"
#                     ), quote=source)
#                     return False
#             elif result == -9900:
#                 try:
#                     error_message = eval(response.text)["error"]["message"]
#                     await app.send_message(group, MessageChain(
#                         f"token无效/参数错误\n错误信息:{error_message}"
#                     ), quote=source)
#                     return False
#                 except:
#                     await app.send_message(group, MessageChain(
#                         f"token无效/参数错误"
#                     ), quote=source)
#                     return False
#             else:
#                 await app.send_message(group, MessageChain(
#                     f"该玩家已在vban"
#                 ), quote=source)
#                 return False
#         except:
#             await app.send_message(group, MessageChain(
#                 f"token出错或该玩家已在vban"
#             ), quote=source)
#             return False
#
#
# # 减vban
# @listen(GroupMessage)
# @decorate(
#     Distribute.require(),
#     Function.require(channel.module),
#     FrequencyLimitation.require(channel.module),
#     Permission.group_require(channel.metadata.level),
#     Permission.user_require(Permission.GroupAdmin, if_noticed=True),
# )
# @dispatch(
#     Twilight(
#         [
#             "action" @ UnionMatch("-unvban", "-uvb", "-减vban").space(
#                 SpacePolicy.NOSPACE),
#             FullMatch("#", optional=True).space(SpacePolicy.NOSPACE),
#             "vban_rank" @ ParamMatch(optional=False).space(SpacePolicy.FORCE),
#             "player_name" @ ParamMatch(optional=False).space(SpacePolicy.PRESERVE),
#             "reason" @ WildcardMatch(optional=True),
#             # 示例: -unvban xiaoxiao test
#         ]
#     )
# )
# async def del_vban(app: Ariadne, group: Group, player_name: RegexResult, reason: RegexResult,
#                    vban_rank: RegexResult, source: Source):
#     if not reason.matched:
#         reason = "解封"
#     else:
#         reason = str(reason.result)
#     # 寻找vban配置
#     try:
#         vban_rank = int(str(vban_rank.result))
#         if vban_rank < 1 or vban_rank > 10:
#             raise Exception
#         if vban_rank == 1:
#             vban_rank = ''
#     except:
#         await app.send_message(group, MessageChain(
#             "请检查vban序号:1~10"
#         ), quote=source)
#         return False
#     # 先检查绑定群组没
#     group_path = f'./data/battlefield/binds/groups/{group.id}'
#     file_path = group_path + "/bfgroups.yaml"
#     if not (os.path.exists(group_path) or os.path.isfile(file_path)):
#         await app.send_message(group, MessageChain(
#             f'请先绑定bf群组'
#         ), quote=source)
#         return False
#     # 打开绑定的文件
#     with open(file_path, 'r', encoding="utf-8") as file1:
#         data = yaml.load(file1, yaml.Loader)
#         try:
#             bfgroups_name = data["bfgroups"]
#         except:
#             await app.send_message(group, MessageChain(
#                 f'未识别到群组，请重新绑定bf群组'
#             ), quote=source)
#     # 根据bf群组名字找到群组绑定服务器文件-获取vban配置
#     group_path = f"./data/battlefield/binds/bfgroups/{bfgroups_name}"
#     if not os.path.exists(group_path):
#         await app.send_message(group, MessageChain(
#             f"群组{bfgroups_name}不存在"
#         ), quote=source)
#         return False
#     # 是否有vban的文件
#     vban_file_path = f'./data/battlefield/binds/bfgroups/{bfgroups_name}/vban{vban_rank}.json'
#     if not os.path.isfile(vban_file_path):
#         await app.send_message(group, MessageChain(
#             f"没有找到群组vban{vban_rank}文件,请先为群组创建vban"
#         ), quote=source)
#         return False
#     else:
#         with open(vban_file_path, 'r', encoding="utf-8") as file1:
#             data = json.load(file1)
#             if data is None:
#                 await app.send_message(group, MessageChain(
#                     f"群组vban{vban_rank}配置为空,请先配置"
#                 ), quote=source)
#                 return False
#             else:
#                 group_id = data["groupid"]
#                 token = data["token"]
#
#     # 调用接口
#     headers = {
#         'accept': 'application/json',
#         'token': token,
#     }
#     json_data = {
#         'groupid': group_id,
#         'reason': '%s' % reason,
#         'playername': '%s' % str(player_name.result),
#         'time': 0
#     }
#     try:
#         async with httpx.AsyncClient() as client:
#             response = await client.post('https://manager-api.gametools.network/api/delautoban', headers=headers,
#                                          json=json_data)
#     except:
#         await app.send_message(group, MessageChain(
#             f"网络出错,请稍后再试!"
#         ), quote=source)
#         return False
#     try:
#         if "message" in eval(response.text):
#             await app.send_message(group, MessageChain(
#                 f"vban解封成功!解封原因:{reason}"
#             ), quote=source)
#             return True
#         else:
#             raise Exception("解封出错")
#     except Exception as e:
#         logger.warning(e)
#         try:
#             result = eval(response.content.decode())["error"]["code"]
#             if result == -9960:
#                 await app.send_message(group, MessageChain(
#                     f"token无效/参数错误"
#                 ), quote=source)
#                 return False
#             elif result == -9900:
#                 await app.send_message(group, MessageChain(
#                     f"token无效/参数错误"
#                 ), quote=str)
#                 return False
#             elif result == -9961:
#                 if eval(response.text)["error"]["message"] == "'id'":
#                     await app.send_message(group, MessageChain(
#                         f"无效的玩家名字"
#                     ), quote=source)
#                     return False
#                 else:
#                     await app.send_message(group, MessageChain(
#                         f"该玩家未在vban"
#                     ), quote=source)
#                     return False
#             else:
#                 await app.send_message(group, MessageChain(
#                     f"该玩家未在vban"
#                 ), quote=source)
#                 return False
#         except:
#             await app.send_message(group, MessageChain(
#                 f"token出错或该玩家未在vban"
#             ), quote=source)
#             return False
#
#
# # vban列表
# @listen(GroupMessage)
# @decorate(
#     Distribute.require(),
#     Function.require(channel.module),
#     FrequencyLimitation.require(channel.module),
#     Permission.group_require(channel.metadata.level),
#     Permission.user_require(Permission.GroupAdmin, if_noticed=True),
# )
# @dispatch(
#     Twilight(
#         [
#             "action" @ UnionMatch("-vbanlist", "-vban列表").space(SpacePolicy.NOSPACE),
#             FullMatch("#", optional=True).space(SpacePolicy.NOSPACE),
#             "vban_rank" @ ParamMatch(optional=False).space(SpacePolicy.PRESERVE),
#             # 示例: -vbanlist#1
#         ]
#     )
# )
# async def get_vban_list(app: Ariadne, group: Group, vban_rank: RegexResult, source: Source):
#     # 寻找vban配置
#     try:
#         vban_rank = int(str(vban_rank.result))
#         if vban_rank < 1 or vban_rank > 10:
#             raise Exception
#         if vban_rank == 1:
#             vban_rank = ''
#     except:
#         await app.send_message(group, MessageChain(
#             "请检查vban序号:1~10"
#         ), quote=source)
#         return False
#     # 先检查绑定群组没
#     group_path = f'./data/battlefield/binds/groups/{group.id}'
#     file_path = group_path + "/bfgroups.yaml"
#     if not (os.path.exists(group_path) or os.path.isfile(file_path)):
#         await app.send_message(group, MessageChain(
#             f'请先绑定bf群组'
#         ), quote=source)
#         return False
#     # 打开绑定的文件
#     with open(file_path, 'r', encoding="utf-8") as file1:
#         data = yaml.load(file1, yaml.Loader)
#         try:
#             bfgroups_name = data["bfgroups"]
#         except:
#             await app.send_message(group, MessageChain(
#                 f'未识别到群组，请重新绑定bf群组'
#             ), quote=source)
#     # 根据bf群组名字找到群组绑定服务器文件-获取vban配置
#     group_path = f"./data/battlefield/binds/bfgroups/{bfgroups_name}"
#     if not os.path.exists(group_path):
#         await app.send_message(group, MessageChain(
#             f"群组{bfgroups_name}不存在"
#         ), quote=source)
#         return False
#     # 是否有vban的文件
#     vban_file_path = f'./data/battlefield/binds/bfgroups/{bfgroups_name}/vban{vban_rank}.json'
#     if not os.path.isfile(vban_file_path):
#         await app.send_message(group, MessageChain(
#             f"没有找到群组vban{vban_rank}文件,请先为群组创建vban"
#         ), quote=source)
#         return False
#     else:
#         with open(vban_file_path, 'r', encoding="utf-8") as file1:
#             data = json.load(file1)
#             if data is None:
#                 await app.send_message(group, MessageChain(
#                     f"群组vban{vban_rank}配置为空,请先配置vban"
#                 ), quote=source)
#                 return False
#             else:
#                 group_id = data["groupid"]
#                 token = data["token"]
#
#     # 调用接口
#     headers = {
#         'accept': 'application/json',
#         'token': token,
#     }
#     params = (
#         ('groupid', group_id),
#     )
#     try:
#         async with httpx.AsyncClient() as client:
#             response = await client.get('https://manager-api.gametools.network/api/autoban', headers=headers,
#                                         params=params)
#     except:
#         await app.send_message(group, MessageChain(
#             "网络出错请稍后再试!"
#         ), quote=source)
#         return False
#     response = eval(response.text)
#     if "error" in response:
#         if response["error"]["code"] == -9900:
#             if response["error"]["message"] == "permission denied":
#                 await app.send_message(group, MessageChain(
#                     "token无效/参数错误"
#                 ), quote=source)
#                 return False
#             else:
#                 await app.send_message(group, MessageChain(
#                     "token无效/参数错误"
#                 ), quote=source)
#                 return False
#         else:
#             await app.send_message(group, MessageChain(
#                 f"错误代码:{response['error']['code']}\n"
#                 f"可能token无效/参数错误!"
#             ), quote=source)
#             return False
#     vban_list = []
#     vban_len = 0
#     player_num = 0
#     for item in response["data"]:
#         temp = [f"名字:{item['playerName']}\n", f"Pid:{item['id']}\n"]
#         # vban_len += 1
#         try:
#             temp.append(f"原因:{item['reason'].encode().decode()}\n")
#         except Exception as e:
#             logger.warning(e)
#             pass
#         temp.append(f"封禁来源:{item['admin']}\n")
#         temp.append(f"封禁时间:{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(int(item['unixTimeStamp'])))}")
#         # vban_len += 1
#         vban_len += 1
#         player_num += 1
#         vban_list.append(temp)
#
#     vban_list.reverse()
#     sender_member = await app.get_member(group, app.account)
#     fwd_nodeList = [ForwardNode(
#         target=sender_member,
#         time=datetime.now(),
#         message=MessageChain(f"vban人数:{player_num}" if len(vban_list) < 100 else f"vban人数:{player_num}\n当前显示最新100条数据"),
#     )]
#     vban_list = vban_list[:100]
#     for item in vban_list:
#         fwd_nodeList.append(ForwardNode(
#             target=sender_member,
#             time=datetime.now(),
#             message=MessageChain(item),
#         ))
#     message = MessageChain(Forward(nodeList=fwd_nodeList))
#     try:
#         await app.send_message(group, message)
#     except Exception as e:
#         await app.send_message(
#             group,
#             MessageChain(
#                 f"发送时出现一个错误:{e}"
#             )
#         )


# =======================================================================================================================


# 换边
@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level),
    Permission.user_require(Permission.User, if_noticed=True),
)
@dispatch(
    Twilight(
        [
            UnionMatch("-move", "-换边", "-挪").space(SpacePolicy.PRESERVE),
            ParamMatch(optional=True).space(SpacePolicy.NOSPACE) @ "bf_group_name",
            FullMatch("#", optional=True).space(SpacePolicy.NOSPACE),
            ParamMatch(optional=False).space(SpacePolicy.FORCE) @ "server_rank",
            ParamMatch(optional=False).space(SpacePolicy.PRESERVE) @ "player_name",
            ParamMatch(optional=True).space(SpacePolicy.PRESERVE) @ "team_index",
            # 示例: -move sakula1 shlsan13
        ]
    )
)
async def move_player(
        app: Ariadne, sender: Member, group: Group, source: Source,
        bf_group_name: RegexResult, server_rank: RegexResult, player_name: RegexResult, team_index: RegexResult
):
    # 队伍序号检查 team_index只能为1/2
    if not team_index.matched:
        return await app.send_message(group, MessageChain("请输入队伍序号!(1/2)"), quote=source)
    if team_index.result.display not in ["1", "2"]:
        return await app.send_message(group, MessageChain("队伍序号只能为 1/2 !"), quote=source)
    team_index = int(team_index.result.display)

    # 服务器序号检查
    server_rank = server_rank.result.display
    if not server_rank.isdigit():
        return await app.send_message(group, MessageChain("请输入正确的服务器序号"), quote=source)
    server_rank = int(server_rank)
    if server_rank < 1 or server_rank > 30:
        return await app.send_message(group, MessageChain("服务器序号只能在1~30内"), quote=source)

    # 获取群组信息
    bf_group_name = bf_group_name.result.display if bf_group_name and bf_group_name.matched else None
    if not bf_group_name:
        bf1_group_info = await BF1GROUP.get_bf1Group_byQQ(group.id)
        if not bf1_group_info:
            return await app.send_message(group, MessageChain("请先绑定BF1群组/指定群组名"), quote=source)
        bf_group_name = bf1_group_info.get("group_name")

    if not await perm_judge(bf_group_name, group, sender):
        return await app.send_message(
            group,
            MessageChain(f"您不是群组[{bf_group_name}]的成员"),
            quote=source,
        )
    server_info = await BF1GROUP.get_bindInfo_byIndex(bf_group_name, server_rank)
    if not server_info:
        return await app.send_message(group, MessageChain(
            f"群组[{bf_group_name}]未绑定服务器{server_rank}"
        ), quote=source)
    elif isinstance(server_info, str):
        return await app.send_message(group, MessageChain(server_info), quote=source)
    server_id = server_info["serverId"]
    server_gameid = server_info["gameId"]
    server_guid = server_info["guid"]

    # 查验玩家是否存在
    player_name = player_name.result.display
    player_info = await get_personas_by_name(player_name)
    if isinstance(player_info, str):
        return await app.send_message(
            group,
            MessageChain(f"查询出错!{player_info}"),
            quote=source
        )
    if not player_info:
        return await app.send_message(
            group,
            MessageChain(f"玩家 {player_name} 不存在"),
            quote=source
        )
    pid = player_info["personas"]["persona"][0]["personaId"]
    # uid = player_info["personas"]["persona"][0]["pidId"]
    player_name = player_info["personas"]["persona"][0]["displayName"]

    # 获取服管账号实例
    if not server_info["account"]:
        return await app.send_message(group, MessageChain(
            f"群组{bf_group_name}服务器{server_rank}未绑定服管账号，请先绑定服管账号!"
        ), quote=source)
    account_instance = await BF1ManagerAccount.get_manager_account_instance(server_info["account"])

    # 移动玩家
    star_time = time.time()
    result = await account_instance.movePlayer(gameId=server_gameid, personaId=pid, teamId=team_index)
    end_time = time.time()
    logger.debug(f"更换队伍耗时:{(end_time - star_time):.2f}秒")

    if isinstance(result, dict):
        await app.send_message(group, MessageChain(
            f"更换队伍成功!"
        ), quote=source)
        # 日志记录
        await BF1Log.record(
            operator_qq=sender.id,
            serverId=server_id,
            persistedGameId=server_guid,
            gameId=server_gameid,
            pid=pid,
            display_name=player_name,
            action="move",
            info="更换队伍",
        )
        return
    return await app.send_message(group, MessageChain(
        f"执行出错!{result}"
    ), quote=source)


# 换图
@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level),
    Permission.user_require(Permission.User, if_noticed=True),
)
@dispatch(
    Twilight(
        [
            UnionMatch("-换图", "-map", "-切图").space(SpacePolicy.PRESERVE),
            ParamMatch(optional=True).space(SpacePolicy.NOSPACE) @ "bf_group_name",
            FullMatch("#", optional=True).space(SpacePolicy.NOSPACE),
            ParamMatch(optional=False).space(SpacePolicy.FORCE) @ "server_rank",
            ParamMatch(optional=False) @ "map_index",
            # 示例: -换图#2 2
        ]
    )
)
async def change_map(
        app: Ariadne, sender: Member, group: Group, source: Source,
        bf_group_name: RegexResult, server_rank: RegexResult, map_index: RegexResult
):
    if bf_group_name.matched and bf_group_name.result.display in ["list", "lis"]:
        return

    # 服务器序号检查
    server_rank = server_rank.result.display
    if not server_rank.isdigit():
        logger.debug(server_rank)
        return await app.send_message(group, MessageChain("请输入正确的服务器序号"), quote=source)
    server_rank = int(server_rank)
    if server_rank < 1 or server_rank > 30:
        return await app.send_message(group, MessageChain("服务器序号只能在1~30内"), quote=source)

    # 获取群组信息
    bf_group_name = bf_group_name.result.display if bf_group_name and bf_group_name.matched else None
    if not bf_group_name:
        bf1_group_info = await BF1GROUP.get_bf1Group_byQQ(group.id)
        if not bf1_group_info:
            return await app.send_message(group, MessageChain("请先绑定BF1群组/指定群组名"), quote=source)
        bf_group_name = bf1_group_info.get("group_name")

    if not await perm_judge(bf_group_name, group, sender):
        return await app.send_message(
            group,
            MessageChain(f"您不是群组[{bf_group_name}]的成员"),
            quote=source,
        )
    server_info = await BF1GROUP.get_bindInfo_byIndex(bf_group_name, server_rank)
    if not server_info:
        return await app.send_message(group, MessageChain(
            f"群组[{bf_group_name}]未绑定服务器{server_rank}"
        ), quote=source)
    elif isinstance(server_info, str):
        return await app.send_message(group, MessageChain(server_info), quote=source)
    server_id = server_info["serverId"]
    server_gameid = server_info["gameId"]
    server_guid = server_info["guid"]

    # 获取地图序号
    map_list = []
    if map_index.result.display.isdigit() and map_index == "2788":
        map_index = "阿奇巴巴"
    else:
        map_index = map_index.result.display
    if not map_index.isdigit():
        map_index = map_index \
            .replace("垃圾厂", "法烏克斯要塞") \
            .replace("2788", "阿奇巴巴").replace("垃圾场", "法烏克斯要塞") \
            .replace("黑湾", "黑爾戈蘭灣").replace("海峡", "海麗絲岬") \
            .replace("噗噗噗山口", "武普库夫山口").replace("绞肉机", "凡爾登高地") \
            .replace("狙利西亞", "加利西亞").replace("沼气池", "法烏克斯要塞") \
            .replace("烧烤摊", "聖康坦的傷痕")
        map_index = zhconv.convert(map_index, 'zh-hk').replace("徵", "征").replace("託", "托")
        # 1.地图池
        result = await (await BF1DA.get_api_instance()).getFullServerDetails(server_gameid)
        if not isinstance(result, dict):
            return await app.send_message(group, MessageChain(
                f"获取图池出错!{result}"
            ), quote=source)
        result = result["result"]["serverInfo"]
        i = 0
        for item in result["rotation"]:
            map_list.append(f"{item['modePrettyName']}-{item['mapPrettyName']}")
            i += 1
        if map_index != "重開":
            map_index_list = []
            for map_temp in map_list:
                if map_index in map_temp and map_temp not in map_index_list:
                    map_index_list.append(map_temp)
            if len(map_index_list) == 0:
                map_index_list = list(set(difflib.get_close_matches(map_index, map_list)))
        else:
            map_index_list = [map_list.index(f'{result["mapModePretty"]}-{result["mapNamePretty"]}')]
        if len(map_index_list) > 1:
            i = 0
            choices = []
            for item in map_index_list:
                map_index_list[i] = f"{i}#{item}●\n".replace("流血", "流\u200b血") if (
                        item.startswith('行動模式') and
                        item.endswith(('聖康坦的傷痕', '窩瓦河', '海麗絲岬', '法歐堡', '攻佔托爾', '格拉巴山',
                                       '凡爾登高地', '加利西亞', '蘇瓦松', '流血宴廳', '澤布呂赫',
                                       '索姆河', '武普庫夫山口', '龐然闇影'))) \
                    else f"{i}#{item}\n".replace('流血', '流\u200b血')
                choices.append(str(i))
                i += 1
            map_index_list[-1] = map_index_list[-1].replace("\n", '')
            await app.send_message(group, MessageChain(
                f"匹配到多个选项,30秒内发送'#'前的序号进行换图,发送其他消息可退出,匹配结果如下:\n", map_index_list
            ), quote=source)

            async def waiter(waiter_member: Member, waiter_group: Group,
                             waiter_message: MessageChain):
                if waiter_member.id == sender.id and waiter_group.id == group.id:
                    saying = waiter_message.display
                    if saying in choices:
                        map_index_temp = map_list.index(
                            map_index_list[int(saying)].replace('#', '').replace(saying, '').replace('\n', '').replace(
                                "●", ""))
                        return True, waiter_member.id, map_index_temp
                    else:
                        return False, waiter_member.id, None

            try:
                result, operator, map_index = await FunctionWaiter(waiter, [GroupMessage], block_propagation=True).wait(
                    30)
            except asyncio.exceptions.TimeoutError:
                await app.send_message(group, MessageChain(
                    f'操作超时!已退出换图'), quote=source)
                return
            if result:
                await app.send_message(group, MessageChain(
                    f"执行ing"
                ), quote=source)
                # 调用换图的接口
                # 获取服管账号实例
                if not server_info["account"]:
                    return await app.send_message(group, MessageChain(
                        f"群组{bf_group_name}服务器{server_rank}未绑定服管账号，请先绑定服管账号!"
                    ), quote=source)
                account_instance = await BF1ManagerAccount.get_manager_account_instance(server_info["account"])
                result = await account_instance.chooseLevel(persistedGameId=server_guid, levelIndex=map_index)
                if isinstance(result, dict):
                    suc_str = f"已更换服务器{server_rank}地图为{map_list[int(map_index)][map_list[int(map_index)].find('-') + 1:]}".replace(
                        "\n", "").replace('流血', '流\u200b血')
                    await app.send_message(group, MessageChain(
                        suc_str
                    ), quote=source)
                    await BF1Log.record(
                        operator_qq=sender.id,
                        serverId=server_id,
                        persistedGameId=server_guid,
                        gameId=server_gameid,
                        pid=None,
                        display_name=None,
                        action="change_map",
                        info=suc_str,
                    )
                    return
                return await app.send_message(group, MessageChain(
                    f"执行出错!{result}"
                ), quote=source)
            else:
                return await app.send_message(group, MessageChain(
                    f"未识别到有效图池序号,退出换图"
                ), quote=source)
        elif len(map_index_list) == 1:
            if type(map_index_list[0]) != int:
                map_index = map_list.index(map_index_list[0])
            else:
                map_index = map_index_list[0]
        elif len(map_index_list) == 0:
            return await app.send_message(group, MessageChain(
                f"匹配到0个选项,请输入更加精确的地图名或加上游戏模式名\n匹配名:{map_index}"
            ), quote=source)
        else:
            return await app.send_message(group, MessageChain(
                f"这是一个bug(奇怪的bug增加了"
            ), quote=source)
    else:
        map_index = int(map_index.result.display)

    # 调用换图的接口
    if not server_info["account"]:
        return await app.send_message(group, MessageChain(
            f"群组{bf_group_name}服务器{server_rank}未绑定服管账号，请先绑定服管账号!"
        ), quote=source)
    await app.send_message(group, MessageChain(
        f"执行ing"
    ), quote=source)

    account_instance = await BF1ManagerAccount.get_manager_account_instance(server_info["account"])
    result = await account_instance.chooseLevel(persistedGameId=server_guid, levelIndex=map_index)
    if isinstance(result, dict):
        if not map_list:
            suc_str = f"成功更换服务器{server_rank}地图"
            await app.send_message(group, MessageChain(
                f"成功更换服务器{server_rank}地图"
            ), quote=source)
            await BF1Log.record(
                operator_qq=sender.id,
                serverId=server_id,
                persistedGameId=server_guid,
                gameId=server_gameid,
                pid=None,
                display_name=None,
                action="change_map",
                info=suc_str,
            )
            return
        else:
            suc_str = f"成功更换服务器{server_rank}地图为:{map_list[int(map_index)]}".replace('流血', '流\u200b血').replace('\n',
                                                                                                              '')
            await app.send_message(group, MessageChain(
                suc_str
            ), quote=source)
            await BF1Log.record(
                operator_qq=sender.id,
                serverId=server_id,
                persistedGameId=server_guid,
                gameId=server_gameid,
                pid=None,
                display_name=None,
                action="change_map",
                info=suc_str,
            )
            return
    return await app.send_message(group, MessageChain(
        f"执行出错!{result}"
    ), quote=source)


# 图池序号换图
@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level),
    Permission.user_require(Permission.User, if_noticed=True),
)
@dispatch(
    Twilight(
        [
            UnionMatch("-图池", "-maplist", "-地图池").space(SpacePolicy.PRESERVE),
            ParamMatch(optional=True).space(SpacePolicy.NOSPACE) @ "bf_group_name",
            FullMatch("#", optional=True).space(SpacePolicy.NOSPACE),
            ParamMatch(optional=False) @ "server_rank",
            # 示例: -图池1
        ]
    )
)
async def change_map_byList(
        app: Ariadne, sender: Member, group: Group, source: Source,
        bf_group_name: RegexResult, server_rank: RegexResult
):
    # 服务器序号检查
    server_rank = server_rank.result.display
    if not server_rank.isdigit():
        return await app.send_message(group, MessageChain("请输入正确的服务器序号"), quote=source)
    server_rank = int(server_rank)
    if server_rank < 1 or server_rank > 30:
        return await app.send_message(group, MessageChain("服务器序号只能在1~30内"), quote=source)

    # 获取群组信息
    bf_group_name = bf_group_name.result.display if bf_group_name and bf_group_name.matched else None
    if not bf_group_name:
        bf1_group_info = await BF1GROUP.get_bf1Group_byQQ(group.id)
        if not bf1_group_info:
            return await app.send_message(group, MessageChain("请先绑定BF1群组/指定群组名"), quote=source)
        bf_group_name = bf1_group_info.get("group_name")

    if not await perm_judge(bf_group_name, group, sender):
        return await app.send_message(
            group,
            MessageChain(f"您不是群组[{bf_group_name}]的成员"),
            quote=source,
        )
    server_info = await BF1GROUP.get_bindInfo_byIndex(bf_group_name, server_rank)
    if not server_info:
        return await app.send_message(group, MessageChain(
            f"群组[{bf_group_name}]未绑定服务器{server_rank}"
        ), quote=source)
    elif isinstance(server_info, str):
        return await app.send_message(group, MessageChain(server_info), quote=source)
    server_id = server_info["serverId"]
    server_gameid = server_info["gameId"]
    server_guid = server_info["guid"]

    # 获取地图池
    result = await (await BF1DA.get_api_instance()).getFullServerDetails(server_gameid)
    if not isinstance(result, dict):
        return await app.send_message(group, MessageChain(
            f"获取图池时出错!{result}"
        ), quote=source)
    result = result["result"]["serverInfo"]
    map_list = []
    choices = []

    map_list_column = [
        ColumnUserInfo(
            name=f"服务器:{result['name'][:17]}",
            description=f"当前地图:{result['mapNamePretty']}—{result['mapModePretty']}",
            avatar=result["mapImageUrl"].replace("[BB_PREFIX]",
                                                 "https://eaassets-a.akamaihd.net/battlelog/battlebinary")
        ),
        ColumnTitle(title="图池如下:")
    ]
    for i, item in enumerate(result["rotation"]):
        map_list.append(f"{item['modePrettyName']}-{item['mapPrettyName']}")
        choices.append(str(i))
        map_list_column.append(
            ColumnUserInfo(
                name=f"{i}:{item['mapPrettyName']}-{item['modePrettyName']}"
                     +
                     ("●" if (
                             item['modePrettyName'] == '行動模式'
                             and
                             item['mapPrettyName'] in
                             [
                                 '聖康坦的傷痕', '窩瓦河',
                                 '海麗絲岬', '法歐堡', '攻佔托爾', '格拉巴山',
                                 '凡爾登高地', '加利西亞', '蘇瓦松', '流血宴廳', '澤布呂赫',
                                 '索姆河', '武普庫夫山口', '龐然闇影'
                             ]
                     ) else ""),
                avatar=item["mapImage"].replace("[BB_PREFIX]", "https://eaassets-a.akamaihd.net/battlelog/battlebinary")
            )
        )
    map_list_column = [Column(elements=map_list_column[i: i + 15]) for i in range(0, len(map_list_column), 15)]
    await app.send_message(group, MessageChain(
        GraiaImage(data_bytes=await OneMockUI.gen(
            GenForm(columns=map_list_column, color_type=get_color_type_follow_time())
        )),
        "\n请在45秒内‘发送’序号来进行换图"
    ), quote=source)

    async def waiter(waiter_member: Member, waiter_group: Group, waiter_message: MessageChain):
        if waiter_member.id == sender.id and waiter_group.id == group.id:
            saying = waiter_message.display
            if saying in choices:
                return True, waiter_member.id, saying
            else:
                return False, waiter_member.id, saying

    try:
        return_result = await FunctionWaiter(waiter, [GroupMessage], block_propagation=True).wait(45)
    except asyncio.exceptions.TimeoutError:
        return await app.send_message(group, MessageChain(f'操作超时!已退出换图'), quote=source)
    if not return_result:
        return await app.send_message(group, MessageChain(
            f"未识别到有效图池序号,退出换图"
        ), quote=source)
    else:
        result, operator, map_index = return_result
    if result:
        if not server_info["account"]:
            return await app.send_message(group, MessageChain(
                f"群组{bf_group_name}服务器{server_rank}未绑定服管账号，请先绑定服管账号!"
            ), quote=source)
        await app.send_message(group, MessageChain(
            f"执行ing"
        ), quote=source)
        account_instance = await BF1ManagerAccount.get_manager_account_instance(server_info["account"])
        result = await account_instance.chooseLevel(persistedGameId=server_guid, levelIndex=map_index)
        if isinstance(result, dict):
            suc_str = f"已更换服务器{server_rank}地图为:{map_list[int(map_index)][map_list[int(map_index)].find('#') + 1:]}".replace(
                "\n", "").replace('流血', '流\u200b血')
            await app.send_message(group, MessageChain(
                suc_str
            ), quote=source)
            await BF1Log.record(
                operator_qq=sender.id,
                serverId=server_id,
                persistedGameId=server_guid,
                gameId=server_gameid,
                pid=None,
                display_name=None,
                action="change_map",
                info=suc_str,
            )
            return
        return await app.send_message(group, MessageChain(
            f"执行出错!{result}"
        ), quote=source)
    else:
        return await app.send_message(group, MessageChain(
            f"未识别到有效图池序号,退出换图"
        ), quote=source)


#  加vip过程:
#  1.获取服务器vip信息，如果玩家信息不在表中就添加到表中且到期时间为无限，如果在表中则跳过,如果有在表中但是不在服务器中则从表中删除玩家信息
#  2.加v成功后，将玩家信息写入vip表
@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level),
    Permission.user_require(Permission.User, if_noticed=True),
)
@dispatch(
    Twilight(
        [
            UnionMatch("-vip", "-v", "-加v", "-上v").space(SpacePolicy.PRESERVE),
            ParamMatch(optional=True).space(SpacePolicy.NOSPACE) @ "bf_group_name",
            FullMatch("#", optional=True).space(SpacePolicy.NOSPACE),
            ParamMatch(optional=False).space(SpacePolicy.FORCE) @ "server_rank",
            ParamMatch(optional=False).space(SpacePolicy.PRESERVE) @ "player_name",
            ParamMatch(optional=True).space(SpacePolicy.PRESERVE) @ "days",
            # 示例: -vip#1 xiaoxiao 0
        ]
    )
)
async def add_vip(
        app: Ariadne, sender: Member, group: Group, source: Source,
        bf_group_name: RegexResult, server_rank: RegexResult, player_name: RegexResult, days: RegexResult
):
    if server_rank.matched and server_rank.result.display in ["iplist", "list", "ip列表", "l", "列表"]:
        logger.debug(server_rank)
        return

    # 日期检查
    if days.matched:
        days = days.result.display
        if not days.replace('-', '').isdigit():
            return await app.send_message(group, MessageChain("请输入正确的天数(数字、可为负数)!"), quote=source)
        days = int(days)
    else:
        days = None

    # 服务器序号检查
    server_rank = server_rank.result.display
    if not server_rank.isdigit():
        return await app.send_message(group, MessageChain("请输入正确的服务器序号"), quote=source)
    server_rank = int(server_rank)
    if server_rank < 1 or server_rank > 30:
        return await app.send_message(group, MessageChain("服务器序号只能在1~30内"), quote=source)

    # 获取群组信息
    bf_group_name = bf_group_name.result.display if bf_group_name and bf_group_name.matched else None
    if not bf_group_name:
        bf1_group_info = await BF1GROUP.get_bf1Group_byQQ(group.id)
        if not bf1_group_info:
            return await app.send_message(group, MessageChain("请先绑定BF1群组/指定群组名"), quote=source)
        bf_group_name = bf1_group_info.get("group_name")

    if not await perm_judge(bf_group_name, group, sender):
        return await app.send_message(
            group,
            MessageChain(f"您不是群组[{bf_group_name}]的成员"),
            quote=source,
        )
    server_info = await BF1GROUP.get_bindInfo_byIndex(bf_group_name, server_rank)
    if not server_info:
        return await app.send_message(group, MessageChain(
            f"群组[{bf_group_name}]未绑定服务器{server_rank}"
        ), quote=source)
    elif isinstance(server_info, str):
        return await app.send_message(group, MessageChain(server_info), quote=source)
    server_id = server_info["serverId"]
    server_gameid = server_info["gameId"]
    server_guid = server_info["guid"]

    # 获取服管账号实例
    if not server_info["account"]:
        return await app.send_message(group, MessageChain(
            f"群组{bf_group_name}服务器{server_rank}未绑定服管账号，请先绑定服管账号!"
        ), quote=source)
    account_instance = await BF1ManagerAccount.get_manager_account_instance(server_info["account"])

    # 查验玩家是否存在
    player_name = player_name.result.display
    player_info = await get_personas_by_name(player_name)
    if isinstance(player_info, str):
        return await app.send_message(
            group,
            MessageChain(f"查询出错!{player_info}"),
            quote=source
        )
    if not player_info:
        return await app.send_message(
            group,
            MessageChain(f"玩家 {player_name} 不存在"),
            quote=source
        )
    pid = player_info["personas"]["persona"][0]["personaId"]
    # uid = player_info["personas"]["persona"][0]["pidId"]
    player_name = player_info["personas"]["persona"][0]["displayName"]

    # 获取服务器信息-fullInfo
    server_fullInfo = await (await BF1DA.get_api_instance()).getFullServerDetails(server_gameid)
    if isinstance(server_fullInfo, str):
        return await app.send_message(group, MessageChain(
            f"获取服务器信息出错!{server_fullInfo}"
        ), quote=source)
    server_fullInfo = server_fullInfo["result"]

    # 同步服务器vip信息
    await BF1ServerVipManager.update_server_vip(server_full_info=server_fullInfo)

    # 是否为行动模式
    # if server_fullInfo["serverInfo"]["mapModePretty"] == "行動模式" and \
    #         server_fullInfo["serverInfo"]["slots"]["Soldier"]["current"] == 0:
    #     await app.send_message(group, MessageChain(
    #         "当前服务器为行动模式且人数为0,操作失败!"
    #     ), quote=source)
    #     return False
    operation_mode = False
    if server_fullInfo["serverInfo"]["mapModePretty"] == "行動模式":
        operation_mode = True

    # 加v逻辑:
    # 如果不是行动模式就直接加
    # 玩家缓存信息,如果没有则说明不在服务器vip位
    player_cache_info = await BF1ServerVipManager.get_server_vip(server_id, pid)
    if not operation_mode:
        # 指定了天数的情况
        if days:
            if not player_cache_info:
                target_date = DateTimeUtils.add_days(datetime.now(), days)
            else:
                if not player_cache_info["expire_time"]:
                    player_cache_info["expire_time"] = datetime.now()
                target_date = DateTimeUtils.add_days(player_cache_info["expire_time"], days)
            # 校验目标日期与今天日期差是否小于0，如果小于0则返回目标日期无效
            date_diff = DateTimeUtils.diff_days(target_date, datetime.now())
            if date_diff < 0:
                return await app.send_message(group, MessageChain(
                    f"目标日期{target_date.strftime('%Y-%m-%d')}小于今天日期{datetime.now().strftime('%Y-%m-%d')},操作失败!"
                ), quote=source)
        # 未指定天数则为永久
        else:
            target_date = None
        if player_cache_info:
            suc_str = f"{'修改成功!' if player_cache_info else '添加成功!'}到期时间：{target_date.strftime('%Y-%m-%d') if target_date else '永久'}"
            await app.send_message(group, MessageChain(suc_str), quote=source)
            # 写入数据库
            await BF1ServerVipManager.update_server_vip_by_pid(
                server_id=server_id, player_pid=pid, displayName=player_name, expire_time=target_date, valid=True
            )
            await BF1Log.record(
                operator_qq=sender.id,
                serverId=server_id,
                persistedGameId=server_guid,
                gameId=server_gameid,
                pid=pid,
                display_name=player_name,
                action="vip",
                info=suc_str,
            )
            return
        result = await account_instance.addServerVip(personaId=pid, serverId=server_id)
        if isinstance(result, dict):
            suc_str = f"{'修改成功!' if player_cache_info else '添加成功!'}到期时间：{target_date.strftime('%Y-%m-%d') if target_date else '永久'}"
            await app.send_message(group, MessageChain(suc_str), quote=source)
            # 写入数据库
            await BF1ServerVipManager.update_server_vip_by_pid(
                server_id=server_id, player_pid=pid, displayName=player_name, expire_time=target_date, valid=True
            )
            await BF1Log.record(
                operator_qq=sender.id,
                serverId=server_id,
                persistedGameId=server_guid,
                gameId=server_gameid,
                pid=pid,
                display_name=player_name,
                action="vip",
                info=suc_str,
            )
            return
        return await app.send_message(group, MessageChain(
            f"添加失败!{result}"
        ), quote=source)
    # 行动模式的话如果有cache信息则直接修改日期valid为True, 否则要获取viplist判断人数是否超过上限(50),且valid为False
    else:
        # 指定了天数的情况
        if days:
            if not player_cache_info:
                target_date = DateTimeUtils.add_days(datetime.now(), days)
            else:
                if not player_cache_info["expire_time"]:
                    player_cache_info["expire_time"] = datetime.now()
                    if days < 0:
                        return await app.send_message(group, MessageChain(
                            "该玩家已经是永久VIP了!"
                        ), quote=source)
                target_date = DateTimeUtils.add_days(player_cache_info["expire_time"], days)
            # 校验目标日期与今天日期差是否小于0，如果小于0则返回目标日期无效
            date_diff = DateTimeUtils.diff_days(target_date, datetime.now())
            if date_diff < 0:
                return await app.send_message(group, MessageChain(
                    f"目标日期{target_date.strftime('%Y-%m-%d')}小于今天日期{datetime.now().strftime('%Y-%m-%d')},操作失败!"
                ), quote=source)
        # 未指定天数则为永久
        else:
            target_date = None
        # 如果有缓存信息则直接修改日期，valid为True
        if player_cache_info:
            if not player_cache_info["valid"]:
                temp_str = "(待生效)"
            else:
                temp_str = "(已生效)"
            await app.send_message(group, MessageChain(
                f"{'修改成功!'}到期时间：{target_date.strftime('%Y-%m-%d') if target_date else '永久'} {temp_str}" +
                f"\n(当前服务器为行动模式,需checkvip生效)"
            ), quote=source)
            # 更新数据库中的VIP信息
            await BF1ServerVipManager.update_server_vip_by_pid(
                server_id=server_id, player_pid=pid, displayName=player_name, expire_time=target_date,
                valid=player_cache_info["valid"]
            )
            return
        # 如果没有缓存信息，则获取viplist判断人数是否超过上限，且valid为False
        else:
            vip_list = await BF1ServerVipManager.get_server_vip_list(server_id)
            # 统计目标天数>=今天的人数
            vip_count = 0
            for item in vip_list:
                # 只精确到天
                date_temp: datetime = item["expire_time"]
                if not date_temp:
                    vip_count += 1
                    continue
                date_temp = date_temp.replace(hour=0, minute=0, second=0, microsecond=0)
                today_date_temp = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
                if date_temp >= today_date_temp:
                    vip_count += 1
            if vip_count >= 50:
                return await app.send_message(group, MessageChain(
                    f"VIP缓存人数已达上限(50)，无法添加！"
                ), quote=source)
            # 如果人数未超过上限，则添加新的VIP，并将valid设为False
            await app.send_message(group, MessageChain(
                f"{'添加成功!'}到期时间：{target_date.strftime('%Y-%m-%d') if target_date else '永久'} (未生效)" +
                f"\n(当前服务器为行动模式,需checkvip生效)"
            ), quote=source)
            # 写入数据库
            await BF1ServerVipManager.update_server_vip_by_pid(
                server_id=server_id, player_pid=pid, displayName=player_name, expire_time=target_date, valid=False
            )
            return


# 移除vip
@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level),
    Permission.user_require(Permission.User, if_noticed=True),
)
@dispatch(
    Twilight(
        [
            UnionMatch("-unvip", "-uvip", "-删v", "-下v", "-减v").space(SpacePolicy.PRESERVE),
            ParamMatch(optional=True).space(SpacePolicy.NOSPACE) @ "bf_group_name",
            FullMatch("#", optional=True).space(SpacePolicy.NOSPACE),
            ParamMatch(optional=False).space(SpacePolicy.FORCE) @ "server_rank",
            ParamMatch(optional=False).space(SpacePolicy.PRESERVE) @ "player_name",
            # 示例: -unvip#1 xiaoxiao
        ]
    )
)
async def del_vip(
        app: Ariadne, sender: Member, group: Group, source: Source,
        bf_group_name: RegexResult, server_rank: RegexResult, player_name: RegexResult
):
    # 服务器序号检查
    server_rank = server_rank.result.display
    if not server_rank.isdigit():
        return await app.send_message(group, MessageChain("请输入正确的服务器序号"), quote=source)
    server_rank = int(server_rank)
    if server_rank < 1 or server_rank > 30:
        return await app.send_message(group, MessageChain("服务器序号只能在1~30内"), quote=source)

    # 获取群组信息
    bf_group_name = bf_group_name.result.display if bf_group_name and bf_group_name.matched else None
    if not bf_group_name:
        bf1_group_info = await BF1GROUP.get_bf1Group_byQQ(group.id)
        if not bf1_group_info:
            return await app.send_message(group, MessageChain("请先绑定BF1群组/指定群组名"), quote=source)
        bf_group_name = bf1_group_info.get("group_name")

    if not await perm_judge(bf_group_name, group, sender):
        return await app.send_message(
            group,
            MessageChain(f"您不是群组[{bf_group_name}]的成员"),
            quote=source,
        )
    server_info = await BF1GROUP.get_bindInfo_byIndex(bf_group_name, server_rank)
    if not server_info:
        return await app.send_message(group, MessageChain(
            f"群组[{bf_group_name}]未绑定服务器{server_rank}"
        ), quote=source)
    elif isinstance(server_info, str):
        return await app.send_message(group, MessageChain(server_info), quote=source)
    server_id = server_info["serverId"]
    server_gameid = server_info["gameId"]
    server_guid = server_info["guid"]

    # 获取服管账号实例
    if not server_info["account"]:
        return await app.send_message(group, MessageChain(
            f"群组{bf_group_name}服务器{server_rank}未绑定服管账号，请先绑定服管账号!"
        ), quote=source)
    account_instance = await BF1ManagerAccount.get_manager_account_instance(server_info["account"])

    # 查验玩家是否存在
    player_name = player_name.result.display
    player_info = await get_personas_by_name(player_name)
    if isinstance(player_info, str):
        return await app.send_message(
            group,
            MessageChain(f"查询出错!{player_info}"),
            quote=source
        )
    if not player_info:
        return await app.send_message(
            group,
            MessageChain(f"玩家 {player_name} 不存在"),
            quote=source
        )
    pid = player_info["personas"]["persona"][0]["personaId"]
    # uid = player_info["personas"]["persona"][0]["pidId"]
    player_name = player_info["personas"]["persona"][0]["displayName"]

    # 获取服务器信息-fullInfo
    server_fullInfo = await (await BF1DA.get_api_instance()).getFullServerDetails(server_gameid)
    if isinstance(server_fullInfo, str):
        return await app.send_message(group, MessageChain(
            f"获取服务器信息出错!{server_fullInfo}"
        ), quote=source)
    server_fullInfo = server_fullInfo["result"]

    # 同步服务器vip信息
    await BF1ServerVipManager.update_server_vip(server_full_info=server_fullInfo)

    # 是否为行动模式
    # if server_fullInfo["serverInfo"]["mapModePretty"] == "行動模式" and \
    #         server_fullInfo["serverInfo"]["slots"]["Soldier"]["current"] == 0:
    #     await app.send_message(group, MessageChain(
    #         "当前服务器为行动模式且人数为0,操作失败!"
    #     ), quote=source)
    #     return False
    operation_mode = False
    if server_fullInfo["serverInfo"]["mapModePretty"] == "行動模式":
        operation_mode = True

    # 服务器
    player_cache_info = await BF1ServerVipManager.get_server_vip(server_id, pid)
    if not player_cache_info:
        return await app.send_message(group, MessageChain(
            "该玩家不在VIP列表中!"
        ), quote=source)

    if not operation_mode:
        result = await account_instance.removeServerVip(personaId=pid, serverId=server_id)
        if isinstance(result, dict):
            await app.send_message(group, MessageChain(
                "删除成功!"
            ), quote=source)
            await BF1Log.record(
                operator_qq=sender.id,
                serverId=server_id,
                persistedGameId=server_guid,
                gameId=server_gameid,
                pid=pid,
                display_name=player_name,
                action="unvip",
                info="删除成功",
            )
            # 写入数据库
            await BF1ServerVipManager.del_server_vip_by_pid(server_id=server_id, player_pid=pid)
            return
    else:
        # 如果valid为false则直接删除数据库信息，否则将expire_time修改为昨天
        if player_cache_info["valid"]:
            player_cache_info["expire_time"]: datetime = datetime.now() - timedelta(days=1)
            await BF1ServerVipManager.update_server_vip_by_pid(
                server_id=server_id, player_pid=pid,
                expire_time=player_cache_info["expire_time"],
                displayName=player_name,
                valid=player_cache_info["valid"]
            )
            return await app.send_message(group, MessageChain(
                "删除成功!(待检查)"
            ), quote=source)
        else:
            await BF1ServerVipManager.del_server_vip_by_pid(server_id=server_id, player_pid=pid)
            return await app.send_message(group, MessageChain(
                "删除成功!"
            ), quote=source)


# 清理过期vip
@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level),
    Permission.user_require(Permission.User, if_noticed=True),
)
@dispatch(
    Twilight(
        [
            UnionMatch("-checkvip").space(SpacePolicy.PRESERVE),
            ParamMatch(optional=True).space(SpacePolicy.NOSPACE) @ "bf_group_name",
            FullMatch("#", optional=True).space(SpacePolicy.NOSPACE),
            ParamMatch(optional=False) @ "server_rank",
        ]
    )
)
async def check_vip(
        app: Ariadne, sender: Member, group: Group, source: Source,
        bf_group_name: RegexResult, server_rank: RegexResult
):
    # 服务器序号检查
    server_rank = server_rank.result.display
    if not server_rank.isdigit():
        return await app.send_message(group, MessageChain("请输入正确的服务器序号"), quote=source)
    server_rank = int(server_rank)
    if server_rank < 1 or server_rank > 30:
        return await app.send_message(group, MessageChain("服务器序号只能在1~30内"), quote=source)

    # 获取群组信息
    bf_group_name = bf_group_name.result.display if bf_group_name and bf_group_name.matched else None
    if not bf_group_name:
        bf1_group_info = await BF1GROUP.get_bf1Group_byQQ(group.id)
        if not bf1_group_info:
            return await app.send_message(group, MessageChain("请先绑定BF1群组/指定群组名"), quote=source)
        bf_group_name = bf1_group_info.get("group_name")

    if not await perm_judge(bf_group_name, group, sender):
        return await app.send_message(
            group,
            MessageChain(f"您不是群组[{bf_group_name}]的成员"),
            quote=source,
        )
    server_info = await BF1GROUP.get_bindInfo_byIndex(bf_group_name, server_rank)
    if not server_info:
        return await app.send_message(group, MessageChain(
            f"群组[{bf_group_name}]未绑定服务器{server_rank}"
        ), quote=source)
    elif isinstance(server_info, str):
        return await app.send_message(group, MessageChain(server_info), quote=source)
    server_id = server_info["serverId"]
    server_gameid = server_info["gameId"]
    server_guid = server_info["guid"]

    # 获取服管账号实例
    if not server_info["account"]:
        return await app.send_message(group, MessageChain(
            f"群组{bf_group_name}服务器{server_rank}未绑定服管账号，请先绑定服管账号!"
        ), quote=source)
    account_instance = await BF1ManagerAccount.get_manager_account_instance(server_info["account"])

    # 获取服务器信息-fullInfo
    server_fullInfo = await (await BF1DA.get_api_instance()).getFullServerDetails(server_gameid)
    if isinstance(server_fullInfo, str):
        return await app.send_message(group, MessageChain(
            f"获取服务器信息出错!{server_fullInfo}"
        ), quote=source)
    server_fullInfo = server_fullInfo["result"]

    operation_mode = False
    if server_fullInfo["serverInfo"]["mapModePretty"] == "行動模式":
        operation_mode = True

    #  行动模式且人数为0的情况不能check
    if operation_mode and server_fullInfo["serverInfo"]["slots"]["Soldier"]["current"] == 0:
        return await app.send_message(group, MessageChain(
            "当前服务器为行动模式且人数为0,操作失败!"
        ), quote=source)

    # 同步服务器vip信息
    await BF1ServerVipManager.update_server_vip(server_full_info=server_fullInfo)
    # 获取服务器vip信息
    # [{serverId: serverId, personaId: personaId, displayName: displayName, expire_time: expire_time, valid: bool},...]
    vip_info = await BF1ServerVipManager.get_server_vip_list(server_id)

    add_task = []
    add_suc_count = 0
    add_fail_count = 0
    del_task = []
    del_suc_count = 0
    del_fail_count = 0
    # 不是行动模式情况下,清理过期的vip
    if not operation_mode:
        for vip in vip_info:
            expire_time = vip.get("expire_time")
            if not expire_time:
                continue
            days_diff = DateTimeUtils.diff_days(expire_time, datetime.now())
            if days_diff < 0:
                del_task.append(vip)
        if not del_task:
            return await app.send_message(group, MessageChain("当前没有过期的VIP!"), quote=source)
        await app.send_message(group, MessageChain(f"预计清理{len(del_task)}个VIP~"), quote=source)
        del_task_result = await asyncio.gather(
            *[account_instance.removeServerVip(task["personaId"], server_id) for task in del_task])
        for i in range(len(del_task)):
            if isinstance(del_task_result[i], dict):
                del_task[i]["result"] = "删除成功"
                # 更新数据库
                await BF1ServerVipManager.del_server_vip_by_pid(server_id=server_id,
                                                                player_pid=del_task[i]["personaId"])
                await BF1Log.record(
                    operator_qq=sender.id,
                    serverId=server_id,
                    persistedGameId=server_guid,
                    gameId=server_gameid,
                    pid=del_task[i]["personaId"],
                    display_name=del_task[i]["displayName"],
                    action="unvip",
                    info="删除成功",
                )
                del_suc_count += 1
            else:
                del_task[i]["result"] = f"删除失败!{del_task_result[i]}"
                del_fail_count += 1
        send = [f"操作完成!成功{del_suc_count}个,失败{del_fail_count}个"]
        if del_fail_count:
            for i in range(len(del_task)):
                if del_task[i]["result"].startswith("删除失败"):
                    send.append(f"{del_task[i]['displayName']}:{del_task[i]['result']}")
        send = "\n".join(send)
        return await app.send_message(group, MessageChain(send), quote=source)
    else:
        for vip in vip_info:
            expire_time = vip.get("expire_time")
            if not expire_time and not vip["valid"]:
                add_task.append(vip)
                continue
            elif not expire_time:
                continue
            days_diff = DateTimeUtils.diff_days(expire_time, datetime.now())
            if days_diff < 0:
                del_task.append(vip)
            elif days_diff >= 0 and not vip["valid"]:
                add_task.append(vip)
        if not add_task and not del_task:
            return await app.send_message(group, MessageChain("当前没有过期的VIP和待生效的VIP!"), quote=source)
        await app.send_message(group, MessageChain(f"预计清理{len(del_task)}个VIP,添加{len(add_task)}个VIP~"), quote=source)
        del_task_result = await asyncio.gather(
            *[account_instance.removeServerVip(task["personaId"], server_id) for task in del_task])
        for i in range(len(del_task)):
            if isinstance(del_task_result[i], dict):
                del_task[i]["result"] = "删除成功"
                # 更新数据库
                await BF1ServerVipManager.del_server_vip_by_pid(
                    server_id=server_id, player_pid=del_task[i]["personaId"]
                )
                await BF1Log.record(
                    operator_qq=sender.id,
                    serverId=server_id,
                    persistedGameId=server_guid,
                    gameId=server_gameid,
                    pid=del_task[i]["personaId"],
                    display_name=del_task[i]["displayName"],
                    action="unvip",
                    info="删除成功(checkvip)",
                )
                del_suc_count += 1
            else:
                del_task[i]["result"] = f"删除失败!{del_task_result[i]}"
                del_fail_count += 1
        add_task_result = await asyncio.gather(
            *[account_instance.addServerVip(task["personaId"], server_id) for task in add_task])
        for i in range(len(add_task)):
            if isinstance(add_task_result[i], dict):
                add_task[i]["result"] = "添加成功"
                # 更新数据库
                await BF1ServerVipManager.update_server_vip_by_pid(
                    server_id=server_id,
                    player_pid=add_task[i]["personaId"],
                    displayName=add_task[i]["displayName"],
                    expire_time=add_task[i]["expire_time"],
                    valid=True
                )
                await BF1Log.record(
                    operator_qq=sender.id,
                    serverId=server_id,
                    persistedGameId=server_guid,
                    gameId=server_gameid,
                    pid=add_task[i]["personaId"],
                    display_name=add_task[i]["displayName"],
                    action="vip",
                    info="添加成功(checkvip)",
                )
                add_suc_count += 1
            else:
                add_task[i]["result"] = f"添加失败!{add_task_result[i]}"
                add_fail_count += 1
        send = [f"操作完成!\n成功添加{add_suc_count}个,失败{add_fail_count}个\n成功删除{del_suc_count}个,失败{del_fail_count}个"]
        if del_fail_count:
            for i in range(len(del_task)):
                if del_task[i]["result"].startswith("删除失败"):
                    send.append(f"{del_task[i]['displayName']}:{del_task[i]['result']}")
        if add_fail_count:
            for i in range(len(add_task)):
                if add_task[i]["result"].startswith("添加失败"):
                    send.append(f"{add_task[i]['displayName']}:{add_task[i]['result']}")
        auto_change_map = True
        if (add_suc_count + del_suc_count > 0) and server_fullInfo["serverInfo"]["mapNamePretty"] not in [
            '聖康坦的傷痕', '窩瓦河', '海麗絲岬', '法歐堡', '攻佔托爾', '格拉巴山',
            '凡爾登高地', '加利西亞', '蘇瓦松', '流血宴廳', '澤布呂赫',
            '索姆河', '武普庫夫山口', '龐然闇影'
        ]:
            send.append("当前地图非战役第一张图，记得切图哦~")
            auto_change_map = False
        send = "\n".join(send)
        await app.send_message(group, MessageChain(send), quote=source)
        # 重开地图
        if not auto_change_map:
            return
        if add_suc_count + del_suc_count == 0:
            return
        server_info = server_fullInfo["serverInfo"]
        map_list = [f"{map_item['modePrettyName']}-{map_item['mapPrettyName']}" for map_item in server_info["rotation"]]
        map_index = map_list.index(f'{server_info["mapModePretty"]}-{server_info["mapNamePretty"]}')
        result = await account_instance.chooseLevel(persistedGameId=server_guid, levelIndex=map_index)
        if isinstance(result, dict):
            suc_str = f"成功重开服务器{server_rank}地图为:{map_list[int(map_index)]}" \
                .replace('流血', '流\u200b血').replace('\n', '')
            await app.send_message(group, MessageChain(
                suc_str
            ), quote=source)
            await BF1Log.record(
                operator_qq=sender.id,
                serverId=server_id,
                persistedGameId=server_guid,
                gameId=server_gameid,
                pid=None,
                display_name=None,
                action="change_map",
                info=suc_str,
            )
            return
        return await app.send_message(group, MessageChain(
            f"重开地图时执行出错!{result}"
        ), quote=source)


# 自动清理征服vip
@channel.use(SchedulerSchema(timers.every_custom_hours(2)))  # 每小时执行一次
async def auto_del_vip_timedOut():
    bf1_group_info = await BF1DB.bf1group.get_all_bf1_group_info()
    if not bf1_group_info:
        return logger.debug("当前没有BF1群组")
    for group_info in bf1_group_info:
        for i, id_info in enumerate(group_info["bind_ids"]):
            if not id_info:
                continue
            if not id_info["account"] or not id_info["guid"]:
                continue
            server_id = id_info["serverId"]
            server_gameid = id_info["gameId"]
            server_guid = id_info["guid"]
            account_instance = await BF1ManagerAccount.get_manager_account_instance(id_info["account"])
            server_fullInfo = await account_instance.getFullServerDetails(server_gameid)
            if isinstance(server_fullInfo, str):
                logger.error(f"获取服务器信息出错!{server_fullInfo}")
                continue
            server_fullInfo = server_fullInfo["result"]
            if server_fullInfo["serverInfo"]["mapModePretty"] == "行動模式":
                logger.debug(f"群组{group_info['group_name']}的服务器{i + 1}为行动模式,已自动跳过")
                continue
            # 同步服务器vip信息
            await BF1ServerVipManager.update_server_vip(server_full_info=server_fullInfo)
            vip_info = await BF1ServerVipManager.get_server_vip_list(server_id)

            # 清理过期的vip
            del_task = []
            del_suc_count = 0
            del_fail_count = 0
            for vip in vip_info:
                expire_time = vip.get("expire_time")
                if not expire_time:
                    continue
                days_diff = DateTimeUtils.diff_days(expire_time, datetime.now())
                if days_diff < 0:
                    del_task.append(vip)
            if not del_task:
                logger.debug(f"群组{group_info['group_name']}的服务器{i + 1}没有过期的VIP,已自动跳过")
                continue
            logger.debug(f"群组{group_info['group_name']}的服务器{i + 1}预计清理{len(del_task)}个过期的VIP")
            del_task_result = await asyncio.gather(
                *[account_instance.removeServerVip(task["personaId"], server_id) for task in del_task])
            for index in range(len(del_task)):
                if isinstance(del_task_result[index], dict):
                    del_task[index]["result"] = "删除成功"
                    # 更新数据库
                    await BF1ServerVipManager.del_server_vip_by_pid(
                        server_id=server_id, player_pid=del_task[index]["personaId"]
                    )
                    await BF1Log.record(
                        operator_qq=0,
                        serverId=server_id,
                        persistedGameId=server_guid,
                        gameId=server_gameid,
                        pid=del_task[index]["personaId"],
                        display_name=del_task[index]["displayName"],
                        action="unvip",
                        info="删除成功(自动清理过期VIP)",
                    )
                    del_suc_count += 1
                else:
                    del_task[index]["result"] = f"删除失败!{del_task_result[index]}"
                    del_fail_count += 1
            logger.debug(f"群组{group_info['group_name']}的服务器{i + 1}清理过期的VIP完成,成功{del_suc_count}个,失败{del_fail_count}个")


# 查vip列表
@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level),
    Permission.user_require(Permission.User, if_noticed=True),
)
@dispatch(
    Twilight(
        [
            UnionMatch("-viplist", "-vip列表", "-vl").space(SpacePolicy.PRESERVE),
            ParamMatch(optional=True).space(SpacePolicy.NOSPACE) @ "bf_group_name",
            FullMatch("#", optional=True).space(SpacePolicy.NOSPACE),
            ParamMatch(optional=False) @ "server_rank",
            # 示例: -viplist#1
        ]
    )
)
async def get_vipList(
        app: Ariadne, group: Group, sender: Member, source: Source,
        bf_group_name: RegexResult, server_rank: RegexResult
):
    # 服务器序号检查
    server_rank = server_rank.result.display
    if not server_rank.isdigit():
        return await app.send_message(group, MessageChain("请输入正确的服务器序号"), quote=source)
    server_rank = int(server_rank)
    if server_rank < 1 or server_rank > 30:
        return await app.send_message(group, MessageChain("服务器序号只能在1~30内"), quote=source)

    # 获取群组信息
    bf_group_name = bf_group_name.result.display if bf_group_name and bf_group_name.matched else None
    if not bf_group_name:
        bf1_group_info = await BF1GROUP.get_bf1Group_byQQ(group.id)
        if not bf1_group_info:
            return await app.send_message(group, MessageChain("请先绑定BF1群组/指定群组名"), quote=source)
        bf_group_name = bf1_group_info.get("group_name")

    # if not await perm_judge(bf_group_name, group, sender):
    #     return await app.send_message(
    #         group,
    #         MessageChain(f"您不是群组[{bf_group_name}]的成员"),
    #         quote=source,
    #     )

    server_info = await BF1GROUP.get_bindInfo_byIndex(bf_group_name, server_rank)
    if not server_info:
        return await app.send_message(group, MessageChain(
            f"群组[{bf_group_name}]未绑定服务器{server_rank}"
        ), quote=source)
    elif isinstance(server_info, str):
        return await app.send_message(group, MessageChain(server_info), quote=source)
    server_id = server_info["serverId"]
    server_gameid = server_info["gameId"]
    server_guid = server_info["guid"]

    # 获取服务器信息-fullInfo
    server_fullInfo = await (await BF1DA.get_api_instance()).getFullServerDetails(server_gameid)
    if isinstance(server_fullInfo, str):
        return await app.send_message(group, MessageChain(
            f"获取服务器信息出错!{server_fullInfo}"
        ), quote=source)
    server_fullInfo = server_fullInfo["result"]

    # 是否为行动模式
    # if server_fullInfo["serverInfo"]["mapModePretty"] == "行動模式" and \
    #         server_fullInfo["serverInfo"]["slots"]["Soldier"]["current"] == 0:
    #     await app.send_message(group, MessageChain(
    #         "当前服务器为行动模式且人数为0,操作失败!"
    #     ), quote=source)
    #     return False
    operation_mode = False
    if server_fullInfo["serverInfo"]["mapModePretty"] == "行動模式":
        operation_mode = True

    # 同步服务器vip信息
    await BF1ServerVipManager.update_server_vip(server_full_info=server_fullInfo)

    # 获取服务器vip信息
    vip_info = await BF1ServerVipManager.get_server_vip_list(server_id)
    vip_list = []
    for vip in vip_info:
        expire_time = vip.get("expire_time")
        days_diff = DateTimeUtils.diff_days(expire_time, datetime.now()) if expire_time else None
        temp_str = expire_time.strftime('%Y-%m-%d') if expire_time else "永久"

        if not operation_mode:
            expired_str = "(已过期)" if days_diff and days_diff < 0 else ""
            vip_list.append(
                f"名字: {vip['displayName']}\n"
                f"PID: {vip['personaId']}\n"
                f"到期时间: {temp_str} {expired_str}\n"
            )
        else:
            valid = vip["valid"]
            expired_str = ""
            if days_diff is not None:
                if days_diff < 0:
                    expired_str = "(已过期,待检查删除)"
                elif days_diff >= 0 and not valid:
                    expired_str = "(待生效)"
            elif not valid:
                expired_str = "(待生效)"
            vip_list.append(
                f"名字: {vip['displayName']}\n"
                f"PID: {vip['personaId']}\n"
                f"到期时间: {temp_str} {expired_str}\n"
            )

    # 组合为转发消息
    vip_list = sorted(vip_list)
    vip_len = len(vip_list)
    fwd_nodeList = [ForwardNode(
        target=sender,
        time=datetime.now(),
        message=MessageChain(
            f"服务器: {server_fullInfo['serverInfo']['name']}\n"
            f"GameId:{server_fullInfo['serverInfo']['gameId']}\n"
            f"VIP人数:{vip_len}"
        ),
    )]
    lists = vip_list
    cut_len = int(vip_len / 99)
    if cut_len == 0:
        cut_len = 1
    res_data = []
    if len(lists) > cut_len:
        for i in range(int(len(lists) / cut_len)):
            cut_a = lists[cut_len * i:cut_len * (i + 1)]
            res_data.append(cut_a)
        last_data = lists[int(len(lists) / cut_len) * cut_len:]
        if last_data:
            res_data.append(last_data)
    else:
        res_data.append(lists)
    for item in res_data:
        fwd_nodeList.append(ForwardNode(
            target=sender,
            time=datetime.now(),
            message=MessageChain(item),
        ))
    message = MessageChain(Forward(nodeList=fwd_nodeList))
    await app.send_message(group, message)
    return app.send_message(group, MessageChain([At(sender.id), "请点击转发消息查看!"]), quote=source)


# 查ban列表
@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level),
    Permission.user_require(Permission.User, if_noticed=True),
)
@dispatch(
    Twilight(
        [
            UnionMatch("-banlist", "-ban列表", "-bl", "-封禁列表", "-封禁list").space(SpacePolicy.PRESERVE),
            ParamMatch(optional=True).space(SpacePolicy.NOSPACE) @ "bf_group_name",
            FullMatch("#", optional=True).space(SpacePolicy.NOSPACE),
            ParamMatch(optional=False) @ "server_rank",
        ]
    )
)
async def get_banList(
        app: Ariadne, group: Group, sender: Member, source: Source,
        bf_group_name: RegexResult, server_rank: RegexResult
):
    # 服务器序号检查
    server_rank = server_rank.result.display
    if not server_rank.isdigit():
        return await app.send_message(group, MessageChain("请输入正确的服务器序号"), quote=source)
    server_rank = int(server_rank)
    if server_rank < 1 or server_rank > 30:
        return await app.send_message(group, MessageChain("服务器序号只能在1~30内"), quote=source)

    # 获取群组信息
    bf_group_name = bf_group_name.result.display if bf_group_name and bf_group_name.matched else None
    if not bf_group_name:
        bf1_group_info = await BF1GROUP.get_bf1Group_byQQ(group.id)
        if not bf1_group_info:
            return await app.send_message(group, MessageChain("请先绑定BF1群组/指定群组名"), quote=source)
        bf_group_name = bf1_group_info.get("group_name")

    # if not await perm_judge(bf_group_name, group, sender):
    #     return await app.send_message(
    #         group,
    #         MessageChain(f"您不是群组[{bf_group_name}]的成员"),
    #         quote=source,
    #     )

    server_info = await BF1GROUP.get_bindInfo_byIndex(bf_group_name, server_rank)
    if not server_info:
        return await app.send_message(group, MessageChain(
            f"群组[{bf_group_name}]未绑定服务器{server_rank}"
        ), quote=source)
    elif isinstance(server_info, str):
        return await app.send_message(group, MessageChain(server_info), quote=source)
    server_id = server_info["serverId"]
    server_gameid = server_info["gameId"]
    server_guid = server_info["guid"]

    # 获取服务器信息-fullInfo
    server_fullInfo = await (await BF1DA.get_api_instance()).getFullServerDetails(server_gameid)
    if isinstance(server_fullInfo, str):
        return await app.send_message(group, MessageChain(
            f"获取服务器信息出错!{server_fullInfo}"
        ), quote=source)
    server_fullInfo = server_fullInfo["result"]

    ban_list = []
    for item in server_fullInfo["rspInfo"]["bannedList"]:
        temp = f"名字:{item['displayName']}\nPid:{item['personaId']}\n"
        ban_list.append(temp)

    ban_list = sorted(ban_list)
    ban_len = len(ban_list)
    sender_member = await app.get_member(group, app.account)
    fwd_nodeList = [ForwardNode(
        target=sender_member,
        time=datetime.now(),
        message=MessageChain(
            f"服务器: {server_fullInfo['serverInfo']['name']}\n"
            f"GameId:{server_fullInfo['serverInfo']['gameId']}\n"
            f"封禁人数:{ban_len}"
        ),
    )]
    lists = ban_list
    cut_len = int(ban_len / 99)
    if cut_len == 0:
        cut_len = 1
    res_data = []
    if len(lists) > cut_len:
        for i in range(int(len(lists) / cut_len)):
            cut_a = lists[cut_len * i:cut_len * (i + 1)]
            res_data.append(cut_a)
        last_data = lists[int(len(lists) / cut_len) * cut_len:]
        if last_data:
            res_data.append(last_data)
    else:
        res_data.append(lists)
    for item in res_data:
        fwd_nodeList.append(ForwardNode(
            target=sender_member,
            time=datetime.now(),
            message=MessageChain(item),
        ))
    message = MessageChain(Forward(nodeList=fwd_nodeList))
    await app.send_message(group, message)
    return app.send_message(group, MessageChain([At(sender.id), "请点击转发消息查看!"]), quote=source)


# 查管理列表
@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level),
    Permission.user_require(Permission.User, if_noticed=True),
)
@dispatch(
    Twilight(
        [
            UnionMatch("-adminlist", "-管理列表", "-al").space(SpacePolicy.NOSPACE),
            ParamMatch(optional=True).space(SpacePolicy.NOSPACE) @ "bf_group_name",
            FullMatch("#", optional=True).space(SpacePolicy.NOSPACE),
            ParamMatch(optional=False) @ "server_rank",
        ]
    )
)
async def get_adminList(
        app: Ariadne, group: Group, sender: Member, source: Source,
        bf_group_name: RegexResult, server_rank: RegexResult
):
    # 服务器序号检查
    server_rank = server_rank.result.display
    if not server_rank.isdigit():
        return await app.send_message(group, MessageChain("请输入正确的服务器序号"), quote=source)
    server_rank = int(server_rank)
    if server_rank < 1 or server_rank > 30:
        return await app.send_message(group, MessageChain("服务器序号只能在1~30内"), quote=source)

    # 获取群组信息
    bf_group_name = bf_group_name.result.display if bf_group_name and bf_group_name.matched else None
    if not bf_group_name:
        bf1_group_info = await BF1GROUP.get_bf1Group_byQQ(group.id)
        if not bf1_group_info:
            return await app.send_message(group, MessageChain("请先绑定BF1群组/指定群组名"), quote=source)
        bf_group_name = bf1_group_info.get("group_name")

    # if not await perm_judge(bf_group_name, group, sender):
    #     return await app.send_message(
    #         group,
    #         MessageChain(f"您不是群组[{bf_group_name}]的成员"),
    #         quote=source,
    #     )

    server_info = await BF1GROUP.get_bindInfo_byIndex(bf_group_name, server_rank)
    if not server_info:
        return await app.send_message(group, MessageChain(
            f"群组[{bf_group_name}]未绑定服务器{server_rank}"
        ), quote=source)
    elif isinstance(server_info, str):
        return await app.send_message(group, MessageChain(server_info), quote=source)
    server_id = server_info["serverId"]
    server_gameid = server_info["gameId"]
    server_guid = server_info["guid"]

    # 获取服务器信息-fullInfo
    server_fullInfo = await (await BF1DA.get_api_instance()).getFullServerDetails(server_gameid)
    if isinstance(server_fullInfo, str):
        return await app.send_message(group, MessageChain(
            f"获取服务器信息出错!{server_fullInfo}"
        ), quote=source)
    server_fullInfo = server_fullInfo["result"]

    admin_list = []
    for item in server_fullInfo["rspInfo"]["adminList"]:
        temp = f"名字:{item['displayName']}\nPid:{item['personaId']}"
        admin_list.append(temp)
    admin_list = sorted(admin_list)
    admin_len = len(admin_list)
    sender_member = await app.get_member(group, app.account)
    fwd_nodeList = [ForwardNode(
        target=sender_member,
        time=datetime.now(),
        message=MessageChain(
            f"服务器: {server_fullInfo['serverInfo']['name']}\n"
            f"GameId:{server_fullInfo['serverInfo']['gameId']}\n"
            f"管理员人数:{admin_len}"
        ),
    )]
    lists = admin_list
    cut_len = int(admin_len / 99)
    if cut_len == 0:
        cut_len = 1
    res_data = []
    if len(lists) > cut_len:
        for i in range(int(len(lists) / cut_len)):
            cut_a = lists[cut_len * i:cut_len * (i + 1)]
            res_data.append(cut_a)
        last_data = lists[int(len(lists) / cut_len) * cut_len:]
        if last_data:
            res_data.append(last_data)
    else:
        res_data.append(lists)
    for item in res_data:
        fwd_nodeList.append(ForwardNode(
            target=sender_member,
            time=datetime.now(),
            message=MessageChain(item),
        ))
    message = MessageChain(Forward(nodeList=fwd_nodeList))
    await app.send_message(group, message)
    return app.send_message(group, MessageChain([At(sender.id), "请点击转发消息查看!"]), quote=source)


# 帮助
@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level),
    Permission.user_require(Permission.User, if_noticed=True),
)
@dispatch(
    Twilight.from_command("-help bf1服管")
)
async def bf1_help(app: Ariadne, group: Group, source: Source):
    send = [
        "查询服务器：-服务器/-fwq/-FWQ/-服/-f/-狐务器/-负无穷",
        "查询服务器详情：上述查询指令后面加上 群组名和服务器序号",
        "如：-服务器 sakula1 即可查询群组sakula群组的第一个服务器的详情，如果当前QQ群绑定了群组，则可以省略群组名，如：-f1",
        "查询服内群友：-谁在玩/-谁在捞 群组名(可选)服务器序号",
        "如：-谁在玩sakula1 1, -谁在捞1",
        "查询玩家列表：-玩家列表/-playerlist/-pl/-lb+群组名(可选)服务器序号",
        "如：-pl sakula1, -lb1",
        "刷新session：-refresh 群组名(可选)服务器序号",
        "如：-refresh1, -refresh 1, -refresh sakula1",
        "踢出玩家：-kick/-踢/-k/-滚出+可选群组名+服务器序号+空格+玩家名+可选原因",
        "如：-kick sakula1 shlsan13 你好 (注意这里的sakula1的sakula为群组名,1为服务器序号，中间不加任何符号，服务器序号后一定要跟空格), -k1 shlsan13 你好",
        "封禁玩家：-ban/-封禁+可选群组名+服务器序号+空格+玩家名+可选原因",
        "如：-ban sakula1 shlsan13 你好, -ban1 shlsan13 你好",
        "解封玩家：-unban/-uban/-解封+可选群组名+服务器序号+空格+玩家名,解封不能加原因！",
        "如：-unban sakula1 shlsan13, -unban1 shlsan13",
        "全部封禁：-banall/-ba+空格+群组名+空格+玩家名+可选原因，全部封禁时不能加服务器序号只能(必须)写群组名",
        "如：-ba sakula 你好, -basakula shlsan13 你好",
        "全部解封：-unbanall/-uba+空格+玩家名+群组名，全部解封时不能加服务器序号只能(必须)写群组名",
        "如：-uba sakula shlsan13, -ubasakula shlsan13",
        "检查是否封禁玩家：-checkban+可选群组名+玩家名,不能写服务器序号",
        "如：-checkban sakula xiaoxiao",
        "清理BAN位：-清理ban位/-清ban+可选群组名+服务器序号+可选数量，当不指定数量时默认为200(全部清理)",
        "如：-清理ban位 sakula1 100, -清ban1",
        "换边：-move/-换边/-挪+可选群组名+服务器序号+空格+玩家名+队伍ID",
        "如：-move sakula1 shlsan13 1, -move1 shlsan13 2",
        "换图：-map/-换图/-切图+可选群组名+服务器序号+空格+地图名/地图序号",
        "如：-map sakula1 要塞, -map1 重开",
        "图池换图：-图池/-maplist/-地图池+可选群组名+服务器序号",
        "如：-图池 sakula1, -maplist1",
        "加VIP：-vip/-v/-加v/-上v+可选群组名+服务器序号+空格+玩家名+可选时间(单位：天，可为负数)",
        "如：-vip sakula1 shlsan13 3, -vip1 shlsan13 -3",
        "下VIP：-unvip/-uvip/-删v/-下v/-减v+可选群组名+服务器序号+空格+玩家名,下v时不能写天数",
        "如：-unvip sakula1 shlsan13, -unvip1 shlsan13",
        "检查VIP：-checkvip+可选群组名+服务器序号",
        "如：-checkvip sakula1, -checkvip1 (行动服用于自动将缓存VIP生效/删除,并重开当前地图(非首图不重开但提示重开)，征服会清理VIP)",
        "VIP列表：-viplist/-vip列表/-vl+可选群组名+服务器序号",
        "如：-vlsakula1, -vl1, -vl sakula1",
        "BAN列表：-banlist/-ban列表/-bl/-封禁列表/-封禁list+可选群组名+服务器序号",
        "如：-bl sakula1, -bl1, -bl sakula1",
        "ADMIN列表：-adminlist/-管理列表/-al+可选群组名+服务器序号",
        "如：-al sakula1, -al1, -al sakula1",
        "BF1群组和服管号相关操作请使用：-help bf群组"
    ]
    send = "\n".join(send)
    await app.send_message(group, MessageChain(send), quote=source)


@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level),
    Permission.user_require(Permission.BotAdmin, if_noticed=True),
)
@dispatch(
    Twilight.from_command("-help bf群组")
)
async def bfgroup_help(app: Ariadne, group: Group, source: Source):
    await app.send_message(group, MessageChain(
        """===================
指令前缀：-bf群组 = -bfg ，参数括号代表可替换的英文
===================
#建立/删除/修改/查询相关：
-bfg 新建(new)/删除(del)/信息(info) 群组名
如: -bfg info sakula

-bfg 改名(rename) 群组名 new_name
如: -bfg rename sakula sakula2

-bf群组列表 / -bfgl
===================
#绑定/解绑相关：
-bfg 群组名 绑服#(bind#)服务器序号 服务器gameid
如: -bfg sakula bind#1 123123123

-bfg 群组名 解绑#服务器序号
如: -bfg sakula 解绑#1

-bfg 群组名 绑群 QQ群号
如：-bfg sakula 绑群 123123
===================
#权限相关：

添加/删除 管理/服主, aa为添加管理员,ao为添加服主,del为删除权限
-bfg 群组名 aa/ao/del qq号(可以为@元素，可为多个用空格隔开)
如：-bfg sakula aa @你 @他

-bfg 群组名 权限列表(permlist)
如：-bfg sakula permlist
===================
#服管帐号相关：
指令前缀：-bf服管账号 = -bfga

查询服管帐号列表：
-bf服管账号列表  = -bfal

登录/新建帐号：
-bf服管帐号 登录 玩家名 remid=xxx,sid=xxx
如：-bfga login SHlSAN13 remid=xxx,sid=xxx

删除：
-bf服管帐号 删除 帐号pid
如：-bfga del 123123      
(123123为获取到的帐号pid)

信息：
-bf服管帐号 信息 帐号pid
如：-bfga info 123123
===================
# 群组绑定/解绑服管：
-bf群组 群组名#服务器序号 使用服管(use) 帐号pid
如：-bfg sakula#1 use 123123        
(绑定指定服)

-bf群组 群组名 使用服管(use) 帐号pid
如：-bfg sakula use 123123            
(绑定所有服)

-bf群组 群组名 #服务器序号 解绑服管
如：-bfg sakula #1 解绑服管

-bf群组 群组名 解绑服管
如：-bfg sakula 解绑服管
"""
    ), quote=source)
