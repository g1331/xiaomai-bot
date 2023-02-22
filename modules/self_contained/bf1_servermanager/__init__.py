import asyncio
import difflib
import json
import math
import os
import shutil
import time
from pathlib import Path
from typing import Union

import aiohttp
import httpx
import yaml
import zhconv
from PIL import Image as PIL_Image
from PIL import ImageFont, ImageDraw, ImageFilter, ImageEnhance
from creart import create
from graia.ariadne.app import Ariadne
from graia.ariadne.event.message import GroupMessage, FriendMessage
from graia.ariadne.message.chain import MessageChain
from graia.ariadne.message.element import Image as GraiaImage
from graia.ariadne.message.element import Source, ForwardNode, Forward
from graia.ariadne.message.parser.twilight import (
    Twilight, FullMatch, ParamMatch, RegexResult, SpacePolicy,
    PRESERVE, UnionMatch, WildcardMatch, RegexMatch)
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
from core.models import saya_model
from utils.UI import *
from utils.string import generate_random_str
from utils.text2img import md2img
from .api_gateway import refresh_api_client, get_player_stat_data
from .bfgroups_log import rsp_log
from .main_session_auto_refresh import auto_refresh_account
from .map_team_info import MapData
from .utils import getPid_byName, server_playing, app_blocked

module_controller = saya_model.get_module_controller()
global_config = create(GlobalConfig)
saya = Saya.current()
channel = Channel.current()
channel.name("BF1服管")
channel.description("战地1服务器管理插件")
channel.author("13")
channel.metadata = module_controller.get_metadata_from_path(Path(__file__))
true = True
false = False
null = ''


# limits = httpx.Limits(max_keepalive_connections=None, max_connections=None)
# client = httpx.AsyncClient(limits=limits)


# TODO: 1.创建群组-增删改查 2.群组添加服务器-增删改查、qq群绑定群组后查服务器 3.服管账号-增删改查、绑定到群组服务器的账号 4.踢人 5.封禁 6.换边 7.换图 8.vip
# TODO: 前置功能: 搜索服务器
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
            "action" @ UnionMatch("-搜服务器", "-服务器").space(SpacePolicy.PRESERVE),
            "server_name" @ WildcardMatch(optional=True).space(SpacePolicy.PRESERVE)
        ]
    )
)
async def search_server(app: Ariadne, group: Group, server_name: RegexResult, source: Source):
    server_name = str(server_name.result)
    if server_name == '':
        return
    elif server_name.startswith("#"):
        return
    try:
        result = await api_gateway.search_server_by_name(server_name)
    except Exception as e:
        logger.error(e)
        await app.send_message(group, MessageChain(
            f'接口出错，请稍后再试'
        ), quote=source)
        return False
    if result == "timed out":
        await app.send_message(group, MessageChain(
            f'网络出错，请稍后再试'
        ), quote=source)
        return False
    if not result:
        await app.send_message(group, MessageChain(
            f'共搜索到0个服务器'
        ), quote=source)
        return True
    temp = []
    length = len(result)
    if 0 < length <= 3:
        temp.append(f"共搜到{length}个服务器\n")
        temp.append("=" * 20 + "\n")
        for item in result:
            temp.append(f'{item["name"]}\n')
            temp.append(f'GameId:{item["gameId"]}\n')
            # temp.append(f'Guid:{item["guid"]}\n')
            # 人数:62/64[1](0)
            temp.append(
                f'{item["slots"]["Soldier"]["current"]}/{item["slots"]["Soldier"]["max"]}[{item["slots"]["Queue"]["current"]}]({item["slots"]["Spectator"]["current"]}) ')
            # 地图:行动模式-苏伊士
            temp.append(f'{item["mapModePretty"]}-{item["mapNamePretty"]}\n'.replace("流血", "流\u200b血").replace("战争",
                                                                                                               "战\u200b争"))
            if item["description"] != '':
                temp.append(f'简介:{item["description"]}\n')
            temp.append("=" * 20 + "\n")
        temp[-1] = temp[-1].replace("\n", '')
        await app.send_message(group, MessageChain(
            temp
        ), quote=source)
        return True
    elif 3 < length <= 10:
        temp.append(f"共搜到{length}个服务器\n")
        temp.append("=" * 20 + "\n")
        for item in result:
            temp.append(f'{item["name"][:30]}\n')
            temp.append(f'GameId:{item["gameId"]}\n')
            # temp.append(f'Guid:{item["guid"]}\n')
            # 人数:62/64[1](0)
            temp.append(
                f'{item["slots"]["Soldier"]["current"]}/{item["slots"]["Soldier"]["max"]}[{item["slots"]["Queue"]["current"]}]({item["slots"]["Spectator"]["current"]})  ')
            # 地图:行动模式-苏伊士
            temp.append(f'{item["mapModePretty"]}-{item["mapNamePretty"]}\n'.replace("流血", "流\u200b血").replace("战争",
                                                                                                               "战\u200b争"))
            temp.append("=" * 20 + "\n")
        temp[-1] = temp[-1].replace("\n", '')

        # await app.send_message(
        #     group,
        #     await MessageChainUtils.messagechain_to_img(
        #         MessageChain(
        #             temp
        #         )
        #     ), quote=message[Source][0]
        # )

        await app.send_message(group, MessageChain(
            temp
        ), quote=source)
        return True
    elif 10 < length <= 20:
        fwd_nodeList = []
        bot_member = await app.get_member(group, app.account)
        servers = []
        # temp = []
        for item in result:
            temp = [
                f'{item["name"]}\n',
                f'{item["slots"]["Soldier"]["current"]}/{item["slots"]["Soldier"]["max"]}[{item["slots"]["Queue"]["current"]}]({item["slots"]["Spectator"]["current"]})\n',
                f'GameId:{item["gameId"]}\n',
                f'{item["mapModePretty"]}-{item["mapNamePretty"]}'.replace("流血", "流\u200b血").replace("战争", "战\u200b争")
            ]
            # temp.append(f'Guid:{item["guid"]}\n')
            # 人数:62/64[1](0)
            # 地图:行动模式-苏伊士
            if item["description"] != '':
                temp.append(f'\n简介:{item["description"]}\n\n')
            # temp.append("=" * 20 + "\n")
            fwd_nodeList.append(
                ForwardNode(
                    target=bot_member,
                    time=datetime.now(),
                    message=MessageChain(temp),
                )
            )
            servers.append(temp)

        # temp[-1] = temp[-1].replace("\n", '')
        # await app.send_message(
        #     group,
        #     await MessageChainUtils.messagechain_to_img(
        #         MessageChain(
        #             temp
        #         )
        #     ), quote=message[Source][0]
        # )

        message_send = MessageChain(Forward(nodeList=fwd_nodeList))
        try:
            await app.send_message(group, MessageChain(
                message_send
            ), quote=source)
            await app.send_message(group, MessageChain(
                f"共搜到{length}个服务器,请点击转发消息查看!"
            ), quote=source)
        except:
            try:
                await app.send_message(
                    group,
                    MessageChain(
                        GraiaImage(data_bytes=await md2img(servers))
                    ),
                    quote=source
                )
                return
            except Exception as e:
                logger.error(e)
                await app.send_message(group, MessageChain(
                    f"发送消息失败,请增加关键词!"
                ), quote=source)
        return
    else:
        result = result[:20]
        bot_member = await app.get_member(group, app.account)
        fwd_nodeList = []
        servers = []
        # temp = []
        for item in result:
            temp = [
                f'{item["name"]}\n',
                f'{item["slots"]["Soldier"]["current"]}/{item["slots"]["Soldier"]["max"]}[{item["slots"]["Queue"]["current"]}]({item["slots"]["Spectator"]["current"]})\n',
                f'GameId:{item["gameId"]}\n',
                f'{item["mapModePretty"]}-{item["mapNamePretty"]}'.replace("流血", "流\u200b血").replace("战争", "战\u200b争")
            ]
            # temp.append(f'Guid:{item["guid"]}\n')
            # 人数:62/64[1](0)
            # 地图:行动模式-苏伊士
            if item["description"] != '':
                temp.append(f'\n简介:{item["description"]}\n\n')
            # temp.append("=" * 20 + "\n")
            fwd_nodeList.append(
                ForwardNode(
                    target=bot_member,
                    time=datetime.now(),
                    message=MessageChain(temp),
                )
            )
            servers.append(temp)

        # temp[-1] = temp[-1].replace("\n", '')
        # await app.send_message(group, MessageChain(
        #             f"共搜到{length}个服务器,已保留前20个结果,请点击图片查看!"
        #         ), quote=message[Source][0])
        # await app.send_message(
        #     group,
        #     await MessageChainUtils.messagechain_to_img(
        #         MessageChain(
        #             temp
        #         )
        #     ), quote=message[Source][0]
        # )

        message_send = MessageChain(Forward(nodeList=fwd_nodeList))
        try:
            await app.send_message(group, MessageChain(
                message_send
            ), quote=source)
            await app.send_message(group, MessageChain(
                f"共搜到{length}个服务器,已保留前20个结果,请点击转发消息查看!"
            ), quote=source)
        except:
            try:
                await app.send_message(
                    group,
                    MessageChain(
                        GraiaImage(data_bytes=await md2img(servers))
                    ),
                    quote=source
                )
                return
            except:
                await app.send_message(group, MessageChain(
                    f"发送消息失败,请增加关键词!"
                ), quote=source)
        return
        # result_list = cut_list(result, int(len(result)/4) + 1)
        # for item_temp in result_list:
        #     fwd_nodeList = []
        #     for item in item_temp:
        #         temp = []
        #         temp.append(f'{item["name"][:30]}\n')
        #         temp.append(f'GameId:{item["gameId"]}\n')
        #         temp.append(f'Guid:{item["guid"]}\n')
        #         # 人数:62/64[1](0)
        #         temp.append(
        #             f'人数:{item["slots"]["Soldier"]["current"]}/{item["slots"]["Soldier"]["max"]}[{item["slots"]["Queue"]["current"]}]({item["slots"]["Spectator"]["current"]})\n')
        #         # 地图:行动模式-苏伊士
        #         temp.append(f'{item["mapModePretty"]}-{item["mapNamePretty"]}\n'.replace("流血", ""))
        #         # temp.append(f'简介:{item["description"]}')
        #         fwd_nodeList.append(
        #             ForwardNode(
        #                 target=bot_member,
        #                 time=datetime.now(),
        #                 message=MessageChain(temp),
        #             )
        #         )
        #     await app.send_message(group, MessageChain(
        #         Forward(nodeList=fwd_nodeList)
        #     ), quote=message[Source][0])


# TODO: 详细服务器
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
            FullMatch("-详细服务器").space(SpacePolicy.PRESERVE),
            "server_gameid" @ ParamMatch(optional=True).space(PRESERVE)
        ]
    )
)
async def get_server_detail(app: Ariadne, group: Group, server_gameid: RegexResult, source: Source):
    server_gameid = str(server_gameid.result)
    if server_gameid is None:
        await app.send_message(group, MessageChain(
            f"请检查输入的服务器gameid"
        ))
        return False
    try:
        # await app.send_message(group, MessageChain(
        #     f'搜索ing'
        # ), quote=message[Source][0])
        result = await api_gateway.get_server_fulldetails(server_gameid)
        if result == "":
            raise Exception
    except:
        await app.send_message(group, MessageChain(
            f'可能网络接口出错/输入gameid有误，请稍后再试'
        ), quote=source)
        return False
    temp = [
        f'{result["serverInfo"]["name"]}\n', "=" * 20 + "\n", f'Gameid:{result["serverInfo"]["gameId"]}\n',
        f'Guid:{result["serverInfo"]["guid"]}\n', f'Serverid:{result["rspInfo"]["server"]["serverId"]}\n',
                                             f"=" * 20 + "\n",
        f'人数:{result["serverInfo"]["slots"]["Soldier"]["current"]}/{result["serverInfo"]["slots"]["Soldier"]["max"]}'
        f'[{result["serverInfo"]["slots"]["Queue"]["current"]}]({result["serverInfo"]["slots"]["Spectator"]["current"]}) ',
        f"收藏:{result['serverInfo']['serverBookmarkCount']}\n",
        f'地图:{result["serverInfo"]["mapModePretty"]}-{result["serverInfo"]["mapNamePretty"]}\n'.replace("流血",
                                                                                                        "流\u200b血").replace(
            "战争", "战\u200b争")
    ]
    try:
        temp.append(f'服主:{result["rspInfo"]["owner"]["displayName"]} Pid:{result["rspInfo"]["owner"]["personaId"]}\n')
    except:
        pass
    if result["serverInfo"]["description"] != '':
        temp.append(f'简介:{result["serverInfo"]["description"]}\n')
    temp.append("=" * 20 + "\n")
    try:
        temp.append(
            f'战队名:{result["platoonInfo"]["name"]}\n战队简写:{result["platoonInfo"]["tag"]} 人数:{result["platoonInfo"]["size"]}\n')
        temp.append(f'战队描述:{result["platoonInfo"]["description"]}\n')
        temp.append("=" * 20 + "\n")
    except:
        pass
    temp.append(
        f'创建时间:{time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(int(result["rspInfo"]["server"]["createdDate"]) / 1000))}\n')
    temp.append(
        f'到期时间:{time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(int(result["rspInfo"]["server"]["expirationDate"]) / 1000))}\n')
    temp.append(
        f'续费时间:{time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(int(result["rspInfo"]["server"]["updatedDate"]) / 1000))}\n')
    temp.append("=" * 20)
    await app.send_message(group, MessageChain(
        temp
    ), quote=source)


# TODO 1：-bf群组 增删改查

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
            FullMatch("-bf群组 新建").space(SpacePolicy.PRESERVE),
            "group_name" @ ParamMatch(optional=True).space(PRESERVE)
        ]
    )
)
async def bfgroup_create(app: Ariadne, group: Group, group_name: RegexResult, source: Source):
    if group_name.result is None:
        await app.send_message(group, MessageChain(
            "请输入bf群组名称"
        ), quote=source)
        return False
    group_path = f"./data/battlefield/binds/bfgroups/{group_name.result}"
    if not os.path.exists(group_path):
        os.makedirs(group_path)
        open(f'{group_path}/log.yaml', 'w', encoding="utf-8")
        open(f'{group_path}/servers.yaml', 'w', encoding="utf-8")
        open(f'{group_path}/perm.yaml', 'w', encoding="utf-8")
        await app.send_message(group, MessageChain(
            f"bf群组创建{group_name.result}成功\n"
            f"已自动生成群组log与servers文件\n"
            f"已创建权限组默认为空"
        ), quote=source)
    else:
        await app.send_message(group, MessageChain(
            f"bf群组{group_name.result}已存在"
        ), quote=source)


# 删除bf群组
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
            FullMatch("-bf群组 删除").space(SpacePolicy.PRESERVE),
            "group_name" @ ParamMatch(optional=True).space(PRESERVE),

        ]
    )
)
async def bfgroup_del(app: Ariadne, group: Group, group_name: RegexResult, source: Source):
    if group_name.result is None:
        await app.send_message(group, MessageChain(
            "请输入bf群组名称"
        ), quote=source)
        return False
    group_path = f"./data/battlefield/binds/bfgroups/{group_name.result}"
    if os.path.exists(group_path):
        shutil.rmtree(group_path)
        await app.send_message(group, MessageChain(
            f"bf群组删除{group_name.result}成功"
        ), quote=source)
        return True
    else:
        await app.send_message(group, MessageChain(
            f"bf群组{group_name.result}不存在"
        ), quote=source)
        return False


# bf群组改名 - os.rename(old_name,new_name) name->文件夹路径
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
            FullMatch("-bf群组").space(SpacePolicy.PRESERVE),
            "group_old_name" @ ParamMatch(optional=False).space(SpacePolicy.FORCE),
            FullMatch("改名").space(SpacePolicy.PRESERVE),
            "group_new_name" @ ParamMatch(optional=False).space(SpacePolicy.PRESERVE),
            # 示例: -bf群组 skl 改名 sakula
        ]
    )
)
async def bfgroup_rename(app: Ariadne, group: Group, group_old_name: RegexResult,
                         group_new_name: RegexResult, source: Source):
    group_old_name = group_old_name.result.display
    group_new_name = group_new_name.result.display
    # 检查是否有bf群组
    group_old_path = f"./data/battlefield/binds/bfgroups/{group_old_name}"
    group_new_oath = f"./data/battlefield/binds/bfgroups/{group_new_name}"
    if not os.path.exists(group_old_path):
        await app.send_message(group, MessageChain(
            f"群组{group_old_name}不存在"
        ), quote=source)
        return False
    else:
        try:
            os.rename(group_old_path, group_new_oath)
            await app.send_message(group, MessageChain(
                f"群组{group_old_name}更名为{group_new_name}成功!"
            ), quote=source)
            return False
        except:
            await app.send_message(group, MessageChain(
                f"操作失败!"
            ), quote=source)
            return False


bfgroup_list_info_send_temp = []
bot_list_temp = []
joined_group = []
group_bot_dict = {}
bot_list = global_config.bot_accounts


# bf群组名单
@listen(GroupMessage)
@decorate(
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level),
    Permission.user_require(Permission.BotAdmin, if_noticed=True),
)
@dispatch(
    Twilight(
        [
            FullMatch("-bf群组列表").space(SpacePolicy.PRESERVE)
        ]
    )
)
async def bfgroup_list_info(app: Ariadne, resv_group: Group, source: Source):
    global bfgroup_list_info_send_temp, bot_list, bot_list_temp, joined_group, group_bot_dict
    bf_group_list_send_temp = []
    # group_path = f"./data/battlefield/binds/bfgroups"
    # group_list = os.listdir(group_path)
    # for item in group_list:
    #     send_temp.append(item + "\n")
    # await app.send_message(group, MessageChain(
    #     f"当前共{len(send_temp)}个群组:\n", send_temp
    # ), quote=message[Source][0])

    # 1.获取bot群列表 2.如果群有绑定的群组就加到send
    bfgroup_path = f"./data/battlefield/binds/bfgroups"
    bfgroup_list = os.listdir(bfgroup_path)
    bfgroups = []
    for item in bfgroup_list:
        bfgroups.append(item)
    group_path = f"./data/battlefield/binds/groups"
    # group_list = os.listdir(group_path)

    bot_group_list_temp = await app.get_group_list()
    # bot_group_list = []
    # for group in bot_group_list_temp:
    #     bot_group_list.append(group.id)

    for group in bot_group_list_temp:
        if group.id != global_config.test_group:
            if os.path.exists(f"{group_path}/{group.id}/bfgroups.yaml"):
                if group.id not in group_bot_dict:
                    group_bot_dict[group.id] = []
                member_list = await app.get_member_list(group)
                member_list = [member_item.id for member_item in member_list]
                for bot in bot_list:
                    if bot in member_list:
                        group_bot_dict[group.id].append(bot)
                    group_bot_dict[group.id].append(app.account)
                with open(f"{group_path}/{group.id}/bfgroups.yaml", 'r', encoding="utf-8") as file1:
                    try:
                        bfgroup_name = (yaml.load(file1, yaml.Loader))["bfgroups"]
                        if f"{bfgroup_name}  " not in bf_group_list_send_temp:
                            bf_group_list_send_temp.append(f"{bfgroup_name}  ")
                            joined_group.append(bfgroup_name.lower())
                    except:
                        pass

    bf_group_list_send_temp = sorted(bf_group_list_send_temp, key=len)
    bot_member = await app.get_member(resv_group, app.account)
    bot_send_temp = [
        f"{bot_member.name}({bot_member.id})加入{len(bf_group_list_send_temp)}个群组:\n",
        bf_group_list_send_temp,
        "\n" + "=" * 18 + "\n"
    ]
    bfgroup_list_info_send_temp.append(bot_send_temp)

    if resv_group.id == global_config.test_group:
        bot_list_temp.append(app.account)
        if len(bot_list_temp) != len(bot_list):
            return
        unjoided_group = [f""]

        for item in bfgroup_list:
            if item.lower() not in joined_group:
                unjoided_group.append(
                    f"{item}|"
                )
        unjoided_group[0] = f"无bot群组{len(unjoided_group)}/{len(bfgroup_list)}:\n"
        if len(unjoided_group) != 1:
            bfgroup_list_info_send_temp.append(
                unjoided_group
            )

        if group_bot_dict != {}:
            for key in group_bot_dict:
                group_bot_dict[key] = list(set(group_bot_dict[key]))
                if len(group_bot_dict[key]) > 1:
                    bfgroup_list_info_send_temp.append(
                        f"\n群{key}包含重复bot:\n{group_bot_dict[key]}"
                    )

    else:
        bot_list_temp2 = []
        member_list = await app.get_member_list(resv_group)
        for member_temp in member_list:
            if member_temp.id in bot_list:
                bot_list_temp2.append(member_temp.id)
        bot_list_temp.append(app.account)
        bot_list_temp2.append(app.account)
        if len(bot_list_temp) != len(bot_list_temp2):
            return
    bfgroup_list_info_send_temp.insert(0, f"当前共{len(bfgroup_list)}个群组:\n")
    await app.send_message(resv_group, MessageChain(
        bfgroup_list_info_send_temp
    ), quote=source)
    # await app.send_message(
    #     resv_group,
    #     await MessageChainUtils.messagechain_to_img(
    #         MessageChain(
    #             bfgroup_list_info_send_temp
    #         )
    #     ),
    #     quote=message[Source][0]
    # )
    bfgroup_list_info_send_temp = []
    bot_list_temp = []
    joined_group = []
    group_bot_dict = {}


# TODO 2:服务器绑定 增删改查

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
            FullMatch("-bf群组").space(SpacePolicy.PRESERVE),
            "group_name" @ ParamMatch(optional=False).space(SpacePolicy.FORCE),
            FullMatch("绑服#").space(SpacePolicy.NOSPACE),
            "server_rank" @ ParamMatch(optional=False).space(SpacePolicy.FORCE),
            "server_gameid" @ ParamMatch(optional=False).space(SpacePolicy.PRESERVE),
            # 示例: -bf群组 skl 绑服1 gameid
        ]
    )
)
async def bfgroup_bind_server(app: Ariadne, group: Group,
                              group_name: RegexResult, server_rank: RegexResult, server_gameid: RegexResult,
                              source: Source):
    group_name = str(group_name.result)
    server_gameid = str(server_gameid.result)
    try:
        server_rank = int(str(server_rank.result))
        if server_rank > 30:
            raise Exception
    except:
        await app.send_message(group, MessageChain(
            f"请检查输入所要绑定的服务器序号(群组最大30)"
        ), quote=source)
        return False
    # 检查是否有bf群组
    group_path = f"./data/battlefield/binds/bfgroups/{group_name}"
    if not os.path.exists(group_path):
        await app.send_message(group, MessageChain(
            f"群组{group_name}不存在"
        ), quote=source)
        return False
    # 检查gameid是否正确
    try:
        result = await api_gateway.get_server_fulldetails(server_gameid)
        if result == '':
            await app.send_message(group, MessageChain(
                f"网络出错或检查输入的gameid"
            ), quote=source)
            return False
    except:
        await app.send_message(group, MessageChain(
            f"网络出错或检查输入的gameid"
        ), quote=source)
        return False
    # 获取管理pid列表，如果服管账号pid在里面则绑定
    admin_list = []
    for item in result["rspInfo"]["adminList"]:
        temp = f"{item['personaId']}"
        admin_list.append(temp)
    # 获取服管账号列表
    file_path = f'./data/battlefield/managerAccount'
    if not (os.path.exists(file_path) or os.path.isfile(file_path)):
        await app.send_message(group, MessageChain(
            f'未检测到managerAccount文件夹'
        ), quote=source)
        return False
    else:
        account_list = os.listdir(file_path)
        if len(account_list) == 0:
            await app.send_message(group, MessageChain(
                f'未检测到任何服管账号，请新建一个'
            ), quote=source)
            return False
        managerAccount_list_temp = {}
        for item in account_list:
            with open(file_path + f"/{item}/info.json", 'r', encoding="utf-8") as file_tamp:
                data = json.load(file_tamp)
                name = data["personas"]["persona"][0]["displayName"]
                pid = data["personas"]["persona"][0]["personaId"]
                managerAccount_list_temp[str(pid)] = name
    managerAccount = None
    for i, item in enumerate(managerAccount_list_temp):
        if str(item) in admin_list:
            managerAccount = item
    # 绑定服务器gameid
    with open(f'./data/battlefield/binds/bfgroups/{group_name}/servers.yaml', 'r', encoding="utf-8") as file1:
        data = yaml.load(file1, yaml.Loader)
        # print(data)
        if data is None:
            data = {"servers": ["" for _ in range(30)]}
            data["servers"][server_rank - 1] = {"gameid": server_gameid, "guid": result["serverInfo"]["guid"],
                                                "serverid": result["rspInfo"]["server"]["serverId"],
                                                "managerAccount": managerAccount}
        else:
            data["servers"][server_rank - 1] = {"gameid": server_gameid, "guid": result["serverInfo"]["guid"],
                                                "serverid": result["rspInfo"]["server"]["serverId"],
                                                "managerAccount": managerAccount}
        with open(f'./data/battlefield/binds/bfgroups/{group_name}/servers.yaml', 'w', encoding="utf-8") as file2:
            yaml.dump(data, file2, allow_unicode=True)
            await app.send_message(group, MessageChain(
                f'群组{group_name}成功绑定服务器{server_rank}:{server_gameid}\n' +
                (f"服管账号为:{managerAccount_list_temp[managerAccount]}({managerAccount})"
                 if managerAccount else "未检测到服管账号请手动指定!")
            ), quote=source)
            return True


# 群组解绑服务器-删
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
            FullMatch("-bf群组").space(SpacePolicy.PRESERVE),
            "group_name" @ ParamMatch(optional=False).space(SpacePolicy.FORCE),
            FullMatch("解绑#").space(SpacePolicy.NOSPACE),
            "server_rank" @ ParamMatch(optional=False).space(SpacePolicy.PRESERVE),
            # 示例: -bf群组 skl 解绑#1
        ]
    )
)
async def bfgroup_del_server(app: Ariadne, group: Group,
                             group_name: RegexResult, server_rank: RegexResult, source: Source):
    group_name = str(group_name.result)
    server_rank = int(str(server_rank.result))
    try:
        server_rank = int(server_rank)
        if server_rank > 30:
            raise Exception
    except:
        await app.send_message(group, MessageChain(
            f"请检查输入所要绑定的服务器序号(群组最大30)"
        ), quote=source)
        return False
    # 检查是否有bf群组
    group_path = f"./data/battlefield/binds/bfgroups/{group_name}"
    if not os.path.exists(group_path):
        await app.send_message(group, MessageChain(
            f"群组{group_name}不存在"
        ), quote=source)
        return False
    # 解绑服务器gameid
    with open(f'./data/battlefield/binds/bfgroups/{group_name}/servers.yaml', 'r', encoding="utf-8") as file1:
        data = yaml.load(file1, yaml.Loader)
        # print(data)
        if data is None:
            data = {"servers": ["" for _ in range(30)]}
            data["servers"][server_rank - 1] = ""
        else:
            data["servers"][server_rank - 1] = ""
        with open(f'./data/battlefield/binds/bfgroups/{group_name}/servers.yaml', 'w', encoding="utf-8") as file2:
            yaml.dump(data, file2, allow_unicode=True)
            await app.send_message(group, MessageChain(
                f'群组{group_name}成功解绑服务器{server_rank}'
            ), quote=source)
            return True


# 查询群组服务器-查
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
            FullMatch("-bf群组").space(SpacePolicy.PRESERVE),
            "group_name" @ ParamMatch(optional=False).space(SpacePolicy.FORCE),
            FullMatch("信息").space(SpacePolicy.PRESERVE),
            # 示例: -bf群组 skl 信息
        ]
    )
)
async def bfgroup_del_server(app: Ariadne, group: Group,
                             group_name: RegexResult, source: Source):
    group_name = str(group_name.result)
    # 检查是否有bf群组
    group_path = f"./data/battlefield/binds/bfgroups/{group_name}"
    if not os.path.exists(group_path):
        await app.send_message(group, MessageChain(
            f"群组{group_name}不存在"
        ), quote=source)
        return False
    with open(f'./data/battlefield/binds/bfgroups/{group_name}/servers.yaml', 'r', encoding="utf-8") as file1:
        data = yaml.load(file1, yaml.Loader)
        # 检查是否servers.yaml是否为空
        if data is None:
            await app.send_message(group, MessageChain(
                f"群组服务器信息为空，请先绑定服务器"
            ), quote=source)
            return False
        else:
            temp = []
            i = 1
            for item in data["servers"]:
                if item != "":
                    # 获取服管账号名字
                    if not ((item["managerAccount"] is None) or (item["managerAccount"] == '')):
                        with open(f'./data/battlefield/managerAccount/{item["managerAccount"]}/info.json') as file2:
                            data = json.load(file2)
                            account_name = data["personas"]["persona"][0]["displayName"]
                    temp.append(f'{i}:Gameid:{item["gameid"]}\n')
                    temp.append(f'Guid:{item["guid"]}\n')
                    temp.append(f'Serverid:{item["serverid"]}\n')
                    temp.append(
                        f'服管账号:{item["managerAccount"]}({account_name})\n' if not (
                                (item["managerAccount"] is None) or (item["managerAccount"] == '')) else "服管账号:无\n")
                    temp.append("=" * 20 + "\n")
                    i += 1
                else:
                    i += 1
            temp[-1] = temp[-1].replace("\n", '')
            await app.send_message(group, MessageChain(
                f"群组{group_name}信息如下:\n",
                temp
            ), quote=source)
            return True


# 群组创建vban
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
            FullMatch("-bf群组").space(SpacePolicy.PRESERVE),
            "group_name" @ ParamMatch(optional=False).space(SpacePolicy.FORCE),
            FullMatch("创建vban#").space(SpacePolicy.NOSPACE),
            "vban_rank" @ ParamMatch(optional=False).space(SpacePolicy.PRESERVE),
            # 示例: -bf群组 skl 创建vban
        ]
    )
)
async def bfgroup_create_vban(app: Ariadne, group: Group,
                              group_name: RegexResult, vban_rank: RegexResult, source: Source):
    group_name = str(group_name.result)
    # 检查是否有bf群组
    group_path = f"./data/battlefield/binds/bfgroups/{group_name}"
    if not os.path.exists(group_path):
        await app.send_message(group, MessageChain(
            f"群组{group_name}不存在"
        ), quote=source)
        return False
    try:
        vban_rank = int(str(vban_rank.result))
        if vban_rank < 1 or vban_rank > 10:
            raise Exception
        if vban_rank == 1:
            vban_rank = ''
    except:
        await app.send_message(group, MessageChain(
            "请检查vban序号:1~10"
        ), quote=source)
        return False
    # 是否有vban的文件
    vban_file_path = f'./data/battlefield/binds/bfgroups/{group_name}/vban{vban_rank}.json'
    if os.path.isfile(vban_file_path):
        await app.send_message(group, MessageChain(
            "vban配置已存在,请勿重复创建"
        ), quote=source)
        return False
    else:
        open(f'./data/battlefield/binds/bfgroups/{group_name}/vban{vban_rank}.json', 'w', encoding="utf-8")
        await app.send_message(group, MessageChain(
            f"群组{group_name}创建vban配置文件成功,请手动配置groupid和token"
        ), quote=source)
        return True


# 群组查询vban
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
            FullMatch("-bf群组").space(SpacePolicy.PRESERVE),
            "group_name" @ ParamMatch(optional=False).space(SpacePolicy.FORCE),
            FullMatch("vban信息").space(SpacePolicy.PRESERVE),
            # 示例: -bf群组 skl vban信息
        ]
    )
)
async def bfgroup_get_vban(app: Ariadne, group: Group,
                           group_name: RegexResult, source: Source):
    group_name = str(group_name.result)
    # 检查是否有bf群组
    group_path = f"./data/battlefield/binds/bfgroups/{group_name}"
    if not os.path.exists(group_path):
        await app.send_message(group, MessageChain(
            f"群组{group_name}不存在"
        ), quote=source)
        return False
    send_temp = []
    # 是否有vban的文件
    vban_file_path = f'./data/battlefield/binds/bfgroups/{group_name}'
    file_list = os.listdir(vban_file_path)
    for file in file_list:
        if "vban" in file:
            with open(f"{vban_file_path}/{file}", 'r', encoding='utf-8') as file1:
                try:
                    data = json.load(file1)["groupid"]
                    send_temp.append(f"{data}\n")
                except:
                    await app.send_message(group, MessageChain(
                        f"群组{group_name}vban信息为空!"
                    ), quote=source)
                    return False
    if len(send_temp) == 0:
        await app.send_message(group, MessageChain(
            f"群组{group_name}没有找到vban信息"
        ), quote=source)
        return True
    else:
        await app.send_message(group, MessageChain(
            f"群组{group_name}vban有:\n", send_temp
        ), quote=source)
        return True


# 群组删除vban
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
            FullMatch("-bf群组").space(SpacePolicy.PRESERVE),
            "group_name" @ ParamMatch(optional=False).space(SpacePolicy.FORCE),
            FullMatch("删除vban#").space(SpacePolicy.NOSPACE),
            "vban_rank" @ ParamMatch(optional=False).space(SpacePolicy.PRESERVE),
            # 示例: -bf群组 skl 删除vban#1
        ]
    )
)
async def bfgroup_del_vban(app: Ariadne, group: Group,
                           group_name: RegexResult, vban_rank: RegexResult, source: Source):
    group_name = str(group_name.result)
    # 检查是否有bf群组
    group_path = f"./data/battlefield/binds/bfgroups/{group_name}"
    if not os.path.exists(group_path):
        await app.send_message(group, MessageChain(
            f"群组{group_name}不存在"
        ), quote=source)
        return False
    try:
        vban_rank = int(str(vban_rank.result))
        if vban_rank < 1 or vban_rank > 10:
            raise Exception
        if vban_rank == 1:
            vban_rank = ''
    except:
        await app.send_message(group, MessageChain(
            "请检查vban序号:1~10"
        ), quote=source)
        return False
    # 是否有vban的文件
    vban_file_path = f'./data/battlefield/binds/bfgroups/{group_name}/vban{vban_rank}.json'
    if not os.path.isfile(vban_file_path):
        await app.send_message(group, MessageChain(
            f"vban{vban_rank}配置不存在!"
        ), quote=source)
        return False
    else:
        os.remove(vban_file_path)
        await app.send_message(group, MessageChain(
            f"群组{group_name}删除vban{vban_rank}成功!"
        ), quote=source)
        return True


# 配置vban的群组id和token
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
            FullMatch("-bf群组").space(SpacePolicy.FORCE),
            "group_name" @ ParamMatch(optional=False).space(SpacePolicy.FORCE),
            FullMatch("配置vban#").space(SpacePolicy.NOSPACE),
            "vban_rank" @ ParamMatch(optional=False).space(SpacePolicy.FORCE),
            FullMatch("gid=").space(SpacePolicy.NOSPACE),
            "group_id" @ ParamMatch(optional=False).space(SpacePolicy.NOSPACE),
            FullMatch(",token=").space(SpacePolicy.NOSPACE),
            "token" @ ParamMatch(optional=False).space(SpacePolicy.PRESERVE),
            # 示例: -bf群组 skl 配置vban#n gid=xxx,token=xxx
        ]
    )
)
async def bfgroup_config_vban(app: Ariadne, group: Group,
                              group_name: RegexResult, group_id: RegexResult,
                              token: RegexResult, vban_rank: RegexResult, source: Source):
    group_name = str(group_name.result)
    # 检查是否有bf群组
    group_path = f"./data/battlefield/binds/bfgroups/{group_name}"
    if not os.path.exists(group_path):
        await app.send_message(group, MessageChain(
            f"群组{group_name}不存在"
        ), quote=source)
        return False
    try:
        vban_rank = int(str(vban_rank.result))
        if vban_rank < 1 or vban_rank > 10:
            raise Exception
        if vban_rank == 1:
            vban_rank = ''
    except:
        await app.send_message(group, MessageChain(
            "请检查vban序号:1~10"
        ), quote=source)
        return False
    # 是否有vban的文件
    vban_file_path = f'./data/battlefield/binds/bfgroups/{group_name}/vban{vban_rank}.json'
    if not os.path.isfile(vban_file_path):
        await app.send_message(group, MessageChain(
            f"没有找到群组vban{vban_rank}文件,请先为群组创建vban{vban_rank}"
        ), quote=source)
        return False
    # 有的话就写入数据
    else:
        data = {
            "groupid": group_id.result.display.replace("\n", ""),
            "token": token.result.display.replace("\n", "")
        }
        with open(vban_file_path, 'w', encoding="utf-8") as file1:
            json.dump(data, file1, indent=4)
            await app.send_message(group, MessageChain(
                f"群组{group_name}写入vban{vban_rank}配置成功!"
            ), quote=source)
            return True


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
            FullMatch("-bf群组").space(SpacePolicy.PRESERVE),
            "group_name" @ ParamMatch(optional=False).space(SpacePolicy.FORCE),
            FullMatch("绑群").space(SpacePolicy.PRESERVE),
            "qqgroup_id" @ ParamMatch(optional=False).space(SpacePolicy.PRESERVE),
            # 示例: -bf群组 skl 绑群 123
        ]
    )
)
async def bfgroup_bind_qqgroup(app: Ariadne, group: Group,
                               group_name: RegexResult, qqgroup_id: RegexResult, source: Source):
    group_name = str(group_name.result)
    qqgroup_id = str(qqgroup_id.result)
    # 检查是否有bf群组
    group_path = f"./data/battlefield/binds/bfgroups/{group_name}"
    if not os.path.exists(group_path):
        await app.send_message(group, MessageChain(
            f"群组{group_name}不存在"
        ), quote=source)
        return False
    # 检查qq群是否正确
    if await app.get_group(int(qqgroup_id)) is None:
        await app.send_message(group, MessageChain(
            f"bot没有找到群{qqgroup_id}"
        ), quote=source)
        return False
    # 检查qq群文件是否存在
    group_path = f'./data/battlefield/binds/groups/{qqgroup_id}'
    file_path = group_path + "/bfgroups.yaml"
    if not os.path.exists(group_path):
        os.makedirs(group_path)
    if not os.path.isfile(file_path):
        open(file_path, "w", encoding="utf-8")
        await app.send_message(group, MessageChain(
            f'已自动创建绑定文件'
        ), quote=source)
    with open(file_path, "w+", encoding="utf-8") as file1:
        data = {"bfgroups": group_name}
        yaml.dump(data, file1, allow_unicode=True)
        await app.send_message(group, MessageChain(
            f'{qqgroup_id}绑定bf群组{group_name}成功'
        ))
        return True


async def auto_update_gameid(group_file_path):
    with open(group_file_path, 'r', encoding="utf-8") as file1:
        data = yaml.load(file1, yaml.Loader)
        # 检查是否servers.yaml是否为空
        if data is None:
            logger.warning("群组服务器信息为空!")
            return
        else:
            for i, item in enumerate(data["servers"]):
                if item != "":
                    # 查询guid_server_path是否存在,如果,gameid!=当前的,就更新成当前的
                    guid_path = f"./data/battlefield/servers/{item['guid']}/searched.json"
                    if not os.path.exists(guid_path):
                        logger.warning("群组服务器guid文件不存在!")
                        continue
                    with open(guid_path, 'r', encoding="utf-8") as file2:
                        data2 = json.load(file2)
                        if data2 is None:
                            logger.warning("服务器guid文件为空!")
                            continue
                        if data2["gameId"] > item["gameid"]:
                            data["servers"][i]["gameid"] = data2["gameId"]
                            with open(group_file_path, 'w', encoding="utf-8") as file3:
                                yaml.dump(data, file3, allow_unicode=True)
                                logger.success(f"更新服务器gameid成功")
                        else:
                            logger.info("服务器gameid未变更")
                else:
                    return


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
            "action" @ UnionMatch("-服务器", "-fwq", "-FWQ", "-服", "-f", "-狐务器", "-负无穷").space(
                SpacePolicy.PRESERVE)
            # 示例: -服务器
        ]
    )
)
async def check_server(app: Ariadne, group: Group, source: Source):
    # 先检查绑定群组没
    # 检查qq群文件是否存在
    group_path = f'./data/battlefield/binds/groups/{group.id}'
    file_path = group_path + "/bfgroups.yaml"
    if not (os.path.exists(group_path) or os.path.isfile(file_path)):
        await app.send_message(group, MessageChain(
            f'请先绑定bf群组'
        ), quote=source)
        return False
    # 打开绑定的文件
    with open(file_path, 'r', encoding="utf-8") as file1:
        data = yaml.load(file1, yaml.Loader)
        try:
            bfgroups_name = data["bfgroups"]
        except:
            await app.send_message(group, MessageChain(
                f'未识别到群组，请重新绑定bf群组'
            ), quote=source)
    # 根据bf群组名字找到群组绑定服务器文件-获取服务器gameid
    group_path = f"./data/battlefield/binds/bfgroups/{bfgroups_name}"
    if not os.path.exists(group_path):
        await app.send_message(group, MessageChain(
            f"群组{bfgroups_name}不存在"
        ), quote=source)
        return False
    group_file_path = f'./data/battlefield/binds/bfgroups/{bfgroups_name}/servers.yaml'
    time_start = time.time()
    # 检查更新服务器gameid
    await auto_update_gameid(group_file_path)
    with open(group_file_path, 'r', encoding="utf-8") as file1:
        data = yaml.load(file1, yaml.Loader)
        # 检查是否servers.yaml是否为空
        if data is None:
            await app.send_message(group, MessageChain(
                f"群组服务器信息为空，请先绑定服务器"
            ), quote=source)
            return False
        else:
            server_list = []
            for item in data["servers"]:
                if item != "":
                    server_list.append(f'{item["gameid"]}')
                else:
                    server_list.append("")
    # 并发查找
    scrape_index_tasks = [asyncio.ensure_future(api_gateway.get_server_details(gameid)) for gameid in server_list]
    # scrape_index_tasks = [asyncio.ensure_future(api_gateway.get_server_fulldetails(gameid)) for gameid in server_list]
    tasks = asyncio.gather(*scrape_index_tasks)
    try:
        await tasks
        logger.info(f"查询{bfgroups_name}服务器ing")
    except:
        await app.send_message(group, MessageChain(
            GraiaImage(path='./data/bqb/狐务器无响应.jpg')
        ), quote=source)
        return False
    logger.info(f"查询{bfgroups_name}服务器完成,耗时:{(time.time() - time_start):.2f}秒")
    result = [f"所属群组:{bfgroups_name}\n" + "=" * 18]
    counter = 1
    servers = 0
    for i in scrape_index_tasks:
        i = i.result()
        if i == "":
            counter += 1
        else:
            result.append(f'\n{counter}#:{i["name"][:20]}\n')
            人数 = f'人数:{i["slots"]["Soldier"]["current"]}/{i["slots"]["Soldier"]["max"]}[{i["slots"]["Queue"]["current"]}]({i["slots"]["Spectator"]["current"]})'
            result.append(人数)
            result.append(f"  收藏:{i['serverBookmarkCount']}\n")
            result.append(
                f'地图:{i["mapModePretty"]}-{i["mapNamePretty"]}\n'.replace("流血", "流\u200b血").replace("战争", "战\u200b争"))
            # result.append(f'GameId:{i["gameId"]} ')
            result.append(f"=" * 18)
            counter += 1
            servers += 1
    if len(result) == 1:
        await app.send_message(group, MessageChain(
            GraiaImage(path='./data/bqb/狐务器无响应.jpg')
        ), quote=source)
        return False
    result.append(f"\n({generate_random_str(20)})")

    server_list_column = [
        ColumnTitle(title=f"所属群组:{bfgroups_name}"),
        ColumnTitle(title=f"可使用-f#n获取服务器详细信息"),
    ]
    for i, item in enumerate(scrape_index_tasks):
        item = item.result()
        if not item:
            continue
        server_list_column.append(
            ColumnUserInfo(
                name=f"{i + 1}:{item['name'][:15]}",
                description=f"{item['name']}",
                avatar=item["mapImageUrl"].replace("[BB_PREFIX]",
                                                   "https://eaassets-a.akamaihd.net/battlelog/battlebinary")
            )
        )
        server_list_column.append(
            ColumnList(
                rows=[
                    ColumnListItem(
                        subtitle=f"当前人数："
                                 f'{item["slots"]["Soldier"]["current"]}/{item["slots"]["Soldier"]["max"]}'
                                 f'[{item["slots"]["Queue"]["current"]}]'
                                 f'({item["slots"]["Spectator"]["current"]})'
                    ),
                    ColumnListItem(
                        subtitle=f"地图模式：{item['mapNamePretty']}--{item['mapModePretty']}"
                    ),
                    ColumnListItem(
                        subtitle=f"当前收藏：{item['serverBookmarkCount']}"
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
            "action" @ UnionMatch("-服务器", "-fwq", "-FWQ", "-服", "-f", "-狐务器",
                                  "-负无穷").space(
                SpacePolicy.NOSPACE),
            FullMatch("#", optional=False).space(SpacePolicy.NOSPACE),
            "server_index" @ ParamMatch(optional=False).space(SpacePolicy.PRESERVE),
            # 示例: -服务器
        ]
    )
)
async def check_server_by_index(app: Ariadne, group: Group,
                                server_index: RegexResult, source: Source):
    try:
        server_index = int(str(server_index.result))
        if server_index > 30 or server_index < 1:
            raise Exception
    except:
        await app.send_message(group, MessageChain(
            f'请检测服务器序号:1~30'
        ), quote=source)
        return False
    # 先检查绑定群组没
    # 检查qq群文件是否存在
    group_path = f'./data/battlefield/binds/groups/{group.id}'
    file_path = group_path + "/bfgroups.yaml"
    if not (os.path.exists(group_path) or os.path.isfile(file_path)):
        await app.send_message(group, MessageChain(
            f'请先绑定bf群组'
        ), quote=source)
        return False
    # 打开绑定的文件
    with open(file_path, 'r', encoding="utf-8") as file1:
        data = yaml.load(file1, yaml.Loader)
        try:
            bfgroups_name = data["bfgroups"]
        except:
            await app.send_message(group, MessageChain(
                f'未识别到群组，请重新绑定bf群组'
            ), quote=source)
    # 根据bf群组名字找到群组绑定服务器文件-获取服务器gameid
    group_path = f"./data/battlefield/binds/bfgroups/{bfgroups_name}"
    if not os.path.exists(group_path):
        await app.send_message(group, MessageChain(
            f"群组{bfgroups_name}不存在"
        ), quote=source)
        return False
    with open(f'./data/battlefield/binds/bfgroups/{bfgroups_name}/servers.yaml', 'r', encoding="utf-8") as file1:
        data = yaml.load(file1, yaml.Loader)
        # 检查是否servers.yaml是否为空
        if data is None:
            await app.send_message(group, MessageChain(
                f"群组服务器信息为空，请先绑定服务器"
            ), quote=source)
            return False
    if data["servers"][server_index - 1] != '':
        server_gameid = data["servers"][server_index - 1]["gameid"]
    else:
        await app.send_message(group, MessageChain(
            f"该序号未绑定服务器，请先绑定服务器"
        ), quote=source)
        return False
    try:
        server_info = await api_gateway.get_server_fulldetails(server_gameid)
        if server_info == '':
            raise Exception
    except:
        await app.send_message(group, MessageChain(
            GraiaImage(path='./data/bqb/狐务器无响应.jpg')
        ), quote=source)
        return False
    result = [f"所属群组:{bfgroups_name}\n" + "=" * 18 + "\n", f'{server_index}:{server_info["serverInfo"]["name"]}\n',
              "=" * 18 + "\n",
              f'地图:{server_info["serverInfo"]["mapModePretty"]}-{server_info["serverInfo"]["mapNamePretty"]}\n'.replace(
                  "流血", "流\u200b血").replace("战争", "战\u200b争"),
              f'人数:{server_info["serverInfo"]["slots"]["Soldier"]["current"]}/{server_info["serverInfo"]["slots"]["Soldier"]["max"]}'
              f'[{server_info["serverInfo"]["slots"]["Queue"]["current"]}]({server_info["serverInfo"]["slots"]["Spectator"]["current"]}) ',
              f"收藏:{server_info['serverInfo']['serverBookmarkCount']}\n",
              f'Guid:{server_info["serverInfo"]["guid"]}\n',
              f'GId:{server_info["serverInfo"]["gameId"]}\n',
              f'SId:{server_info["rspInfo"]["server"]["serverId"]}\n',
              "=" * 18 + "\n",

              f'简介:{server_info["serverInfo"]["description"]}\n' + "=" * 20 + "\n"
              if server_info['serverInfo']["description"] != ''
              else
              '',

              f'创建时间:{time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(int(server_info["rspInfo"]["server"]["createdDate"]) / 1000))}\n',
              f'到期时间:{time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(int(server_info["rspInfo"]["server"]["expirationDate"]) / 1000))}\n',
              f'续费时间:{time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(int(server_info["rspInfo"]["server"]["updatedDate"]) / 1000))}\n',
              f"=" * 18]

    # await app.send_message(
    #     group,
    #     await MessageChainUtils.messagechain_to_img(
    #         MessageChain(
    #             result
    #         )
    #     ), quote=message[Source][0]
    # )

    await app.send_message(group, MessageChain(
        result
    ), quote=source)


async def get_group_bindList(app: Ariadne, group) -> list:
    group_member_list_temp = await app.get_member_list(group.id)
    group_member_list = []
    bind_path = "./data/battlefield/binds/players"
    for item in group_member_list_temp:
        group_member_list.append(item.name.upper())
        if os.path.exists(f"{bind_path}/{item.id}"):
            try:
                with open(f"{bind_path}/{item.id}/bind.json", 'r', encoding="utf-8") as file1:
                    data = json.load(file1)
                    group_member_list.append(data["personas"]["persona"][0]["displayName"].upper())
            except:
                pass
    return group_member_list


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
            "action" @ UnionMatch("-谁在玩", "-谁在捞").space(
                SpacePolicy.NOSPACE),
            FullMatch("#", optional=True).space(SpacePolicy.NOSPACE),
            "server_rank" @ ParamMatch(optional=False).space(SpacePolicy.PRESERVE),
            # 示例: -谁在玩#1
        ]
    )
)
async def who_are_playing(app: Ariadne, group: Group, message: MessageChain, server_rank: RegexResult, src: Source):
    try:
        server_rank = int(str(server_rank.result))
        if server_rank > 30 or server_rank < 1:
            raise Exception
    except:
        await app.send_message(group, MessageChain(
            f'请检测服务器序号:1~30'
        ), quote=src)
        return False
    # 先检查绑定群组没
    # 检查qq群文件是否存在
    group_path = f'./data/battlefield/binds/groups/{group.id}'
    file_path = group_path + "/bfgroups.yaml"
    if not (os.path.exists(group_path) or os.path.isfile(file_path)):
        await app.send_message(group, MessageChain(
            f'请先绑定bf群组'
        ), quote=src)
        return False
    # 打开绑定的文件
    with open(file_path, 'r', encoding="utf-8") as file1:
        data = yaml.load(file1, yaml.Loader)
        try:
            bfgroups_name = data["bfgroups"]
        except:
            await app.send_message(group, MessageChain(
                f'未识别到群组，请重新绑定bf群组'
            ), quote=src)
    # 根据bf群组名字找到群组绑定服务器文件-获取服务器gameid
    group_path = f"./data/battlefield/binds/bfgroups/{bfgroups_name}"
    if not os.path.exists(group_path):
        await app.send_message(group, MessageChain(
            f"群组{bfgroups_name}不存在"
        ), quote=src)
        return False
    with open(f'./data/battlefield/binds/bfgroups/{bfgroups_name}/servers.yaml', 'r', encoding="utf-8") as file1:
        data = yaml.load(file1, yaml.Loader)
        # 检查是否servers.yaml是否为空
        if data is None:
            await app.send_message(group, MessageChain(
                f"群组服务器信息为空，请先绑定服务器"
            ), quote=src)
            return False
        else:
            if data["servers"][server_rank - 1] != "":
                server_gameid = data["servers"][server_rank - 1]["gameid"]
            else:
                await app.send_message(group, MessageChain(
                    f"该序号没有绑定服务器"
                ), quote=str)
                return False

    await app.send_message(group, MessageChain(
        "查询ing"
    ), quote=src)

    # 获取绑定的成员列表
    group_member_list = await get_group_bindList(app, group)

    # 获取服务器信息-fullInfo
    try:
        server_fullInfo = await api_gateway.get_server_fulldetails(server_gameid)
        if server_fullInfo == "":
            raise Exception
    except:
        await app.send_message(group, MessageChain(
            "获取服务器信息出现错误!"
        ), quote=src)
        return False
    admin_list = []
    vip_list = []
    try:
        for item in server_fullInfo["rspInfo"]["adminList"]:
            admin_list.append(f"{item['displayName']}".upper())
        for item in server_fullInfo["rspInfo"]["vipList"]:
            vip_list.append(f"{item['displayName']}".upper())
    except:
        pass

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
        return await app.send_message(group, MessageChain(playerlist_data), quote=src)
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
        player_list1[f'[{playerlist_data["teams"][0][i]["rank"]}]{playerlist_data["teams"][0][i]["display_name"]}'] = \
            "%s" % playerlist_data["teams"][0][i]["time"]
        i += 1
    i = 0
    while i < team2_num:
        player_list2[f'[{playerlist_data["teams"][1][i]["rank"]}]{playerlist_data["teams"][1][i]["display_name"]}'] = \
            "%s" % playerlist_data["teams"][1][i]["time"]
        i += 1
    player_dict_all = player_list1.copy()
    player_dict_all.update(player_list2)
    # 按照加入时间排序
    player_list_all = sorted(player_dict_all.items(), key=lambda kv: ([kv[1]], kv[0]))
    # print(player_list_all[0:20])
    player_list = []
    for item in player_list_all:
        player_list.append(item[0])
    if len(player_list) == 0:
        await app.send_message(group, MessageChain(
            f"获取到服务器内玩家数为0"
        ), quote=src)
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
        ), quote=src)
    else:
        await app.send_message(group, MessageChain(
            f"服内群友数:0", f"\n{update_time}"
        ), quote=src)


# 通过接口获取玩家列表
async def get_playerList_byGameid(server_gameid: Union[str, int, list]) -> Union[str, dict]:
    """
    :param server_gameid: 服务器gameid
    :return: 成功返回字典,失败返回信息
    """
    header = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/86.0.4240.193 Safari/537.36',
        'ContentType': 'json',
    }
    api_url = "https://delivery.easb.cc/games/get_server_status"
    if type(server_gameid) != list:
        data = {
            "gameIds": [
                server_gameid
            ]
        }
    else:
        data = {
            "gameIds": server_gameid
        }
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(api_url, headers=header, data=json.dumps(data), timeout=5)
        response = eval(response.text)
    except:
        return "网络超时!"
    if type(server_gameid) != list:
        if str(server_gameid) in response["data"]:
            return response["data"][str(server_gameid)] if response["data"][
                                                               str(server_gameid)] != '' else "服务器信息为空!"
        else:
            return f"获取服务器信息失败:{response}"
    else:
        return response["data"]


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
            "action" @ UnionMatch("-ppl").space(
                SpacePolicy.NOSPACE),
            FullMatch("#", optional=True).space(SpacePolicy.NOSPACE),
            "server_rank" @ ParamMatch(optional=False).space(SpacePolicy.PRESERVE),
            # 示例: -ppl#1
        ]
    )
)
async def get_server_playerList(app: Ariadne, group: Group, server_rank: RegexResult, source: Source):
    # 服务器序号检测
    try:
        server_rank = int(str(server_rank.result)) - 1
        if server_rank < 0 or server_rank > 30:
            raise Exception
    except:
        await app.send_message(group, MessageChain(
            f"请检查服务器序号"
        ), quote=source)
        return False
    # 获取服务器id信息
    id_dict = await get_bfgroup_ids(app, group, server_rank, source)
    if type(id_dict) != dict:
        return False
    else:
        # server_id = id_dict["serverid"]
        server_gameid = id_dict["gameid"]
        # server_guid = id_dict["guid"]
    data = await get_playerList_byGameid(server_gameid)
    if type(data) == str:
        if data == '':
            await app.send_message(group, MessageChain(
                "服务器信息为空!"
            ), quote=source)
            return
        else:
            await app.send_message(group, MessageChain(
                data
            ), quote=source)
            return
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
    try:
        await app.send_message(group, message_send)
    except Exception as e:
        logger.error(e)
        await app.send_message(group, MessageChain(
            f"发送消息失败,请检查日志!"
        ), quote=source)
        # try:
        #     await app.send_message(group, MessageChain(
        #         message_servername,"\n",
        #         message0,
        #         message1
        #     ), quote=message[Source][0])
        # except:
        #     await app.send_message(group, MessageChain(
        #         f"发送消息失败,请检查日志!"
        #     ), quote=message[Source][0])


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
                        fp = open(file_name, 'wb')
                        fp.write(pic)
                        fp.close()
                        return file_name
                except Exception as e:
                    logger.error(e)
                    i += 1
        return None


async def get_server_map_pic(map_name: str) -> str:
    file_path = f"./data/battlefield/游戏模式/data.json"
    with open(file_path, 'r', encoding="utf-8") as file1:
        data = json.load(file1)["result"]["maps"]
    for item in data:
        if item["assetName"] == map_name:
            try:
                pic = await download_serverMap_pic(item["images"]["JpgAny"].replace("[BB_PREFIX]",
                                                                                    "https://eaassets-a.akamaihd.net/battlelog/battlebinary"))
                return pic
            except:
                return None


def get_team_pic(team_name: str) -> str:
    team_pic_list = os.listdir(f"./data/battlefield/pic/team/")
    for item in team_pic_list:
        if team_name in item:
            return f"./data/battlefield/pic/team/{item}"


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


def get_width(o):
    """Return the screen column width for unicode ordinal o."""
    global widths
    if o == 0xe or o == 0xf:
        return 0
    for num, wid in widths:
        if o <= num:
            return wid
    return 1


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
            "action" @ UnionMatch("-玩家列表", "-playerlist", "-pl", "-lb").space(
                SpacePolicy.NOSPACE),
            FullMatch("#", optional=True).space(SpacePolicy.NOSPACE),
            "server_rank" @ ParamMatch(optional=False).space(SpacePolicy.PRESERVE),
            # 示例: -玩家列表#1
        ]
    )
)
async def get_server_playerList_pic(app: Ariadne, sender: Member, group: Group, server_rank: RegexResult, src: Source):
    # 服务器序号检测
    try:
        server_rank = int(str(server_rank.result)) - 1
        if server_rank < 0 or server_rank > 30:
            raise Exception
    except:
        await app.send_message(group, MessageChain(
            f"请检查服务器序号:1~30"
        ), quote=src)
        return False
    # 获取服务器id信息
    try:
        id_dict = await get_bfgroup_ids(app, group, server_rank, src)
    except:
        await app.send_message(group, MessageChain(
            f"请检查服务器序号:1~30"
        ), quote=src)
        return False
    if type(id_dict) != dict:
        return False
    else:
        server_id = id_dict["serverid"]
        server_gameid = id_dict["gameid"]
        # server_guid = id_dict["guid"]

    await app.send_message(group, MessageChain(
        f"查询ing"

    ), quote=src)
    time_start = time.time()
    try:
        server_info = await api_gateway.get_server_fulldetails(server_gameid)
        if server_info == '':
            raise Exception
    except:
        await app.send_message(group, MessageChain(
            GraiaImage(path='./data/bqb/狐务器无响应.jpg')
        ), quote=src)
        return False
    admin_pid_list = [str(item['personaId']) for item in server_info["rspInfo"]["adminList"]]
    admin_counter = 0
    admin_color = (0,255,127)
    vip_pid_list = [str(item['personaId']) for item in server_info["rspInfo"]["vipList"]]
    vip_counter = 0
    vip_color = (255,99,71)
    bind_pid_list = await get_group_bindList(app, group)
    bind_color = (100,149,237)
    bind_counter = 0
    max_level_counter = 0

    server_info = await api_gateway.get_server_fulldetails(server_gameid)
    if not server_info:
        return await app.send_message(group, MessageChain("获取服务器信息失败~"), quote=src)

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
        return await app.send_message(group, MessageChain(playerlist_data), quote=src)
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
        ), quote=src)
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
        "\n回复'-k 序号 原因'可踢出玩家(60秒内有效)"
    )
    bot_message = await app.send_group_message(group, message_send, quote=src)
    os.remove(SavePic)

    async def waiter(event: GroupMessage, waiter_member: Member, waiter_group: Group, waiter_message: MessageChain):
        if (await Permission.require_user_perm(waiter_group.id, waiter_member.id, 32)) and waiter_group.id == group.id:
            if event.quote and \
                    event.quote.id == bot_message.id:
                saying = waiter_message.display.replace(f"@{app.account} ", "").replace(f"@{app.account}", "")
                return saying

    try:
        result = await FunctionWaiter(waiter, [GroupMessage]).wait(60)
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
    # 获取session
    session = await get_bfgroup_session(app, group, server_rank, src)
    if type(session) != str:
        return False
    # 并发踢出
    scrape_index_tasks = []
    name_temp = []
    for index in index_list:
        index = int(index)
        try:
            if index <= (int(server_info["serverInfo"]["slots"]["Soldier"]["max"]) / 2):
                index = index - 1
                scrape_index_tasks.append(asyncio.ensure_future(
                    api_gateway.rsp_kickPlayer(server_gameid, session,
                                               playerlist_data["teams"][0][index]["pid"], reason)
                ))
                name_temp.append(playerlist_data["teams"][0][index]["display_name"])
            else:
                index = index - 1 - int((int(server_info["serverInfo"]["slots"]["Soldier"]["max"]) / 2))
                scrape_index_tasks.append(asyncio.ensure_future(
                    api_gateway.rsp_kickPlayer(server_gameid, session,
                                               playerlist_data["teams"][1][index]["pid"], reason)
                ))
                name_temp.append(playerlist_data["teams"][1][index]["display_name"])
        except:
            await app.send_message(group, MessageChain(
                f"无效序号:{index}"
            ), quote=src)
            return False
    tasks = asyncio.gather(*scrape_index_tasks)
    try:
        await tasks
    except Exception as e:
        await app.send_message(group, MessageChain(
            f"执行中出现了一个错误!{e}"
        ), quote=src)
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
            rsp_log.kick_logger(sender.id, group_id=group.id, action_object=name_temp[i],
                                server_id=server_id,
                                reason=reason)
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
    ), quote=src)


# TODO 3.服管账号相关-查增改、删、绑定到bfgroups-servers里的managerAccount
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
            FullMatch("-bf服管账号列表").space(SpacePolicy.PRESERVE)
        ]
    )
)
async def managerAccount_list(app: Ariadne, group: Group, source: Source):
    file_path = f'./data/battlefield/managerAccount'
    if not (os.path.exists(file_path) or os.path.isfile(file_path)):
        os.makedirs(file_path)
        await app.send_message(group, MessageChain(
            f'未检测到managerAccount文件夹，已自动新建'
        ), quote=source)
        return False
    else:
        account_list = os.listdir(file_path)
        if len(account_list) == 0:
            await app.send_message(group, MessageChain(
                f'未检测到任何服管账号，请新建一个'
            ), quote=source)
            return False
        temp = []
        for item in account_list:
            with open(file_path + f"/{item}/info.json", 'r', encoding="utf-8") as file_tamp:
                data = json.load(file_tamp)
                name = data["personas"]["persona"][0]["displayName"]
            temp.append(item + "\n")
            temp.append(name + "\n")
            temp.append("=" * 20 + "\n")
        account_list[-1] = account_list[-1].replace("\n", '')
        await app.send_message(group, MessageChain(
            f'当前共{len(account_list)}个账号:\n',
            temp
        ), quote=source)
        return False


# 新建一个服管账号 根据账号名字来创建-实际上本地存储的是pid
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
            FullMatch("-bf服管账号 新建").space(SpacePolicy.PRESERVE),
            "account_name" @ ParamMatch(optional=False).space(SpacePolicy.PRESERVE)

        ]
    )
)
async def managerAccount_create(app: Ariadne, group: Group,
                                account_name: RegexResult, source: Source):
    account_name = str(account_name.result)
    # 根据名字获取到pid
    try:
        player_info = await getPid_byName(account_name)
    except:
        await app.send_message(group, MessageChain(
            f"网络出错，请稍后再试"
        ), quote=source)
        return False
    personaId = player_info['personas']['persona'][0]['personaId']
    group_path = f'./data/battlefield/managerAccount'
    account_path = group_path + f"/{personaId}"
    if not os.path.exists(group_path):
        os.makedirs(group_path)
        await app.send_message(group, MessageChain(
            f'未检测到managerAccount文件,已自动新建文件夹'
        ), quote=source)
    if not os.path.exists(account_path):
        os.makedirs(account_path)
        open(account_path + "/account.json", "w", encoding="utf-8")
        open(account_path + "/session.json", "w", encoding="utf-8")
        with open(account_path + "/info.json", "w", encoding="utf-8") as file:
            json.dump(player_info, file, indent=4)
        await app.send_message(group, MessageChain(
            f'成功创建{personaId}文件夹\n自动创建account与session.json文件成功\n写入玩家info成功\n请手动导入remid与sid'
        ), quote=source)
    else:
        await app.send_message(group, MessageChain(
            f'账号{account_name}已存在\npid:{personaId}'
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
            FullMatch("-bf服管账号 删除").space(SpacePolicy.PRESERVE),
            "account_pid" @ ParamMatch(optional=False).space(SpacePolicy.PRESERVE)
            # 示例: -bf服管账号 删除 123
        ]
    )
)
async def managerAccount_del(app: Ariadne, group: Group,
                             account_pid: RegexResult, source: Source):
    account_pid = str(account_pid.result)
    file_path = f'./data/battlefield/managerAccount'
    if not (os.path.exists(file_path) or os.path.isfile(file_path)):
        os.makedirs(file_path)
        await app.send_message(group, MessageChain(
            f'未检测到managerAccount文件夹，已自动新建'
        ), quote=source)
        return False
    else:
        account_list = os.listdir(file_path)
        if len(account_list) == 0:
            await app.send_message(group, MessageChain(
                f'未检测到任何服管账号，请新建一个'
            ), quote=source)
            return False
    if account_pid in account_list:
        shutil.rmtree(f'{file_path}/{account_pid}')
        await app.send_message(group, MessageChain(
            f"删除服管账号{account_pid}成功"
        ), quote=source)
        return True
    else:
        await app.send_message(group, MessageChain(
            f"服管账号{account_pid}不存在"
        ), quote=source)
        return False


# 传入remid和sid信息-登录
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
            FullMatch("-bf服管账号 登录").space(SpacePolicy.FORCE),
            "account_pid" @ ParamMatch(optional=False).space(SpacePolicy.FORCE),
            FullMatch("remid=").space(SpacePolicy.NOSPACE),
            "remid" @ ParamMatch(optional=False).space(SpacePolicy.NOSPACE),
            FullMatch(",sid=").space(SpacePolicy.NOSPACE),
            "sid" @ ParamMatch(optional=False).space(SpacePolicy.PRESERVE),
            # 示例: -bf服管账号 登录 123 remid=xxx,sid=xxx
        ]
    )
)
async def managerAccount_login(app: Ariadne, group: Union[Group, Friend],
                               account_pid: RegexResult, remid: RegexResult, sid: RegexResult, source: Source):
    # 先查找有无对应服管帐号，然后写入remid和sid，然后自动写入session
    account_pid = account_pid.result.display.replace("\n", "")
    remid = remid.result.display.replace("\n", "")

    sid = str(sid.result)
    file_path = f'./data/battlefield/managerAccount'
    if not (os.path.exists(file_path) or os.path.isfile(file_path)):
        os.makedirs(file_path)
        await app.send_message(group, MessageChain(
            f'未检测到managerAccount文件夹，已自动新建'
        ), quote=source)
        return False
    else:
        account_list = os.listdir(file_path)
        if len(account_list) == 0:
            await app.send_message(group, MessageChain(
                f'未检测到任何服管账号，请新建一个'
            ), quote=source)
            return False
    if account_pid not in account_list:
        await app.send_message(group, MessageChain(
            f"没有找到服管账号{account_pid}"
        ), quote=source)
        return False
    with open(f'{file_path}/{account_pid}/account.json', 'w', encoding="utf-8") as file1:
        data1 = {"remid": remid, "sid": sid}
        json.dump(data1, file1, indent=4)
        await app.send_message(group, MessageChain(
            f"账号{account_pid}写入数据成功\nremid:{remid}\nsid:{sid}"
        ), quote=source)
    refresh_result = await auto_refresh_account(account_pid)
    if refresh_result == "刷新成功":
        await app.send_message(group, MessageChain(
            f"账号{account_pid}刷新session文件成功"
        ), quote=source)
    else:
        await app.send_message(group, MessageChain(
            f"账号{account_pid}刷新session失败，请检查账号信息是否无误"
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
            FullMatch("-bf服管账号").space(SpacePolicy.FORCE),
            "account_pid" @ ParamMatch(optional=False).space(SpacePolicy.FORCE),
            FullMatch("信息").space(SpacePolicy.PRESERVE)
            # 示例: -bf服管账号 123 信息
        ]
    )
)
async def managerAccount_info(app: Ariadne, group: Group,
                              account_pid: RegexResult, source: Source):
    # 先查找有无对应服管帐号，然后写入remid和sid，然后自动写入session
    account_pid = account_pid.result.display.replace("_", "")
    file_path = f'./data/battlefield/managerAccount/'
    account_list = os.listdir(file_path)
    for pid_temp in account_list:
        data_path = f"{file_path}{pid_temp}/info.json"
        with open(data_path, 'r', encoding='utf-8') as file1:
            data = json.load(file1)
            player_pid = data['personas']['persona'][0]['personaId']
            player_displayName = data['personas']['persona'][0]['displayName']
            player_name = data['personas']['persona'][0]['name']
            if account_pid.upper() in [str(player_pid), player_displayName.upper().replace("_", ""),
                                       player_name.upper().replace("_", "")]:
                # 水神api
                try:
                    url1 = 'https://api.s-wg.net/ServersCollection/getPlayerAll?PersonId=' + str(player_pid)
                    async with httpx.AsyncClient() as client:
                        response = await client.get(url1, timeout=10)
                    html1 = response.text
                    if html1 == 404:
                        raise Exception
                    html1 = eval(html1)
                    if html1["status"]:
                        player_server_list = html1["result"][0]["data"]
                        player_admin_list = html1["result"][1]["data"]
                    send = []
                    if len(player_server_list) != 0:
                        send.append(f"拥有以下服务器({len(player_server_list)}):\n")
                        for server in player_server_list:
                            send.append(f"{server}\n")
                    if len(player_admin_list) != 0:
                        send.append(f"管理以下服务器({len(player_admin_list)}):\n")
                        for server in player_admin_list:
                            send.append(f"{server}\n")
                    if send:
                        send[-1] = send[-1].replace("\n", '')
                    await app.send_message(group, MessageChain(
                        send
                    ), quote=source)
                    return
                except:
                    await app.send_message(group, MessageChain(
                        f"网络出错!"
                    ), quote=source)
                    return
            else:
                continue
    await app.send_message(group, MessageChain(
        f"没有找到服管账号{account_pid}"
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
            FullMatch("-bf群组").space(SpacePolicy.PRESERVE),
            "group_name" @ ParamMatch(optional=False).space(SpacePolicy.NOSPACE),
            FullMatch("#").space(SpacePolicy.NOSPACE),
            "server_rank" @ ParamMatch(optional=False).space(SpacePolicy.FORCE),
            FullMatch("使用服管").space(SpacePolicy.PRESERVE),
            "account_pid" @ ParamMatch(optional=False).space(SpacePolicy.PRESERVE),
            # 示例: -bf群组 sakula#1 使用服管pid
        ]
    )
)
async def bfgroup_bind_managerAccount(app: Ariadne, group: Group,
                                      server_rank: RegexResult, account_pid: RegexResult, group_name: RegexResult,
                                      source: Source):
    server_rank = int(str(server_rank.result))
    if server_rank < 1:
        await app.send_message(group, MessageChain(
            f"服务器序号范围:1-30"
        ), quote=source)
        return False
    account_pid = str(account_pid.result)
    group_name = str(group_name.result)
    # 先检查有无群组
    group_path = f"./data/battlefield/binds/bfgroups/{group_name}"
    if not os.path.exists(group_path):
        await app.send_message(group, MessageChain(
            f"群组{group_name}不存在"
        ), quote=source)
        return False
    # 根据服务器序号检查序号位置是否绑定服务器
    with open(f'./data/battlefield/binds/bfgroups/{group_name}/servers.yaml', 'r', encoding="utf-8") as file1:
        data = yaml.load(file1, yaml.Loader)
        # print(data)
        if data is None:
            await app.send_message(group, MessageChain(
                "该群组还未绑定服务器，请先为群组绑定服务器"
            ), quote=source)
            return False
        if data["servers"][server_rank - 1] == "":
            await app.send_message(group, MessageChain(
                f"群组{group_name}该位置未绑定服务器"
            ), quote=source)
            return False
        else:
            data["servers"][server_rank - 1]["managerAccount"] = account_pid
            with open(f'./data/battlefield/binds/bfgroups/{group_name}/servers.yaml', 'w', encoding="utf-8") as file2:
                yaml.dump(data, file2, allow_unicode=True)
            await app.send_message(group, MessageChain(
                f"群组{group_name}服#{server_rank}绑定服管账号{account_pid}成功"
            ), quote=source)
            return True


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
            FullMatch("-bf群组").space(SpacePolicy.PRESERVE),
            "group_name" @ ParamMatch(optional=False).space(SpacePolicy.FORCE),
            FullMatch("使用服管").space(SpacePolicy.PRESERVE),
            "account_pid" @ ParamMatch(optional=False).space(SpacePolicy.PRESERVE),
            # 示例: -bf群组 sakula 使用服管pid
        ]
    )
)
async def bfgroup_bind_managerAccount_all(app: Ariadne, group: Group,
                                          account_pid: RegexResult, group_name: RegexResult, source: Source):
    if "#" in group_name.result.display:
        return
    account_pid = str(account_pid.result)
    group_name = str(group_name.result)
    # 先检查有无群组
    group_path = f"./data/battlefield/binds/bfgroups/{group_name}"
    if not os.path.exists(group_path):
        await app.send_message(group, MessageChain(
            f"群组{group_name}不存在"
        ), quote=source)
        return False
    # 根据服务器序号检查序号位置是否绑定服务器
    with open(f'./data/battlefield/binds/bfgroups/{group_name}/servers.yaml', 'r', encoding="utf-8") as file1:
        data = yaml.load(file1, yaml.Loader)
        # print(data)
        if data is None:
            await app.send_message(group, MessageChain(
                "该群组还未绑定服务器，请先为群组绑定服务器"
            ), quote=source)
            return False
        counter = 0
        for item in data["servers"]:
            if item != "":
                item["managerAccount"] = account_pid
                data["servers"][counter] = item
                counter += 1
        if counter != 0:
            with open(f'./data/battlefield/binds/bfgroups/{group_name}/servers.yaml', 'w',
                      encoding="utf-8") as file2:
                yaml.dump(data, file2, allow_unicode=True)
            await app.send_message(group, MessageChain(
                f"群组{group_name}绑定服管账号{account_pid}成功"
            ), quote=source)
            return True
        else:
            await app.send_message(group, MessageChain(
                "该群组还未绑定服务器，请先为群组绑定服务器"
            ), quote=source)
            return False


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
            FullMatch("-bf群组").space(SpacePolicy.PRESERVE),
            "group_name" @ ParamMatch(optional=False).space(SpacePolicy.FORCE),
            FullMatch("服#").space(SpacePolicy.NOSPACE),
            "server_rank" @ ParamMatch(optional=False).space(SpacePolicy.FORCE),
            FullMatch("解绑服管").space(SpacePolicy.PRESERVE),
            # 示例: -bf群组 sakula 服#1 解绑服管
        ]
    )
)
async def bfgroup_del_managerAccount(app: Ariadne, group: Group,
                                     server_rank: RegexResult, group_name: RegexResult, source: Source):
    server_rank = int(str(server_rank.result))
    if server_rank < 1:
        await app.send_message(group, MessageChain(
            f"服务器序号范围:1-30"
        ), quote=source)
        return False
    group_name = str(group_name.result)
    # 先检查有无群组
    group_path = f"./data/battlefield/binds/bfgroups/{group_name}"
    if not os.path.exists(group_path):
        await app.send_message(group, MessageChain(
            f"群组{group_name}不存在"
        ), quote=source)
        return False
    # 根据服务器序号检查序号位置是否绑定服务器
    with open(f'./data/battlefield/binds/bfgroups/{group_name}/servers.yaml', 'r', encoding="utf-8") as file1:
        data = yaml.load(file1, yaml.Loader)
        # print(data)
        if data is None:
            await app.send_message(group, MessageChain(
                "该群组还未绑定服务器，请先为群组绑定服务器"
            ), quote=source)
            return False
        if data["servers"][server_rank - 1] == "":
            await app.send_message(group, MessageChain(
                f"群组{group_name}该位置未绑定服务器"
            ), quote=source)
            return False
        else:
            data["servers"][server_rank - 1]["managerAccount"] = ''
            with open(f'./data/battlefield/binds/bfgroups/{group_name}/servers.yaml', 'w', encoding="utf-8") as file2:
                yaml.dump(data, file2, allow_unicode=True)
            await app.send_message(group, MessageChain(
                f"群组{group_name}服#{server_rank}解绑服管账号成功"
            ), quote=source)
            return True


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
            FullMatch("-bf群组").space(SpacePolicy.PRESERVE),
            "group_name" @ ParamMatch(optional=False).space(SpacePolicy.FORCE),
            FullMatch("解绑服管").space(SpacePolicy.PRESERVE),
            # 示例: -bf群组 sakula 解绑服管
        ]
    )
)
async def bfgroup_del_managerAccount_all(app: Ariadne, group: Group,
                                         group_name: RegexResult, source: Source):
    group_name = str(group_name.result)
    # 先检查有无群组
    group_path = f"./data/battlefield/binds/bfgroups/{group_name}"
    if not os.path.exists(group_path):
        await app.send_message(group, MessageChain(
            f"群组{group_name}不存在"
        ), quote=source)
        return False
    # 根据服务器序号检查序号位置是否绑定服务器
    with open(f'./data/battlefield/binds/bfgroups/{group_name}/servers.yaml', 'r', encoding="utf-8") as file1:
        data = yaml.load(file1, yaml.Loader)
        # print(data)
        if data is None:
            await app.send_message(group, MessageChain(
                "该群组还未绑定服务器，请先为群组绑定服务器"
            ), quote=source)
            return False
        counter = 0
        for item in data["servers"]:
            if item != "":
                data["servers"][counter]["managerAccount"] = ''
                counter += 1
        if counter != 0:
            with open(f'./data/battlefield/binds/bfgroups/{group_name}/servers.yaml', 'w',
                      encoding="utf-8") as file2:
                yaml.dump(data, file2, allow_unicode=True)
                counter += 1
            await app.send_message(group, MessageChain(
                f"群组{group_name}解绑服管账号成功"
            ), quote=source)
            return True
        else:
            await app.send_message(group, MessageChain(
                "该群组还未绑定服务器，请先为群组绑定服务器"
            ), quote=source)
            return False


async def get_required_log(log: list, action: str, action_object: str) -> list:
    logger.warning(f"查找操作:{action},查找对象:{action_object}")
    temp = []
    for item in log:
        if action == "上v" and "上v" in item:
            if item[item.index("上v") + 3] == "-":
                up_num = 2
            else:
                up_num = 3
            str_list = list(item)
            counter = 0
            for i, str_temp in enumerate(str_list):
                if str_temp == "-":
                    counter += 1
                    if counter <= up_num:
                        str_list[i] = "\n"
                    if counter == up_num + 2 and up_num == 2:
                        str_list[i] = "\n"
            last_index = item.rfind("-")
            str_list[last_index] = "\n"
            item = ''
            for str_temp in str_list:
                item += str_temp
        elif action in ["踢出", "封禁", "解封", "换边"]:
            str_list = list(item)
            counter = 0
            for i, str_temp in enumerate(str_list):
                if str_temp == "-":
                    counter += 1
                    if counter <= 4:
                        str_list[i] = "\n"
            last_index = item.rfind("-")
            str_list[last_index] = "\n"
            item = ''
            for str_temp in str_list:
                item += str_temp
        else:
            item = item.replace("-", "\n")
        if (action in item) and (action_object.lower() in item.lower()):
            temp.append(item)
    temp.reverse()
    return temp[:100]


# 查日志
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
            FullMatch("-bf群组").space(SpacePolicy.PRESERVE),
            "group_name" @ ParamMatch(optional=True).space(SpacePolicy.PRESERVE),
            FullMatch("日志").space(SpacePolicy.PRESERVE),
            "member_id" @ RegexMatch(r"[0-9]+", optional=True).space(SpacePolicy.PRESERVE),
            "action" @ UnionMatch("踢出", "封禁", "解封", "上v", "下v", "换图", "玩家",
                                  optional=True).space(
                SpacePolicy.PRESERVE),
            "action_object" @ ParamMatch(optional=True).space(SpacePolicy.PRESERVE)
            # 示例: -bf群组 sakula 日志 1257661006 踢出 shlsan13
        ]
    )
)
async def bfgroup_search_log(app: Ariadne, sender: Member, group: Group,
                             group_name: RegexResult, member_id: RegexResult, action: RegexResult,
                             action_object: RegexResult, source: Source):
    if action.matched:
        if action.result.display == "玩家":
            action = ''
        else:
            action = action.result.display
    else:
        action = ''
    if action_object.matched:
        action_object = action_object.result.display
    else:
        action_object = ''
    # 没有匹配就看群绑定没有
    if not group_name.matched:
        # 检查qq群文件是否存在
        group_path = f'./data/battlefield/binds/groups/{group.id}'
        file_path = group_path + "/bfgroups.yaml"
        if not (os.path.exists(group_path) or os.path.isfile(file_path)):
            await app.send_message(group, MessageChain(
                f'请先绑定bf群组'
            ), quote=source)
            return False
        # 打开绑定的文件
        with open(file_path, 'r', encoding="utf-8") as file1:
            data = yaml.load(file1, yaml.Loader)
            try:
                group_name = data["bfgroups"]
            except:
                await app.send_message(group, MessageChain(
                    f'未识别到群组，请重新绑定bf群组'
                ), quote=source)
                return False
    # 有匹配的时候如果绑定不一致就判断权限
    else:
        group_name = group_name.result.display
        # 检查qq群文件是否存在
        group_path = f'./data/battlefield/binds/groups/{group.id}'
        file_path = group_path + "/bfgroups.yaml"
        if not (os.path.exists(group_path) or os.path.isfile(file_path)):
            await app.send_message(group, MessageChain(
                f'请先绑定bf群组'
            ), quote=source)
            return False
        # 打开绑定的文件
        with open(file_path, 'r', encoding="utf-8") as file1:
            data = yaml.load(file1, yaml.Loader)
            try:
                bfgroups_name = data["bfgroups"]
            except:
                await app.send_message(group, MessageChain(
                    f'未识别到群组，请重新绑定bf群组'
                ), quote=source)
                return False
        if bfgroups_name != group_name and await Permission.require_user_perm(group.id, sender.id, 128):
            await app.send_message(group, MessageChain(
                f'你没有进行此操作的权限,你的权限级:{Permission.get_user_perm_byID(group_id=group.id, member_id=sender.id)},所需权限级:{128}'
            ), quote=source)
            return False
        group_path_check = f"./data/battlefield/binds/bfgroups/{group_name}"
        if not os.path.exists(group_path_check):
            await app.send_message(group, MessageChain(
                f"群组{group_name}不存在"
            ), quote=source)
            return False
    # 根据群组名读日志
    with open(f'./data/battlefield/binds/bfgroups/{group_name}/log.yaml', 'r',
              encoding="utf-8") as file1:
        data = yaml.load(file1, yaml.Loader)
        if data is None:
            await app.send_message(group, MessageChain(
                f'群组日志为空!'
            ), quote=source)
            return False
        # 如果成员没有匹配，就拿总数据
        if not member_id.matched:
            log_data = await get_required_log(data["total"], action, action_object)
            # for log in data["total"][-100:]:
            #     log_data.append(log.replace("-", "\n"))
            log_len = len(log_data)
            log_member = await app.get_member(group, app.account)
            fwd_nodeList = [ForwardNode(
                target=log_member,
                time=datetime.now(),
                message=MessageChain(
                    f"群组{group_name}日志数:%s\n日志格式:\n日期\n操作者qq\n操作\n操作对象\n服务器serverid" % log_len),
            )]
        else:
            member_id = int(member_id.result.display)
            if member_id in data["operators"]:
                log_data = await get_required_log(data["operators"][member_id], action, action_object)
                # for log in data["operators"][member_id][-100:]:
                #     log_data.append(log.replace("-", "\n"))
                log_len = len(log_data)
                try:
                    log_member = await app.get_member(group, member_id)
                except Exception as e:
                    logger.warning(e)
                    log_member = await app.get_member(group, app.account)
                fwd_nodeList = [ForwardNode(
                    target=log_member,
                    time=datetime.now(),
                    message=MessageChain(
                        f"群组[{group_name}]\n操作者[{member_id}]日志数:%s\n日志格式:\n日期\n操作\n操作对象\n服务器serverid" % log_len),
                )]
            else:
                await app.send_message(group, MessageChain(
                    f"群组{group_name}未找到{member_id}的日志"
                ), quote=source)
                return False
        for item in log_data:
            try:
                bot_member = await app.get_member(group,
                                                  item[item.find("\n") + 1:item.find("\n", item.find("\n") + 1)])
            except Exception as e:
                logger.warning(e)
                bot_member = await app.get_member(group, app.account)
            if member_id:
                temp_member = log_member
            else:
                temp_member = bot_member
            fwd_nodeList.append(ForwardNode(
                target=temp_member,
                time=datetime.now(),
                message=MessageChain(item),
            ))
        message = MessageChain(Forward(nodeList=fwd_nodeList))
        await app.send_message(group, message)
        return True


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
            FullMatch("-refresh").space(SpacePolicy.PRESERVE)
            # 示例: -refresh
        ]
    )
)
async def bfgroup_refresh(app: Ariadne, group: Group, source: Source):
    # 先检查绑定群组没
    # 检查qq群文件是否存在
    group_path = f'./data/battlefield/binds/groups/{group.id}'
    file_path = group_path + "/bfgroups.yaml"
    if not (os.path.exists(group_path) or os.path.isfile(file_path)):
        await app.send_message(group, MessageChain(
            f'请先绑定bf群组'
        ), quote=source)
        return False
    # 打开绑定的文件
    with open(file_path, 'r', encoding="utf-8") as file1:
        data = yaml.load(file1, yaml.Loader)
        try:
            bfgroups_name = data["bfgroups"]
        except:
            await app.send_message(group, MessageChain(
                f'未识别到群组，请重新绑定bf群组'
            ), quote=source)
    # 根据bf群组名字找到群组绑定服务器文件-获取服务器gameid
    group_path = f"./data/battlefield/binds/bfgroups/{bfgroups_name}"
    if not os.path.exists(group_path):
        await app.send_message(group, MessageChain(
            f"群组{bfgroups_name}不存在"
        ), quote=source)
        return False
    with open(f'./data/battlefield/binds/bfgroups/{bfgroups_name}/servers.yaml', 'r', encoding="utf-8") as file1:
        data = yaml.load(file1, yaml.Loader)
        # 检查是否servers.yaml是否为空
        if data is None:
            await app.send_message(group, MessageChain(
                f"群组服务器信息为空，请先绑定服务器"
            ), quote=source)
            return False
        else:
            pid_list = []
            for item in data["servers"]:
                if item != "":
                    if item["managerAccount"] not in ["", "None", None]:
                        pid_list.append(f'{item["managerAccount"]}')
    if pid_list == 0:
        await app.send_message(group, MessageChain(
            f"没有获取到服管账号,请检查群组信息"
        ), quote=source)
        return False
    else:
        account_pid = pid_list[0]
        file_path = f'./data/battlefield/managerAccount'
        account_list = os.listdir(file_path)
        if account_pid not in account_list:
            await app.send_message(group, MessageChain(
                f"没有找到服管账号{account_pid}"
            ), quote=source)
            return False
        await app.send_message(group, MessageChain(
            f"执行ing,该操作需要一定时间!"
        ), quote=source)
        try:
            refresh_result = await auto_refresh_account(account_pid)
        except Exception as e:
            await app.send_message(group, MessageChain(
                f"出现了未知的错误!可能是账号信息已过期,请重新登录!\n错误信息:{e}"
            ), quote=source)
            return False
        if refresh_result == "刷新成功":
            await app.send_message(group, MessageChain(
                f"群组{bfgroups_name}成功获取到新的session!"
            ), quote=source)
            return True
        else:
            await app.send_message(group, MessageChain(
                f"账号{account_pid}刷新session失败,请检查账号信息!\n错误信息:{refresh_result}"
            ), quote=source)
            return False


# TODO 获取session流程: 1.根据群找到绑定的群组，否则返回未绑定 2.根据群组找到绑定的服务器，否则返回未绑定服务器 3.根据服务器返回session，否则返回没有找到session

# bf群组绑定服务器所绑定的服管账号session
async def get_bfgroup_session(app: Ariadne, group: Group, server_rank: int, source: Source) -> str:
    """
    bf群组绑定服务器所绑定的服管账号session,该函数会触发bot回复
    失败返回False，成功返回str->session
    :param group:
    :param app:
    :param server_rank: 请传入-1后的序号
    :param source: 源
    :return: session字符串
    """
    # 先检查绑定群组没
    group_path = f'./data/battlefield/binds/groups/{group.id}'
    file_path = group_path + "/bfgroups.yaml"
    if not (os.path.exists(group_path) or os.path.isfile(file_path)):
        await app.send_message(group, MessageChain(
            f'请先绑定bf群组'
        ), quote=source)
        return False
    # 打开绑定的文件
    with open(file_path, 'r', encoding="utf-8") as file1:
        data = yaml.load(file1, yaml.Loader)
        try:
            bfgroups_name = data["bfgroups"]
        except:
            await app.send_message(group, MessageChain(
                f'未识别到群组，请重新绑定bf群组'
            ), quote=source)
            return False
    # 根据bf群组名字找到群组
    group_path = f"./data/battlefield/binds/bfgroups/{bfgroups_name}"
    if not os.path.exists(group_path):
        await app.send_message(group, MessageChain(
            f"群组{bfgroups_name}不存在"
        ), quote=source)
        return False
    # 获取对应序号上的服务器的服管账号
    with open(f'./data/battlefield/binds/bfgroups/{bfgroups_name}/servers.yaml', 'r', encoding="utf-8") as file1:
        data = yaml.load(file1, yaml.Loader)
        if data is None:
            await app.send_message(group, MessageChain(
                f"群组{bfgroups_name}服务器信息为空，请先绑定服务器"
            ), quote=source)
            return False
        elif data["servers"][server_rank] == '':
            await app.send_message(group, MessageChain(
                f"群组{bfgroups_name}服务器{server_rank + 1}未绑定服务器，请先绑定服务器与服管账号!"
            ), quote=source)
            return False
        else:
            managerAccount = data["servers"][server_rank]["managerAccount"]
            if managerAccount == '' or managerAccount is None:
                await app.send_message(group, MessageChain(
                    f"群组{bfgroups_name}服务器{server_rank + 1}未绑定服管账号，请先绑定服管账号!"
                ), quote=source)
                return False
    # 根据服管账号获取session
    account_pid = managerAccount
    file_path = f'./data/battlefield/managerAccount'
    account_list = os.listdir(file_path)
    if len(account_list) == 0:
        await app.send_message(group, MessageChain(
            f'未检测到任何服管账号，请新建一个'
        ), quote=source)
        return False
    if account_pid not in account_list:
        await app.send_message(group, MessageChain(
            f"没有找到服管账号{account_pid}"
        ), quote=source)
        return False
    with open(f'{file_path}/{account_pid}/session.json', 'r', encoding="utf-8") as file1:
        try:
            data1 = json.load(file1)
            session = data1["session"]
            return session
        except:
            await app.send_message(group, MessageChain(
                f"获取session出错，请检查服管账号{managerAccount}"
            ), quote=source)
            return False


# bf群组绑定服务器所绑定的服管账号session
async def get_bfgroup_session_noApp(group: Group, server_rank: int) -> str:
    """
    bf群组绑定服务器所绑定的服管账号session,该函数不会触发bot回复
    :param group:
    :param server_rank: 传入index->0,1,2
    :return:
    """
    # 先检查绑定群组没
    group_path = f'./data/battlefield/binds/groups/{group.id}'
    file_path = group_path + "/bfgroups.yaml"
    if not (os.path.exists(group_path) or os.path.isfile(file_path)):
        return f'请先绑定bf群组'
    # 打开绑定的文件
    with open(file_path, 'r', encoding="utf-8") as file1:
        data = yaml.load(file1, yaml.Loader)
        try:
            bfgroups_name = data["bfgroups"]
        except:
            return f'未识别到群组，请重新绑定bf群组'
    # 根据bf群组名字找到群组
    group_path = f"./data/battlefield/binds/bfgroups/{bfgroups_name}"
    if not os.path.exists(group_path):
        return f"群组{bfgroups_name}不存在"
    # 获取对应序号上的服务器的服管账号
    with open(f'./data/battlefield/binds/bfgroups/{bfgroups_name}/servers.yaml', 'r', encoding="utf-8") as file1:
        data = yaml.load(file1, yaml.Loader)
        if data is None:
            return f"群组{bfgroups_name}服务器信息为空，请先绑定服务器"
        elif data["servers"][server_rank] == '':
            return f"群组{bfgroups_name}服务器{server_rank + 1}未绑定服务器，请先绑定服务器与服管账号!"
        else:
            managerAccount = data["servers"][server_rank]["managerAccount"]
            if managerAccount == '' or managerAccount is None:
                return f"群组{bfgroups_name}服务器{server_rank + 1}未绑定服管账号，请先绑定服管账号!"
    # 根据服管账号获取session
    account_pid = managerAccount
    file_path = f'./data/battlefield/managerAccount'
    account_list = os.listdir(file_path)
    if account_pid not in account_list:
        return f"没有找到服管账号{account_pid}"
    with open(f'{file_path}/{account_pid}/session.json', 'r', encoding="utf-8") as file1:
        try:
            data1 = json.load(file1)
            session = data1["session"]
            return session
        except:
            return f"获取session出错，请检查服管账号{managerAccount}"


# 获取gameid、guid、serverid
async def get_bfgroup_ids(app: Ariadne, group: Group, server_rank: int, source: Source) -> dict:
    """
    失败返回False，成功返回dict
    :param group:
    :param app:
    :param source:
    :param server_rank:
    :return:
    """
    # 先检查绑定群组没
    group_path = f'./data/battlefield/binds/groups/{group.id}'
    file_path = group_path + "/bfgroups.yaml"
    if not (os.path.exists(group_path) or os.path.isfile(file_path)):
        await app.send_message(group, MessageChain(
            f'请先绑定bf群组'
        ), quote=source)
        return False
    # 打开绑定的文件
    with open(file_path, 'r', encoding="utf-8") as file1:
        data = yaml.load(file1, yaml.Loader)
        try:
            bfgroups_name = data["bfgroups"]
        except:
            await app.send_message(group, MessageChain(
                f'未识别到群组，请重新绑定bf群组'
            ), quote=source)
            return False
    # 根据bf群组名字找到群组
    group_path = f"./data/battlefield/binds/bfgroups/{bfgroups_name}"
    if not os.path.exists(group_path):
        await app.send_message(group, MessageChain(
            f"群组{bfgroups_name}不存在"
        ), quote=source)
        return False
    # 获取对应序号上的服务器的服管账号
    with open(f'./data/battlefield/binds/bfgroups/{bfgroups_name}/servers.yaml', 'r', encoding="utf-8") as file1:
        data = yaml.load(file1, yaml.Loader)
        if data is None:
            await app.send_message(group, MessageChain(
                f"群组{bfgroups_name}服务器信息为空，请先绑定服务器"
            ), quote=source)
            return False
            # managerAccount = data["servers"][server_rank]["managerAccount"]
            # if managerAccount == '' or managerAccount is None:
            #     await app.send_message(group, MessageChain(
            #         f"群组{bfgroups_name}服务器{server_rank+1}未绑定服管账号，请先绑定服管账号!"
            #     ), quote=message[Source][0])
            #     return False
    return data["servers"][server_rank]


# TODO 服管功能:  指定服务器序号版 1.踢人 2.封禁/解封 3.换边 4.换图 5.vip

# 踢人
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
            "action" @ UnionMatch("-kick", "-踢", "-k").space(SpacePolicy.NOSPACE),
            FullMatch("#", optional=True).space(SpacePolicy.NOSPACE),
            "server_rank" @ ParamMatch(optional=False).space(SpacePolicy.FORCE),
            "player_name" @ ParamMatch(optional=False).space(SpacePolicy.PRESERVE),
            "reason" @ WildcardMatch(optional=True),
            # 示例: -k#1 xiaoxiao test
        ]
    )
)
async def kick(app: Ariadne, sender: Member, group: Group, action: RegexResult,
               server_rank: RegexResult, player_name: RegexResult, reason: RegexResult, source: Source):
    # 服务器序号检测
    try:
        server_rank = int(str(server_rank.result)) - 1
        if server_rank < 0 or server_rank > 30:
            raise Exception
    except:
        # await app.send_message(group, MessageChain(
        #     f"请检查服务器序号"
        # ), quote=message[Source][0])
        return False
    player_name = str(player_name.result)
    # 原因检测
    if str(reason.result) == "":
        reason = "违反规则"
    else:
        reason = str(reason.result).replace("ADMINPRIORITY", "违反规则")
    reason = zhconv.convert(reason, 'zh-tw')
    if ("空間" or "寬帶" or "帶寬" or "網絡" or "錯誤代碼" or "位置") in reason:
        await app.send_message(group, MessageChain(
            "操作失败:踢出原因包含违禁词"
        ), quote=source)
        return False
    # 字数检测
    if 30 < len(reason.encode("utf-8")):
        await app.send_message(group, MessageChain(
            "原因字数过长(汉字10个以内)"
        ), quote=source)
        return False

    # 获取session
    session = await get_bfgroup_session(app, group, server_rank, source)
    if type(session) != str:
        return False
    # 获取服务器id信息
    id_dict = await get_bfgroup_ids(app, group, server_rank, source)
    if type(id_dict) != dict:
        return False
    else:
        server_id = id_dict["serverid"]
        server_gameid = id_dict["gameid"]
        # server_guid = id_dict["guid"]

    # 查验玩家存不存在
    try:
        player_info = await getPid_byName(player_name)
    except:
        await app.send_message(group, MessageChain(
            f"网络出错，请稍后再试"
        ), quote=source)
        return False
    if player_info['personas'] == {}:
        await app.send_message(group, MessageChain(
            f"玩家[{player_name}]不存在"
        ), quote=source)
        return False
    player_pid = player_info['personas']['persona'][0]['personaId']

    # 调用踢人的接口
    star_time = time.time()
    result = await api_gateway.rsp_kickPlayer(server_gameid, session, player_pid, reason)
    end_time = time.time()
    logger.info(f"踢人耗时:{(end_time - star_time):.2f}秒")
    if type(result) == str:
        await app.send_message(group, MessageChain(
            f"{result}"
        ), quote=source)
        return False
    elif type(result) == dict:
        await app.send_message(group, MessageChain(
            f"踢出成功!原因:{reason}"
        ), quote=source)
        rsp_log.kick_logger(sender.id, group.id, player_name, server_id, reason)
        return True
    else:
        await app.send_message(group, MessageChain(
            f"收到指令:({action.result})({server_rank})({player_name})({reason})\n但执行出错了"
        ), quote=source)
        return False


# 不用指定服务器序号
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
            "action" @ UnionMatch("-kick", "-k").space(SpacePolicy.FORCE),
            "player_name" @ ParamMatch(optional=False).space(SpacePolicy.PRESERVE),
            "reason" @ WildcardMatch(optional=True),
            # 示例: -k#1 xiaoxiao test
        ]
    )
)
async def kick_no_need_rank(
        app: Ariadne, sender: Member, group: Group, action: RegexResult, player_name: RegexResult, reason: RegexResult,
        event: GroupMessage, source: Source
):
    # TODO 1.获取玩家所在服务器gameid 2.如果没获取到就返回用k#1 3.获取到后判断是否在群组的服务器内若在则踢出 不在则返回正在游玩的服务器
    if event.quote:
        return
    # 原因检测
    if str(reason.result) == "":
        reason = "违反规则"
    else:
        reason = str(reason.result).replace("ADMINPRIORITY", "违反规则")
    reason = zhconv.convert(reason, 'zh-tw')
    if ("空間" or "寬帶" or "帶寬" or "網絡" or "錯誤代碼" or "位置") in reason:
        await app.send_message(group, MessageChain(
            "操作失败:踢出原因包含违禁词"
        ), quote=source)
        return False
    # 字数检测
    if 30 < len(reason.encode("utf-8")):
        await app.send_message(group, MessageChain(
            "原因字数过长(汉字10个以内)"
        ), quote=source)
        return False
    try:
        player_info = await getPid_byName(str(player_name.result))
    except:
        await app.send_message(group, MessageChain(
            f"网络出错，请稍后再试"
        ), quote=source)
        return False
    if player_info['personas'] == {}:
        await app.send_message(group, MessageChain(
            f"玩家[{player_name.result}]不存在"
        ), quote=source)
        return False
    player_pid = player_info['personas']['persona'][0]['personaId']
    server_info = await server_playing(player_pid)
    if type(server_info) == str:
        await app.send_message(group, MessageChain(
            f"{server_info},如果该玩家在线,请指定服务器序号"
        ), quote=source)
        return False
    else:
        server_gid = server_info["gameId"]

    # 获取服务器gameid列表 str-list
    # 先检查绑定群组没
    group_path = f'./data/battlefield/binds/groups/{group.id}'
    file_path = group_path + "/bfgroups.yaml"
    if not (os.path.exists(group_path) or os.path.isfile(file_path)):
        await app.send_message(group, MessageChain(
            f'请先绑定bf群组'
        ), quote=source)
        return False
    # 打开绑定的文件
    with open(file_path, 'r', encoding="utf-8") as file1:
        data = yaml.load(file1, yaml.Loader)
        try:
            bfgroups_name = data["bfgroups"]
        except:
            await app.send_message(group, MessageChain(
                f'未识别到群组，请重新绑定bf群组'
            ), quote=source)
            return False
    # 根据bf群组名字找到群组
    group_path = f"./data/battlefield/binds/bfgroups/{bfgroups_name}"
    if not os.path.exists(group_path):
        await app.send_message(group, MessageChain(
            f"群组{bfgroups_name}不存在"
        ), quote=source)
        return False
    # 获取对应序号上的服务器的服管账号
    with open(f'./data/battlefield/binds/bfgroups/{bfgroups_name}/servers.yaml', 'r', encoding="utf-8") as file1:
        data = yaml.load(file1, yaml.Loader)
        if data is None:
            await app.send_message(group, MessageChain(
                f"群组{bfgroups_name}服务器信息为空，请先绑定服务器"
            ), quote=source)
            return False
        else:
            i = 0
            for server_item in data["servers"]:
                if server_item != '':
                    if server_gid == server_item["gameid"]:
                        if server_item["managerAccount"] == '' or None:
                            await app.send_message(group, MessageChain(
                                f"操作服务器未绑定服管账号，请先绑定服管账号!"
                            ), quote=source)
                            return False
                        else:
                            session = await get_bfgroup_session(app, group, i, source)
                            # 调用踢人的接口
                            result = await api_gateway.rsp_kickPlayer(server_gid, session, player_pid, reason)
                            if type(result) == str:
                                await app.send_message(group, MessageChain(
                                    f"{result}"
                                ), quote=source)
                                return False
                            elif type(result) == dict:
                                await app.send_message(group, MessageChain(
                                    f"踢出成功!原因:{reason}"
                                ), quote=source)
                                rsp_log.kick_logger(sender.id, group.id, player_name.result, server_item["serverid"],
                                                    reason)
                                return True
                            else:
                                await app.send_message(group, MessageChain(
                                    f"收到指令:({action.result})({player_name})({reason})\n但执行出错了"
                                ), quote=source)
                                return False
                    else:
                        pass
                i += 1
        await app.send_message(group, MessageChain(
            f"该玩家未在所绑定群组的服务器内游玩!\n正在游玩:{server_info['name']}"
        ), quote=source)
        return False


# sk
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
            "action" @ UnionMatch("-sk").space(SpacePolicy.FORCE),
            "player_name" @ ParamMatch(optional=False).space(SpacePolicy.PRESERVE),
            "reason" @ WildcardMatch(optional=True),
            # 示例: -sk xiao7xiao test
        ]
    )
)
async def kick_by_searched(app: Ariadne, sender: Member, group: Group,
                           action: RegexResult, player_name: RegexResult, reason: RegexResult, source: Source):
    # TODO 1.并发获取群组服务器玩家列表组成一个大字典 玩家pid-gameid 然后模糊搜索玩家id
    #  如果搜索到 返回列表 只有一个就回复y踢出n取消 多个则回复序号踢出

    player_name = player_name.result.display.lower()
    if player_name == "条形码":
        player_name = "iill"
    #  原因检测
    if str(reason.result) == "":
        reason = "违反规则"
    else:
        reason = str(reason.result).replace("ADMINPRIORITY", "违反规则")
    reason = zhconv.convert(reason, 'zh-tw')
    if ("空間" or "寬帶" or "帶寬" or "網絡" or "錯誤代碼") in reason:
        await app.send_message(group, MessageChain(
            "操作失败:踢出原因包含违禁词"
        ), quote=source)
        return False
    # 字数检测
    if 30 < len(reason.encode("utf-8")):
        await app.send_message(group, MessageChain(
            "原因字数过长(汉字10个以内)"
        ), quote=source)
        return False

    # 并发搜索所有服务器得到玩家列表
    # 获取服务器gameid列表 str-list
    # 先检查绑定群组没
    group_path = f'./data/battlefield/binds/groups/{group.id}'
    file_path = group_path + "/bfgroups.yaml"
    if not (os.path.exists(group_path) or os.path.isfile(file_path)):
        await app.send_message(group, MessageChain(
            f'请先绑定bf群组'
        ), quote=source)
        return False
    # 打开绑定的文件
    with open(file_path, 'r', encoding="utf-8") as file1:
        data = yaml.load(file1, yaml.Loader)
        try:
            bfgroups_name = data["bfgroups"]
        except:
            await app.send_message(group, MessageChain(
                f'未识别到群组，请重新绑定bf群组'
            ), quote=source)
            return False
    # 根据bf群组名字找到群组
    group_path = f"./data/battlefield/binds/bfgroups/{bfgroups_name}"
    if not os.path.exists(group_path):
        await app.send_message(group, MessageChain(
            f"群组{bfgroups_name}不存在"
        ), quote=source)
        return False
    # 获取服务器-序号-session-gameid字典
    info_dict = {}
    # info_dict  = {
    #     1:{
    #           session:xxx,
    #           sid:xxx,
    #           gameid:xxx
    #     },
    #     2:xxx
    # }
    with open(f'./data/battlefield/binds/bfgroups/{bfgroups_name}/servers.yaml', 'r', encoding="utf-8") as file1:
        data = yaml.load(file1, yaml.Loader)
        if data is None:
            await app.send_message(group, MessageChain(
                f"群组{bfgroups_name}服务器信息为空，请先绑定服务器"
            ), quote=source)
            return False
        else:
            for i, server_item in enumerate(data["servers"]):
                if server_item != '':
                    if server_item["managerAccount"] == '' or None:
                        pass
                    else:
                        info_dict[i] = {
                            "session": ""
                        }
                        info_dict[i]["session"] = await get_bfgroup_session_noApp(group, i)
                        info_dict[i]["serverid"] = data["servers"][i]["serverid"]
                        info_dict[i]["gameid"] = data["servers"][i]["gameid"]
    result_dict = {
        # server_rank :{
        #       player_matched:[] name_str list
        # }
    }
    player_matched_list = []  # name_str list
    player_pid_dict = {}  # name:pid
    player_list_info = await get_playerList_byGameid([info_dict[item]["gameid"] for item in info_dict])
    if type(player_list_info) == str:
        await app.send_message(group, MessageChain(
            player_list_info
        ), quote=source)
        return False
    for key in info_dict:
        result_dict[key] = {}
        player_list_data_temp = player_list_info[info_dict[key]["gameid"]]
        if player_list_data_temp != '':
            player_list_temp = []
            for player_item in player_list_data_temp["players"]:
                player_list_temp.append(player_item["display_name"].lower())
                player_pid_dict[player_item["display_name"].lower()] = player_item["pid"]
            player_matched = list(set(difflib.get_close_matches(player_name, player_list_temp)))
            for player_matched_item in player_matched:
                player_matched_list.append(player_matched_item)
            result_dict[key]["player_matched"] = player_matched
        else:
            result_dict[key]["player_matched"] = []

    send_temp_1 = []
    for key in result_dict:
        if result_dict[key]["player_matched"]:
            # 发送搜索到的玩家
            choices = []
            send_temp_1.append(f"在{key + 1}服搜索到玩家:")
            for i, item in enumerate(result_dict[key]["player_matched"]):
                send_temp_1.append(f"\n{i}#{item}")
                choices.append(str(i))
            # 等待回复踢出
            await app.send_message(group, MessageChain(
                send_temp_1,
                "\n30秒内发送'#'前的序号进行踢出,发送其他消息可退出"
            ), quote=source)

            async def waiter(waiter_member: Member, waiter_group: Group, waiter_message: MessageChain):
                if waiter_member.id == sender.id and waiter_group.id == group.id:
                    saying = waiter_message.display
                    if saying in choices:
                        _player_matched_kick = result_dict[key]["player_matched"][int(saying)]
                        _player_matched_kick = player_pid_dict[_player_matched_kick.lower()]
                        return True, waiter_member.id, _player_matched_kick
                    else:
                        return False, waiter_member.id, False

            try:
                result = await FunctionWaiter(waiter, [GroupMessage], block_propagation=True).wait(30)
            except asyncio.exceptions.TimeoutError:
                await app.send_message(group, MessageChain(
                    f'操作超时!已退出踢出'), quote=source)
                return

            if result:
                _, operator, player_matched_kick = result
                await app.send_message(group, MessageChain(
                    f"执行ing"
                ), quote=source)
                # 调用踢人的接口
                result = await api_gateway.rsp_kickPlayer(info_dict[key]["gameid"], info_dict[key]["session"],
                                                          player_matched_kick, reason)
                if type(result) == str:
                    return await app.send_message(group, MessageChain(
                        f"{result}"
                    ), quote=source)
                elif type(result) == dict:
                    await app.send_message(group, MessageChain(
                        f"踢出成功!原因:{reason}"
                    ), quote=source)
                    rsp_log.kick_logger(sender.id, group.id, player_name, info_dict[key]["serverid"], reason)
                    return
                else:
                    return await app.send_message(group, MessageChain(
                        f"收到指令:({action.result})({player_name})({reason})\n但执行出错了"
                    ), quote=source)
            else:
                return await app.send_message(group, MessageChain(
                    f"未识别到有效序号,取消踢出"
                ), quote=source)
    await app.send_message(group, MessageChain(
        f"未搜索到玩家~"
    ), quote=source)


# 封禁
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
            "action" @ UnionMatch("-ban", "-封禁", "-封").space(SpacePolicy.NOSPACE),
            FullMatch("#", optional=True).space(SpacePolicy.NOSPACE),
            "server_rank" @ ParamMatch(optional=False).space(SpacePolicy.FORCE),
            "player_name" @ ParamMatch(optional=False).space(SpacePolicy.PRESERVE),
            "reason" @ WildcardMatch(optional=True),
            # 示例: -b#1 xiaoxiao test
        ]
    )
)
async def add_ban(app: Ariadne, sender: Member, group: Group, action: RegexResult,
                  server_rank: RegexResult, player_name: RegexResult, reason: RegexResult, source: Source):
    if server_rank.result.display.startswith("f群组"):
        return
    elif server_rank.result.display.startswith("all"):
        return
    elif server_rank.result.display.startswith("ind"):
        return
    elif server_rank.result.display.startswith("f1百科"):
        return
    # 服务器序号检测
    try:
        server_rank = int(str(server_rank.result)) - 1
        if server_rank < 0 or server_rank > 30:
            await app.send_message(group, MessageChain(
                f"请检查服务器序号:1~30"
            ), quote=source)
            raise Exception
    except:
        return False
    player_name = str(player_name.result)
    # 原因检测
    reason = str(reason.result)
    if reason == "":
        reason = "违反规则"
    # 字数检测
    if 45 < len(reason.encode("utf-8")):
        await app.send_message(group, MessageChain(
            "请控制原因在15个汉字以内!"
        ), quote=source)
        return False

    # 获取session
    session = await get_bfgroup_session(app, group, server_rank, source)
    if type(session) != str:
        return False
    # 获取服务器id信息
    id_dict = await get_bfgroup_ids(app, group, server_rank, source)
    if type(id_dict) != dict:
        return False
    else:
        server_id = id_dict["serverid"]
        # server_gameid = id_dict["gameid"]
        # server_guid = id_dict["guid"]

    # 调用ban人的接口
    result = await api_gateway.rsp_addServerBan(server_id, session, player_name)
    if type(result) == str:
        await app.send_message(group, MessageChain(
            f"{result}"
        ), quote=source)
        return False
    elif type(result) == dict:
        await app.send_message(group, MessageChain(
            f"封禁成功!原因:{reason}"
        ), quote=source)
        rsp_log.ban_logger(sender.id, group_id=group.id, action_object=player_name, server_id=server_id,
                           reason=reason)
        return True
    else:
        await app.send_message(group, MessageChain(
            f"收到指令:({action.result})({server_rank})({player_name})({reason})\n但执行出错了"
        ), quote=source)
        return False


# 解封
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
            "action" @ UnionMatch("-unban", "-ub", "-解封").space(SpacePolicy.NOSPACE),
            FullMatch("#", optional=True).space(SpacePolicy.NOSPACE),
            "server_rank" @ ParamMatch(optional=False).space(SpacePolicy.FORCE),
            "player_name" @ ParamMatch(optional=False).space(SpacePolicy.PRESERVE),
            # 示例: -ub#1 xiaoxiao
        ]
    )
)
async def del_ban(app: Ariadne, sender: Member, group: Group, action: RegexResult,
                  server_rank: RegexResult, player_name: RegexResult, source: Source):
    if server_rank.result.display.startswith("all"):
        return
    # 服务器序号检测
    try:
        server_rank = int(str(server_rank.result)) - 1
        if server_rank < 0 or server_rank > 30:
            raise Exception
    except:
        await app.send_message(group, MessageChain(
            f"请检查服务器序号"
        ), quote=source)
        return False
    player_name = str(player_name.result)

    # 查验玩家存不存在
    try:
        player_info = await getPid_byName(player_name)
    except:
        await app.send_message(group, MessageChain(
            f"网络出错，请稍后再试"
        ), quote=source)
        return False
    if player_info['personas'] == {}:
        await app.send_message(group, MessageChain(
            f"玩家[{player_name}]不存在"
        ), quote=source)
        return False
    player_pid = player_info['personas']['persona'][0]['personaId']

    # 获取session
    session = await get_bfgroup_session(app, group, server_rank, source)
    if type(session) != str:
        return False
    # 获取服务器id信息
    id_dict = await get_bfgroup_ids(app, group, server_rank, source)
    if type(id_dict) != dict:
        return False
    else:
        server_id = id_dict["serverid"]
        # server_gameid = id_dict["gameid"]
        # server_guid = id_dict["guid"]

    # 调用解ban的接口
    result = await api_gateway.rsp_removeServerBan(server_id, session, player_pid)
    if type(result) == str:
        await app.send_message(group, MessageChain(
            f"{result}"
        ), quote=source)
        return False
    elif type(result) == dict:
        await app.send_message(group, MessageChain(
            f"解封成功!"
        ), quote=source)
        rsp_log.unban_logger(sender.id, group_id=group.id, action_object=player_name, server_id=server_id)
        return True
    else:
        await app.send_message(group, MessageChain(
            f"收到指令:({action.result})({server_rank})({player_name})\n但执行出错了"
        ), quote=source)
        return False


# banall
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
            "action" @ UnionMatch("-banall").space(SpacePolicy.FORCE),
            "player_name" @ ParamMatch(optional=False).space(SpacePolicy.PRESERVE),
            "reason" @ WildcardMatch(optional=True),
            # 示例: -banall xiaoxiao test
        ]
    )
)
async def add_banall(app: Ariadne, sender: Member, group: Group,
                     player_name: RegexResult, reason: RegexResult, source: Source):
    # TODO 循环 -> task = ban(session,id) ->并发 -> 循环 result -> 输出
    player_name = player_name.result.display
    try:
        player_info = await getPid_byName(player_name)
    except:
        await app.send_message(group, MessageChain(
            f"网络出错，请稍后再试"
        ), quote=source)
        return False
    if player_info['personas'] == {}:
        await app.send_message(group, MessageChain(
            f"玩家[{player_name}]不存在"
        ), quote=source)
        return False
    else:
        # player_pid = player_info['personas']['persona'][0]['personaId']
        player_name = player_info['personas']['persona'][0]['displayName']

    # 原因检测
    reason = str(reason.result)
    if reason == "":
        reason = "违反规则"
    # 字数检测
    if 45 < len(reason.encode("utf-8")):
        await app.send_message(group, MessageChain(
            "请控制原因在15个汉字以内!"
        ), quote=source)
        return False

    # 先检查绑定群组没
    group_path = f'./data/battlefield/binds/groups/{group.id}'
    file_path = group_path + "/bfgroups.yaml"
    if not (os.path.exists(group_path) or os.path.isfile(file_path)):
        await app.send_message(group, MessageChain(
            f'请先绑定bf群组'
        ), quote=source)
        return False
    # 打开绑定的文件
    with open(file_path, 'r', encoding="utf-8") as file1:
        data = yaml.load(file1, yaml.Loader)
        try:
            bfgroups_name = data["bfgroups"]
        except:
            await app.send_message(group, MessageChain(
                f'未识别到群组，请重新绑定bf群组'
            ), quote=source)
            return False
    # 根据bf群组名字找到群组
    group_path = f"./data/battlefield/binds/bfgroups/{bfgroups_name}"
    if not os.path.exists(group_path):
        await app.send_message(group, MessageChain(
            f"群组{bfgroups_name}不存在"
        ), quote=source)
        return False
    # 获取对应序号上的服务器的服管账号
    # dict ={
    #    i:{session:""}
    # }
    session_dict = {}
    with open(f'./data/battlefield/binds/bfgroups/{bfgroups_name}/servers.yaml', 'r', encoding="utf-8") as file1:
        data = yaml.load(file1, yaml.Loader)
        if data is None:
            await app.send_message(group, MessageChain(
                f"群组{bfgroups_name}服务器信息为空，请先绑定服务器"
            ), quote=source)
            return False
        else:
            for i, server_item in enumerate(data["servers"]):
                if server_item != '':
                    if server_item["managerAccount"] == '' or None:
                        pass
                    else:
                        session_dict[i] = {
                            "session": ""
                        }
                        session_dict[i]["session"] = await get_bfgroup_session_noApp(group, i)
                        session_dict[i]["serverid"] = data["servers"][i]["serverid"]

    scrape_index_tasks = [
        asyncio.ensure_future(
            api_gateway.rsp_addServerBan(session_dict[i]["serverid"], session_dict[i]["session"], player_name)
        )
        for i in session_dict
    ]
    tasks = asyncio.gather(*scrape_index_tasks)
    try:
        await tasks
    except Exception as e:
        await app.send_message(group, MessageChain(
            f"执行中出现了一个错误!{e}"
        ), quote=source)
        return False
    banall_result = []
    for i, result in enumerate(scrape_index_tasks):
        result = result.result()
        keys = [key for key in session_dict]
        i = keys[i]
        if type(result) == dict:
            banall_result.append(
                f"{i + 1}服:封禁成功!\n"
            )
            rsp_log.ban_logger(sender.id, group_id=group.id, action_object=player_name,
                               server_id=session_dict[i]["serverid"],
                               reason=reason)
        else:
            banall_result.append(
                f"{i + 1}服:{result}\n"
            )
    try:
        banall_result[-1] = banall_result[-1].replace("\n", "")
    except:
        pass
    await app.send_message(group, MessageChain(
        banall_result
    ), quote=source)


# unbanll
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
            "action" @ UnionMatch("-unbanall").space(SpacePolicy.FORCE),
            "player_name" @ ParamMatch(optional=False).space(SpacePolicy.PRESERVE)
            # 示例: -unbanall xiaoxiao
        ]
    )
)
async def del_banall(app: Ariadne, sender: Member, group: Group,
                     player_name: RegexResult, source: Source):
    # TODO 循环 -> task = ban(session,id) ->并发 -> 循环 result -> 输出
    player_name = player_name.result.display
    try:
        player_info = await getPid_byName(player_name)
    except:
        await app.send_message(group, MessageChain(
            f"网络出错，请稍后再试"
        ), quote=source)
        return False
    if player_info['personas'] == {}:
        await app.send_message(group, MessageChain(
            f"玩家[{player_name}]不存在"
        ), quote=source)
        return False
    else:
        player_pid = player_info['personas']['persona'][0]['personaId']
        player_name = player_info['personas']['persona'][0]['displayName']

    # 先检查绑定群组没
    group_path = f'./data/battlefield/binds/groups/{group.id}'
    file_path = group_path + "/bfgroups.yaml"
    if not (os.path.exists(group_path) or os.path.isfile(file_path)):
        await app.send_message(group, MessageChain(
            f'请先绑定bf群组'
        ), quote=source)
        return False
    # 打开绑定的文件
    with open(file_path, 'r', encoding="utf-8") as file1:
        data = yaml.load(file1, yaml.Loader)
        try:
            bfgroups_name = data["bfgroups"]
        except:
            await app.send_message(group, MessageChain(
                f'未识别到群组，请重新绑定bf群组'
            ), quote=source)
            return False
    # 根据bf群组名字找到群组
    group_path = f"./data/battlefield/binds/bfgroups/{bfgroups_name}"
    if not os.path.exists(group_path):
        await app.send_message(group, MessageChain(
            f"群组{bfgroups_name}不存在"
        ), quote=source)
        return False
    # 获取对应序号上的服务器的服管账号
    # dict ={
    #    i:{session:""}
    # }
    session_dict = {}
    with open(f'./data/battlefield/binds/bfgroups/{bfgroups_name}/servers.yaml', 'r', encoding="utf-8") as file1:
        data = yaml.load(file1, yaml.Loader)
        if data is None:
            await app.send_message(group, MessageChain(
                f"群组{bfgroups_name}服务器信息为空，请先绑定服务器"
            ), quote=source)
            return False
        else:
            for i, server_item in enumerate(data["servers"]):
                if server_item != '':
                    if server_item["managerAccount"] == '' or None:
                        pass
                    else:
                        session_dict[i] = {
                            "session": ""
                        }
                        session_dict[i]["session"] = await get_bfgroup_session_noApp(group, i)
                        session_dict[i]["serverid"] = data["servers"][i]["serverid"]

    scrape_index_tasks = [
        asyncio.ensure_future(
            api_gateway.rsp_removeServerBan(session_dict[i]["serverid"], session_dict[i]["session"], player_pid)
        )
        for i in session_dict
    ]
    tasks = asyncio.gather(*scrape_index_tasks)
    try:
        await tasks
    except Exception as e:
        await app.send_message(group, MessageChain(
            f"执行中出现了一个错误!{e}"
        ), quote=source)
        return False
    unbanall_result = []
    for i, result in enumerate(scrape_index_tasks):
        result = result.result()
        if type(result) == dict:
            unbanall_result.append(
                f"{i + 1}服:解封成功!\n"
            )
            rsp_log.unban_logger(sender.id, group_id=group.id, action_object=player_name,
                                 server_id=session_dict[i]["serverid"])
        else:
            unbanall_result.append(
                f"{i + 1}服:{result}\n"
            )
    try:
        unbanall_result[-1] = unbanall_result[-1].replace("\n", "")
    except:
        pass
    await app.send_message(group, MessageChain(
        unbanall_result
    ), quote=source)


async def check_vban(player_pid) -> dict or str:
    url = f"https://api.gametools.network/manager/checkban?playerid={player_pid}&platform=pc&skip_battlelog=false"
    head = {
        'accept': 'application/json',
        "Connection": "Keep-Alive"
    }
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=head, timeout=5)
        try:
            return eval(response.text)
        except:
            return "获取出错!"
    except:
        return '网络出错!'


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
            "action" @ UnionMatch("-checkban").space(SpacePolicy.PRESERVE),
            "player_name" @ ParamMatch(optional=True).space(SpacePolicy.PRESERVE)
            # 示例: -checkban xiaoxiao
        ]
    )
)
async def check_ban(app: Ariadne, group: Group, player_name: RegexResult, source: Source):
    # 检查qq群文件是否存在
    group_path = f'./data/battlefield/binds/groups/{group.id}'
    file_path = group_path + "/bfgroups.yaml"
    if not (os.path.exists(group_path) or os.path.isfile(file_path)):
        await app.send_message(group, MessageChain(
            f'请先绑定bf群组'
        ), quote=source)
        return False
    # 打开绑定的文件
    with open(file_path, 'r', encoding="utf-8") as file1:
        data = yaml.load(file1, yaml.Loader)
        try:
            bfgroups_name = data["bfgroups"]
        except:
            await app.send_message(group, MessageChain(
                f'未识别到群组，请重新绑定bf群组'
            ), quote=source)
    # 根据bf群组名字找到群组绑定服务器文件-获取服务器gameid
    group_path = f"./data/battlefield/binds/bfgroups/{bfgroups_name}"
    if not os.path.exists(group_path):
        await app.send_message(group, MessageChain(
            f"群组{bfgroups_name}不存在"
        ), quote=source)
        return False
    with open(f'./data/battlefield/binds/bfgroups/{bfgroups_name}/servers.yaml', 'r', encoding="utf-8") as file1:
        data = yaml.load(file1, yaml.Loader)
        # 检查是否servers.yaml是否为空
        if data is None:
            await app.send_message(group, MessageChain(
                f"群组服务器信息为空，请先绑定服务器"
            ), quote=source)
            return False
        else:
            server_list = []
            for item in data["servers"]:
                if item != "":
                    server_list.append(f'{item["gameid"]}')
                else:
                    server_list.append("")
    # 并发查找
    scrape_index_tasks = [asyncio.ensure_future(api_gateway.get_server_fulldetails(gameid)) for gameid in server_list]
    # scrape_index_tasks = [asyncio.ensure_future(api_gateway.get_server_fulldetails(gameid)) for gameid in server_list]
    tasks = asyncio.gather(*scrape_index_tasks)
    try:
        await tasks
    except:
        await app.send_message(group, MessageChain(
            GraiaImage(path='./data/bqb/狐务器无响应.jpg')
        ), quote=source)
        return False
    send = []
    if not player_name.matched:
        ban_list_all = []
        for i, result in enumerate(scrape_index_tasks):
            server_fullInfo = result.result()
            if server_fullInfo == '':
                # send.append(f"{i + 1}服:获取信息失败\n")
                continue
            else:
                ban_list = []
                for item in server_fullInfo["rspInfo"]["bannedList"]:
                    # temp = f"名字:{item['displayName']}\nPid:{item['personaId']}\n"
                    ban_list.append(item['personaId'])
                    ban_list_all.append(item['personaId'])
                send.append(f"{i + 1}服:封禁数{len(ban_list)}\n")
        if send:
            try:
                send[-1] = send[-1].replace("\n", "")
            except:
                pass
        send.insert(0, f"群组{bfgroups_name}服务器ban位共:{len(ban_list_all)}个玩家:\n")
        await app.send_message(group, MessageChain(
            send
        ), quote=source)
        return True
    else:
        # 检查玩家名是否有效
        player_name = player_name.result.display
        try:
            player_info = await getPid_byName(player_name)
        except:
            await app.send_message(group, MessageChain(
                f"网络出错，请稍后再试"
            ), quote=source)
            return False
        if player_info['personas'] == {}:
            await app.send_message(group, MessageChain(
                f"玩家[{player_name}]不存在"
            ), quote=source)
            return False
        else:
            player_pid = player_info['personas']['persona'][0]['personaId']
            # player_name = player_info['personas']['persona'][0]['displayName']
        # ban位检查
        ban_list_all = []
        for i, result in enumerate(scrape_index_tasks):
            server_fullInfo = result.result()
            if server_fullInfo == '':
                # send.append(f"{i + 1}服:获取信息失败\n")
                continue
            else:
                ban_list = []
                for item in server_fullInfo["rspInfo"]["bannedList"]:
                    # temp = f"名字:{item['displayName']}\nPid:{item['personaId']}\n"
                    ban_list.append(item['personaId'])
                    ban_list_all.append(item['personaId'])
                if str(player_pid) in ban_list:
                    send.append(f"{i + 1}服:已封禁\n")
                else:
                    send.append(f"{i + 1}服:未封禁\n")
        vban_info = await check_vban(player_pid)
        if type(vban_info) == str:
            pass
        else:
            vban_num = len(vban_info["vban"])
            send.append(f"该玩家被vban数:{vban_num}")
        if send:
            try:
                send[-1] = send[-1].replace("\n", "")
            except:
                pass
        await app.send_message(group, MessageChain(
            send
        ), quote=source)
        return True


# # 群组封禁
# @listen(GroupMessage)
# @decorate(
#     Permission.user_require(Permission.GroupAdmin, if_noticed=True),
#     Permission.group_require(channel.metadata.level),
#     Function.require(channel.module),
#     FrequencyLimitation.require(channel.module),
#     Distribute.require()
# )
# @dispatch(
#     Twilight(
#         [
#             "action" @ UnionMatch("-群组ban").space(SpacePolicy.FORCE),
#             "player_name" @ ParamMatch(optional=False).space(SpacePolicy.PRESERVE),
#             "reason" @ WildcardMatch(optional=True),
#             # 示例: -b#1 xiaoxiao test
#         ]
#     )
# )
# async def add_groupBan(app: Ariadne, sender: Member, group: Group, message: MessageChain, player_name: RegexResult,
#                        reason: RegexResult):
#     player_name = player_name.result.display
#     try:
#         player_info = await getPid_byName(player_name)
#     except:
#         await app.send_message(group, MessageChain(
#             f"网络出错，请稍后再试"
#         ), quote=message[Source][0])
#         return False
#     if player_info['personas'] == {}:
#         await app.send_message(group, MessageChain(
#             f"玩家[{player_name}]不存在"
#         ), quote=message[Source][0])
#         return False
#     else:
#         player_pid = player_info['personas']['persona'][0]['personaId']
#         player_name = player_info['personas']['persona'][0]['displayName']
#     # 原因检测
#     reason = str(reason.result)
#     if reason == "":
#         reason = "违反规则"
#     # 字数检测
#     if 45 < len(reason.encode("utf-8")):
#         await app.send_message(group, MessageChain(
#             "请控制原因在15个汉字以内!"
#         ), quote=message[Source][0])
#         return False
#
#     # 获取session
#     session = None
#     # 先检查绑定群组没
#     group_path = f'./data/battlefield/binds/groups/{group.id}'
#     file_path = group_path + "/bfgroups.yaml"
#     if not (os.path.exists(group_path) or os.path.isfile(file_path)):
#         await app.send_message(group, MessageChain(
#             f'请先绑定bf群组'
#         ), quote=message[Source][0])
#         return False
#     # 打开绑定的文件
#     with open(file_path, 'r', encoding="utf-8") as file1:
#         data = yaml.load(file1, yaml.Loader)
#         try:
#             bfgroups_name = data["bfgroups"]
#         except:
#             await app.send_message(group, MessageChain(
#                 f'未识别到群组，请重新绑定bf群组'
#             ), quote=message[Source][0])
#             return False
#     # 根据bf群组名字找到群组
#     group_path = f"./data/battlefield/binds/bfgroups/{bfgroups_name}"
#     if not os.path.exists(group_path):
#         await app.send_message(group, MessageChain(
#             f"群组{bfgroups_name}不存在"
#         ), quote=message[Source][0])
#         return False
#     with open(f'./data/battlefield/binds/bfgroups/{bfgroups_name}/servers.yaml', 'r', encoding="utf-8") as file1:
#         data = yaml.load(file1, yaml.Loader)
#         if data is None:
#             await app.send_message(group, MessageChain(
#                 f"群组{bfgroups_name}服务器信息为空，请先绑定服务器"
#             ), quote=message[Source][0])
#             return False
#         else:
#             i = 0
#             for server_item in data["servers"]:
#                 if server_item != '':
#                     if server_item["managerAccount"] == '' or None:
#                         pass
#                     else:
#                         session = await get_bfgroup_session(app, group, message, i)
#                         break
#     if session is None:
#         await app.send_message(group, MessageChain(
#             f"没有获取到群组{bfgroups_name}有效的服管账号!"
#         ), quote=message[Source][0])
#         return False
#
#     # TODO 1.创建一个群组的群组ban位文件 2.将该玩家添加到文件里
#     group_ban_file_path = f"./data/battlefield/binds/bfgroups/{bfgroups_name}/groupban.json"
#     if not os.path.exists(group_ban_file_path):
#         with open(group_ban_file_path, 'w', encoding="utf-8") as file1:
#             await app.send_message(group, MessageChain(
#                 f"初始化{bfgroups_name}群组ban成功!"
#             ), quote=message[Source][0])
#             init_data = {"data": [
#                 {
#                     "displayName": player_name,
#                     "personaId": player_pid,
#                     "time": str(int(time.time() * 1000)),
#                     "reason": reason,
#                     "operator": sender.id,
#                 }
#             ]}
#             json.dump(init_data, file1, indent=4, ensure_ascii=False)
#             await app.send_message(group, MessageChain(
#                 f"群组封禁成功!原因:{reason}"
#             ), quote=message[Source][0])
#             return True
#     else:
#         with open(group_ban_file_path, 'r', encoding="utf-8") as file1:
#             ban_data = json.load(file1)
#             # 如果已在群组ban位则返回信息,不在则添加
#             for banned_player in ban_data["data"]:
#                 if player_pid == banned_player["personaId"]:
#                     await app.send_message(group, MessageChain(
#                         f"该玩家已在群组ban位!"
#                     ), quote=message[Source][0])
#                     return True
#             ban_data["data"].append(
#                 {
#                     "displayName": player_name,
#                     "personaId": player_pid,
#                     "time": str(int(time.time() * 1000)),
#                     "reason": reason,
#                     "operator": sender.id,
#                 }
#             )
#             with open(group_ban_file_path, 'w', encoding="utf-8") as file2:
#                 json.dump(ban_data, file2, indent=4, ensure_ascii=False)
#                 await app.send_message(group, MessageChain(
#                     f"群组封禁成功!原因:{reason}"
#                 ), quote=message[Source][0])
#                 return True
#
#
# # 群组解封
# @channel.use(ListenerSchema(listening_events=[GroupMessage],
#                             decorators=[Perm.require(32),
#                                         Switch.require("bf1服管"),
#                                         DuoQ.require()],
#                             inline_dispatchers=[
#                                 Twilight(
#                                     [
#                                         "action" @ UnionMatch("-un群组ban").space(SpacePolicy.FORCE),
#                                         "player_name" @ ParamMatch(optional=False).space(SpacePolicy.PRESERVE),
#                                         # 示例: -b#1 xiaoxiao test
#                                     ]
#                                 )
#                             ]))
# async def del_groupBan(app: Ariadne, group: Group, message: MessageChain, player_name: RegexResult):
#     player_name = player_name.result.display
#     try:
#         player_info = await getPid_byName(player_name)
#     except:
#         await app.send_message(group, MessageChain(
#             f"网络出错，请稍后再试"
#         ), quote=message[Source][0])
#         return False
#     if player_info['personas'] == {}:
#         await app.send_message(group, MessageChain(
#             f"玩家[{player_name}]不存在"
#         ), quote=message[Source][0])
#         return False
#     else:
#         player_pid = player_info['personas']['persona'][0]['personaId']
#         player_name = player_info['personas']['persona'][0]['displayName']
#
#     # 获取session
#     session = None
#     # 先检查绑定群组没
#     group_path = f'./data/battlefield/binds/groups/{group.id}'
#     file_path = group_path + "/bfgroups.yaml"
#     if not (os.path.exists(group_path) or os.path.isfile(file_path)):
#         await app.send_message(group, MessageChain(
#             f'请先绑定bf群组'
#         ), quote=message[Source][0])
#         return False
#     # 打开绑定的文件
#     with open(file_path, 'r', encoding="utf-8") as file1:
#         data = yaml.load(file1, yaml.Loader)
#         try:
#             bfgroups_name = data["bfgroups"]
#         except:
#             await app.send_message(group, MessageChain(
#                 f'未识别到群组，请重新绑定bf群组'
#             ), quote=message[Source][0])
#             return False
#     # 根据bf群组名字找到群组
#     group_path = f"./data/battlefield/binds/bfgroups/{bfgroups_name}"
#     if not os.path.exists(group_path):
#         await app.send_message(group, MessageChain(
#             f"群组{bfgroups_name}不存在"
#         ), quote=message[Source][0])
#         return False
#     server_serverids = []
#     with open(f'./data/battlefield/binds/bfgroups/{bfgroups_name}/servers.yaml', 'r', encoding="utf-8") as file1:
#         data = yaml.load(file1, yaml.Loader)
#         if data is None:
#             await app.send_message(group, MessageChain(
#                 f"群组{bfgroups_name}服务器信息为空，请先绑定服务器"
#             ), quote=message[Source][0])
#             return False
#         else:
#             i = 0
#             for server_item in data["servers"]:
#                 if server_item != '':
#                     server_serverids.append(server_item["serverid"])
#                     if server_item["managerAccount"] == '' or None:
#                         pass
#                     else:
#                         session = await get_bfgroup_session(app, group, message, i)
#     if session is None:
#         await app.send_message(group, MessageChain(
#             f"没有获取到群组{bfgroups_name}有效的服管账号!"
#         ), quote=message[Source][0])
#         return False
#
#     group_ban_file_path = f"./data/battlefield/binds/bfgroups/{bfgroups_name}/groupban.json"
#     if not os.path.exists(group_ban_file_path):
#         await app.send_message(group, MessageChain(
#             f"群组ban未初始化!"
#         ), quote=message[Source][0])
#         return False
#     else:
#         with open(group_ban_file_path, 'r', encoding="utf-8") as file1:
#             ban_data = json.load(file1)
#             # 如果已在群组ban位则返回信息,不在则添加
#             for i, banned_player in enumerate(ban_data["data"]):
#                 if player_pid == banned_player["personaId"]:
#                     ban_data["data"].pop(i)
#                     tasks = [api_gateway.rsp_removeServerBan(server_id, session, player_pid) for server_id in
#                              server_serverids]
#                     tasks = asyncio.gather(*tasks)
#                     await tasks
#                     for item in tasks:
#                         if type(item.result) == dict:
#                             rsp_log.unban_logger("群组ban解ban", player_name, server_serverids[i],
#                                                  bfgroups_name=bfgroups_name)
#                         else:
#                             logger.error(f"处理群组{bfgroups_name}解封{player_name}出错:{item.result}")
#                         i += 1
#                     with open(group_ban_file_path, 'w', encoding="utf-8") as file2:
#                         json.dump(ban_data, file2, indent=4, ensure_ascii=False)
#                     await app.send_message(group, MessageChain(
#                         f"群组ban解封{player_name}成功!"
#                     ), quote=message[Source][0])
#                     return True
#             await app.send_message(group, MessageChain(
#                 f"未在群组ban找到该玩家!"
#             ), quote=message[Source][0])
#             return True


# 群组自动封禁
# @channel.use(SchedulerSchema(timers.every_custom_minutes(5)))
# async def auto_ban(app: Ariadne):
#     groups_path = f"./data/battlefield/binds/bfgroups"
#     group_list = os.listdir(groups_path)
#     scrape_index_tasks = []
#     for group_item in group_list:
#         group_ban_file_path = f"./data/battlefield/binds/bfgroups/{group_item}/groupban.json"
#         if not os.path.exists(group_ban_file_path):
#             pass
#         else:
#             scrape_index_tasks.append(asyncio.ensure_future(auto_ban_byGroupBan(group_item)))
#     tasks = asyncio.gather(*scrape_index_tasks)
#     try:
#         logger.warning("执行群组ban中")
#         await tasks
#     except:
#         return False


# 群组ban自动封禁
async def auto_ban_byGroupBan(group_item):
    logger.info(f"开始处理[{group_item}]群组ban")
    group_ban_file_path = f"./data/battlefield/binds/bfgroups/{group_item}/groupban.json"
    # TODO:
    #  流程:
    #  按照封禁时间 将最近封禁的上ban位,如果ban位已满,则往最早的时间找(上限50)解ban,
    with open(f'./data/battlefield/binds/bfgroups/{group_item}/servers.yaml', 'r', encoding="utf-8") as file1:
        data = yaml.load(file1, yaml.Loader)
        if data is not None:
            server_gameids = []
            for server in data["servers"]:
                if server != "":
                    managerAccount = server["managerAccount"]
                    if not (managerAccount == '' or managerAccount is None):
                        # 获取id信息
                        server_id = server["serverid"]
                        server_gameid = server["gameid"]
                        # 根据服管账号获取session
                        account_pid = managerAccount
                        file_path = f'./data/battlefield/managerAccount'
                        account_list = os.listdir(file_path)
                        if len(account_list) == 0:
                            continue
                        if account_pid not in account_list:
                            continue
                        with open(f'{file_path}/{account_pid}/session.json', 'r', encoding="utf-8") as file2:
                            try:
                                data1 = json.load(file2)
                                session = data1["session"]
                            except:
                                continue
                        server_gameids.append(server_gameid)
                    else:
                        continue
            if not session:
                return
            # 每隔50个玩家就并发查找玩家所在服务器,如果在群组服务器内,就执行ban
            with open(group_ban_file_path, 'r', encoding="utf-8") as file2:
                ban_data = json.load(file2)
                player_list_temp = []
                for item in ban_data["data"]:
                    player_list_temp.append(asyncio.ensure_future(server_playing(item["personaId"])))
                player_list_temp = asyncio.gather(*player_list_temp)
                await player_list_temp
                result_list = player_list_temp
                temp_counter = 0
                for item_result in result_list.result():
                    if type(item_result) == dict:
                        server_gameid = item_result["gameId"]
                        if server_gameid in server_gameids:
                            # 如果ban位已满或占用ban位已经达到50则先解ban，找既在ban位又在群组ban名单上的人,找最早的第50个解ban
                            try:
                                server_fullInfo = await api_gateway.get_server_fulldetails(server_gameid)
                                if server_fullInfo == "":
                                    raise Exception
                            except:
                                logger.error("获取服务器信息失败")
                                temp_counter += 1
                                continue
                            ban_list = []
                            for item2 in server_fullInfo["rspInfo"]["bannedList"]:
                                temp = f"{item2['personaId']}"
                                ban_list.append(temp)
                            banned_counter = 0
                            for item2 in ban_data["data"]:
                                if item2["personaId"] in ban_list:
                                    banned_counter += 1
                            if len(ban_list) == 200 or banned_counter == 50:
                                temp_counter2 = 0
                                temp_compare = ban_data["data"][0]["time"]
                                del_ban_pid = ban_data["data"][0]["personaId"]
                                del_ban_name = ban_data["data"][0]["displayName"]
                                for item2 in ban_data["data"]:
                                    if item2["personaId"] in ban_list:
                                        if item2["time"] < temp_compare:
                                            temp_compare = item2["time"]
                                            del_ban_pid = item2["personaId"]
                                            del_ban_name = item2["displayName"]
                                        temp_counter2 += 1
                                        if temp_counter2 == 50:
                                            break
                                try:
                                    # 调用解ban的接口
                                    result = await api_gateway.rsp_removeServerBan(server_id, session,
                                                                                   del_ban_pid)
                                    if type(result) == str:
                                        pass
                                    elif type(result) == dict:
                                        logger.success(f"群组ban自动腾出空间{del_ban_name}成功!")
                                        rsp_log.unban_logger(qq_id="群组ban自动腾出空间", action_object=del_ban_name,
                                                             server_id=server_id,
                                                             bfgroups_name=group_item)
                                except:
                                    logger.error(f"处理群组{group_item}自动解ban腾出空间出错!")

                            # 调用ban人的接口,
                            try:
                                for server in data["servers"]:
                                    if server != "":
                                        managerAccount = server["managerAccount"]
                                        if not (managerAccount == '' or managerAccount is None):
                                            if server["gameid"] == server_gameid:
                                                server_id = server["serverid"]
                                logger.warning(f"群组ban自动封禁{ban_data['data'][temp_counter]['displayName']}中")
                                result = await api_gateway.rsp_addServerBan(server_id, session,
                                                                            player_pid=ban_data["data"][temp_counter][
                                                                                "personaId"])
                            except:
                                logger.error(
                                    f"处理群组{group_item}封禁{ban_data['data'][temp_counter]['personaId']}出错!")
                                temp_counter += 1
                                continue
                            if type(result) == str:
                                logger.error(f"处理群组{group_item}封禁出错:{result}")
                            if type(result) == dict:
                                logger.success(f"群组ban自动封禁{ban_data['data'][temp_counter]['displayName']}成功!")
                                try:
                                    rsp_log.ban_logger(qq_id="群组ban", bfgroups_name=group_item,
                                                       action_object=ban_data['data'][temp_counter]['displayName'],
                                                       server_id=server_id,
                                                       reason=f"群组ban自动封禁:{ban_data['data'][temp_counter]['reason']}")
                                except Exception as e:
                                    logger.error(f"日志出错!信息如下:{e}")
                    temp_counter += 1


# 服务器150白名单自动踢出
@channel.use(SchedulerSchema(timers.every_custom_seconds(30)))
async def auto_kick_byWhitelist_main():
    ...


async def auto_kick_byWhitelist():
    ...


# 添加白名单开启服务器
async def akbw_add_server():
    ...


# 删除白名单开启服务器
async def akbw_del_server():
    ...


# 检查白名单是否开启
async def akbw_check_server():
    ...


# 添加白名单
async def akbw_add_whitelist():
    ...


# 删除白名单
async def akbw_del_whitelist():
    ...


# 查看白名单
async def akbw_check_whitelist():
    ...


# 添加群组白名单
async def akbw_add_global_whitelist():
    ...


# 删除群组白名单
async def akbw_del_global_whitelist():
    ...


# 查看群组白名单
async def akbw_check_global_whitelist():
    ...


# 清理ban位
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
            "action" @ UnionMatch("-清理ban位", "-清ban").space(SpacePolicy.NOSPACE),
            FullMatch("#", optional=True).space(SpacePolicy.NOSPACE),
            "server_rank" @ ParamMatch(optional=False).space(SpacePolicy.PRESERVE),
            "clear_num" @ ParamMatch(optional=True).space(SpacePolicy.PRESERVE),
            # 示例: -清ban#
        ]
    )
)
async def clear_ban(app: Ariadne, sender: Member, group: Group, server_rank: RegexResult,
                    clear_num: RegexResult, source: Source):
    # 检查清理ban位的数量
    if clear_num.matched:
        try:
            clear_num = int(str(clear_num.result))
            if clear_num < 0 or clear_num > 200:
                raise Exception
        except:
            await app.send_message(group, MessageChain(
                f"请检查清理的数量(0~200)"
            ), quote=source)
    else:
        clear_num = 200
    # 服务器序号检测
    try:
        server_rank = int(str(server_rank.result)) - 1
        if server_rank < 0 or server_rank > 30:
            raise Exception
    except:
        await app.send_message(group, MessageChain(
            f"请检查服务器序号"
        ), quote=source)
        return False

    # 获取session
    session = await get_bfgroup_session(app, group, server_rank, source)
    if type(session) != str:
        return False
    # 获取服务器id信息
    id_dict = await get_bfgroup_ids(app, group, server_rank, source)
    if type(id_dict) != dict:
        return False
    else:
        server_id = id_dict["serverid"]
        server_gameid = id_dict["gameid"]
        # server_guid = id_dict["guid"]

    # 获取服务器信息-fullInfo
    try:
        server_fullInfo = await api_gateway.get_server_fulldetails(server_gameid)
        if server_fullInfo == "":
            raise Exception
    except:
        await app.send_message(group, MessageChain(
            "获取服务器信息出现错误!"
        ), quote=source)
        return False
    # 判空
    if len(server_fullInfo["rspInfo"]["bannedList"]) == 0:
        await app.send_message(group, MessageChain(
            f"当前ban位数量为0"
        ), quote=source)
        return False
    # 获取要清理的pid列表
    ban_pid_list = []
    i = 0
    clear_num = clear_num if clear_num <= len(server_fullInfo["rspInfo"]["bannedList"]) else len(
        server_fullInfo["rspInfo"]["bannedList"])
    await app.send_message(group, MessageChain(
        f'当前ban位数量为{len(server_fullInfo["rspInfo"]["bannedList"])}'
    ), quote=source)
    while i < clear_num:
        ban_pid_list.append(server_fullInfo["rspInfo"]["bannedList"][i]["personaId"])
        i += 1
    await app.send_message(group, MessageChain(
        f"预计释放{len(ban_pid_list)}个ban位"
    ), quote=source)

    # 开始清理
    # 记录成功的，失败的
    success = 0
    fail = 0
    # 任务列表
    scrape_index_tasks = [asyncio.ensure_future(api_gateway.rsp_removeServerBan(server_id, session, item)) for item
                          in ban_pid_list]
    tasks = asyncio.gather(*scrape_index_tasks)
    await tasks
    result = []
    for i in scrape_index_tasks:
        result.append(i.result())
    i = 0
    for result_temp in result:
        # 先使用移除vip的接口，再处理vip.json文件
        if type(result_temp) == dict:
            success += 1
        else:
            fail += 1
        i += 1
    await app.send_message(group, MessageChain(
        f"清理ban位完毕!成功:{success}个,失败:{fail}个"
    ), quote=source)
    rsp_log.clearBan_logger(sender.id, group.id, success, server_id)
    return True


# 加vban
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
            "action" @ UnionMatch("-vban", "-加vban", "-vb").space(SpacePolicy.NOSPACE),
            FullMatch("#", optional=True).space(SpacePolicy.NOSPACE),
            "vban_rank" @ ParamMatch(optional=False).space(SpacePolicy.FORCE),
            "player_name" @ ParamMatch(optional=False).space(SpacePolicy.PRESERVE),
            "reason" @ ParamMatch(optional=True).space(SpacePolicy.PRESERVE),
            # 示例: -vban xiaoxiao test 1
        ]
    )
)
async def add_vban(app: Ariadne, group: Group, player_name: RegexResult, reason: RegexResult, vban_rank: RegexResult,
                   source: Source):
    if not reason.matched:
        reason = "违反规则"
    else:
        reason = str(reason.result)
    # 寻找vban配置
    try:
        vban_rank = int(str(vban_rank.result))
        if vban_rank < 1 or vban_rank > 10:
            raise Exception
        if vban_rank == 1:
            vban_rank = ''
    except:
        await app.send_message(group, MessageChain(
            "请检查vban序号:1~10"
        ), quote=source)
        return False
    # 先检查绑定群组没
    group_path = f'./data/battlefield/binds/groups/{group.id}'
    file_path = group_path + "/bfgroups.yaml"
    if not (os.path.exists(group_path) or os.path.isfile(file_path)):
        await app.send_message(group, MessageChain(
            f'请先绑定bf群组'
        ), quote=source)
        return False
    # 打开绑定的文件
    with open(file_path, 'r', encoding="utf-8") as file1:
        data = yaml.load(file1, yaml.Loader)
        try:
            bfgroups_name = data["bfgroups"]
        except:
            await app.send_message(group, MessageChain(
                f'未识别到群组，请重新绑定bf群组'
            ), quote=source)
    # 根据bf群组名字找到群组绑定服务器文件-获取vban配置
    group_path = f"./data/battlefield/binds/bfgroups/{bfgroups_name}"
    if not os.path.exists(group_path):
        await app.send_message(group, MessageChain(
            f"群组{bfgroups_name}不存在"
        ), quote=source)
        return False
    # 是否有vban的文件
    vban_file_path = f'./data/battlefield/binds/bfgroups/{bfgroups_name}/vban{vban_rank}.json'
    if not os.path.isfile(vban_file_path):
        await app.send_message(group, MessageChain(
            f"没有找到群组vban{vban_rank}文件,请先为群组创建vban"
        ), quote=source)
        return False
    else:
        with open(vban_file_path, 'r', encoding="utf-8") as file1:
            data = json.load(file1)
            if data is None:
                await app.send_message(group, MessageChain(
                    f"群组vban{vban_rank}配置为空,请先配置"
                ), quote=source)
                return False
            else:
                group_id = data["groupid"]
                token = data["token"]

    # 调用接口
    headers = {
        'accept': 'application/json',
        'token': token,
    }
    json_data = {
        'groupid': group_id,
        'reason': '%s' % reason,
        'playername': '%s' % str(player_name.result),
        'time': 0
    }
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post('https://manager-api.gametools.network/api/addautoban', headers=headers,
                                         json=json_data)
    except:
        await app.send_message(group, MessageChain(
            f"网络出错,请稍后再试!"
        ), quote=source)
        return False
    try:
        if "message" in eval(response.text):
            await app.send_message(group, MessageChain(
                f"vban封禁成功!原因:{reason}"
            ), quote=source)
            return True
        else:
            raise Exception("封禁出错")
    except Exception as e:
        logger.warning(e)
        try:
            result = eval(response.text)["error"]["code"]
            if result == -9960:
                if eval(response.text)["error"]["message"] == "Player already in autoban for this group":
                    await app.send_message(group, MessageChain(
                        f"该玩家已在vban"
                    ), quote=source)
                    return False
                elif eval(response.text)["error"]["message"] == "Player not found":
                    await app.send_message(group, MessageChain(
                        f"无效的玩家名字"
                    ), quote=source)
                    return False
                else:
                    error_message = eval(response.text)["error"]["message"]
                    await app.send_message(group, MessageChain(
                        f"token无效/参数错误\n错误信息:{error_message}"
                    ), quote=source)
                    return False
            elif result == -9900:
                try:
                    error_message = eval(response.text)["error"]["message"]
                    await app.send_message(group, MessageChain(
                        f"token无效/参数错误\n错误信息:{error_message}"
                    ), quote=source)
                    return False
                except:
                    await app.send_message(group, MessageChain(
                        f"token无效/参数错误"
                    ), quote=source)
                    return False
            else:
                await app.send_message(group, MessageChain(
                    f"该玩家已在vban"
                ), quote=source)
                return False
        except:
            await app.send_message(group, MessageChain(
                f"token出错或该玩家已在vban"
            ), quote=source)
            return False


# 减vban
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
            "action" @ UnionMatch("-unvban", "-uvb", "-减vban").space(
                SpacePolicy.NOSPACE),
            FullMatch("#", optional=True).space(SpacePolicy.NOSPACE),
            "vban_rank" @ ParamMatch(optional=False).space(SpacePolicy.FORCE),
            "player_name" @ ParamMatch(optional=False).space(SpacePolicy.PRESERVE),
            "reason" @ WildcardMatch(optional=True),
            # 示例: -unvban xiaoxiao test
        ]
    )
)
async def del_vban(app: Ariadne, group: Group, player_name: RegexResult, reason: RegexResult,
                   vban_rank: RegexResult, source: Source):
    if not reason.matched:
        reason = "解封"
    else:
        reason = str(reason.result)
    # 寻找vban配置
    try:
        vban_rank = int(str(vban_rank.result))
        if vban_rank < 1 or vban_rank > 10:
            raise Exception
        if vban_rank == 1:
            vban_rank = ''
    except:
        await app.send_message(group, MessageChain(
            "请检查vban序号:1~10"
        ), quote=source)
        return False
    # 先检查绑定群组没
    group_path = f'./data/battlefield/binds/groups/{group.id}'
    file_path = group_path + "/bfgroups.yaml"
    if not (os.path.exists(group_path) or os.path.isfile(file_path)):
        await app.send_message(group, MessageChain(
            f'请先绑定bf群组'
        ), quote=source)
        return False
    # 打开绑定的文件
    with open(file_path, 'r', encoding="utf-8") as file1:
        data = yaml.load(file1, yaml.Loader)
        try:
            bfgroups_name = data["bfgroups"]
        except:
            await app.send_message(group, MessageChain(
                f'未识别到群组，请重新绑定bf群组'
            ), quote=source)
    # 根据bf群组名字找到群组绑定服务器文件-获取vban配置
    group_path = f"./data/battlefield/binds/bfgroups/{bfgroups_name}"
    if not os.path.exists(group_path):
        await app.send_message(group, MessageChain(
            f"群组{bfgroups_name}不存在"
        ), quote=source)
        return False
    # 是否有vban的文件
    vban_file_path = f'./data/battlefield/binds/bfgroups/{bfgroups_name}/vban{vban_rank}.json'
    if not os.path.isfile(vban_file_path):
        await app.send_message(group, MessageChain(
            f"没有找到群组vban{vban_rank}文件,请先为群组创建vban"
        ), quote=source)
        return False
    else:
        with open(vban_file_path, 'r', encoding="utf-8") as file1:
            data = json.load(file1)
            if data is None:
                await app.send_message(group, MessageChain(
                    f"群组vban{vban_rank}配置为空,请先配置"
                ), quote=source)
                return False
            else:
                group_id = data["groupid"]
                token = data["token"]

    # 调用接口
    headers = {
        'accept': 'application/json',
        'token': token,
    }
    json_data = {
        'groupid': group_id,
        'reason': '%s' % reason,
        'playername': '%s' % str(player_name.result),
        'time': 0
    }
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post('https://manager-api.gametools.network/api/delautoban', headers=headers,
                                         json=json_data)
    except:
        await app.send_message(group, MessageChain(
            f"网络出错,请稍后再试!"
        ), quote=source)
        return False
    try:
        if "message" in eval(response.text):
            await app.send_message(group, MessageChain(
                f"vban解封成功!解封原因:{reason}"
            ), quote=source)
            return True
        else:
            raise Exception("解封出错")
    except Exception as e:
        logger.warning(e)
        try:
            result = eval(response.content.decode())["error"]["code"]
            if result == -9960:
                await app.send_message(group, MessageChain(
                    f"token无效/参数错误"
                ), quote=source)
                return False
            elif result == -9900:
                await app.send_message(group, MessageChain(
                    f"token无效/参数错误"
                ), quote=str)
                return False
            elif result == -9961:
                if eval(response.text)["error"]["message"] == "'id'":
                    await app.send_message(group, MessageChain(
                        f"无效的玩家名字"
                    ), quote=source)
                    return False
                else:
                    await app.send_message(group, MessageChain(
                        f"该玩家未在vban"
                    ), quote=source)
                    return False
            else:
                await app.send_message(group, MessageChain(
                    f"该玩家未在vban"
                ), quote=source)
                return False
        except:
            await app.send_message(group, MessageChain(
                f"token出错或该玩家未在vban"
            ), quote=source)
            return False


# vban列表
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
            "action" @ UnionMatch("-vbanlist", "-vban列表").space(SpacePolicy.NOSPACE),
            FullMatch("#", optional=True).space(SpacePolicy.NOSPACE),
            "vban_rank" @ ParamMatch(optional=False).space(SpacePolicy.PRESERVE),
            # 示例: -vbanlist#1
        ]
    )
)
async def get_vban_list(app: Ariadne, group: Group, vban_rank: RegexResult, source: Source):
    # 寻找vban配置
    try:
        vban_rank = int(str(vban_rank.result))
        if vban_rank < 1 or vban_rank > 10:
            raise Exception
        if vban_rank == 1:
            vban_rank = ''
    except:
        await app.send_message(group, MessageChain(
            "请检查vban序号:1~10"
        ), quote=source)
        return False
    # 先检查绑定群组没
    group_path = f'./data/battlefield/binds/groups/{group.id}'
    file_path = group_path + "/bfgroups.yaml"
    if not (os.path.exists(group_path) or os.path.isfile(file_path)):
        await app.send_message(group, MessageChain(
            f'请先绑定bf群组'
        ), quote=source)
        return False
    # 打开绑定的文件
    with open(file_path, 'r', encoding="utf-8") as file1:
        data = yaml.load(file1, yaml.Loader)
        try:
            bfgroups_name = data["bfgroups"]
        except:
            await app.send_message(group, MessageChain(
                f'未识别到群组，请重新绑定bf群组'
            ), quote=source)
    # 根据bf群组名字找到群组绑定服务器文件-获取vban配置
    group_path = f"./data/battlefield/binds/bfgroups/{bfgroups_name}"
    if not os.path.exists(group_path):
        await app.send_message(group, MessageChain(
            f"群组{bfgroups_name}不存在"
        ), quote=source)
        return False
    # 是否有vban的文件
    vban_file_path = f'./data/battlefield/binds/bfgroups/{bfgroups_name}/vban{vban_rank}.json'
    if not os.path.isfile(vban_file_path):
        await app.send_message(group, MessageChain(
            f"没有找到群组vban{vban_rank}文件,请先为群组创建vban"
        ), quote=source)
        return False
    else:
        with open(vban_file_path, 'r', encoding="utf-8") as file1:
            data = json.load(file1)
            if data is None:
                await app.send_message(group, MessageChain(
                    f"群组vban{vban_rank}配置为空,请先配置vban"
                ), quote=source)
                return False
            else:
                group_id = data["groupid"]
                token = data["token"]

    # 调用接口
    headers = {
        'accept': 'application/json',
        'token': token,
    }
    params = (
        ('groupid', group_id),
    )
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get('https://manager-api.gametools.network/api/autoban', headers=headers,
                                        params=params)
    except:
        await app.send_message(group, MessageChain(
            "网络出错请稍后再试!"
        ), quote=source)
        return False
    response = eval(response.text)
    if "error" in response:
        if response["error"]["code"] == -9900:
            if response["error"]["message"] == "permission denied":
                await app.send_message(group, MessageChain(
                    "token无效/参数错误"
                ), quote=source)
                return False
            else:
                await app.send_message(group, MessageChain(
                    "token无效/参数错误"
                ), quote=source)
                return False
        else:
            await app.send_message(group, MessageChain(
                f"错误代码:{response['error']['code']}\n"
                f"可能token无效/参数错误!"
            ), quote=source)
            return False
    vban_list = []
    vban_len = 0
    player_num = 0
    for item in response["data"]:
        temp = [f"名字:{item['playerName']}\n", f"Pid:{item['id']}\n"]
        # vban_len += 1
        try:
            temp.append(f"原因:{item['reason'].encode().decode()}\n")
        except Exception as e:
            logger.warning(e)
            pass
        temp.append(f"封禁来源:{item['admin']}\n")
        temp.append(f"封禁时间:{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(int(item['unixTimeStamp'])))}")
        # vban_len += 1
        vban_len += 1
        player_num += 1
        vban_list.append(temp)

    vban_list.reverse()
    sender_member = await app.get_member(group, app.account)
    fwd_nodeList = [ForwardNode(
        target=sender_member,
        time=datetime.now(),
        message=MessageChain(f"vban人数:{player_num}" if len(vban_list) < 100 else f"vban人数:{player_num}\n当前显示最新100条数据"),
    )]
    vban_list = vban_list[:100]
    for item in vban_list:
        fwd_nodeList.append(ForwardNode(
            target=sender_member,
            time=datetime.now(),
            message=MessageChain(item),
        ))
    message = MessageChain(Forward(nodeList=fwd_nodeList))
    try:
        await app.send_message(group, message)
    except Exception as e:
        await app.send_message(
            group,
            MessageChain(
                f"发送时出现一个错误:{e}"
            )
        )


# 换边
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
            "action" @ UnionMatch("-move", "-换边", "-挪").space(SpacePolicy.NOSPACE),
            FullMatch("#", optional=True).space(SpacePolicy.NOSPACE),
            "server_rank" @ ParamMatch(optional=False).space(SpacePolicy.FORCE),
            "player_name" @ ParamMatch(optional=False).space(SpacePolicy.PRESERVE),
            "team_index" @ ParamMatch(optional=True).space(SpacePolicy.PRESERVE),
            # 示例: -ub#1 xiaoxiao
        ]
    )
)
async def move_player(app: Ariadne, sender: Member, group: Group, action: RegexResult,
                      server_rank: RegexResult, player_name: RegexResult, team_index: RegexResult, source: Source):
    # 服务器序号检测
    try:
        server_rank = int(server_rank.result.display) - 1
        if server_rank < 0 or server_rank > 30:
            raise Exception
    except:
        await app.send_message(group, MessageChain(
            f"请检查服务器序号"
        ), quote=source)
        return False
    # 队伍序号检测
    if team_index.matched:
        try:
            team_index = int(team_index.result.display)
            if team_index not in [0, 1, 2]:
                raise Exception
        except:
            await app.send_message(group, MessageChain(
                f"请检查队伍序号(1/2)"
            ), quote=source)
            return False
    else:
        team_index = 0
    player_name = str(player_name.result)

    # 获取session
    session = await get_bfgroup_session(app, group, server_rank, source)
    if type(session) != str:
        return False
    # 获取服务器id信息
    id_dict = await get_bfgroup_ids(app, group, server_rank, source)
    if type(id_dict) != dict:
        return False
    else:
        server_id = id_dict["serverid"]
        server_gameid = id_dict["gameid"]
        # server_guid = id_dict["guid"]

    # 查验玩家存不存在
    try:
        player_info = await getPid_byName(player_name)
    except:
        await app.send_message(group, MessageChain(
            f"网络出错，请稍后再试"
        ), quote=source)
        return False
    if player_info['personas'] == {}:
        await app.send_message(group, MessageChain(
            f"玩家{player_name}不存在"
        ), quote=source)
        return False
    player_pid = player_info['personas']['persona'][0]['personaId']

    # 调用挪人的接口
    try:
        result = await api_gateway.rsp_movePlayer(server_gameid, session, int(player_pid), team_index)
    except:
        await app.send_message(group, MessageChain(
            f"网络出错,请稍后再试!"
        ), quote=source)
        return False
    if type(result) == str:
        if "成功" in result:
            await app.send_message(group, MessageChain(
                f"更换玩家队伍成功"
            ), quote=source)
            rsp_log.move_logger(sender.id, group.id, player_name, server_id)
            return True
        elif "获取玩家列表失败!" == result:
            await app.send_message(group, MessageChain(
                f"{result}请指定队伍序号(1/2)"
            ), quote=source)
            return False
        else:
            await app.send_message(group, MessageChain(
                result
            ), quote=source)
            return False
    else:
        await app.send_message(group, MessageChain(
            f"收到指令:({action.result})({server_rank})({player_name})\n但执行出错了"
            f"result:{result}"
        ), quote=source)
        return False


# 换图
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
            "action" @ UnionMatch("-换图", "-map", "-切图").space(SpacePolicy.NOSPACE),
            FullMatch("#", optional=True).space(SpacePolicy.NOSPACE),
            "server_rank" @ ParamMatch(optional=False).space(SpacePolicy.FORCE),
            "map_index" @ ParamMatch(optional=False).space(SpacePolicy.PRESERVE),
            # 示例: -换图#2 2
        ]
    )
)
async def change_map(app: Ariadne, sender: Member, group: Group, action: RegexResult,
                     server_rank: RegexResult, map_index: RegexResult, source: Source):
    if server_rank.result.display.startswith("list"):
        return
    # 服务器序号检测
    try:
        server_rank = int(str(server_rank.result)) - 1
    except:
        await app.send_message(group, MessageChain(
            f"请检查服务器序号"
        ), quote=source)
        return False
    # 获取session
    session = await get_bfgroup_session(app, group, server_rank, source)
    if type(session) != str:
        return False
    # 获取服务器id信息
    id_dict = await get_bfgroup_ids(app, group, server_rank, source)
    if type(id_dict) != dict:
        return False
    else:
        server_id = id_dict["serverid"]
        server_gameid = id_dict["gameid"]
        server_guid = id_dict["guid"]

    map_list = []
    try:
        map_index = int(str(map_index.result))
        if map_index == 2788:
            raise Exception
    except:
        # 识别是否为图池名字
        if map_index == 2788:
            map_index = "阿奇巴巴"
        else:
            map_index = map_index.result.display \
                .replace("垃圾厂", "法烏克斯要塞") \
                .replace("2788", "阿奇巴巴").replace("垃圾场", "法烏克斯要塞") \
                .replace("黑湾", "黑爾戈蘭灣").replace("海峡", "海麗絲岬") \
                .replace("噗噗噗山口", "武普库夫山口").replace("绞肉机", "凡爾登高地") \
                .replace("狙利西亞", "加利西亞").replace("沼气池", "法烏克斯要塞") \
                .replace("烧烤摊", "聖康坦的傷痕")
        map_index = zhconv.convert(map_index, 'zh-hk').replace("徵", "征").replace("託", "托")
        # 1.地图池
        result = await api_gateway.get_server_details(server_gameid)
        if type(result) == str:
            await app.send_message(group, MessageChain(
                f"获取图池出错!"
            ), quote=source)
            return False
        i = 0
        for item in result["rotation"]:
            map_list.append(f"{item['modePrettyName']}-{item['mapPrettyName']}")
            i += 1
        if map_index != "重開":
            map_index_list = []
            for map_temp in map_list:
                if map_index in map_temp:
                    if map_temp not in map_index_list:
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
                result = await api_gateway.rsp_changeMap(server_guid, session, map_index)
                if type(result) == str:
                    await app.send_message(group, MessageChain(
                        f"{result}"
                    ), quote=source)
                    return False
                elif type(result) == dict:
                    await app.send_message(group, MessageChain(
                        f"已更换服务器{server_rank + 1}地图为{map_list[int(map_index)][map_list[int(map_index)].find('-') + 1:]}"
                        f"".replace("\n", "").replace('流血', '流\u200b血')
                    ), quote=source)
                    rsp_log.map_logger(sender.id, group.id, map_list[int(map_index)].replace("-", " "), server_id)
                    return True
                else:
                    await app.send_message(group, MessageChain(
                        f"收到指令:({action.result})({server_rank})\n但执行出错了"
                    ), quote=source)
                    return False
            else:
                await app.send_message(group, MessageChain(
                    f"未识别到有效图池序号,退出换图"
                ), quote=source)
                return
        elif len(map_index_list) == 1:
            if type(map_index_list[0]) != int:
                map_index = map_list.index(map_index_list[0])
                # await app.send_message(group, MessageChain(
                #     f"匹配到的图池名:{map_index_list[0]}\n序号:{map_index}"
                # ), quote=source)
                # return
            else:
                map_index = map_index_list[0]
                # await app.send_message(group, MessageChain(
                #     f"匹配到的图池名:{map_list[map_index_list[0]]}\n序号:{map_index}"
                # ), quote=source)
                # return
        elif len(map_index_list) == 0:
            await app.send_message(group, MessageChain(
                f"匹配到0个选项,请输入更加精确的地图名或加上游戏模式名\n匹配名:{map_index}"
            ), quote=source)
            return False
        else:
            await app.send_message(group, MessageChain(
                f"这是一个bug(奇怪的bug增加了"
            ), quote=source)
            return False

    # 调用换图的接口
    await app.send_message(group, MessageChain(
        f"执行ing"
    ), quote=source)
    result = await api_gateway.rsp_changeMap(server_guid, session, map_index)
    if type(result) == str:
        await app.send_message(group, MessageChain(
            f"{result}"
        ), quote=source)
        return False
    elif type(result) == dict:
        if not map_list:
            await app.send_message(group, MessageChain(
                f"成功更换服务器{server_rank + 1}地图"
            ), quote=source)
            rsp_log.map_logger(sender.id, group.id, map_index, server_id)
            return True
        else:
            await app.send_message(group, MessageChain(
                f"成功更换服务器{server_rank + 1}地图为:{map_list[int(map_index)]}".replace('流血', '流\u200b血').replace('\n', '')
            ), quote=source)
            rsp_log.map_logger(sender.id, group.id,
                               map_list[int(map_index)][map_list[int(map_index)].find('#') + 1:].replace('-',
                                                                                                         ' ').replace(
                                   '\n', ''), server_id)
            return True
    else:
        await app.send_message(group, MessageChain(
            f"收到指令:({action.result})({server_rank + 1})\n但执行出错了"
        ), quote=source)
        return False


# 图池序号换图
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
            "action" @ UnionMatch("-图池", "-maplist", "-地图池").space(SpacePolicy.NOSPACE),
            FullMatch("#", optional=True).space(SpacePolicy.NOSPACE),
            "server_rank" @ ParamMatch(optional=False).space(SpacePolicy.PRESERVE),
            # 示例: -图池1
        ]
    )
)
async def change_map_byList(app: Ariadne, sender: Member, group: Group, action: RegexResult,
                            server_rank: RegexResult, source: Source):
    # 服务器序号检测
    try:
        server_rank = int(str(server_rank.result)) - 1
    except:
        await app.send_message(group, MessageChain(
            f"请检查服务器序号"
        ), quote=source)
        return False

    # 获取服务器id信息
    id_dict = await get_bfgroup_ids(app, group, server_rank, source)
    if type(id_dict) != dict:
        return False
    else:
        server_id = id_dict["serverid"]
        server_gameid = id_dict["gameid"]
        server_guid = id_dict["guid"]

    # 获取地图池
    result = await api_gateway.get_server_details(server_gameid)
    if isinstance(result, str):
        await app.send_message(group, MessageChain(
            f"获取图池时网络出错!"
        ), quote=source)
        return False
    map_list = []
    choices = []
    # for item in result["rotation"]:
    #     map_list.append(
    #         f"{i}#{item['modePrettyName']}-{item['mapPrettyName']}●\n".replace('流血', '流\u200b血')
    #         if (
    #                 item['modePrettyName'] == '行動模式'
    #                 and
    #                 item['mapPrettyName'] in
    #                 [
    #                     '聖康坦的傷痕', '窩瓦河',
    #                     '海麗絲岬', '法歐堡', '攻佔托爾', '格拉巴山',
    #                     '凡爾登高地', '加利西亞', '蘇瓦松', '流血宴廳', '澤布呂赫',
    #                     '索姆河', '武普庫夫山口', '龐然闇影'
    #                 ]
    #         )
    #         else f"{i}#{item['modePrettyName']}-{item['mapPrettyName']}\n".replace('流血', '流\u200b血')
    #     )
    #     choices.append(str(i))
    #     i += 1

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
    await app.send_message(
        group,
        MessageChain(
            GraiaImage(data_bytes=await OneMockUI.gen(
                GenForm(columns=map_list_column, color_type=get_color_type_follow_time())
            )),
            "\n请在45秒内‘发送’序号来进行换图"
        ),
        quote=source)

    # await app.send_message(group, MessageChain(
    #     "获取到图池:\n", map_list, "发送消息的人45秒内发送'#'前面的序号可更换地图,发送其他消息可退出"
    # ), quote=source)

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
        await app.send_message(group, MessageChain(
            f"执行ing"
        ), quote=source)
        # 获取session
        session = await get_bfgroup_session(app, group, server_rank, source)
        if type(session) != str:
            return False
        # 调用换图的接口
        result = await api_gateway.rsp_changeMap(server_guid, session, map_index)
        if type(result) == str:
            await app.send_message(group, MessageChain(
                f"{result}"
            ), quote=source)
            return False
        elif type(result) == dict:
            await app.send_message(group, MessageChain(
                f"已更换服务器{server_rank + 1}地图为:{map_list[int(map_index)][map_list[int(map_index)].find('#') + 1:]}".replace(
                    "\n", "").replace('流血', '流\u200b血')
            ), quote=source)
            rsp_log.map_logger(sender.id, group.id,
                               map_list[int(map_index)][map_list[int(map_index)].find('#') + 1:].replace('-',
                                                                                                         ' ').replace(
                                   '\n', ''), server_id)
            return True
        else:
            await app.send_message(group, MessageChain(
                f"收到指令:({action.result})({server_rank})\n但执行出错了"
            ), quote=source)
            return False
    else:
        return await app.send_message(group, MessageChain(
            f"未识别到有效图池序号,退出换图"
        ), quote=source)


def vip_file_bak(old_name):
    old_name = old_name
    index = old_name.rfind('.')
    if index > 0:
        # 提取后缀，这里提取不到，后面拼接新文件名字的时候就会报错
        postfix = old_name[index:]
    else:
        logger.error("备份出错!")
        return
    new_name = old_name[:index] + 'bak' + postfix
    # 备份文件写入数据
    old_f = open(old_name, 'rb')
    con = old_f.read()
    if len(con) == 0:  # 当没有内容备份时终止循环
        with open(new_name, 'r') as fr:  # 默认为 encoding='utf-8‘ 注意是否需要改为 encoding='gbk'等
            json_file = json.load(fr)
            if len(fr.read()) == 0:
                old_f = open(old_name, 'w+', encoding="utf-8")
                json.dump(json_file, old_f, indent=4, ensure_ascii=False)
                logger.success("已经自动还原失效vip文件!")
                return
            logger.error(f"{new_name}:vip文件失效!")
            return
    new_f = open(new_name, 'wb')
    new_f.write(con)
    # 关闭文件
    old_f.close()
    new_f.close()
    logger.success("备份文件成功")


# TODO: vip过程:1.根据guid找到服务器文件夹 2.如果文件夹没有vip.json文件就创建 3.读取fullInfo，从里面读取vip列表
#  4.写入info的信息到json 5.如果vip玩家在名单内就加时间 6.不在就调用接口
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
            "action" @ UnionMatch("-vip", "-v", "-加v", "-上v").space(
                SpacePolicy.NOSPACE),
            FullMatch("#", optional=True).space(SpacePolicy.NOSPACE),
            "server_rank" @ ParamMatch(optional=False).space(SpacePolicy.FORCE),
            "player_name" @ ParamMatch(optional=False).space(SpacePolicy.PRESERVE),
            "days" @ ParamMatch(optional=True).space(SpacePolicy.PRESERVE),
            # 示例: -vip#1 xiaoxiao 0
        ]
    )
)
async def add_vip(app: Ariadne, sender: Member, group: Group, action: RegexResult,
                  server_rank: RegexResult, player_name: RegexResult, days: RegexResult, source: Source):
    if server_rank.result.display.startswith("ban") or server_rank.result.display.startswith("b"):
        return
    # 服务器序号检测
    try:
        server_rank = int(str(server_rank.result)) - 1
        if server_rank < 0 or server_rank > 30:
            raise Exception
    except:
        await app.send_message(group, MessageChain(
            f"请检查服务器序号:1~30"
        ), quote=source)
        return False
    player_name = str(player_name.result).upper()

    # 获取session
    session = await get_bfgroup_session(app, group, server_rank, source)
    if type(session) != str:
        return False
    # 获取服务器id信息
    id_dict = await get_bfgroup_ids(app, group, server_rank, source)
    if type(id_dict) != dict:
        return False
    else:
        server_id = id_dict["serverid"]
        server_gameid = id_dict["gameid"]
        server_guid = id_dict["guid"]

    # 获取服务器信息-fullInfo
    try:
        server_fullInfo = await api_gateway.get_server_fulldetails(server_gameid)
        # logger.warning(server_fullInfo)
        if server_fullInfo == "":
            raise Exception
    except Exception as e:
        logger.error(e)
        await app.send_message(group, MessageChain(
            "获取服务器信息出现错误!"
        ), quote=source)
        return False
    # 获取服务器json文件,不存在就创建文件夹
    server_path = f"./data/battlefield/servers/{server_guid}"
    file_path = f"./data/battlefield/servers/{server_guid}/vip.json"
    if not os.path.exists(server_path):
        os.makedirs(server_path)
        vip_data = {}
        for item in server_fullInfo["rspInfo"]["vipList"]:
            vip_data[item["personaId"]] = {"displayName": item["displayName"], "days": "0000-00-00"}
        with open(f"{server_path}/vip.json", 'w', encoding="utf-8") as file1:
            json.dump(vip_data, file1, indent=4, ensure_ascii=False)
            await app.send_message(group, MessageChain(
                "初始化服务器文件成功!"
            ), quote=source)
    else:
        if not os.path.exists(file_path):
            vip_data = {}
            for item in server_fullInfo["rspInfo"]["vipList"]:
                vip_data[item["personaId"]] = {"displayName": item["displayName"], "days": "0000-00-00"}
            with open(f"{server_path}/vip.json", 'w', encoding="utf-8") as file1:
                json.dump(vip_data, file1, indent=4, ensure_ascii=False)
                await app.send_message(group, MessageChain(
                    "初始化服务器文件成功!"
                ), quote=source)

    vip_file_bak(file_path)

    vip_pid_list = {}
    for item in server_fullInfo["rspInfo"]["vipList"]:
        vip_pid_list[item["personaId"]] = item["displayName"]
    vip_name_list = {}
    for item in server_fullInfo["rspInfo"]["vipList"]:
        vip_name_list[item["displayName"].upper()] = item["personaId"]
    # 刷新本地文件,如果本地vip不在服务器vip位就删除,在的话就更新名字 如果服务器pid不在本地，就写入
    with open(f"{server_path}/vip.json", 'r', encoding="utf-8") as file1:
        # 服务器vip信息
        data1 = json.load(file1)
        # 刷新本地
        del_list = []
        for key in data1:
            if key not in vip_pid_list:
                del_list.append(key)
            else:
                data1[key]["displayName"] = vip_pid_list[key]
        for key in del_list:
            del data1[key]
        # 写入服务器的
        for pid in vip_pid_list:
            if pid not in data1:
                data1[pid] = {"displayName": vip_pid_list[pid], "days": "0000-00-00"}
        with open(f"{server_path}/vip.json", 'w', encoding="utf-8") as file2:
            json.dump(data1, file2, indent=4)

    # 如果为行动模式且人数为0，则添加失败
    if server_fullInfo["serverInfo"]["mapModePretty"] == "行動模式" and \
            server_fullInfo["serverInfo"]["slots"]["Soldier"]["current"] == 0:
        await app.send_message(group, MessageChain(
            "当前服务器为行动模式且人数为0,操作失败!"
        ), quote=source)
        return False
    if server_fullInfo["serverInfo"]["mapModePretty"] == "行動模式":
        server_mode = "\n(当前服务器为行动模式)"
    else:
        server_mode = ''
    # 如果在vip位就更新json文件,不在就调用接口,如果没有匹配到天数或为0,就改成永久，如果有天数就进行增加
    if player_name in vip_name_list:
        player_pid = vip_name_list[player_name]
        with open(f"{server_path}/vip.json", 'r', encoding="utf-8") as file1:
            # 服务器vip信息
            data1 = json.load(file1)
            # 如果没有匹配到天数或为0,就改成永久，如果有天数就进行增加
            if (not days.matched) or (str(days.result) == "0"):
                data1[player_pid]["days"] = "0000-00-00"
                with open(f"{server_path}/vip.json", 'w', encoding="utf-8") as file2:
                    json.dump(data1, file2, indent=4)
                    await app.send_message(group, MessageChain(
                        f"修改成功!到期时间:永久{server_mode}"
                    ), quote=source)
                    rsp_log.addVip_logger(sender.id, group.id, player_name, "永久", server_id)
                    return True
            else:
                try:
                    days = int(str(days.result))
                except:
                    await app.send_message(group, MessageChain(
                        "请检查输入的天数"
                    ), quote=source)
                    return False
                # 如果是0000则说明以前是永久
                if data1[player_pid]["days"] == "0000-00-00":
                    try:
                        data1[player_pid]["days"] = await add_day_vip(days,
                                                                      datetime.fromtimestamp(time.time()).strftime(
                                                                          "%Y-%m-%d"))
                    except:
                        await app.send_message(group, MessageChain(
                            f"添加日期出错!"
                        ), quote=source)
                        return False
                    if data1[player_pid]["days"] < datetime.fromtimestamp(time.time()).strftime("%Y-%m-%d"):
                        await app.send_message(group, MessageChain(
                            f"操作出错!目的日期小于今天日期\n目的日期:{data1[player_pid]['days']}"
                        ), quote=source)
                        return False
                    with open(f"{server_path}/vip.json", 'w', encoding="utf-8") as file2:
                        json.dump(data1, file2, indent=4)
                        await app.send_message(group, MessageChain(
                            f"修改成功!到期时间:{data1[player_pid]['days']}{server_mode}"
                        ), quote=source)
                        rsp_log.addVip_logger(sender.id, group.id, player_name, f"{days}天", server_id)
                        return True
                else:
                    try:
                        data1[player_pid]["days"] = await add_day_vip(days, data1[player_pid]["days"])
                    except:
                        await app.send_message(group, MessageChain(
                            f"添加日期出错!"
                        ), quote=source)
                        return False
                    if data1[player_pid]["days"] < datetime.fromtimestamp(time.time()).strftime("%Y-%m-%d"):
                        await app.send_message(group, MessageChain(
                            f"操作出错!目的日期小于今天日期\n目的日期:{data1[player_pid]['days']}"
                        ), quote=source)
                        return False
                    with open(f"{server_path}/vip.json", 'w', encoding="utf-8") as file2:
                        json.dump(data1, file2, indent=4)
                        await app.send_message(group, MessageChain(
                            f"修改成功!到期时间:{data1[player_pid]['days']}{server_mode}"
                        ), quote=source)
                        rsp_log.addVip_logger(sender.id, group.id, player_name, f"{days}天", server_id)
                        return True
    # 不在vip位的情况
    else:
        try:
            result = await api_gateway.rsp_addServerVip(server_id, session, player_name)
        except:
            await app.send_message(group, MessageChain(
                "网络出错!"
            ), quote=source)
            return False
        # 如果类型为
        if result == "玩家已在vip位":
            await app.send_message(group, MessageChain(
                "操作出错,未成功识别玩家信息!"
            ), quote=source)
            return False
        elif type(result) == str:
            if "已满" in result:
                await app.send_message(group, MessageChain(
                    "服务器vip位已满!"
                ), quote=source)
                return
            await app.send_message(group, MessageChain(
                result
            ), quote=source)
            return False
        # 字典就是成功的情况
        elif type(result) == dict:
            with open(f"{server_path}/vip.json", 'r', encoding="utf-8") as file1:
                # 服务器vip信息
                data1 = json.load(file1)
                i = 1
                while i <= 5:
                    try:
                        player_info = await getPid_byName(player_name)
                        break
                    except:
                        i += 1
                if i > 5:
                    await app.send_message(group, MessageChain(
                        f"成功添加玩家[{player_name}]vip但写入时间数据时出错!(比较罕见的情况)"
                    ), quote=source)
                    rsp_log.addVip_logger(sender.id, group.id, player_name, f"时间出错", server_id)
                    return True
                player_pid = player_info['personas']['persona'][0]['personaId']
                data1[player_pid] = {"displayName": player_name, "days": "0000-00-00"}
                # 写入配置
                # 如果没有匹配到天数或为0,就改成永久，如果有天数就进行增加
                if (not days.matched) or (str(days.result) == "0"):
                    data1[player_pid]["days"] = "0000-00-00"
                    with open(f"{server_path}/vip.json", 'w', encoding="utf-8") as file2:
                        json.dump(data1, file2, indent=4)
                        await app.send_message(group, MessageChain(
                            f"添加成功!到期时间:永久{server_mode}"
                        ), quote=source)
                        rsp_log.addVip_logger(sender.id, group.id, player_name, "永久", server_id)
                        return True
                else:
                    try:
                        days = int(str(days.result))
                    except:
                        await app.send_message(group, MessageChain(
                            "请检查输入的天数"
                        ), quote=source)
                        return False
                    try:
                        data1[player_pid]["days"] = await add_day_vip(days,
                                                                      datetime.fromtimestamp(time.time()).strftime(
                                                                          "%Y-%m-%d"))
                    except:
                        await app.send_message(group, MessageChain(
                            f"添加日期出错!"
                        ), quote=source)
                        return False
                    if data1[player_pid]["days"] < datetime.fromtimestamp(time.time()).strftime("%Y-%m-%d"):
                        await app.send_message(group, MessageChain(
                            f"操作出错!目的日期小于今天日期\n目的日期:{data1[player_pid]['days']}"
                        ), quote=source)
                        return False
                    with open(f"{server_path}/vip.json", 'w', encoding="utf-8") as file2:
                        json.dump(data1, file2, indent=4)
                        await app.send_message(group, MessageChain(
                            f"添加成功!到期时间:{data1[player_pid]['days']}{server_mode}"
                        ), quote=source)
                        rsp_log.addVip_logger(sender.id, group.id, player_name, f"{days}天", server_id)
                        return True
        else:
            await app.send_message(group, MessageChain(
                f"收到指令:({action.result})({server_rank})({player_name})({days.result})\n但执行出错了"
            ), quote=source)
            return False


# 移除vip
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
            "action" @ UnionMatch("-unvip", "-uv", "-删v", "-下v", "-减v").space(
                SpacePolicy.NOSPACE),
            FullMatch("#", optional=True).space(SpacePolicy.NOSPACE),
            "server_rank" @ ParamMatch(optional=False).space(SpacePolicy.FORCE),
            "player_name" @ ParamMatch(optional=False).space(SpacePolicy.PRESERVE)
            # 示例: -unvip#1 xiaoxiao
        ]
    )
)
async def del_vip(app: Ariadne, sender: Member, group: Group, action: RegexResult,
                  server_rank: RegexResult, player_name: RegexResult, source: Source):
    if server_rank.result.display.startswith("b"):
        return
    # 服务器序号检测
    try:
        server_rank = int(server_rank.result.display) - 1
        if server_rank < 0 or server_rank > 30:
            raise Exception
    except:
        await app.send_message(group, MessageChain(
            f"请检查服务器序号"
        ), quote=source)
        return False
    player_name = player_name.result.display

    # 查验玩家存不存在
    try:
        player_info = await getPid_byName(player_name)
    except Exception as e:
        logger.error(e)
        return await app.send_message(group, MessageChain(
            f"获取玩家信息出错，请稍后再试"
        ), quote=source)
    if player_info['personas'] == {}:
        await app.send_message(group, MessageChain(
            f"玩家{player_name}不存在"
        ), quote=source)
        return False
    player_pid = player_info['personas']['persona'][0]['personaId']

    # 获取session
    session = await get_bfgroup_session(app, group, server_rank, source)
    if type(session) != str:
        return False
    # 获取服务器id信息
    id_dict = await get_bfgroup_ids(app, group, server_rank, source)
    if type(id_dict) != dict:
        return False
    else:
        server_id = id_dict["serverid"]
        server_gameid = id_dict["gameid"]
        # server_guid = id_dict["guid"]

    # 获取服务器信息-fullInfo
    try:
        server_fullInfo = await api_gateway.get_server_fulldetails(server_gameid)
        if server_fullInfo == "":
            raise Exception
    except:
        await app.send_message(group, MessageChain(
            "获取服务器信息出现错误!"
        ), quote=source)
        return False
    # 如果为行动模式且人数为0，则删除失败
    if server_fullInfo["serverInfo"]["mapModePretty"] == "行動模式" and \
            server_fullInfo["serverInfo"]["slots"]["Soldier"][
                "current"] == 0:
        await app.send_message(group, MessageChain(
            "当前服务器为行动模式且人数为0,操作失败!"
        ), quote=source)
        return False

    # 调用删除vip的接口
    result = await api_gateway.rsp_removeServerVip(server_id, session, player_pid)
    if type(result) == str:
        await app.send_message(group, MessageChain(
            f"{result}"
        ), quote=source)
        return False
    elif type(result) == dict:
        await app.send_message(group, MessageChain(
            f"删除vip成功"
        ), quote=source)
        rsp_log.delVip_logger(sender.id, group.id, player_name, server_id)
        return True
    else:
        await app.send_message(group, MessageChain(
            f"收到指令:({action.result})({server_rank})({player_name})\n但执行出错了"
        ), quote=source)
        return False


# 清理过期vip
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
            "action" @ UnionMatch("-清v", "-清理vip", "-清vip").space(
                SpacePolicy.NOSPACE),
            FullMatch("#", optional=True).space(SpacePolicy.NOSPACE),
            "server_rank" @ ParamMatch(optional=False).space(SpacePolicy.PRESERVE)
            # 示例: -清v#1
        ]
    )
)
async def del_vip_timedOut(app: Ariadne, sender: Member, group: Group, server_rank: RegexResult,
                           source: Source):
    # 服务器序号检测
    try:
        server_rank = int(str(server_rank.result)) - 1
        if server_rank < 0 or server_rank > 30:
            raise Exception
    except:
        await app.send_message(group, MessageChain(
            f"请检查服务器序号"
        ), quote=source)
        return False

    # 获取session
    session = await get_bfgroup_session(app, group, server_rank, source)
    if type(session) != str:
        return False
    # 获取服务器id信息
    id_dict = await get_bfgroup_ids(app, group, server_rank, source)
    if type(id_dict) != dict:
        return False
    else:
        server_id = id_dict["serverid"]
        server_gameid = id_dict["gameid"]
        server_guid = id_dict["guid"]

    # 获取服务器信息-fullInfo
    try:
        server_fullInfo = await api_gateway.get_server_fulldetails(server_gameid)
        if server_fullInfo == "":
            raise Exception
    except:
        await app.send_message(group, MessageChain(
            "获取服务器信息出现错误!"
        ), quote=source)
        return False

    # 获取服务器json文件,不存在就创建文件夹
    server_path = f"./data/battlefield/servers/{server_guid}"
    file_path = f"./data/battlefield/servers/{server_guid}/vip.json"
    if not os.path.exists(server_path):
        os.makedirs(server_path)
        vip_data = {}
        for item in server_fullInfo["rspInfo"]["vipList"]:
            vip_data[item["personaId"]] = {"displayName": item["displayName"], "days": "0000-00-00"}
        with open(f"{server_path}/vip.json", 'w', encoding="utf-8") as file1:
            json.dump(vip_data, file1, indent=4, ensure_ascii=False)
            await app.send_message(group, MessageChain(
                "初始化服务器文件成功!"
            ), quote=source)
    else:
        if not os.path.exists(file_path):
            vip_data = {}
            for item in server_fullInfo["rspInfo"]["vipList"]:
                vip_data[item["personaId"]] = {"displayName": item["displayName"], "days": "0000-00-00"}
            with open(f"{server_path}/vip.json", 'w', encoding="utf-8") as file1:
                json.dump(vip_data, file1, indent=4, ensure_ascii=False)
                await app.send_message(group, MessageChain(
                    "初始化服务器文件成功!"
                ), quote=source)

    vip_pid_list = {}
    for item in server_fullInfo["rspInfo"]["vipList"]:
        vip_pid_list[item["personaId"]] = item["displayName"]
    vip_name_list = {}
    for item in server_fullInfo["rspInfo"]["vipList"]:
        vip_name_list[item["displayName"].upper()] = item["personaId"]
    # 刷新本地文件,如果本地vip不在服务器vip位就删除,在的话就更新名字 如果服务器pid不在本地，就写入
    with open(f"{server_path}/vip.json", 'r', encoding="utf-8") as file1:
        # 服务器vip信息
        data1 = json.load(file1)
        # 刷新本地
        del_list = []
        for key in data1:
            if key not in vip_pid_list:
                del_list.append(key)
            else:
                data1[key]["displayName"] = vip_pid_list[key]
        for key in del_list:
            del data1[key]
        # 写入服务器的
        for pid in vip_pid_list:
            if pid not in data1:
                data1[pid] = {"displayName": vip_pid_list[pid], "days": "0000-00-00"}
        with open(f"{server_path}/vip.json", 'w', encoding="utf-8") as file2:
            json.dump(data1, file2, indent=4)

    # 如果为行动模式且人数为0，则删除失败
    if server_fullInfo["serverInfo"]["mapModePretty"] == "行動模式" and \
            server_fullInfo["serverInfo"]["slots"]["Soldier"][
                "current"] == 0:
        await app.send_message(group, MessageChain(
            "当前服务器为行动模式且人数为0,操作失败!"
        ), quote=source)
        return False

    # 将过期的pid放进列表里面
    del_list = []
    with open(f"{server_path}/vip.json", 'r', encoding="utf-8") as file1:
        data1 = json.load(file1)
        for pid in data1:
            if data1[pid]["days"] != "0000-00-00":
                if await get_days_diff(data1[pid]["days"]) > 0:
                    del_list.append(pid)
    if len(del_list) == 0:
        await app.send_message(group, MessageChain(
            f"当前没有过期的vip哦"
        ), quote=source)
        return True
    else:
        await app.send_message(group, MessageChain(
            f"执行ing,预计移除{len(del_list)}个vip"
        ), quote=source)

    # 记录成功的，失败的
    success = 0
    fail = 0
    # 任务列表
    scrape_index_tasks = [asyncio.ensure_future(api_gateway.rsp_removeServerVip(server_id, session, item)) for item in
                          del_list]
    tasks = asyncio.gather(*scrape_index_tasks)
    await tasks
    result = []
    for i in scrape_index_tasks:
        result.append(i.result())
    i = 0
    for result_temp in result:
        # 先使用移除vip的接口，再处理vip.json文件
        if type(result_temp) == dict:
            with open(f"{server_path}/vip.json", 'r', encoding="utf-8") as file1:
                dict_temp = json.load(file1)
                del dict_temp[del_list[i]]
                with open(f"{server_path}/vip.json", 'w', encoding="utf-8") as file2:
                    json.dump(dict_temp, file2, indent=4)
                    success += 1
        else:
            fail += 1
        i += 1
    await app.send_message(group, MessageChain(
        f"清理完毕!成功:{success}个,失败:{fail}个"
    ), quote=source)
    rsp_log.checkVip_logger(sender.id, group.id, success, server_id)
    return True


# 自动清理征服vip
@channel.use(SchedulerSchema(timers.every_custom_hours(2)))  # 每小时执行一次
async def auto_del_vip_timedOut():
    groups_path = f"./data/battlefield/binds/bfgroups"
    group_list = os.listdir(groups_path)
    for group_item in group_list:
        # 如果有服管账号就去获取session
        with open(f'./data/battlefield/binds/bfgroups/{group_item}/servers.yaml', 'r', encoding="utf-8") as file1:
            data = yaml.load(file1, yaml.Loader)
            if data is None:
                continue
            else:
                for server in data["servers"]:
                    if server != "":
                        managerAccount = server["managerAccount"]
                        if not (managerAccount == '' or managerAccount is None):
                            # 获取id信息
                            server_id = server["serverid"]
                            server_gameid = server["gameid"]
                            server_guid = server["guid"]
                            # 根据服管账号获取session
                            account_pid = managerAccount
                            file_path = f'./data/battlefield/managerAccount'
                            account_list = os.listdir(file_path)
                            if len(account_list) == 0:
                                continue
                            if account_pid not in account_list:
                                continue
                            with open(f'{file_path}/{account_pid}/session.json', 'r', encoding="utf-8") as file2:
                                try:
                                    data1 = json.load(file2)
                                    session = data1["session"]
                                except:
                                    continue
                            # 获取服务器信息-fullInfo
                            try:
                                server_fullInfo = await api_gateway.get_server_fulldetails(server_gameid)
                                if server_fullInfo == "":
                                    raise Exception
                            except:
                                continue

                            # 获取服务器json文件,不存在就跳过循环
                            server_path = f"./data/battlefield/servers/{server_guid}"
                            file_path = f"./data/battlefield/servers/{server_guid}/vip.json"
                            if not os.path.exists(file_path):
                                continue

                            vip_pid_list = {}
                            for item in server_fullInfo["rspInfo"]["vipList"]:
                                vip_pid_list[item["personaId"]] = item["displayName"]
                            vip_name_list = {}
                            for item in server_fullInfo["rspInfo"]["vipList"]:
                                vip_name_list[item["displayName"].upper()] = item["personaId"]
                            # 刷新本地文件,如果本地vip不在服务器vip位就删除,在的话就更新名字 如果服务器pid不在本地，就写入
                            with open(f"{server_path}/vip.json", 'r', encoding="utf-8") as file3:
                                # 服务器vip信息
                                try:
                                    data1 = json.load(file3)
                                except Exception as e:
                                    logger.warning(f"清理群组{group_item}服务器{server_id}的vip出错:{e}")
                                    continue
                                # 刷新本地
                                del_list = []
                                for key in data1:
                                    if key not in vip_pid_list:
                                        del_list.append(key)
                                    else:
                                        data1[key]["displayName"] = vip_pid_list[key]
                                for key in del_list:
                                    del data1[key]
                                # 写入服务器的
                                for pid in vip_pid_list:
                                    if pid not in data1:
                                        data1[pid] = {"displayName": vip_pid_list[pid], "days": "0000-00-00"}
                                with open(f"{server_path}/vip.json", 'w', encoding="utf-8") as file2:
                                    json.dump(data1, file2, indent=4)

                            # 如果为行动模式且人数为0，则跳过
                            if server_fullInfo["serverInfo"]["mapModePretty"] == "行動模式":
                                logger.warning("识别到行动模式,已经自动跳过")
                                continue
                            logger.info(f"开始清理群组{group_item}服务器{server_id}的vip")
                            # 将过期的pid放进列表里面
                            del_list = []
                            with open(f"{server_path}/vip.json", 'r', encoding="utf-8") as file1_1:
                                data1 = json.load(file1_1)
                                for pid in data1:
                                    if data1[pid]["days"] != "0000-00-00":
                                        if await get_days_diff(data1[pid]["days"]) > 0:
                                            del_list.append(pid)
                            if len(del_list) == 0:
                                logger.info(f"群组{group_item}没有要清理的vip")
                                continue
                            else:
                                logger.info(f"预计移除群组{group_item}共{len(del_list)}个vip")
                            # 记录成功的，失败的
                            success = 0
                            fail = 0
                            # 任务列表
                            scrape_index_tasks = [
                                asyncio.ensure_future(api_gateway.rsp_removeServerVip(server_id, session, item)) for
                                item in
                                del_list]
                            tasks = asyncio.gather(*scrape_index_tasks)
                            await tasks
                            result = []
                            for i in scrape_index_tasks:
                                result.append(i.result())
                            i = 0
                            for result_temp in result:
                                # 先使用移除vip的接口，再处理vip.json文件
                                if type(result_temp) == dict:
                                    with open(f"{server_path}/vip.json", 'r', encoding="utf-8") as file1_1:
                                        dict_temp = json.load(file1_1)
                                        del dict_temp[del_list[i]]
                                        with open(f"{server_path}/vip.json", 'w', encoding="utf-8") as file2:
                                            json.dump(dict_temp, file2, indent=4)
                                            success += 1
                                else:
                                    fail += 1
                                i += 1
                            logger.success(f"清理群组{group_item}vip完毕!成功:{success}个,失败:{fail}个")


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
            "action" @ UnionMatch("-viplist", "-vip列表", "-vl").space(
                SpacePolicy.NOSPACE),
            FullMatch("#", optional=True).space(SpacePolicy.NOSPACE),
            "server_rank" @ ParamMatch(optional=False).space(SpacePolicy.PRESERVE)
            # 示例: -viplit#1
        ]
    )
)
async def get_vipList(app: Ariadne, group: Group, server_rank: RegexResult, source: Source):
    # 服务器序号检测
    try:
        server_rank = int(str(server_rank.result)) - 1
        if server_rank < 0 or server_rank > 30:
            raise Exception
    except:
        await app.send_message(group, MessageChain(
            f"请检查服务器序号"
        ), quote=source)
        return False
    # 获取服务器id信息
    id_dict = await get_bfgroup_ids(app, group, server_rank, source)
    if type(id_dict) != dict:
        return False
    else:
        # server_id = id_dict["serverid"]
        server_gameid = id_dict["gameid"]
        server_guid = id_dict["guid"]

    # 获取服务器信息-fullInfo
    try:
        server_fullInfo = await api_gateway.get_server_fulldetails(server_gameid)
        if server_fullInfo == "":
            raise Exception
    except:
        await app.send_message(group, MessageChain(
            "获取服务器信息出现错误!"
        ), quote=source)
        return False
    # 获取服务器json文件,不存在就创建文件夹
    server_path = f"./data/battlefield/servers/{server_guid}"
    file_path = f"./data/battlefield/servers/{server_guid}/vip.json"
    if not os.path.exists(server_path):
        os.makedirs(server_path)
        vip_data = {}
        for item in server_fullInfo["rspInfo"]["vipList"]:
            vip_data[item["personaId"]] = {"displayName": item["displayName"], "days": "0000-00-00"}
        with open(f"{server_path}/vip.json", 'w', encoding="utf-8") as file1:
            json.dump(vip_data, file1, indent=4, ensure_ascii=False)
            await app.send_message(group, MessageChain(
                "初始化服务器文件成功!"
            ), quote=source)
    else:
        if not os.path.exists(file_path):
            vip_data = {}
            for item in server_fullInfo["rspInfo"]["vipList"]:
                vip_data[item["personaId"]] = {"displayName": item["displayName"], "days": "0000-00-00"}
            with open(f"{server_path}/vip.json", 'w', encoding="utf-8") as file1:
                json.dump(vip_data, file1, indent=4, ensure_ascii=False)
                await app.send_message(group, MessageChain(
                    "初始化服务器文件成功!"
                ), quote=source)

    vip_file_bak(file_path)

    vip_pid_list = {}
    try:
        for item in server_fullInfo["rspInfo"]["vipList"]:
            vip_pid_list[item["personaId"]] = item["displayName"]
    except:
        await app.send_message(group, MessageChain(
            "接口出错,请稍后再试"
        ), quote=source)
        return
    vip_name_list = {}
    for item in server_fullInfo["rspInfo"]["vipList"]:
        vip_name_list[item["displayName"].upper()] = item["personaId"]
    # 刷新本地文件,如果本地vip不在服务器vip位就删除,在的话就更新名字 如果服务器pid不在本地，就写入
    with open(f"{server_path}/vip.json", 'r', encoding="utf-8") as file1:
        # 服务器vip信息
        try:
            data1 = json.load(file1)
        except:
            vip_file_bak(f"{server_path}/vip.json")
            await app.send_message(group, MessageChain(
                "已自动重新恢复失效数据, 请重试操作"
            ), quote=source)
            return
        # 刷新本地
        del_list = []
        for key in data1:
            if key not in vip_pid_list:
                del_list.append(key)
            else:
                data1[key]["displayName"] = vip_pid_list[key]
        for key in del_list:
            del data1[key]
        # 写入服务器的
        for pid in vip_pid_list:
            if pid not in data1:
                data1[pid] = {"displayName": vip_pid_list[pid], "days": "0000-00-00"}
        with open(f"{server_path}/vip.json", 'w', encoding="utf-8") as file2:
            json.dump(data1, file2, indent=4)
    # 重新读取vip
    vip_list = []
    with open(f"{server_path}/vip.json", 'r', encoding="utf-8") as file1:
        # 服务器vip信息
        data1 = json.load(file1)
        for pid in data1:
            if "days" not in data1[pid]:
                data1[pid]['days'] = data1[pid]['day']
                data1[pid].pop("day")
                with open(f"{server_path}/vip.json", 'w', encoding="utf-8") as file2:
                    json.dump(data1, file2, indent=4)
            if data1[pid]['days'] != '0000-00-00':
                if await get_days_diff(data1[pid]["days"]) > 0:
                    day_temp = f"{data1[pid]['days']}(已过期)"
                else:
                    day_temp = f"{data1[pid]['days']}"
            else:
                day_temp = f"永久"
            temp = f"名字:{data1[pid]['displayName']}\nPid:{pid}\n到期时间:{day_temp}"
            vip_list.append(temp)
    # 组合为转发消息
    vip_list = sorted(vip_list)
    vip_len = len(vip_list)
    sender_member = await app.get_member(group, app.account)
    fwd_nodeList = [ForwardNode(
        target=sender_member,
        time=datetime.now(),
        message=MessageChain("vip人数:%s" % vip_len),
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
            target=sender_member,
            time=datetime.now(),
            message=MessageChain(item),
        ))
    message = MessageChain(Forward(nodeList=fwd_nodeList))
    await app.send_message(group, message)


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
            "action" @ UnionMatch("-banlist", "-ban列表", "-bl").space(
                SpacePolicy.NOSPACE),
            FullMatch("#", optional=True).space(SpacePolicy.NOSPACE),
            "server_rank" @ ParamMatch(optional=False).space(SpacePolicy.PRESERVE)
            # 示例: -viplit#1
        ]
    )
)
async def get_banList(app: Ariadne, group: Group, server_rank: RegexResult, source: Source):
    # 服务器序号检测
    try:
        server_rank = int(str(server_rank.result)) - 1
        if server_rank < 0 or server_rank > 30:
            raise Exception
    except:
        await app.send_message(group, MessageChain(
            f"请检查服务器序号"
        ), quote=source)
        return False
    # 获取服务器id信息
    id_dict = await get_bfgroup_ids(app, group, server_rank, source)
    if type(id_dict) != dict:
        return False
    else:
        # server_id = id_dict["serverid"]
        server_gameid = id_dict["gameid"]
        # server_guid = id_dict["guid"]

    # 获取服务器信息-fullInfo
    try:
        server_fullInfo = await api_gateway.get_server_fulldetails(server_gameid)
        if server_fullInfo == "":
            raise Exception
    except:
        await app.send_message(group, MessageChain(
            "获取服务器信息出现错误!"
        ), quote=source)
        return False
    ban_list = []
    try:
        for item in server_fullInfo["rspInfo"]["bannedList"]:
            temp = f"名字:{item['displayName']}\nPid:{item['personaId']}\n"
            ban_list.append(temp)
    except:
        await app.send_message(group, MessageChain(
            "接口出错,请稍后再试"
        ), quote=source)
        return
    ban_list = sorted(ban_list)
    ban_len = len(ban_list)
    sender_member = await app.get_member(group, app.account)
    fwd_nodeList = [ForwardNode(
        target=sender_member,
        time=datetime.now(),
        message=MessageChain("ban位人数:%s" % ban_len),
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
            "action" @ UnionMatch("-adminlist", "-管理列表", "-al").space(
                SpacePolicy.NOSPACE),
            FullMatch("#", optional=True).space(SpacePolicy.NOSPACE),
            "server_rank" @ ParamMatch(optional=False).space(SpacePolicy.PRESERVE)
            # 示例: -viplit#1
        ]
    )
)
async def get_adminList(app: Ariadne, group: Group, server_rank: RegexResult, source: Source):
    # 服务器序号检测
    try:
        server_rank = int(str(server_rank.result)) - 1
        if server_rank < 0 or server_rank > 30:
            raise Exception
    except:
        await app.send_message(group, MessageChain(
            f"请检查服务器序号"
        ), quote=source)
        return False
    # 获取服务器id信息
    id_dict = await get_bfgroup_ids(app, group, server_rank, source)
    if type(id_dict) != dict:
        return False
    else:
        # server_id = id_dict["serverid"]
        server_gameid = id_dict["gameid"]
        # server_guid = id_dict["guid"]

    # 获取服务器信息-fullInfo
    try:
        server_fullInfo = await api_gateway.get_server_fulldetails(server_gameid)
        if server_fullInfo == "":
            raise Exception
    except:
        await app.send_message(group, MessageChain(
            "获取服务器信息出现错误!"
        ), quote=source)
        return False
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
        message=MessageChain("管理人数:%s" % admin_len),
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


def deal_duration(duration: int) -> str:
    """
    处理时长 example: 90 --> 00:01:30
    TODO 浮点数存在计算误差
    :param duration: int 时长 单位s
    :return: str '00:01:30'
    """
    hour = 3600
    minute = 60

    h_rest, h = math.modf(duration / hour)
    h = '%02d' % int(h)

    m_rest, m = math.modf(round(h_rest * minute, 6))
    m = '%02d' % int(m)

    s_rest, s = math.modf(m_rest * minute)
    s = '%02d' % int(s)

    ret = f'{h}小时{m}分{s}秒'

    return ret


# 全场最佳
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
            FullMatch("-全场最佳", optional=False).space(SpacePolicy.NOSPACE),
            FullMatch("#", optional=True).space(SpacePolicy.NOSPACE),
            "server_rank" @ ParamMatch(optional=False).space(SpacePolicy.PRESERVE),
            "sort" @ ParamMatch(optional=False).space(SpacePolicy.PRESERVE)
            # 示例: -全场最佳#1 时长
        ]
    )
)
async def get_best_player(app: Ariadne, group: Group,
                          server_rank: RegexResult, sort: RegexResult, source: Source):
    sort = sort.result.display
    sort_dict = {
        "时长": "timePlayed",
        "击杀": "kills",
        "死亡": "deaths",
        "胜场": "wins",
        "败场": "losses"
    }
    if sort not in ["时长", "击杀", "死亡", "胜场", "败场"]:
        await app.send_message(group, MessageChain(
            f"请检查查询类型\n仅支持:时长、击杀、死亡、胜场、败场\n"
            f"例如:-全场最佳#1 时长"
        ), quote=source)
        return False
    # 服务器序号检测
    try:
        server_rank = int(str(server_rank.result)) - 1
        if server_rank < 0 or server_rank > 30:
            raise Exception
    except:
        await app.send_message(group, MessageChain(
            f"请检查服务器序号"
        ), quote=source)
        return False
    # 获取服务器id信息
    id_dict = await get_bfgroup_ids(app, group, server_rank, source)
    if type(id_dict) != dict:
        return False
    else:
        # server_id = id_dict["serverid"]
        server_gameid = id_dict["gameid"]
        # server_guid = id_dict["guid"]

    # gtapi查询
    api_url = f"https://api.gametools.network/manager/leaderboard/?sort={sort_dict[sort]}&amount=2&gameid={server_gameid}"
    head = {
        "Connection": "Keep-Alive"
    }
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(api_url, headers=head, timeout=5)
    except:
        await app.send_message(group, MessageChain(
            f"网络超时,请稍后再试!"
        ), quote=source)
        return False
    response = eval(response.text)
    try:
        data = response["data"]
    except:
        await app.send_message(group, MessageChain(
            f"获取服务器信息出错!"
        ), quote=source)
        return False
    if len(data) == 0:
        await app.send_message(group, MessageChain(
            f"数据为空,请确保服务器已经接入了gt"
        ), quote=source)
        return False
    send = []
    for i, item in enumerate(data):
        temp = [
            f"{i + 1}:[{item['platoon']}]{item['name']}\n" if item['platoon'] != '' else f"{i + 1}:{item['name']}\n",
            f"击杀:{item['kills']} ", f"死亡:{item['deaths']} ", f"KD:{item['killDeath']}\n",
            f"胜场:{item['wins']} ", f"败场:{item['losses']} ", f"得分:{item['score']}\n",
            f"游玩时长:{deal_duration(item['timePlayed'])}\n",
            f"上次游玩:{item['timeStamp']}\n",
            "=" * 20 + "\n"
        ]
        send.append(temp)
    await app.send_message(group, MessageChain(
        send
    ), quote=source)


# 增加天数
async def add_day_vip(time_temp: int, time_before: str):
    """
    :param time_temp: 要增加的天数
    :param time_before: 原来的日期
    :return: 增加后的天数-str:2022-02-26
    """
    time_temp = time_temp * 3600 * 24 + int(time.mktime(time.strptime(time_before, "%Y-%m-%d")))
    time_after = datetime.fromtimestamp(time_temp).strftime("%Y-%m-%d")
    return time_after


# 比较今天和指定日期之间相差的天数
async def get_days_diff(time_temp: str):
    """
    :param time_temp: 指定比较的实际如:2022-5-12
    :return: int
    """
    # 获取今天的时间戳time_tempt
    nowTime_str = datetime.now().strftime('%Y-%m-%d')
    time1 = time.mktime(time.strptime(nowTime_str, '%Y-%m-%d'))
    time2 = time.mktime(time.strptime(time_temp, '%Y-%m-%d'))
    # 日期转化为int比较
    diff = (int(time1) - int(time2)) / 24 / 3600
    # print(diff)
    return diff


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
    # await app.send_message(group, MessageChain(
    #     f"'n'为服务器序号,注意指令空格\n",
    #     f"'#'现在已经改为选填\n",
    #     f"-服务器\n",
    #     f"-谁在玩#n\n",
    #     f"-adminlist#n\n",
    #     f"adnminlist=al=管理列表\n",
    #     f"-bf群组日志(qq号可选) 查日志\n",
    #     f"=" * 20, "\n",
    #     f"-refresh 刷新session\n",
    #     f"=" * 20, "\n",
    #     f"-k#n 玩家名字 原因(可省)(序号可选)\n",
    #     f"-k 玩家名字 原因(可省))\n",
    #     f"-sk 玩家名字 原因(可省)\n",
    #     f"-换边#n 玩家名字\n",
    #     f"k=kick=踢\n换边=挪=move\n",
    #     f"=" * 20, "\n",
    #     f"-v#n 玩家名字 天数\n(天数可选,不填为永久,可为负数)\n",
    #     f"-uv#n 玩家名字\n",
    #     f"-清v#n\n",
    #     f"-viplist#n\n",
    #     f"v=上v=vip=加v\nuv=unvip=下v=删v=减v\nviplist=vl=vip列表\n清v=清vip=清理vip\n",
    #     f"=" * 20, "\n",
    #     f"-b#n 玩家名字 原因(可省)\n",
    #     f"-ub#n 玩家名字\n",
    #     f"-banall 玩家名字 原因(可省)\n",
    #     f"-unbanall 玩家名字\n",
    #     f"-群组ban 玩家名字 这是群组ban->识别到进入服务器游玩的玩家才ban\n",
    #     f"-un群组ban 玩家名字 这是群组解封->整个群组的全部服务器解封一个玩家\n",
    #     f"-清ban#n (0~200,不填默认200)\n",
    #     f"-banlist#n\n",
    #     f"b=ban=封禁\nub=unban=解封\nbanlist=bl=ban列表\n清ban=清理ban位\n",
    #     f"=" * 20, "\n",
    #     f"-vban#n 玩家名字 原因(可省)\n",
    #     f"-unvban#n 玩家名字 原因(可省)\n",
    #     f"-vbanlist#n\n",
    #     f"vban=vb=加vban\nunvban=uvb=减vban\nvbanlist=vban列表\n",
    #     f"=" * 20, "\n",
    #     f"-换图#n <地图序号/地图名>\n",
    #     f"-图池#n\n",
    #     f"换图=切图=map\n地图池=图池=maplist\n",
    #     f"=" * 20, "\n",
    # ), quote=source)
    await app.send_message(group, MessageChain(
        GraiaImage(path="./data/battlefield/pic/menu/bf1服管.png"),
        "注意:\n1.'#'现在已经改为选填\n2.群组ban暂停"
    ), quote=source)


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
        f"bf群组操作:\n"
        f"-bf群组 新建/删除 组名\n"
        f"-bf群组列表\n"
        f"-bf群组 组名 绑服#n <gameid>\n"
        f"-bf群组 组名 解绑#n\n"
        f"-bf群组 组名 信息\n"
        f"-bf群组 组名 改名 <新组名>\n"
        f"-bf群组 组名 绑群 <群号>\n"
        f"-bf群组 组名#n 使用服管<pid>\n"
        f"-bf群组 组名 使用服管<pid> (全部绑定)\n"
        f"-bf群组 组名 解绑服管 (全部解绑)\n"
        f"-bf群组 组名 创建vban#n\n"
        f"-bf群组 组名 删除vban#n\n"
        f"-bf群组 组名 vban信息\n"
        f"-bf群组 组名 配置vban#n gid=<gid>,token=<token>\n"
        f"bf服管账号操作:\n"
        f"-bf服管账号列表\n"
        f"-bf服管账号 新建 <游戏名字>\n"
        f"-bf服管账号 删除 <pid>\n"
        f"-bf服管账号 <pid/name> 信息\n"
        f"-bf服管账号 登录 <pid> remid=<remid>,sid=<sid>"
    ), quote=source)


# # 自动刷新client
# @channel.use(SchedulerSchema(timers.every_custom_minutes(8)))
# async def auto_refresh_client1():
#     global client
#     # noinspection PyBroadException
#     try:
#         del client
#         client = httpx.AsyncClient(limits=limits)
#         logger.success("刷新bf1服管client1成功")
#     except Exception as e:
#         logger.error(f"刷新bf1服管client失败:{e}")


# 自动刷新client
@channel.use(SchedulerSchema(timers.every_custom_minutes(30)))
async def auto_refresh_client2():
    # noinspection PyBroadException
    try:
        await refresh_api_client()
        logger.success("刷新bf1服管api_client成功")
    except Exception as e:
        logger.error(f"刷新bf1服管api_client失败:{e}")
