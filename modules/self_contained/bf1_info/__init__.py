import asyncio
import datetime
import html
import json
import math
import os
import random
import time
from pathlib import Path
from typing import List, Tuple

import httpx
from creart import create
from graia.ariadne.app import Ariadne
from graia.ariadne.event.lifecycle import ApplicationLaunched
from graia.ariadne.event.message import GroupMessage, FriendMessage
from graia.ariadne.event.mirai import NudgeEvent
from graia.ariadne.message.chain import MessageChain
from graia.ariadne.message.element import Source, Image, At, ForwardNode, Forward
from graia.ariadne.message.parser.twilight import Twilight, UnionMatch, SpacePolicy, FullMatch, ParamMatch, \
    RegexResult, ArgumentMatch, ArgResult, WildcardMatch
from graia.ariadne.model import Group, Friend, Member
from graia.ariadne.util.interrupt import FunctionWaiter
from graia.ariadne.util.saya import listen, dispatch, decorate
from graia.saya import Channel, Saya
from graia.scheduler import timers
from graia.scheduler.saya.schema import SchedulerSchema
from loguru import logger
from rapidfuzz import fuzz
from zhconv import zhconv

from core.bot import Umaru
from core.config import GlobalConfig
from core.control import (
    Permission,
    Function,
    FrequencyLimitation,
    Distribute
)
from core.models import saya_model
from utils.bf1.bf_utils import (
    get_personas_by_name, check_bind, BTR_get_recent_info,
    bfeac_checkBan, bfban_checkBan, gt_checkVban, record_api,
    gt_get_player_id_by_pid, EACUtils, get_personas_by_player_pid, BattlefieldTracker
)
from utils.bf1.data_handle import WeaponData, VehicleData, ServerData
from utils.bf1.database import BF1DB
from utils.bf1.default_account import BF1DA
from utils.bf1.draw import PlayerStatPic, PlayerVehiclePic, PlayerWeaponPic, Exchange
from utils.bf1.gateway_api import api_instance
from utils.bf1.map_team_info import MapData

config = create(GlobalConfig)
core = create(Umaru)
module_controller = saya_model.get_module_controller()

saya = Saya.current()
channel = Channel.current()
channel.meta["name"] = ("Bf1Info")
channel.meta["description"] = ("战地一战绩查询")
channel.meta["author"] = ("十三")
channel.metadata = module_controller.get_metadata_from_path(Path(__file__))


# 当bot启动时自动检查默认账号信息
@listen(ApplicationLaunched)
async def check_default_account(app: Ariadne):
    logger.debug("正在检查默认账号信息")
    # 检查默认账号信息
    default_account_info = await BF1DA.read_default_account()
    if not default_account_info["pid"]:
        return await app.send_friend_message(
            config.Master,
            MessageChain("BF1默认查询账号信息不完整，请使用 '-设置默认账号 pid remid=xxx,sid=xxx' 命令设置默认账号信息")
        )
    # 登录默认账号
    account_instance = await BF1DA.get_api_instance()
    await account_instance.login(account_instance.remid, account_instance.sid)
    # 更新默认账号信息
    if account_info := await BF1DA.update_player_info():
        logger.debug("默认账号信息检查完毕")
        # 给Master发送提示
        return await app.send_friend_message(
            config.Master,
            MessageChain(
                f"BF1默认查询账号信息已更新，当前默认账号信息为：\n"
                f"display_name: {account_info['display_name']}\n"
                f"pid: {account_info['pid']}\n"
                f"session: {account_info['session']}"
            ),
        )
    else:
        logger.warning("默认账号信息更新失败")
        # 给Master发送提示
        return await app.send_friend_message(
            config.Master, MessageChain("BF1更新默认查询账号失败!")
        )


# 设置默认账号信息
@listen(FriendMessage)
@dispatch(
    Twilight(
        [
            FullMatch("-设置默认账号"),
            ParamMatch(optional=False).space(SpacePolicy.FORCE) @ "account_pid",
            FullMatch("remid=").space(SpacePolicy.NOSPACE),
            ParamMatch(optional=False).space(SpacePolicy.NOSPACE) @ "remid",
            FullMatch(",sid=").space(SpacePolicy.NOSPACE),
            ParamMatch(optional=False) @ "sid",
        ]
    )
)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module, 5),
    Permission.group_require(channel.metadata.level),
    Permission.user_require(Permission.BotAdmin),
)
async def set_default_account(
        app: Ariadne,
        sender: Friend,
        source: Source,
        account_pid: RegexResult,
        remid: RegexResult,
        sid: RegexResult
):
    # 如果pid不是数字,则返回错误信息
    account_pid = account_pid.result.display
    if not account_pid.isdigit():
        return await app.send_friend_message(
            sender,
            MessageChain("pid必须为数字"),
            quote=source
        )
    else:
        account_pid = int(account_pid)
    remid = remid.result.display
    sid = sid.result.display
    # 登录默认账号
    try:
        await app.send_friend_message(
            sender,
            MessageChain(f"正在登录默认账号{account_pid}"),
            quote=source
        )
        # 数据库写入默认账号信息
        await BF1DA.write_default_account(
            pid=account_pid,
            remid=remid,
            sid=sid
        )
        BF1DA.account_instance = api_instance.get_api_instance(account_pid)
        session = await (await BF1DA.get_api_instance()).login(remid=remid, sid=sid)
    except Exception as e:
        logger.error(e)
        return await app.send_friend_message(
            sender,
            MessageChain(f"登录默认账号{account_pid}失败，请检查remid和sid是否正确"),
            quote=source
        )
    if not isinstance(session, str):
        # 登录失败,返回错误信息
        return await app.send_friend_message(
            sender,
            MessageChain(f"登录默认账号{account_pid}失败，错误信息: {session}"),
            quote=source
        )
    logger.success(f"登录默认账号{account_pid}成功")
    # 登录成功,返回账号信息和session
    player_info = await (await BF1DA.get_api_instance()).getPersonasByIds(account_pid)
    # 如果pid不存在,则返回错误信息
    if isinstance(player_info, str) or not player_info.get("result"):
        return await app.send_message(
            sender,
            MessageChain(
                f"登录默认账号{account_pid}成功,但是pid不存在,请检查pid是否正确!!!\n"
                f"请在 utils/bf1/default_account.json 中修改默认账号的pid信息以保证账号的正常查询!"
            ),
            quote=source
        )
    displayName = f"{player_info['result'][str(account_pid)]['displayName']}"
    pid = f"{player_info['result'][str(account_pid)]['personaId']}"
    uid = f"{player_info['result'][str(account_pid)]['nucleusId']}"
    return await app.send_friend_message(
        sender,
        MessageChain(
            f"登录默认账号{account_pid}成功!\n"
            f"账号信息如下:\n"
            f"displayName: {displayName}\n"
            f"pid: {pid}\n"
            f"uid: {uid}\n"
            f"remid: {remid}\n"
            f"sid: {sid}\n"
            f"session: {session}"
        ),
        quote=source
    )


# 绑定
@listen(GroupMessage)
@dispatch(
    Twilight(
        [
            UnionMatch("-bind", "-绑定"),
            ParamMatch() @ "player_name",
        ]
    )
)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level),
    Permission.user_require(Permission.User),
)
async def bind(app: Ariadne, group: Group, source: Source, sender: Member, player_name: RegexResult):
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
    uid = player_info["personas"]["persona"][0]["pidId"]
    display_name = player_info["personas"]["persona"][0]["displayName"]
    # name = player_info["personas"]["persona"][0]["name"]
    # dateCreated = player_info["personas"]["persona"][0]["dateCreated"]
    # lastAuthenticated = player_info["personas"]["persona"][0]["lastAuthenticated"]
    # 进行比对，如果大写后的玩家名不一致，返回错误
    if player_name.upper() != display_name.upper():
        return await app.send_message(
            group,
            MessageChain(f"玩家 {player_name} 不存在"),
            quote=source
        )
    # 查询绑定信息，如果有旧id就获取旧id
    old_display_name = None
    old_pid = None
    old_uid = None
    if bind_info := await check_bind(sender.id):
        if isinstance(bind_info, str):
            return await app.send_message(
                group,
                MessageChain(f"查询出错!{bind_info}"),
                quote=source
            )
        old_display_name = bind_info.get("displayName")
        old_pid = bind_info.get("pid")
        old_uid = bind_info.get("uid")
    # 写入玩家绑定信息
    try:
        await BF1DB.bf1account.bind_player_qq(sender.id, pid)
        if old_display_name and (old_pid != pid):
            result = f"绑定ID变更!\n" \
                     f"displayName: {old_display_name}\n -> {display_name}\n" \
                     f"pid: {old_pid}\n -> {pid}\n" \
                     f"uid: {old_uid}\n -> {uid}"
        else:
            result = f"绑定成功!你的信息如下:\n" \
                     f"displayName: {display_name}\n" \
                     f"pid: {pid}\n" \
                     f"uid: {uid}"
        return await app.send_message(
            group,
            MessageChain(result),
            quote=source
        )
    except Exception as e:
        logger.error(e)
        return await app.send_message(
            group,
            MessageChain("绑定失败!"),
            quote=source
        )


# 查询玩家信息
@listen(GroupMessage)
@dispatch(
    Twilight(
        [
            UnionMatch("-info", "-信息"),
            ParamMatch(optional=True) @ "player_name",
        ]
    )
)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module, 5),
    Permission.group_require(channel.metadata.level),
    Permission.user_require(Permission.User),
)
async def info(
        app: Ariadne,
        group: Group,
        source: Source,
        sender: Member,
        player_name: RegexResult
):
    # 如果没有参数，查询绑定信息
    if not player_name.matched:
        if not (bind_info := await check_bind(sender.id)):
            return await app.send_message(
                group, MessageChain("你还没有绑定!请使用'-绑定 玩家名'进行绑定!"), quote=source
            )
        if isinstance(bind_info, str):
            return await app.send_message(
                group,
                MessageChain(f"查询出错!{bind_info}"),
                quote=source
            )
        display_name = bind_info.get("displayName")
        pid = bind_info.get("pid")
        uid = bind_info.get("uid")
        return await app.send_message(
            group,
            MessageChain(
                f"你的信息如下:\n"
                f"玩家名: {display_name}\n"
                f"pid: {pid}\n"
                f"uid: {uid}"
            ),
            quote=source
        )
    else:
        player_name = player_name.result.display
        if player_name.startswith("#"):
            player_pid = player_name[1:]
            if not player_pid.isdigit():
                return await app.send_message(group, MessageChain("pid必须为数字"), quote=source)
            else:
                player_pid = int(player_pid)
            player_info = await get_personas_by_player_pid(player_pid)
            if player_info is None:
                return await app.send_message(
                    group,
                    MessageChain(f"玩家 {player_name} 不存在"),
                    quote=source
                )
            if not isinstance(player_info, dict):
                return await app.send_message(group, MessageChain(f"查询出错!{player_info}"), quote=source)
            player_info["result"][str(player_pid)]["pidId"] = player_info["result"][str(player_pid)]["nucleusId"]
            dict_temp = {
                "personas": {
                    "persona": [player_info["result"][str(player_pid)]]
                }
            }
            player_info = dict_temp
        else:
            player_info = await get_personas_by_name(player_name)
        if player_info is None:
            return await app.send_message(
                group,
                MessageChain(f"玩家 {player_name} 不存在"),
                quote=source
            )
        elif not isinstance(player_info, dict):
            return await app.send_message(group, MessageChain(f"查询出错!{player_info}"), quote=source)

        pid = player_info["personas"]["persona"][0]["personaId"]
        uid = player_info["personas"]["persona"][0]["pidId"]
        display_name = player_info["personas"]["persona"][0]["displayName"]
        # name = player_info["personas"]["persona"][0]["name"]
        # dateCreated = player_info["personas"]["persona"][0]["dateCreated"]
        # lastAuthenticated = player_info["personas"]["persona"][0]["lastAuthenticated"]
        return await app.send_message(
            group,
            MessageChain(
                f"玩家名: {display_name}\n"
                f"pid: {pid}\n"
                f"uid: {uid}\n"
            ),
            quote=source
        )


# 查询战绩信息
@listen(GroupMessage)
@dispatch(
    Twilight(
        [
            UnionMatch("-s", "-stat", "-生涯", "-战绩").space(SpacePolicy.PRESERVE),
            ParamMatch(optional=True) @ "player_name",
            ArgumentMatch("-t", "-text", action="store_true", optional=True) @ "text",
        ]
    )
)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level),
    Permission.user_require(Permission.User),
)
async def player_stat_pic(
        app: Ariadne,
        sender: Member,
        group: Group,
        source: Source,
        player_name: RegexResult,
        text: ArgResult,
):
    # 如果没有参数，查询绑定信息,获取display_name
    if player_name.matched:
        player_name = player_name.result.display
        if player_name.startswith("#"):
            player_pid = player_name[1:]
            if not player_pid.isdigit():
                return await app.send_message(group, MessageChain("pid必须为数字"), quote=source)
            player_pid = int(player_pid)
            player_info = await get_personas_by_player_pid(player_pid)
            if player_info is None:
                return await app.send_message(
                    group,
                    MessageChain(f"玩家 {player_name} 不存在"),
                    quote=source
                )
            if not isinstance(player_info, dict):
                return await app.send_message(group, MessageChain(f"查询出错!{player_info}"), quote=source)
            player_info["result"][str(player_pid)]["pidId"] = player_info["result"][str(player_pid)]["nucleusId"]
            dict_temp = {
                "personas": {
                    "persona": [player_info["result"][str(player_pid)]]
                }
            }
            player_info = dict_temp
        else:
            player_info = await get_personas_by_name(player_name)
        if not player_info:
            return await app.send_message(
                group,
                MessageChain(f"玩家 {player_name} 不存在"),
                quote=source
            )
        if not isinstance(player_info, dict):
            return await app.send_message(
                group,
                MessageChain(f"查询出错!{player_info}"),
                quote=source
            )
        player_pid = player_info["personas"]["persona"][0]["personaId"]
        display_name = player_info["personas"]["persona"][0]["displayName"]
    elif bind_info := await check_bind(sender.id):
        if isinstance(bind_info, str):
            return await app.send_message(
                group,
                MessageChain(f"查询出错!{bind_info}"),
                quote=source
            )
        display_name = bind_info.get("displayName")
        player_pid = bind_info.get("pid")
    else:
        return await app.send_message(
            group, MessageChain("你还没有绑定!请使用'-绑定 玩家名'进行绑定!"), quote=source
        )
    await app.send_message(group, MessageChain("查询ing"), quote=source)

    # 并发获取生涯、武器、载具、正在游玩
    origin_start_time = start_time = time.time()
    tasks = [
        (await BF1DA.get_api_instance()).getPersonasByIds(player_pid),
        (await BF1DA.get_api_instance()).detailedStatsByPersonaId(player_pid),
        (await BF1DA.get_api_instance()).getWeaponsByPersonaId(player_pid),
        (await BF1DA.get_api_instance()).getVehiclesByPersonaId(player_pid),
        bfeac_checkBan(display_name),
        bfban_checkBan(player_pid),
        (await BF1DA.get_api_instance()).getServersByPersonaIds(player_pid),
        (await BF1DA.get_api_instance()).getActivePlatoon(player_pid),
        (await BF1DA.get_api_instance()).getPresetsByPersonaId(player_pid),
        gt_get_player_id_by_pid(player_pid)
    ]
    tasks = await asyncio.gather(*tasks)
    logger.debug(f"查询玩家战绩耗时: {round(time.time() - start_time)}秒")
    for task in tasks:
        if isinstance(task, str):
            logger.error(task)
            return await app.send_message(
                group,
                MessageChain(f"查询出错!{task}"),
                quote=source
            )

    # 检查返回结果
    (
        player_persona, player_stat, player_weapon, player_vehicle, bfeac_info, bfban_info,
        server_playing_info, platoon_info, skin_info, gt_id_info
    ) = tasks
    player_stat["result"]["displayName"] = display_name

    if not text.matched:
        # 生成图片
        start_time = time.time()
        player_stat_img = await PlayerStatPic(
            player_name=display_name,
            player_pid=player_pid,
            personas=player_persona,
            stat=player_stat,
            weapons=player_weapon,
            vehicles=player_vehicle,
            bfeac_info=bfeac_info,
            bfban_info=bfban_info,
            server_playing_info=server_playing_info,
            platoon_info=platoon_info,
            skin_info=skin_info,
            gt_id_info=gt_id_info
        ).draw()
        logger.debug(f"生成玩家战绩图片耗时: {round(time.time() - start_time)}秒")
        msg_chain = [Image(path=player_stat_img)]
        bfeac_info = (
            f'\nBFEAC状态:{bfeac_info.get("stat")}\n案件地址:{bfeac_info.get("url")}'
            if bfeac_info.get("stat")
            else None
        )
        if bfeac_info:
            msg_chain.append(bfeac_info)
        bfban_info = (
            f'\nBFBAN状态:{bfban_info.get("stat")}\n案件地址:{bfban_info.get("url")}'
            if bfban_info.get("stat")
            else None
        )
        if bfban_info:
            msg_chain.append(bfban_info)
        if player_stat_img:
            start_time = time.time()
            await app.send_message(group, MessageChain(msg_chain), quote=source)
            # 移除图片临时文件
            Path(player_stat_img).unlink()
            logger.debug(f"发送玩家战绩图片耗时: {round(time.time() - start_time)}秒")
            logger.debug(f"查询玩家战绩总耗时: {round(time.time() - origin_start_time)}秒")
            return
    # 发送文字
    # 包含等级、游玩时长、击杀、死亡、KD、胜局、败局、胜率、KPM、SPM、步战击杀、载具击杀、技巧值、最远爆头距离
    # 协助击杀、最高连杀、复活数、治疗数、修理数、狗牌数
    player_weapon: list = WeaponData(player_weapon).filter()
    player_vehicle: list = VehicleData(player_vehicle).filter()
    player_info = player_stat["result"]
    rank = player_info.get('basicStats').get('rank')
    rank_list = [
        0, 1000, 5000, 15000, 25000, 40000, 55000, 75000, 95000, 120000, 145000, 175000, 205000, 235000,
        265000, 295000, 325000, 355000, 395000, 435000, 475000, 515000, 555000, 595000, 635000, 675000, 715000,
        755000, 795000, 845000, 895000, 945000, 995000, 1045000, 1095000, 1145000, 1195000, 1245000, 1295000,
        1345000, 1405000, 1465000, 1525000, 1585000, 1645000, 1705000, 1765000, 1825000, 1885000, 1945000,
        2015000, 2085000, 2155000, 2225000, 2295000, 2365000, 2435000, 2505000, 2575000, 2645000, 2745000,
        2845000, 2945000, 3045000, 3145000, 3245000, 3345000, 3445000, 3545000, 3645000, 3750000, 3870000,
        4000000, 4140000, 4290000, 4450000, 4630000, 4830000, 5040000, 5260000, 5510000, 5780000, 6070000,
        6390000, 6730000, 7110000, 7510000, 7960000, 8430000, 8960000, 9520000, 10130000, 10800000, 11530000,
        12310000, 13170000, 14090000, 15100000, 16190000, 17380000, 20000000, 20500000, 21000000, 21500000,
        22000000, 22500000, 23000000, 23500000, 24000000, 24500000, 25000000, 25500000, 26000000, 26500000,
        27000000, 27500000, 28000000, 28500000, 29000000, 29500000, 30000000, 30500000, 31000000, 31500000,
        32000000, 32500000, 33000000, 33500000, 34000000, 34500000, 35000000, 35500000, 36000000, 36500000,
        37000000, 37500000, 38000000, 38500000, 39000000, 39500000, 40000000, 41000000, 42000000, 43000000,
        44000000, 45000000, 46000000, 47000000, 48000000, 49000000, 50000000
    ]
    # 转换成xx小时xx分钟
    time_seconds = player_info.get('basicStats').get('timePlayed')
    time_played = f"{time_seconds // 3600}小时{time_seconds % 3600 // 60}分钟"
    kills = player_info.get('basicStats').get('kills')
    deaths = player_info.get('basicStats').get('deaths')
    kd = round(kills / deaths, 2) if deaths else kills
    wins = player_info.get('basicStats').get('wins')
    losses = player_info.get('basicStats').get('losses')
    # 百分制
    win_rate = round(wins / (wins + losses) * 100, 2) if wins + losses else 100
    kpm = player_info.get('basicStats').get('kpm')
    spm = player_info.get('basicStats').get('spm')
    # 用spm / 60 * 游玩时间 得出经验值exp,看exp在哪个区间,可确定整数等级
    exp = spm * time_seconds / 60
    rank = 0
    for i in range(len(rank_list)):
        if exp <= rank_list[1]:
            rank = 0
            break
        if exp >= rank_list[-1]:
            rank = 150
            break
        if exp <= rank_list[i]:
            rank = i - 1
            break
    vehicle_kill = sum(item["killsAs"] for item in player_info["vehicleStats"])
    vehicle_kill = int(vehicle_kill)
    infantry_kill = int(player_info['basicStats']['kills'] - vehicle_kill)
    skill = player_info.get('basicStats').get('skill')
    longest_headshot = player_info.get('longestHeadShot')
    killAssists = int(player_info.get('killAssists'))
    highestKillStreak = int(player_info.get('highestKillStreak'))
    revives = int(player_info.get('revives'))
    heals = int(player_info.get('heals'))
    repairs = int(player_info.get('repairs'))
    dogtagsTaken = int(player_info.get('dogtagsTaken'))
    bfeac_info = (
        f'{bfeac_info.get("stat")}\n案件地址:{bfeac_info.get("url")}'
        if bfeac_info.get("stat")
        else "未查询到BFEAC信息"
    )
    bfban_info = (
        f'{bfban_info.get("stat")}\n案件地址:{bfban_info.get("url")}'
        if bfban_info.get("stat")
        else "未查询到BFBAN信息"
    )
    result = [
        f"玩家:{display_name}\n"
        f"等级:{rank}\n"
        f"游玩时长:{time_played}\n"
        f"击杀:{kills}  死亡:{deaths}  KD:{kd}\n"
        f"胜局:{wins}  败局:{losses}  胜率:{win_rate}%\n"
        f"KPM:{kpm}  SPM:{spm}\n"
        f"步战击杀:{infantry_kill}  载具击杀:{vehicle_kill}\n"
        f"技巧值:{skill}\n"
        f"最远爆头距离:{longest_headshot}米\n"
        f"协助击杀:{killAssists}  最高连杀:{highestKillStreak}\n"
        f"复活数:{revives}   治疗数:{heals}\n"
        f"修理数:{repairs}   狗牌数:{dogtagsTaken}\n"
        f"BFEAC状态:{bfeac_info}\n"
        f"BFBAN状态:{bfban_info}\n" + "=" * 18
    ]
    weapon = player_weapon[0]
    name = zhconv.convert(weapon.get('name'), 'zh-hans')
    kills = int(weapon["stats"]["values"]["kills"])
    seconds = weapon["stats"]["values"]["seconds"]
    kpm = "{:.2f}".format(kills / seconds * 60) if seconds != 0 else kills
    acc = (
        round(
            weapon["stats"]["values"]["hits"]
            / weapon["stats"]["values"]["shots"]
            * 100,
            2,
        )
        if weapon["stats"]["values"]["shots"] != 0
        else 0
    )
    hs = round(weapon["stats"]["values"]["headshots"] / weapon["stats"]["values"]["kills"] * 100, 2) \
        if weapon["stats"]["values"]["kills"] != 0 else 0
    eff = round(weapon["stats"]["values"]["hits"] / weapon["stats"]["values"]["kills"], 2) \
        if weapon["stats"]["values"]["kills"] != 0 else 0
    time_played = "{:.1f}H".format(seconds / 3600)
    result.append(
        f"最佳武器:{name}\n"
        f"击杀: {kills}\tKPM: {kpm}\n"
        f"命中率: {acc}%\t爆头率: {hs}%\n"
        f"效率: {eff}\t时长: {time_played}\n"
        + "=" * 18
    )

    vehicle = player_vehicle[0]
    name = zhconv.convert(vehicle["name"], 'zh-cn')
    kills = vehicle["stats"]["values"]["kills"]
    seconds = vehicle["stats"]["values"]["seconds"]
    kpm = "{:.2f}".format(kills / seconds * 60) if seconds != 0 else kills
    destroyed = vehicle["stats"]["values"]["destroyed"]
    time_played = "{:.1f}H".format(vehicle["stats"]["values"]["seconds"] / 3600)
    result.append(
        f"最佳载具:{name}\n"
        f"击杀:{kills}\tKPM:{kpm}\n"
        f"摧毁:{destroyed}\t时长:{time_played}\n"
        + "=" * 18
    )
    result = "\n".join(result)

    return await app.send_message(group, MessageChain(result), quote=source)


# 查询武器信息
@listen(GroupMessage)
@dispatch(
    Twilight(
        [
            FullMatch("-").space(SpacePolicy.NOSPACE),
            UnionMatch(
                "武器", "weapon", "wp", "精英兵", "机枪", "轻机枪", "步枪", "狙击枪", "装备", "配备",
                "半自动步枪", "半自动", "手榴弹", "手雷", "投掷物", "霰弹枪", "散弹枪", "驾驶员", "坦克驾驶员",
                "冲锋枪", "佩枪", "手枪", "近战", "突击兵", "土鸡兵", "土鸡", "突击",
                "侦察兵", "侦察", "斟茶兵", "斟茶", "医疗兵", "医疗", "支援兵", "支援"
            ).space(SpacePolicy.PRESERVE) @ "weapon_type",
            ParamMatch(optional=True) @ "player_name",
            ArgumentMatch("-r", "-row", "-行", optional=True, type=int, default=6) @ "row",
            ArgumentMatch("-c", "-col", "-列", optional=True, type=int, default=2) @ "col",
            ArgumentMatch("-n", "-name", optional=True) @ "weapon_name",
            ArgumentMatch("-s", "-sort", optional=True) @ "sort_type",
            ArgumentMatch("-t", "-text", action="store_true", optional=True) @ "text",
        ]
    )
)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level),
    Permission.user_require(Permission.User),
)
async def player_weapon_pic(
        app: Ariadne,
        sender: Member,
        group: Group,
        source: Source,
        player_name: RegexResult,
        weapon_type: RegexResult,
        row: ArgResult,
        col: ArgResult,
        weapon_name: ArgResult,
        sort_type: ArgResult,
        text: ArgResult,
):
    # 如果没有参数，查询绑定信息,获取display_name
    if player_name.matched:
        player_name = player_name.result.display
        if player_name.startswith("#"):
            player_pid = player_name[1:]
            if not player_pid.isdigit():
                return await app.send_message(group, MessageChain("pid必须为数字"), quote=source)
            player_pid = int(player_pid)
            player_info = await get_personas_by_player_pid(player_pid)
            if player_info is None:
                return await app.send_message(
                    group,
                    MessageChain(f"玩家 {player_name} 不存在"),
                    quote=source
                )
            if not isinstance(player_info, dict):
                return await app.send_message(group, MessageChain(f"查询出错!{player_info}"), quote=source)
            player_info["result"][str(player_pid)]["pidId"] = player_info["result"][str(player_pid)]["nucleusId"]
            dict_temp = {
                "personas": {
                    "persona": [player_info["result"][str(player_pid)]]
                }
            }
            player_info = dict_temp
        else:
            player_info = await get_personas_by_name(player_name)
        if not player_info:
            return await app.send_message(
                group,
                MessageChain(f"玩家 {player_name} 不存在"),
                quote=source
            )
        if not isinstance(player_info, dict):
            return await app.send_message(
                group,
                MessageChain(f"查询出错!{player_info}"),
                quote=source
            )
        player_pid = player_info["personas"]["persona"][0]["personaId"]
        display_name = player_info["personas"]["persona"][0]["displayName"]
    elif bind_info := await check_bind(sender.id):
        if isinstance(bind_info, str):
            return await app.send_message(
                group,
                MessageChain(f"查询出错!{bind_info}"),
                quote=source
            )
        display_name = bind_info.get("displayName")
        player_pid = bind_info.get("pid")
    else:
        return await app.send_message(
            group, MessageChain("你还没有绑定!请使用'-绑定 玩家名'进行绑定!"), quote=source
        )
    await app.send_message(group, MessageChain("查询ing"), quote=source)

    # 获取武器信息
    api_instance_temp = await BF1DA.get_api_instance()
    player_weapon_task = api_instance_temp.getWeaponsByPersonaId(player_pid)
    player_stat_task = api_instance_temp.detailedStatsByPersonaId(player_pid)
    player_persona_task = api_instance_temp.getPersonasByIds(player_pid)
    skin_info_task = api_instance_temp.getPresetsByPersonaId(player_pid)
    playing_info_task = api_instance_temp.getServersByPersonaIds(player_pid)
    gt_id_info_task = gt_get_player_id_by_pid(player_pid)
    player_stat, player_weapon, player_persona, skin_info, playing_info, gt_id_info = await asyncio.gather(
        player_stat_task,
        player_weapon_task,
        player_persona_task,
        skin_info_task,
        playing_info_task,
        gt_id_info_task
    )
    # 检查返回结果
    for task in [player_stat, player_weapon, player_persona, skin_info, playing_info, gt_id_info_task]:
        if isinstance(task, str):
            logger.error(task)
            return await app.send_message(
                group,
                MessageChain(f"查询出错!{task}"),
                quote=source
            )

    # 武器排序
    if not weapon_name.matched:
        player_weapon: list = WeaponData(player_weapon).filter(
            rule=weapon_type.result.display if weapon_type.matched else "",
            sort_type=sort_type.result.display if sort_type.matched else "",
        )
    else:
        weapon_name = weapon_name.result.display.strip("\"").strip("'")
        player_weapon: list = WeaponData(player_weapon).search_weapon(
            weapon_name,
            sort_type=sort_type.result.display if sort_type.matched else "",
        )
        if not player_weapon:
            return await app.send_message(
                group,
                MessageChain(f"没有找到武器[{weapon_name}]哦~"),
                quote=source
            )

    # 生成图片
    if not text.matched:
        player_weapon_img = await PlayerWeaponPic(
            player_name=display_name,
            player_pid=player_pid,
            personas=player_persona,
            stat=player_stat,
            weapons=player_weapon,
            skin_info=skin_info,
            server_playing_info=playing_info,
            gt_id_info=gt_id_info
        ).draw(col.result, row.result)
        if player_weapon_img:
            msg_chain = [Image(path=player_weapon_img)]
            await app.send_message(group, MessageChain(msg_chain), quote=source)
            # 移除图片临时文件
            Path(player_weapon_img).unlink()
            return

    # 发送文字数据
    result = [f"玩家: {display_name}\n" + "=" * 18]
    for weapon in player_weapon:
        if not weapon.get("stats").get('values'):
            continue
        name = zhconv.convert(weapon.get('name'), 'zh-hans')
        kills = int(weapon["stats"]["values"]["kills"])
        seconds = weapon["stats"]["values"]["seconds"]
        kpm = "{:.2f}".format(kills / seconds * 60) if seconds != 0 else kills
        acc = (
            round(
                weapon["stats"]["values"]["hits"]
                / weapon["stats"]["values"]["shots"]
                * 100,
                2,
            )
            if weapon["stats"]["values"]["shots"] != 0
            else 0
        )
        hs = round(weapon["stats"]["values"]["headshots"] / weapon["stats"]["values"]["kills"] * 100, 2) \
            if weapon["stats"]["values"]["kills"] != 0 else 0
        eff = round(weapon["stats"]["values"]["hits"] / weapon["stats"]["values"]["kills"], 2) \
            if weapon["stats"]["values"]["kills"] != 0 else 0
        time_played = "{:.1f}H".format(seconds / 3600)
        result.append(
            f"{name}\n"
            f"击杀: {kills}\tKPM: {kpm}\n"
            f"命中率: {acc}%\t爆头率: {hs}%\n"
            f"效率: {eff}\t时长: {time_played}\n"
            + "=" * 18
        )
    result = result[:5]
    result = "\n".join(result)
    return await app.send_message(
        group,
        MessageChain(
            result
        ),
        quote=source
    )


# 查询载具信息
@listen(GroupMessage)
@dispatch(
    Twilight(
        [
            FullMatch("-").space(SpacePolicy.NOSPACE),
            UnionMatch(
                "载具", "vehicle", "vc", "坦克", "地面", "飞机", "飞船", "飞艇", "空中", "海上", "定点", "巨兽", "机械巨兽"
            ).space(SpacePolicy.PRESERVE) @ "vehicle_type",
            ParamMatch(optional=True) @ "player_name",
            ArgumentMatch("-r", "-row", "-行", optional=True, type=int, default=6) @ "row",
            ArgumentMatch("-c", "-col", "-列", optional=True, type=int, default=2) @ "col",
            ArgumentMatch("-n", "-name", optional=True) @ "vehicle_name",
            ArgumentMatch("-s", "-sort", optional=True) @ "sort_type",
            ArgumentMatch("-t", "-text", action="store_true", optional=True) @ "text",
        ]
    )
)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level),
    Permission.user_require(Permission.User),
)
async def player_vehicle_pic(
        app: Ariadne,
        sender: Member,
        group: Group,
        source: Source,
        player_name: RegexResult,
        vehicle_type: RegexResult,
        row: ArgResult,
        col: ArgResult,
        vehicle_name: ArgResult,
        sort_type: ArgResult,
        text: ArgResult,
):
    # 如果没有参数，查询绑定信息,获取display_name
    if player_name.matched:
        player_name = player_name.result.display
        if player_name.startswith("#"):
            player_pid = player_name[1:]
            if not player_pid.isdigit():
                return await app.send_message(group, MessageChain("pid必须为数字"), quote=source)
            player_pid = int(player_pid)
            player_info = await get_personas_by_player_pid(player_pid)
            if player_info is None:
                return await app.send_message(
                    group,
                    MessageChain(f"玩家 {player_name} 不存在"),
                    quote=source
                )
            if not isinstance(player_info, dict):
                return await app.send_message(group, MessageChain(f"查询出错!{player_info}"), quote=source)
            player_info["result"][str(player_pid)]["pidId"] = player_info["result"][str(player_pid)]["nucleusId"]
            dict_temp = {
                "personas": {
                    "persona": [player_info["result"][str(player_pid)]]
                }
            }
            player_info = dict_temp
        else:
            player_info = await get_personas_by_name(player_name)
        if not player_info:
            return await app.send_message(
                group,
                MessageChain(f"玩家 {player_name} 不存在"),
                quote=source
            )
        if not isinstance(player_info, dict):
            return await app.send_message(
                group,
                MessageChain(f"查询出错!{player_info}"),
                quote=source
            )
        player_pid = player_info["personas"]["persona"][0]["personaId"]
        display_name = player_info["personas"]["persona"][0]["displayName"]
    elif bind_info := await check_bind(sender.id):
        if isinstance(bind_info, str):
            return await app.send_message(
                group,
                MessageChain(f"查询出错!{bind_info}"),
                quote=source
            )
        display_name = bind_info.get("displayName")
        player_pid = bind_info.get("pid")
    else:
        return await app.send_message(
            group, MessageChain("你还没有绑定!请使用'-绑定 玩家名'进行绑定!"), quote=source
        )
    await app.send_message(group, MessageChain("查询ing"), quote=source)

    # 获取载具信息
    api_instance_temp = await BF1DA.get_api_instance()
    player_vehicle_task = api_instance_temp.getVehiclesByPersonaId(player_pid)
    player_stat_task = api_instance_temp.detailedStatsByPersonaId(player_pid)
    player_persona_task = api_instance_temp.getPersonasByIds(player_pid)
    skin_info_task = api_instance_temp.getPresetsByPersonaId(player_pid)
    playing_info_task = api_instance_temp.getServersByPersonaIds(player_pid)
    gt_id_info_task = gt_get_player_id_by_pid(player_pid)
    player_stat, player_vehicle, player_persona, skin_info, playing_info, gt_id_info = await asyncio.gather(
        player_stat_task,
        player_vehicle_task,
        player_persona_task,
        skin_info_task,
        playing_info_task,
        gt_id_info_task
    )
    # 检查返回结果
    for task in [player_stat, player_vehicle, player_persona, skin_info, playing_info, gt_id_info_task]:
        if isinstance(task, str):
            logger.error(task)
            return await app.send_message(
                group,
                MessageChain(f"查询出错!{task}"),
                quote=source
            )

    # 载具排序
    if not vehicle_name.matched:
        player_vehicle: list = VehicleData(player_vehicle).filter(
            rule=vehicle_type.result.display if vehicle_type.matched else "",
            sort_type=sort_type.result.display if sort_type.matched else "",
        )
    else:
        vehicle_name = vehicle_name.result.display.strip("\"").strip("'")
        player_vehicle: list = VehicleData(player_vehicle).search_vehicle(
            target_vehicle_name=vehicle_name,
            sort_type=sort_type.result.display if sort_type.matched else "",
        )
        if not player_vehicle:
            return await app.send_message(
                group,
                MessageChain(f"没有找到载具[{vehicle_name}]哦~"),
                quote=source
            )

    # 生成图片
    if not text.matched:
        player_vehicle_img = await PlayerVehiclePic(
            player_name=display_name,
            player_pid=player_pid,
            personas=player_persona,
            stat=player_stat,
            vehicles=player_vehicle,
            skin_info=skin_info,
            server_playing_info=playing_info,
            gt_id_info=gt_id_info
        ).draw(col.result, row.result)
        if player_vehicle_img:
            msg_chain = [Image(path=player_vehicle_img)]
            await app.send_message(group, MessageChain(msg_chain), quote=source)
            # 移除图片临时文件
            Path(player_vehicle_img).unlink()
            return

    # 发送文字数据
    result = [f"玩家: {display_name}\n" + "=" * 18]
    for vehicle in player_vehicle:
        name = zhconv.convert(vehicle["name"], 'zh-cn')
        kills = int(vehicle["stats"]["values"]["kills"])
        seconds = vehicle["stats"]["values"]["seconds"]
        kpm = "{:.2f}".format(kills / seconds * 60) if seconds != 0 else kills
        destroyed = int(vehicle["stats"]["values"]["destroyed"])
        time_played = "{:.1f}H".format(vehicle["stats"]["values"]["seconds"] / 3600)
        result.append(
            f"{name}\n"
            f"击杀:{kills}\tKPM:{kpm}\n"
            f"摧毁:{destroyed}\t时长:{time_played}\n"
            + "=" * 18
        )
    result = result[:5]
    result = "\n".join(result)
    return await app.send_message(
        group,
        MessageChain(
            result
        ),
        quote=source
    )


# 最近数据
@listen(GroupMessage)
@dispatch(
    Twilight(
        [
            UnionMatch("-r", "-recent", "-最近").space(SpacePolicy.PRESERVE),
            ParamMatch(optional=True) @ "player_name",
        ]
    )
)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level),
    Permission.user_require(Permission.User),
)
async def player_recent_info(
        app: Ariadne,
        sender: Member,
        group: Group,
        source: Source,
        player_name: RegexResult
):
    # 如果没有参数，查询绑定信息,获取display_name
    if player_name.matched:
        player_name = player_name.result.display
        if player_name.startswith("#"):
            player_pid = player_name[1:]
            if not player_pid.isdigit():
                return await app.send_message(group, MessageChain("pid必须为数字"), quote=source)
            player_pid = int(player_pid)
            player_info = await get_personas_by_player_pid(player_pid)
            if player_info is None:
                return await app.send_message(
                    group,
                    MessageChain(f"玩家 {player_name} 不存在"),
                    quote=source
                )
            if not isinstance(player_info, dict):
                return await app.send_message(group, MessageChain(f"查询出错!{player_info}"), quote=source)
            player_info["result"][str(player_pid)]["pidId"] = player_info["result"][str(player_pid)]["nucleusId"]
            dict_temp = {
                "personas": {
                    "persona": [player_info["result"][str(player_pid)]]
                }
            }
            player_info = dict_temp
        else:
            player_info = await get_personas_by_name(player_name)
        if not player_info:
            return await app.send_message(
                group,
                MessageChain(f"玩家 {player_name} 不存在"),
                quote=source
            )
        if not isinstance(player_info, dict):
            return await app.send_message(
                group,
                MessageChain(f"查询出错!{player_info}"),
                quote=source
            )
        # player_pid = player_info["personas"]["persona"][0]["personaId"]
        display_name = player_info["personas"]["persona"][0]["displayName"]
    elif bind_info := await check_bind(sender.id):
        if isinstance(bind_info, str):
            return await app.send_message(
                group,
                MessageChain(f"查询出错!{bind_info}"),
                quote=source
            )
        display_name = bind_info.get("displayName")
        # player_pid = bind_info.get("pid")
    else:
        return await app.send_message(
            group, MessageChain("你还没有绑定!请使用'-绑定 玩家名'进行绑定!"), quote=source
        )
    await app.send_message(group, MessageChain("查询ing"), quote=source)

    # 从BTR获取数据
    try:
        player_recent = await BTR_get_recent_info(display_name)
        if not player_recent:
            return await app.send_message(
                group,
                MessageChain("没有查询到最近记录哦~"),
                quote=source
            )
        result = [f"玩家: {display_name}\n" + "=" * 15]
        result.extend(
            f"{item['time']}\n"
            f"得分: {item['score']}\nSPM: {item['spm']}\n"
            f"KD: {item['kd']}  KPM: {item['kpm']}\n"
            f"游玩时长: {item['time_play']}\n局数: {item['win_rate']}\n" + "=" * 15
            for item in player_recent[:3]
        )
        return await app.send_message(
            group,
            MessageChain("\n".join(result)),
            quote=source
        )
    except Exception as e:
        logger.error(e)
        return await app.send_message(
            group,
            MessageChain("查询出错!"),
            quote=source
        )


# 对局数据
@listen(GroupMessage)
@dispatch(
    Twilight(
        [
            UnionMatch("-match", "-对局").space(SpacePolicy.PRESERVE),
            ParamMatch(optional=True) @ "player_name",
        ]
    )
)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level),
    Permission.user_require(Permission.User),
)
async def player_match_info(
        app: Ariadne,
        sender: Member,
        group: Group,
        source: Source,
        player_name: RegexResult
):
    # 如果没有参数，查询绑定信息,获取display_name
    if player_name.matched:
        player_name = player_name.result.display
        if player_name.startswith("#"):
            player_pid = player_name[1:]
            if not player_pid.isdigit():
                return await app.send_message(group, MessageChain("pid必须为数字"), quote=source)
            player_pid = int(player_pid)
            player_info = await get_personas_by_player_pid(player_pid)
            if player_info is None:
                return await app.send_message(
                    group,
                    MessageChain(f"玩家 {player_name} 不存在"),
                    quote=source
                )
            if not isinstance(player_info, dict):
                return await app.send_message(group, MessageChain(f"查询出错!{player_info}"), quote=source)
            player_info["result"][str(player_pid)]["pidId"] = player_info["result"][str(player_pid)]["nucleusId"]
            dict_temp = {
                "personas": {
                    "persona": [player_info["result"][str(player_pid)]]
                }
            }
            player_info = dict_temp
        else:
            player_info = await get_personas_by_name(player_name)
        if not player_info:
            return await app.send_message(
                group,
                MessageChain(f"玩家 {player_name} 不存在"),
                quote=source
            )
        if not isinstance(player_info, dict):
            return await app.send_message(
                group,
                MessageChain(f"查询出错!{player_info}"),
                quote=source
            )
        player_pid = player_info["personas"]["persona"][0]["personaId"]
        display_name = player_info["personas"]["persona"][0]["displayName"]
    elif bind_info := await check_bind(sender.id):
        if isinstance(bind_info, str):
            return await app.send_message(
                group,
                MessageChain(f"查询出错!{bind_info}"),
                quote=source
            )
        display_name = bind_info.get("displayName")
        player_pid = bind_info.get("pid")
    else:
        return await app.send_message(group, MessageChain("你还没有绑定!请使用'-绑定 玩家名'进行绑定!"), quote=source)
    await app.send_message(group, MessageChain("查询ing"), quote=source)

    # 从BTR获取数据
    try:
        _ = await BattlefieldTracker.update_match_data(display_name, player_pid)
        player_match = await BattlefieldTracker.get_player_match_data(player_pid)
        if not player_match:
            return await app.send_message(
                group,
                MessageChain("没有查询到对局记录哦~"),
                quote=source
            )
        result = [f"玩家: {display_name}\n" + "=" * 15]
        # 处理数据
        # 按game_info['game_time']时间排序,game_info['game_time']是datetime类型
        player_match.sort(key=lambda x: x.get("game_info").get("game_time"), reverse=True)
        for match in player_match:
            game_info = match.get("game_info")
            player_data = match.get("player")
            map_name = game_info['map_name']
            player_data["team_name"] = f"Team{player_data['team_name']}" if player_data["team_name"] else "No Team"
            team_name = next(
                (
                    MapData.MapTeamDict.get(key).get(
                        player_data["team_name"], "No Team"
                    )
                    for key in MapData.MapTeamDict
                    if MapData.MapTeamDict.get(key).get("Chinese") == map_name
                ),
                "No Team",
            )
            # team_win是胜利队伍的id,如果为0则显示未结算，如果玩家的队伍id和胜利队伍id相同则显示🏆,否则显示🏳
            team_win = "未结算" if game_info["team_win"] == 0 else "🏆" \
                if player_data["team_name"] == game_info["team_win"] else "🏳"
            # 将游玩时间秒转换为 如果大于1小时则显示xxhxxmxxs,如果小于1小时则显示xxmxxs
            time_played = player_data["time_played"]
            result.append(
                f"服务器: {game_info['server_name'][:20]}\n"
                f"时间: {game_info['game_time'].strftime('%Y年%m月%d日-%H时%M分')}\n"
                f"地图: {game_info['map_name']}-{game_info['mode_name']}\n"
                f"队伍: {team_name}  {team_win}\n"
                f"击杀: {player_data['kills']}\t死亡: {player_data['deaths']}\n"
                f"KD: {player_data['kd']}\tKPM: {player_data['kpm']}\n"
                f"得分: {player_data['score']}\tSPM: {player_data['spm']}\n"
                f"命中率: {player_data['accuracy']}\t爆头: {player_data['headshots']}\n"
                f"游玩时长: {time_played}\n"
                + "=" * 15
            )
        result = result[:4]
        result = "\n".join(result)
        return await app.send_message(group, MessageChain(result), quote=source)
    except Exception as e:
        logger.error(e)
        return await app.send_message(
            group,
            MessageChain("查询出错!"),
            quote=source
        )


# 搜服务器
@listen(GroupMessage)
@dispatch(
    Twilight(
        [
            UnionMatch("-搜服务器", "-ss").space(SpacePolicy.PRESERVE),
            WildcardMatch(optional=True) @ "server_name",
        ]
    )
)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level),
    Permission.user_require(Permission.User),
)
async def search_server(
        app: Ariadne,
        group: Group,
        source: Source,
        server_name: RegexResult
):
    if (not server_name.matched) or (server_name.result.display == ""):
        return await app.send_message(group, MessageChain("请输入服务器名称!"), quote=source)
    else:
        server_name = server_name.result.display

    # 调用接口获取数据
    filter_dict = {"name": server_name}
    server_info = await (await BF1DA.get_api_instance()).searchServers(server_name, filter_dict=filter_dict)
    if isinstance(server_info, str):
        return await app.send_message(
            group,
            MessageChain(f"查询出错!{server_info}"),
            quote=source
        )
    else:
        server_info = server_info["result"]

    if not (server_list := ServerData(server_info).sort()):
        return await app.send_message(group, MessageChain("没有搜索到服务器哦~"), quote=source)
    result = []
    # 只显示前10个
    if len(server_list) > 10:
        result.append(f"搜索到{len(server_list)}个服务器,显示前10个\n" + "=" * 20)
        server_list = server_list[:10]
    else:
        result.append(f"搜索到{len(server_list)}个服务器\n" + "=" * 20)
    result.extend(
        f"{server.get('name')[:25]}\n"
        f"人数: {server.get('SoldierCurrent')}/{server.get('SoldierMax')}"
        f"[{server.get('QueueCurrent')}]({server.get('SpectatorCurrent')})\n"
        f"地图: {server.get('map_name')}-{server.get('mode_name')}\n"
        f"GameId: {server.get('game_id')}\n" + "=" * 20
        for server in server_list
    )
    result = "\n".join(result)
    return await app.send_message(
        group,
        MessageChain(result),
        quote=source
    )


# 详细服务器
@listen(GroupMessage)
@dispatch(
    Twilight(
        [
            UnionMatch("-详细服务器", "-ds").space(SpacePolicy.PRESERVE),
            ParamMatch(optional=False) @ "game_id",
        ]
    )
)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level),
    Permission.user_require(Permission.User),
)
async def detailed_server(
        app: Ariadne,
        group: Group,
        source: Source,
        game_id: RegexResult
):
    game_id = game_id.result.display
    if not game_id.isdigit():
        return await app.send_message(
            group,
            MessageChain("GameId必须为数字!"),
            quote=source
        )

    # 调用接口获取数据
    server_info = await (await BF1DA.get_api_instance()).getFullServerDetails(game_id)
    if isinstance(server_info, str):
        return await app.send_message(
            group,
            MessageChain(f"查询出错!{server_info}"),
            quote=source
        )
    else:
        server_info = server_info["result"]

    # 处理数据
    # 第一部分为serverInfo,其下:包含服务器名、简介、人数、地图、模式、gameId、guid、收藏数serverBookmarkCount
    # 第二部分为rspInfo,其下包含owner（名字和pid）、serverId、createdDate、expirationDate、updatedDate
    # 第三部分为platoonInfo，其下包含战队名、tag、人数、description
    result = []
    Info = server_info["serverInfo"]
    result.append(
        f"服务器名: {Info.get('name')}\n"
        f"当前人数: {Info.get('slots').get('Soldier').get('current')}/{Info.get('slots').get('Soldier').get('max')}"
        f"[{Info.get('slots').get('Queue').get('current')}]({Info.get('slots').get('Spectator').get('current')})\n"
        f"当前地图: {Info.get('mapNamePretty')}-{Info.get('mapModePretty')}\n"
        f"地图数量: {len(Info.get('rotation'))}\n"
        f"收藏: {Info.get('serverBookmarkCount')}\n"
        + "=" * 20 + "\n" +
        f"简介: {Info.get('description')}\n"
        f"GameId: {Info.get('gameId')}\n"
        f"Guid: {Info.get('guid')}\n"
        + "=" * 20
    )
    if rspInfo := server_info.get("rspInfo"):
        owner_info_str = ""
        if owner_info := rspInfo.get("owner"):
            owner_name = owner_info.get("displayName")
            owner_pid = owner_info.get("personaId")
            owner_info_str = f"服主名: {owner_name}\n服主Pid: {owner_pid}\n"
        result.append(
            f"ServerId:{rspInfo.get('server').get('serverId')}\n"
            f"创建时间: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(int(rspInfo['server']['createdDate']) / 1000))}\n"
            f"到期时间: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(int(rspInfo['server']['expirationDate']) / 1000))}\n"
            f"更新时间: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(int(rspInfo['server']['updatedDate']) / 1000))}\n"
            f"{owner_info_str}"
            f"管理数量: {len(rspInfo.get('adminList'))}/50\n"
            f"VIP数量: {len(rspInfo.get('vipList'))}/50\n"
            f"Ban数量: {len(rspInfo.get('bannedList'))}/200\n"
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


# 定时服务器详细信息收集，每60分钟执行一次
@channel.use(SchedulerSchema(timers.every_custom_minutes(60)))
async def server_info_collect():
    await update_server_info()


async def update_server_info():
    time_start = time.time()
    filter_dict = {
        "name": "",  # 服务器名
        "serverType": {  # 服务器类型
            "OFFICIAL": "off",  # 官服
            "RANKED": "on",  # 私服
            "UNRANKED": "on",  # 私服(不计战绩)
            "PRIVATE": "on"  # 密码服
        }
    }
    game_id_list = []
    tasks = [(await BF1DA.get_api_instance()).searchServers("", filter_dict=filter_dict) for _ in range(50)]
    logger.debug("开始更新私服数据")
    results = await asyncio.gather(*tasks)
    for result in results:
        if isinstance(result, str):
            continue
        result = result["result"]
        server_list = ServerData(result).sort()
        for server in server_list:
            if server["game_id"] not in game_id_list:
                game_id_list.append(server["game_id"])
    logger.success(f"共获取{len(game_id_list)}个私服")

    #   获取详细信息
    #   每250个私服分为一组获取详细信息
    tasks = []
    results = []
    for game_id in game_id_list:
        tasks.append((await BF1DA.get_api_instance()).getFullServerDetails(game_id))
        if len(tasks) == 250:
            logger.debug(f"开始获取私服详细信息，共{len(tasks)}个")
            temp = await asyncio.gather(*tasks)
            results.extend(temp)
            tasks = []
    if tasks:
        logger.debug(f"开始获取私服详细信息，共{len(tasks)}个")
        temp = await asyncio.gather(*tasks)
        results.extend(temp)

    results = [result for result in results if not isinstance(result, str)]
    logger.success(f"共获取{len(results)}个私服详细信息")

    #   整理数据
    serverId_list = []
    server_info_list: List[Tuple[str, str, str, int, datetime, datetime, datetime]] = []
    vip_dict = {}
    ban_dict = {}
    admin_dict = {}
    owner_dict = {}
    for result in results:
        server = result["result"]
        rspInfo = server.get("rspInfo", {})
        Info = server["serverInfo"]
        if not rspInfo:
            continue
        server_name = Info["name"]
        server_server_id = rspInfo.get("server", {}).get("serverId")
        server_guid = Info["guid"]
        server_game_id = Info["gameId"]
        serverBookmarkCount = Info["serverBookmarkCount"]
        playerCurrent = Info["slots"]["Soldier"]["current"]
        playerMax = Info["slots"]["Soldier"]["max"]
        playerQueue = Info["slots"]["Queue"]["current"]
        playerSpectator = Info["slots"]["Spectator"]["current"]
        mapName = Info["mapName"]
        mapNamePretty = Info["mapNamePretty"]
        mapMode = Info["mapMode"]
        mapModePretty = Info["mapModePretty"]

        #   将其转换为datetime
        createdDate = rspInfo.get("server", {}).get("createdDate")
        createdDate = datetime.datetime.fromtimestamp(int(createdDate) / 1000)
        expirationDate = rspInfo.get("server", {}).get("expirationDate")
        expirationDate = datetime.datetime.fromtimestamp(int(expirationDate) / 1000)
        updatedDate = rspInfo.get("server", {}).get("updatedDate")
        updatedDate = datetime.datetime.fromtimestamp(int(updatedDate) / 1000)
        server_info_list.append(
            (
                server_name, server_server_id,
                server_guid, server_game_id, serverBookmarkCount,
                createdDate, expirationDate, updatedDate,
                playerCurrent, playerMax, playerQueue, playerSpectator
            )
        )
        serverId_list.append(server_server_id)
        vip_dict[server_server_id] = rspInfo.get("vipList", [])
        ban_dict[server_server_id] = rspInfo.get("bannedList", [])
        admin_dict[server_server_id] = rspInfo.get("adminList", [])
        if owner := rspInfo.get("owner"):
            owner_dict[server_server_id] = [owner]

    #   保存数据
    start_time = time.time()
    await BF1DB.server.update_serverInfoList(server_info_list)
    logger.debug(f"更新服务器信息完成，耗时{round(time.time() - start_time, 2)}秒")
    start_time = time.time()
    await BF1DB.server.update_serverVipList(vip_dict)
    logger.debug(f"更新服务器VIP完成，耗时{round(time.time() - start_time, 2)}秒")
    start_time = time.time()
    await BF1DB.server.update_serverBanList(ban_dict)
    logger.debug(f"更新服务器封禁完成，耗时{round(time.time() - start_time, 2)}秒")
    await BF1DB.server.update_serverAdminList(admin_dict)
    start_time = time.time()
    logger.debug(f"更新服务器管理员完成，耗时{round(time.time() - start_time, 2)}秒")
    await BF1DB.server.update_serverOwnerList(owner_dict)
    logger.debug(f"更新服务器所有者完成，耗时{round(time.time() - start_time, 2)}秒")
    logger.success(f"共更新{len(serverId_list)}个私服详细信息，耗时{round(time.time() - time_start, 2)}秒")
    return len(serverId_list)


# 手动指令更新
@listen(GroupMessage)
@dispatch(
    Twilight(
        [
            UnionMatch("-更新服务器", "-ups").space(SpacePolicy.PRESERVE)
        ]
    )
)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level),
    Permission.user_require(Permission.BotAdmin),
)
async def update_server(app: Ariadne, group: Group, source: Source):
    await app.send_message(group, MessageChain("更新服务器信息ing"), quote=source)
    start_time = time.time()
    result = await update_server_info()
    end_time = time.time()
    time_cost = round(end_time - start_time, 2)
    if result:
        return await app.send_message(group, MessageChain(
                f"成功更新了{result}个服务器的信息!耗时{time_cost}秒"
            ), quote=source)
    return await app.send_message(group, MessageChain(f"更新失败!耗时{time_cost}秒"), quote=source)

# TODO 定时记录服务器人数曲线


# 天眼查
@listen(GroupMessage)
@dispatch(
    Twilight(
        [
            UnionMatch("-天眼查", "-tyc").space(SpacePolicy.PRESERVE),
            ParamMatch(optional=True) @ "player_name",
            ArgumentMatch("-a", "-admin", action="store_true", optional=True) @ "admin",
            ArgumentMatch("-v", "-vip", action="store_true", optional=True) @ "vip",
            ArgumentMatch("-b", "-ban", action="store_true", optional=True) @ "ban",
            ArgumentMatch("-o", "-owner", action="store_true", optional=True) @ "owner",
        ]
    )
)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level),
    Permission.user_require(Permission.User),
)
async def tyc(
        app: Ariadne,
        sender: Member,
        group: Group,
        source: Source,
        player_name: RegexResult,
        admin: ArgResult,
        vip: ArgResult,
        ban: ArgResult,
        owner: ArgResult,
):
    # 如果没有参数，查询绑定信息,获取display_name
    if not player_name.matched:
        if bind_info := await check_bind(sender.id):
            if isinstance(bind_info, str):
                return await app.send_message(
                    group,
                    MessageChain(f"查询出错!{bind_info}"),
                    quote=source
                )
            display_name = bind_info.get("displayName")
            player_pid = bind_info.get("pid")
        else:
            return await app.send_message(
                group,
                MessageChain(f"你还没有绑定!请使用'-绑定 玩家名'进行绑定!"),
                quote=source
            )
    else:
        player_name = player_name.result.display
        if player_name.startswith("#"):
            player_pid = player_name[1:]
            if not player_pid.isdigit():
                return await app.send_message(group, MessageChain("pid必须为数字"), quote=source)
            player_pid = int(player_pid)
            player_info = await get_personas_by_player_pid(player_pid)
            if player_info is None:
                return await app.send_message(
                    group,
                    MessageChain(f"玩家 {player_name} 不存在"),
                    quote=source
                )
            if not isinstance(player_info, dict):
                return await app.send_message(group, MessageChain(f"查询出错!{player_info}"), quote=source)
            player_info["result"][str(player_pid)]["pidId"] = player_info["result"][str(player_pid)]["nucleusId"]
            dict_temp = {
                "personas": {
                    "persona": [player_info["result"][str(player_pid)]]
                }
            }
            player_info = dict_temp
        else:
            player_info = await get_personas_by_name(player_name)
        if not player_info:
            return await app.send_message(
                group,
                MessageChain(f"玩家 {player_name} 不存在"),
                quote=source
            )
        if not isinstance(player_info, dict):
            return await app.send_message(
                group,
                MessageChain(f"查询出错!{player_info}"),
                quote=source
            )
        player_pid = player_info["personas"]["persona"][0]["personaId"]
        display_name = player_info["personas"]["persona"][0]["displayName"]

    await app.send_message(group, MessageChain(f"查询ing"), quote=source)

    # 如果admin/vip/ban/owner有一个匹配,就查询对应信息
    if admin.matched:
        adminServerList = await BF1DB.server.get_playerAdminServerList(player_pid)
        if not adminServerList:
            return await app.send_message(group, MessageChain(f"玩家{display_name}没有拥有admin哦~"), quote=source)
        fwd_nodeList = [
            ForwardNode(
                target=sender,
                time=datetime.datetime.now(),
                message=MessageChain(f"玩家{display_name}拥有{len(adminServerList)}个服务器的admin权限:"),
            )
        ]
        for serverName in adminServerList:
            fwd_nodeList.append(
                ForwardNode(
                    target=sender,
                    time=datetime.datetime.now(),
                    message=MessageChain(f"{serverName}"),
                )
            )
        return await app.send_message(group, MessageChain(Forward(nodeList=fwd_nodeList)))
    elif vip.matched:
        vipServerList = await BF1DB.server.get_playerVipServerList(player_pid)
        if not vipServerList:
            return await app.send_message(group, MessageChain(f"玩家{display_name}没有拥有vip哦~"), quote=source)
        fwd_nodeList = [
            ForwardNode(
                target=sender,
                time=datetime.datetime.now(),
                message=MessageChain(f"玩家{display_name}拥有{len(vipServerList)}个服务器的vip权限:"),
            )
        ]
        for serverName in vipServerList:
            fwd_nodeList.append(
                ForwardNode(
                    target=sender,
                    time=datetime.datetime.now(),
                    message=MessageChain(f"{serverName}"),
                )
            )
        return await app.send_message(group, MessageChain(Forward(nodeList=fwd_nodeList)))
    elif ban.matched:
        banServerList = await BF1DB.server.get_playerBanServerList(player_pid)
        if not banServerList:
            return await app.send_message(group, MessageChain(f"玩家{display_name}没有封禁信息哦~"), quote=source)
        fwd_nodeList = [
            ForwardNode(
                target=sender,
                time=datetime.datetime.now(),
                message=MessageChain(f"玩家{display_name}被{len(banServerList)}个服务器封禁了:"),
            )
        ]
        if len(banServerList) <= 200:
            for serverName in banServerList:
                fwd_nodeList.append(
                    ForwardNode(
                        target=sender,
                        time=datetime.datetime.now(),
                        message=MessageChain(f"{banServerList.index(serverName) + 1}.{serverName}"),
                    )
                )
        else:
            # 总长度超过200,则每m个合并为一个,m = len//200 + 1
            m = len(banServerList) // 200 + 1
            for i in range(0, len(banServerList), m):
                banServerListStr = ""
                for j in range(m):
                    if i + j < len(banServerList):
                        banServerListStr += f"{i + j + 1}.{banServerList[i + j]}\n"
                fwd_nodeList.append(
                    ForwardNode(
                        target=sender,
                        time=datetime.datetime.now(),
                        message=MessageChain(banServerListStr),
                    )
                )
        return await app.send_message(group, MessageChain(Forward(nodeList=fwd_nodeList)))
    elif owner.matched:
        ownerServerList = await BF1DB.server.get_playerOwnerServerList(player_pid)
        if not ownerServerList:
            return await app.send_message(group, MessageChain(f"玩家{display_name}未持有服务器哦~"), quote=source)
        fwd_nodeList = [
            ForwardNode(
                target=sender,
                time=datetime.datetime.now(),
                message=MessageChain(f"玩家{display_name}拥有{len(ownerServerList)}个服务器:"),
            )
        ]
        for serverName in ownerServerList:
            fwd_nodeList.append(
                ForwardNode(
                    target=sender,
                    time=datetime.datetime.now(),
                    message=MessageChain(f"{serverName}"),
                )
            )
        return await app.send_message(group, MessageChain(Forward(nodeList=fwd_nodeList)))

    send = [f'玩家名:{display_name}\n玩家Pid:{player_pid}\n' + "=" * 20 + '\n']
    # TODO: 添加账号注册和登录信息、重新整理消息格式
    # 查询最近游玩、vip/admin/owner/ban数、bfban信息、bfeac信息、正在游玩
    tasks = [
        (await BF1DA.get_api_instance()).mostRecentServers(player_pid),
        bfeac_checkBan(display_name),
        bfban_checkBan(player_pid),
        gt_checkVban(player_pid),
        record_api(player_pid),
        (await BF1DA.get_api_instance()).getServersByPersonaIds(player_pid),
        (await BF1DA.get_api_instance()).getActivePlatoon(player_pid),
        (await BF1DA.get_api_instance()).getPlatoons(player_pid),
    ]
    tasks = await asyncio.gather(*tasks)

    # 最近游玩
    recent_play_data = tasks[0]
    if isinstance(recent_play_data, dict):
        recent_play_data: dict = recent_play_data
        send.append("最近游玩:\n")
        for data in recent_play_data["result"][:3]:
            send.append(f'{data["name"][:25]}\n')
        send.append("=" * 20 + '\n')

    platoon_data = tasks[6]
    if isinstance(platoon_data, dict):
        platoon_data: dict = platoon_data
        if platoon_data["result"]:
            send.append("战排信息:\n")
            platoon_count_data = tasks[7]
            if isinstance(platoon_count_data, dict):
                platoon_count = len(platoon_count_data["result"])
                send.append(f"累计加入{platoon_count}个战排\n")
            tag = platoon_data["result"]["tag"]
            name = platoon_data["result"]["name"]
            size = platoon_data["result"]["size"]
            isFreeJoin = platoon_data["result"]["joinConfig"]["isFreeJoin"]
            description = platoon_data["result"]["description"]
            send.append(f"代表战排: [{tag}]{name}\n")
            send.append(f"人数: {size}\t是否开放加入: {'是' if isFreeJoin else '否'}\n")
            send.append(f"描述: {description}\n")
            send.append("=" * 20 + '\n')

    vip_count = await BF1DB.server.get_playerVip(player_pid)
    admin_count = await BF1DB.server.get_playerAdmin(player_pid)
    owner_count = await BF1DB.server.get_playerOwner(player_pid)
    ban_count = await BF1DB.server.get_playerBan(player_pid)
    vban_count = tasks[3]
    send.append(
        f"VIP数:{vip_count}\t"
        f"管理数:{admin_count}\n"
        f"BAN数:{ban_count}\t"
        f"服主数:{owner_count}\n"
        f"VBAN数:{vban_count}\n"
        + "=" * 20 + '\n'
    )

    # bfban信息
    bfban_data = tasks[2]
    if bfban_data.get("stat"):
        send.append("BFBAN信息:\n")
        send.append(
            f'状态:{bfban_data["status"]}\n' + f"案件地址:{bfban_data['url']}\n" if bfban_data.get("url") else "")
        send.append("=" * 20 + '\n')

    # bfeac信息
    bfeac_data = tasks[1]
    if bfeac_data.get("stat"):
        send.append("BFEAC信息:\n")
        send.append(
            f'状态:{bfeac_data["stat"]}\n'
            f'案件地址:{bfeac_data["url"]}\n'
        )
        send.append("=" * 20 + '\n')

    # 小助手标记信息
    record_data = tasks[4]
    if record_data and record_data.get("data"):
        browse = record_data["data"]["browse"]
        hacker = record_data["data"]["hacker"]
        doubt = record_data["data"]["doubt"]
        send.append("标记查询结果:\n")
        send.append(f"浏览量:{browse} ")
        send.append(f"外挂标记:{hacker} ")
        send.append(f"怀疑标记:{doubt}\n")
        send.append("=" * 20 + '\n')
    else:
        send.append("标记查询出错!\n")
        send.append("=" * 20 + '\n')

    # 正在游玩
    playing_data = tasks[5]
    if isinstance(playing_data, dict):
        playing_data = playing_data["result"]
        send.append("正在游玩:\n")
        if not playing_data[f"{player_pid}"]:
            send.append("玩家未在线/未进入服务器游玩\n")
        else:
            send.append(playing_data[f"{player_pid}"]['name'] + '\n')
        send.append("=" * 20 + '\n')

    # 去掉最后一个换行
    if send[-1].endswith("\n"):
        send[-1] = send[-1][:-1]
    return await app.send_message(group, MessageChain(f"{''.join(send)}"), quote=source)


# 举报到EAC，指令：-举报 玩家名
@listen(GroupMessage)
@dispatch(
    Twilight(
        [
            UnionMatch("-举报", "-report").space(SpacePolicy.PRESERVE),
            ParamMatch(optional=False) @ "player_name",
        ]
    )
)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level),
    Permission.user_require(Permission.GroupAdmin),
)
async def report(
        app: Ariadne, sender: Member, group: Group, source: Source,
        player_name: RegexResult,
):
    # 1.查询玩家是否存在
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
    player_name = display_name

    # 2.查验是否已经有举报信息
    check_eacInfo_url = f"https://api.bfeac.com/case/EAID/{player_name}"
    header = {
        "Connection": "Keep-Alive"
    }
    # noinspection PyBroadException
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(check_eacInfo_url, headers=header, timeout=10)
            response = response.json()
    except Exception as e:
        logger.error(e)
        await app.send_message(group, MessageChain(
            f"网络出错，请稍后再试"
        ), quote=source)
        return False
    if response["data"]:
        data = response["data"][0]
        case_id = data["case_id"]
        case_url = f"https://bfeac.com/#/case/{case_id}"
        await app.send_message(group, MessageChain(
            f"查询到已有案件信息如下:\n",
            case_url
        ), quote=source)
        return

    # 3.选择举报类型 1/5,其他则退出
    # report_type = 0
    # await app.send_message(group, MessageChain(
    #     f"请在10秒内发送举报的游戏:1"
    # ), quote=message[Source][0])
    #
    # async def waiter_report_type(waiter_member: Member, waiter_group: Group,
    #                              waiter_message: MessageChain):
    #     if waiter_member.id == sender.id and waiter_group.id == group.id:
    #         choices = ["1"]
    #         say = waiter_message.display
    #         if say in choices:
    #             return True, waiter_member.id, say
    #         else:
    #             return False, waiter_member.id, say
    #
    # try:
    #     result, operator, report_type = await FunctionWaiter(waiter_report_type, [GroupMessage],
    #                                                          block_propagation=True).wait(timeout=10)
    # except asyncio.exceptions.TimeoutError:
    #     await app.send_message(group, MessageChain(
    #         f'操作超时,请重新举报!'), quote=message[Source][0])
    #     return
    # if result:
    #     await app.send_message(group, MessageChain(
    #         f"已获取到举报的游戏:bf{report_type},请在30秒内发送举报的理由(不带图片)!"
    #     ), quote=message[Source][0])
    # else:
    #     await app.send_message(group, MessageChain(
    #         f"获取到举报的游戏:{report_type}无效的选项,已退出举报!"
    #     ), quote=message[Source][0])
    #     return False

    # 4.发送举报的理由
    # report_reason = None
    await app.send_message(group, MessageChain(
        f"注意:请勿随意、乱举报,否则将会撤销BOT的使用权!请在1分钟内发送举报的理由(请不要附带图片,发送`exit`取消举报)"
    ), quote=source)
    saying = None

    async def waiter_report_reason(
            waiter_member: Member, waiter_group: Group, waiter_message: MessageChain
    ):
        if waiter_member.id == sender.id and waiter_group.id == group.id:
            nonlocal saying
            saying = waiter_message
            return waiter_member.id, saying

    try:
        operator, report_reason = await FunctionWaiter(
            waiter_report_reason, [GroupMessage], block_propagation=True
        ).wait(timeout=60)
        # report_reason 要对html信息进行转义，防止别人恶意发送html信息,然后再转换为 <p>标签
        report_reason = report_reason.display
        report_reason = html.escape(report_reason)
        report_reason = f"<p>{report_reason}</p>"

    except asyncio.exceptions.TimeoutError:
        return await app.send_message(group, MessageChain(f'操作超时,请重新举报!'), quote=source)
    except Exception as e:
        logger.error(f"获取举报理由出错:{e}")
        return await app.send_message(group, MessageChain(f'获取举报理由出错,请重新举报!'), quote=source)

    saying: MessageChain = saying
    if saying.has(Image):
        return await app.send_message(group, MessageChain(
            f"举报理由请不要附带图片,已退出举报!"
        ), quote=source)

    # 进行预审核
    # pre_str = saying.display
    # logger.debug(pre_str)
    # if len(pre_str) < 500:
    #     await app.send_message(group, MessageChain(f'处理ing'), quote=source)
    #     pre_check_result = await EACUtils.report_precheck(pre_str)
    #     if not pre_check_result.get("valid"):
    #         pre_check_reason = pre_check_result.get("reason")
    #         return await app.send_message(group, MessageChain(
    #             f"举报理由未通过预审核!\n原因:{pre_check_reason}\n已退出举报!"
    #         ), quote=source)

    if saying.display.strip() == "exit":
        return await app.send_message(group, MessageChain(
            "已退出举报!"
        ), quote=source)
    await app.send_message(group, MessageChain(
        f"获取到举报理由:{saying.display}\n若需补充图片请在60秒内发送一张图片,无图片则发送'确认'以提交举报。\n(每次只能发送1张图片!)"
    ), quote=source)

    # 5.发送举报的图片,其他则退出
    list_pic = []
    if_confirm = False
    while not if_confirm:
        if len(list_pic) == 0:
            pass
        else:
            await app.send_message(group, MessageChain(
                f"收到{len(list_pic)}张图片,如需添加请继续发送图片,否则发送'确认'以提交举报。"
            ), quote=source)

        async def waiter_report_pic(
                waiter_member: Member, waiter_message: MessageChain, waiter_group: Group
        ) -> Tuple[bool, MessageChain]:
            nonlocal if_confirm  # 内部函数修改外部函数的变量
            waiter_message = waiter_message.replace(At(app.account), '')
            if group.id == waiter_group.id and waiter_member.id == sender.id:
                say = waiter_message.display
                if say == '[图片]' and waiter_message.has(Image):
                    return True, waiter_message
                elif say == "确认":
                    if_confirm = True
                    return True, waiter_message
                else:
                    return False, waiter_message

        try:
            result, img = await FunctionWaiter(
                waiter_report_pic, [GroupMessage], block_propagation=True
            ).wait(timeout=60)
        except asyncio.exceptions.TimeoutError:
            return await app.send_message(group, MessageChain(f'操作超时,已自动退出!'), quote=source)
        except Exception as e:
            logger.error(f"获取举报图片出错:{e}")
            return await app.send_message(group, MessageChain(f'获取举报图片出错,请重新举报!'), quote=source)

        if result:
            # 如果是图片则下载
            if img.display == '[图片]':
                try:
                    img_url = img[Image][0]
                    logger.debug(img_url)
                    img_url = img_url.url
                    headers = {
                        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_3) AppleWebKit/537.36 '
                                      '(KHTML, like Gecko) Chrome/85.0.4183.102 Safari/537.36'
                    }
                    # noinspection PyBroadException
                    try:
                        async with httpx.AsyncClient() as client:
                            response = await client.get(img_url, headers=headers, timeout=5)
                            r = response
                    except Exception as e:
                        logger.error(e)
                        await app.send_message(group, MessageChain(
                            f'获取图片出错,请重新举报!'
                        ), quote=source)
                        return False
                    # wb 以二进制打开文件并写入，文件名不存在会创
                    file_name = int(time.time())
                    file_path = f'./data/battlefield/Temp/{file_name}.png'
                    with open(file_path, 'wb') as f:
                        f.write(r.content)  # 写入二进制内容
                        f.close()

                    # 获取图床
                    image_api_option = config.functions.get("bf1", {}).get("image_api", "")
                    # TODO Use switch case to support more image API in future
                    # Use which image API by reading option in config
                    if image_api_option == "smms":
                        tc_url = "https://sm.ms/api/v2/upload?format=json"
                        tc_files = {'smfile': open(file_path, 'rb')}
                        image_apikey = config.functions.get("bf1", {}).get("image_apikey", "")
                        tc_headers = {
                            "Authorization": image_apikey
                        }
                        try:
                            async with httpx.AsyncClient() as client:
                                response = await client.post(tc_url, files=tc_files, headers=tc_headers)
                        except Exception as e:
                            logger.error(e)
                            await app.send_message(group, MessageChain(
                                f'获取图片图床失败,请重新举报!'
                            ), quote=source)
                            return False
                        json_temp = response.json()
                        response_data = json_temp["data"]

                        img_temp = f'<img class="img-fluid" src="{response_data["url"]}">'
                        report_reason += img_temp
                        list_pic.append(response_data['url'])
                    # Use BFEAC image API by default
                    else :
                        # tc_url = "https://www.imgurl.org/upload/aws_s3"
                        tc_url = "https://api.bfeac.com/inner_api/upload_image"
                        tc_files = {'file': open(file_path, 'rb')}
                        # tc_data = {'file': tc_files}
                        apikey = config.functions.get("bf1", {}).get("apikey", "")
                        tc_headers = {
                            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
                                          '(KHTML, like Gecko) Chrome/103.0.0.0 Safari/537.36',
                            "apikey": apikey
                        }
                        try:
                            async with httpx.AsyncClient() as client:
                                response = await client.post(tc_url, files=tc_files, headers=tc_headers)
                        except Exception as e:
                            logger.error(e)
                            await app.send_message(group, MessageChain(
                                f'获取图片图床失败,请重新举报!'
                            ), quote=source)
                            return False
                        json_temp = response.json()

                        # img_temp = f"<img src = '{json_temp['data']}' />"
                        img_temp = f'<img class="img-fluid" src="{json_temp["data"]}">'
                        report_reason += img_temp
                        list_pic.append(json_temp['data'])
                    # noinspection PyBroadException
                    try:
                        os.remove(file_path)
                    except Exception as e:
                        logger.error(e)
                        pass
                except Exception as e:
                    logger.error(response)
                    logger.error(e)
                    await app.send_message(group, MessageChain(
                        f'获取图片图床失败,请重新举报!'
                    ), quote=source)
                    return False
            # 是确认则提交
            if img.display == '确认':
                # 添加水印图片: https://s2.loli.net/2023/11/25/MpHD5Wbv9IqeVTa.png
                report_reason += '<img class="img-fluid" src="https://s2.loli.net/2023/11/25/MpHD5Wbv9IqeVTa.png">'
                await app.send_message(group, MessageChain(
                    f"提交举报ing"
                ), quote=source)
                # 调用接口
                report_result = await EACUtils.report_interface(
                    sender.id, player_name, report_reason, config.functions.get("bf1", {}).get("apikey", "")
                )
                if not isinstance(report_result, dict):
                    return await app.send_message(group, MessageChain(f"举报出错:{report_result}"), quote=source)
                if isinstance(report_result["data"], int):
                    file_path = Path(f"./data/battlefield/report_log/data.json")
                    if not file_path.exists():
                        file_path.touch()
                    try:
                        # 记录日志，包含举报人QQ，举报时间，案件ID，举报人所在群号，举报信息，被举报玩家的name、pid
                        with open(file_path, "r", encoding="utf-8") as file_read:
                            log_data = json.load(file_read)
                            log_data["data"].append(
                                {
                                    "time": time.time(),
                                    "operatorQQ": sender.id,
                                    "caseId": report_result['data'],
                                    "sourceGroupId": f"{group.id}",
                                    "reason": report_reason,
                                    "playerName": player_name,
                                    "playerPid": player_pid,
                                }
                            )
                            with open(file_path, "w", encoding="utf-8") as file_write:
                                json.dump(log_data, file_write, indent=4, ensure_ascii=False)
                    except Exception as e:
                        logger.error(f"日志出错:{e}")
                    await app.send_message(group, MessageChain(
                        f"举报成功!案件地址:https://bfeac.com/?#/case/{report_result['data']}"
                    ), quote=source)
                    return
                else:
                    await app.send_message(group, MessageChain(
                        f"举报结果:{report_result}"
                    ), quote=source)
                    return
        else:
            await app.send_message(group, MessageChain(
                f'未识成功别到图片,请重新举报!'
            ), quote=source)
            return


# 查询排名信息
@listen(GroupMessage)
@dispatch(
    Twilight(
        [
            UnionMatch("-bf1rank").space(SpacePolicy.PRESERVE),
            UnionMatch(
                "收藏", "bookmark", "vip", "ban", "admin", "owner", "管理", "服主", "封禁", optional=False
            ).space(SpacePolicy.PRESERVE) @ "rank_type",
            ArgumentMatch("-p", "-page", optional=True, type=int, default=1) @ "page",
            ArgumentMatch("-n", "-name", optional=True, type=str) @ "name",
        ]
    )
)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level),
    Permission.user_require(Permission.User),
)
async def BF1Rank(
        app: Ariadne, group: Group,
        rank_type: RegexResult, page: ArgResult, name: ArgResult, source: Source
):
    rank_type = rank_type.result.display
    page = page.result
    await app.send_message(group, MessageChain(f"查询ing"), quote=source)
    if not name.matched:
        if rank_type in ["收藏", "bookmark"]:
            bookmark_list = await BF1DB.server.get_server_bookmark()
            if not bookmark_list:
                return await app.send_message(group, MessageChain(f"没有在数据库中找到服务器收藏信息!"), quote=source)
            # 将得到的数据15个一页分组，如果page超出范围则返回错误,否则返回对应页的数据
            if page > math.ceil(len(bookmark_list) / 15):
                return await app.send_message(
                    group,
                    MessageChain(f"超出范围!({page}/{math.ceil(len(bookmark_list) / 15)})"),
                    quote=source
                )
            send = [
                f"服务器收藏排名(page:{page}/{math.ceil(len(bookmark_list) / 15)})",
            ]
            for data in bookmark_list[(page - 1) * 15:page * 15]:
                # 获取服务器排名,组合为: index. serverName[:20] bookmark
                index = bookmark_list.index(data) + 1
                send.append(f"{index}.{data['serverName'][:20]} {data['bookmark']}")
            send = "\n".join(send)
            return await app.send_message(group, MessageChain(f"{send}"), quote=source)
        elif rank_type in ["vip"]:
            vip_list = await BF1DB.server.get_allServerPlayerVipList()
            if not vip_list:
                return await app.send_message(group, MessageChain(f"没有在数据库中找到服务器VIP信息!"), quote=source)
            # 将得到的数据15个一页分组，如果page超出范围则返回错误,否则返回对应页的数据
            # data = [
            #     {
            #         "pid": 123,
            #         "displayName": "xxx",
            #         "server_list": []
            #     }
            # ]
            if page > math.ceil(len(vip_list) / 15):
                return await app.send_message(
                    group,
                    MessageChain(f"超出范围!({page}/{math.ceil(len(vip_list) / 15)})"),
                    quote=source
                )
            send = [
                f"服务器VIP排名(page:{page}/{math.ceil(len(vip_list) / 15)})",
            ]
            for data in vip_list[(page - 1) * 15:page * 15]:
                # 获取服务器排名,组合为: index. serverName[:20] bookmark
                index = vip_list.index(data) + 1
                send.append(f"{index}.{data['displayName'][:20]} {len(data['server_list'])}")
            send = "\n".join(send)
            return await app.send_message(group, MessageChain(f"{send}"), quote=source)
        elif rank_type in ["ban", "封禁"]:
            ban_list = await BF1DB.server.get_allServerPlayerBanList()
            if not ban_list:
                return await app.send_message(group, MessageChain(f"没有在数据库中找到服务器封禁信息!"), quote=source)
            # 将得到的数据15个一页分组，如果page超出范围则返回错误,否则返回对应页的数据
            if page > math.ceil(len(ban_list) / 15):
                return await app.send_message(
                    group,
                    MessageChain(f"超出范围!({page}/{math.ceil(len(ban_list) / 15)})"),
                    quote=source
                )
            send = [f"服务器封禁排名(page:{page}/{math.ceil(len(ban_list) / 15)})"]
            for data in ban_list[(page - 1) * 15:page * 15]:
                # 获取服务器排名,组合为: index. serverName[:20] bookmark
                index = ban_list.index(data) + 1
                send.append(f"{index}.{data['displayName'][:20]} {len(data['server_list'])}")
            send = "\n".join(send)
            return await app.send_message(group, MessageChain(f"{send}"), quote=source)
        elif rank_type in ["admin", "管理"]:
            admin_list = await BF1DB.server.get_allServerPlayerAdminList()
            if not admin_list:
                return await app.send_message(group, MessageChain(f"没有在数据库中找到服务器管理信息!"), quote=source)
            # 将得到的数据15个一页分组，如果page超出范围则返回错误,否则返回对应页的数据
            if page > math.ceil(len(admin_list) / 15):
                return await app.send_message(
                    group,
                    MessageChain(f"超出范围!({page}/{math.ceil(len(admin_list) / 15)})"),
                    quote=source
                )
            send = [
                f"服务器管理排名(page:{page}/{math.ceil(len(admin_list) / 15)})",
            ]
            for data in admin_list[(page - 1) * 15:page * 15]:
                # 获取服务器排名,组合为: index. serverName[:20] bookmark
                index = admin_list.index(data) + 1
                send.append(f"{index}.{data['displayName'][:20]} {len(data['server_list'])}")
            send = "\n".join(send)
            return await app.send_message(group, MessageChain(f"{send}"), quote=source)
        elif rank_type in ["owner", "服主"]:
            owner_list = await BF1DB.server.get_allServerPlayerOwnerList()
            if not owner_list:
                return await app.send_message(group, MessageChain(f"没有在数据库中找到服务器服主信息!"), quote=source)
            # 将得到的数据15个一页分组，如果page超出范围则返回错误,否则返回对应页的数据
            if page > math.ceil(len(owner_list) / 15):
                return await app.send_message(
                    group,
                    MessageChain(f"超出范围!({page}/{math.ceil(len(owner_list) / 15)})"),
                    quote=source
                )
            send = [
                f"服务器服主排名(page:{page}/{math.ceil(len(owner_list) / 15)})",
            ]
            for data in owner_list[(page - 1) * 15:page * 15]:
                # 获取服务器排名,组合为: index. serverName[:20] bookmark
                index = owner_list.index(data) + 1
                send.append(f"{index}.{data['displayName'][:20]} {len(data['server_list'])}")
            send = "\n".join(send)
            return await app.send_message(group, MessageChain(f"{send}"), quote=source)
    else:
        name = name.result
        # 查询服务器/玩家对应分类的排名
        if rank_type in ["收藏", "bookmark"]:
            bookmark_list = await BF1DB.server.get_server_bookmark()
            if not bookmark_list:
                return await app.send_message(group, MessageChain(f"没有在数据库中找到服务器收藏信息!"), quote=source)
            result = []
            for item in bookmark_list:
                if (fuzz.ratio(name.upper(), item['serverName'].upper()) > 80) or \
                        name.upper() in item['serverName'].upper() or \
                        item['serverName'].upper() in name.upper():
                    result.append(item)
            if not result:
                return await app.send_message(group, MessageChain(f"没有在数据库中找到该服务器的收藏信息!"),
                                              quote=source)
            send = [f"搜索到{len(result)}个结果:" if len(result) <= 15 else f"搜索到超过15个结果,只显示前15个结果!"]
            result = result[:15]
            for data in result:
                # 获取服务器排名,组合为: index. serverName[:20] bookmark
                index = bookmark_list.index(data) + 1
                send.append(f"{index}.{data['serverName'][:20]} {data['bookmark']}")
            send = "\n".join(send)
            return await app.send_message(group, MessageChain(f"{send}"), quote=source)
        elif rank_type in ["vip"]:
            vip_list = await BF1DB.server.get_allServerPlayerVipList()
            if not vip_list:
                return await app.send_message(group, MessageChain(f"没有在数据库中找到服务器VIP信息!"), quote=source)
            display_name = [item['displayName'].upper() for item in vip_list]
            if name.upper() not in display_name:
                return await app.send_message(group, MessageChain(f"没有在数据库中找到该玩家的VIP信息!"), quote=source)
            index = display_name.index(name.upper()) + 1
            return await app.send_message(group, MessageChain(f"{name}的VIP排名为{index}"), quote=source)
        elif rank_type in ["ban", "封禁"]:
            ban_list = await BF1DB.server.get_allServerPlayerBanList()
            if not ban_list:
                return await app.send_message(group, MessageChain(f"没有在数据库中找到服务器封禁信息!"), quote=source)
            display_name = [item['displayName'].upper() for item in ban_list]
            if name.upper() not in display_name:
                return await app.send_message(group, MessageChain(f"没有在数据库中找到该玩家的封禁信息!"), quote=source)
            index = display_name.index(name.upper()) + 1
            return await app.send_message(group, MessageChain(f"{name}的封禁排名为{index}"), quote=source)
        elif rank_type in ["admin", "管理"]:
            admin_list = await BF1DB.server.get_allServerPlayerAdminList()
            if not admin_list:
                return await app.send_message(group, MessageChain(f"没有在数据库中找到服务器管理信息!"), quote=source)
            display_name = [item['displayName'].upper() for item in admin_list]
            if name.upper() not in display_name:
                return await app.send_message(group, MessageChain(f"没有在数据库中找到该玩家的管理信息!"), quote=source)
            index = display_name.index(name.upper()) + 1
            return await app.send_message(group, MessageChain(f"{name}的管理排名为{index}"), quote=source)
        elif rank_type in ["owner", "服主"]:
            owner_list = await BF1DB.server.get_allServerPlayerOwnerList()
            if not owner_list:
                return await app.send_message(group, MessageChain(f"没有在数据库中找到服务器服主信息!"), quote=source)
            display_name = [item['displayName'].upper() for item in owner_list]
            if name.upper() not in display_name:
                return await app.send_message(group, MessageChain(f"没有在数据库中找到该玩家的服主信息!"), quote=source)
            index = display_name.index(name.upper()) + 1
            return await app.send_message(group, MessageChain(f"{name}的服主排名为{index}"), quote=source)


# 被戳回复小标语
@listen(NudgeEvent)
async def NudgeReply(app: Ariadne, event: NudgeEvent):
    if event.group_id and event.target == app.account and module_controller.if_module_switch_on(
            channel.module, event.group_id
    ):
        # 98%的概率从文件获取tips
        if random.randint(0, 99) > 1:
            file_path = f"./data/battlefield/小标语/data.json"
            with open(file_path, 'r', encoding="utf-8") as file1:
                data = json.load(file1)['result']
                a = random.choice(data)['name']
                send = zhconv.convert(a, 'zh-cn')
        else:
            bf_dic = [
                "你知道吗,小埋BOT最初的灵感来自于胡桃-by水神",
                f"当武器击杀达到60⭐时为蓝光,当达到100⭐之后会发出耀眼的金光~",
            ]
            send = random.choice(bf_dic)
        return await app.send_group_message(event.group_id, MessageChain(At(event.supplicant), '\n', send))


# 战地一私服情况
@listen(GroupMessage)
@dispatch(
    Twilight(
        [
            UnionMatch("-bf1", "-bfstat").space(SpacePolicy.PRESERVE),
            ArgumentMatch("-i", "-img", action="store_true", optional=True) @ "img",
        ]
    )
)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level),
    Permission.user_require(Permission.User),
)
async def bf1_server_info_check(app: Ariadne, group: Group, source: Source, img: ArgResult):
    # 弃用的gt_bf1_stat
    # result = await gt_bf1_stat()
    # if not isinstance(result, str):
    #     return await app.send_message(group, MessageChain(f"查询出错!{result}"), quote=source)
    # return await app.send_message(group, MessageChain(f"{result}"), quote=source)
    bf1_account = await BF1DA.get_api_instance()
    time_start = time.time()
    #   搜索获取私服game_id
    filter_dict = {
        "name": "",  # 服务器名
        "serverType": {  # 服务器类型
            "OFFICIAL": "on",  # 官服
            "RANKED": "on",  # 私服
            "UNRANKED": "on",  # 私服(不计战绩)
            "PRIVATE": "on"  # 密码服
        },
        "slots": {  # 空位
            "oneToFive": "on",  # 1-5
            "sixToTen": "on",  # 6-10
            "none": "on",  # 无
            "tenPlus": "on",  # 10+
            "spectator": "on"  # 观战
        },
    }
    guid_list = []
    server_total_list = []
    tasks = [bf1_account.searchServers("", filter_dict=filter_dict) for _ in range(50)]
    logger.debug("开始获取私服数据")
    await app.send_message(group, MessageChain("查询ing"), quote=source)
    results = await asyncio.gather(*tasks)
    for result in results:
        if isinstance(result, str):
            continue
        result: dict = result["result"]
        for server in result.get("gameservers", []):
            if server["guid"] not in guid_list:
                guid_list.append(server["guid"])
                server["mapModePretty"] = zhconv.convert(server["mapModePretty"], 'zh-hans')
                server["mapNamePretty"] = zhconv.convert(server["mapNamePretty"], 'zh-hans')
                server_total_list.append(server)
    if not server_total_list:
        logger.error("获取服务器列表失败!")
        return await app.send_message(group, MessageChain(f"获取服务器信息失败!"), quote=source)
    logger.success(f"共获取{len(server_total_list)}个服务器,耗时{round(time.time() - time_start, 2)}秒")
    # 人数、排队数、观众、模式、地图、地区、国家
    server_list = []
    # official_server_list = []
    # private_server_list = []
    for server in server_total_list:
        players = server["slots"]["Soldier"]["current"]
        queues = server["slots"]["Queue"]["current"]
        spectators = server["slots"]["Spectator"]["current"]
        mapName = server["mapName"]
        mapNamePretty = server["mapNamePretty"]
        mapMode = server["mapMode"]
        mapModePretty = server["mapModePretty"]
        region = server["region"]
        country = server["country"]
        temp = {
            "players": players,
            "queues": queues,
            "spectators": spectators,
            "mapName": mapName,
            "mapNamePretty": mapNamePretty,
            "mapMode": mapMode,
            "mapModePretty": mapModePretty,
            "region": region,
            "country": country,
            "official": True if server["serverType"] == "OFFICIAL" else False,
        }
        server_list.append(temp)
        # if server["serverType"] != "OFFICIAL":
        #     private_server_list.append(temp)
        # else:
        #     official_server_list.append(temp)
    region_dict = {
        "OC": "大洋洲",
        "Asia": "亚洲",
        "EU": "欧洲",
        "Afr": "非洲",
        "AC": "南极洲",
        "SAm": "南美洲",
        "NAm": "北美洲"
    }
    country_dict = {
        "JP": "日本",
        "US": "美国",
        "DE": "德国",
        "AU": "澳大利亚",
        "BR": "巴西",
        "HK": "中国香港",
        "AE": "阿联酋",
        "ZA": "南非",
    }

    # 文字版本：
    # 服务器总数(官/私): xxx (xxx/xxx)                 服务器数量 = 官服数量 + 私服数量
    # 总人数(官/私): xxx (xxx/xxx)                 总人数 = 游玩人数 + 排队人数 + 观众人数
    # 游玩人数(官/私|亚/欧): xxx (xxx/xxx/xxx/xxx)
    # 排队人数(官/私|亚/欧): xxx (xxx/xxx/xxx/xxx)
    # 观众人数(官/私): xxx (xxx/xxx)
    # 热门地图: xxx,xxx,xxx      (只显示前三个，地图名：数量)
    # 征服: xx   ,行动: xx       (所有模式的人数)
    # 时间: xx.xx.xx xx:xx:xx
    # 示例:
    # 服务器总数(官/私):
    # 总:100 (50/50)
    # 总人数(官/私):
    # 总:1000 (500/500)
    # 游玩人数(官/私|亚/欧):
    # 总:900, 100/800, 400/200
    # 排队人数(官/私|亚/欧):
    # 总:60, 10/50, 15,23
    # 观众人数(官/私):
    # 总:40, 10/30
    # ==========================
    # 热门地图:
    # xxx:100, xxx:90, xxx:80
    # ==========================
    # 游玩模式:
    # 征服: 100, 行动: 90
    # ==========================
    # 更新时间: 2021-08-04 12:00:00

    # 总人数
    total_players = 0
    total_queues = 0
    total_spectators = 0
    # 官服人数
    official_players = 0
    official_queues = 0
    official_spectators = 0
    # 私服人数
    private_players = 0
    private_queues = 0
    private_spectators = 0
    # 亚服人数
    asia_players = 0
    asia_queues = 0
    asia_spectators = 0
    # 欧服人数
    eu_players = 0
    eu_queues = 0
    eu_spectators = 0
    # 整理数据
    for server in server_list:
        total_players += server["players"]
        total_queues += server["queues"]
        total_spectators += server["spectators"]
        if server["official"]:
            official_players += server["players"]
            official_queues += server["queues"]
            official_spectators += server["spectators"]
        else:
            private_players += server["players"]
            private_queues += server["queues"]
            private_spectators += server["spectators"]
        if server["region"] == "Asia":
            asia_players += server["players"]
            asia_queues += server["queues"]
            asia_spectators += server["spectators"]
        elif server["region"] == "EU":
            eu_players += server["players"]
            eu_queues += server["queues"]
            eu_spectators += server["spectators"]
    # TODO: 可视化
    # if img.matched:
    #     img_bytes = Bf1Status(private_server_data, official_server_data).generate_comparison_charts()
    #     return await app.send_message(group, MessageChain(Image(data_bytes=img_bytes)), quote=source)
    # 用一个变量存 =*15 用于发送
    equals = "=" * 15
    send = [
        f"总人数(官/私):\n"
        f"{total_players + total_queues + total_spectators} "
        f"({official_players + official_queues + official_spectators}/"
        f"{private_players + private_queues + private_spectators})\n"
        f"游玩人数(官/私|亚/欧):\n"
        f"{total_players} ({official_players}/{private_players}|{asia_players}/{eu_players})\n"
        f"排队人数(官/私|亚/欧):\n"
        f"{total_queues} ({official_queues}/{private_queues}|{asia_queues}/{eu_queues})\n"
        f"观众人数(官/私):\n"
        f"{total_spectators} ({official_spectators}/{private_spectators})\n"
        f"{equals}\n"
        f"服务器总数(官/私):\n"
        f"{len(server_list)} ({len([server for server in server_list if server['official']])}/"
        f"{len([server for server in server_list if not server['official']])})\n"
        f"{equals}\n"
    ]
    # 热门地图
    map_list = {}
    for server in server_list:
        # if server["mapNamePretty"] not in map_list:
        #     map_list[server["mapNamePretty"]] = 0
        # map_list[server["mapNamePretty"]] += 1
        # 组成 模式-地图
        temp = f"{server['mapModePretty']}-{server['mapNamePretty']}"
        if temp not in map_list:
            map_list[temp] = 0
        map_list[temp] += 1
    map_list = sorted(map_list.items(), key=lambda x: x[1], reverse=True)
    map_list = [f"{item[0]}:{item[1]}" for item in map_list]
    map_list = map_list[:3]
    map_list = "\n".join(map_list)
    send.append(f"前三热门地图:\n{map_list}\n{equals}\n")
    # 模式 每两个换一行
    mode_list = {}
    for server in server_list:
        if server["mapModePretty"] not in mode_list:
            mode_list[server["mapModePretty"]] = 0
        mode_list[server["mapModePretty"]] += 1
    mode_list = sorted(mode_list.items(), key=lambda x: x[1], reverse=True)
    mode_list = [f"{item[0]}:{item[1]}" for item in mode_list]
    mode_list = [mode_list[i:i + 2] for i in range(0, len(mode_list), 2)]
    mode_list = [" ".join(item) for item in mode_list]
    mode_list = "\n".join(mode_list)
    send.append(f"游玩模式:\n{mode_list}\n{equals}\n")
    # 更新时间
    send.append(f"更新时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    send = "".join(send)
    return await app.send_message(group, MessageChain(f"{send}"), quote=source)


# 交换
@listen(GroupMessage)
@dispatch(
    Twilight(
        [
            UnionMatch("-exchange", "-ex", "-交换").space(SpacePolicy.PRESERVE),
            ArgumentMatch("-t", "-time", optional=True, type=str) @ "search_time",
        ]
    )
)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level),
    Permission.user_require(Permission.User),
)
async def get_exchange(app: Ariadne, group: Group, source: Source, search_time: ArgResult):
    # 交换缓存图片的路径
    file_path = Path("./data/battlefield/exchange/")
    # 获取今天的日期
    file_date = datetime.datetime.now()
    date_now = file_date
    # 1.如果文件夹为空,则获取gw api的数据制图
    # 2.如果不为空,直接发送最新的缓存图片
    # 3.发送完毕后从gw api获取数据,如果和缓存的json文件内容一样,则不做任何操作,否则重新制图并保存为今天日期的文件
    if not file_path.exists():
        file_path.mkdir(parents=True)
    if file_path.exists() and len(list(file_path.iterdir())) == 0:
        # 获取gw api的数据
        result = await (await BF1DA.get_api_instance()).getOffers()
        if not isinstance(result, dict):
            return await app.send_message(group, MessageChain(f"查询出错!{result}"), quote=source)
        # 将数据写入json文件
        with open(file_path / f"{date_now.year}年{date_now.month}月{date_now.day}日.json", 'w',
                  encoding="utf-8") as file1:
            json.dump(result, file1, ensure_ascii=False, indent=4)
        # 将数据制图
        img = await Exchange(result).draw()
        return await app.send_message(
            group,
            MessageChain(
                Image(data_bytes=img),
                f"更新时间:{date_now.year}年{date_now.month}月{date_now.day}日"
            ),
            quote=source
        )
    if search_time.matched:
        try:
            strptime_temp = datetime.datetime.strptime(search_time.result, "%Y.%m.%d")
        except ValueError:
            return await app.send_message(group, MessageChain(f"日期格式错误!示例:xxxx.x.x"), quote=source)
        # 转换成xx年x月xx日
        strptime_temp = f"{strptime_temp.year}年{strptime_temp.month}月{strptime_temp.day}日"
        # 发送缓存里指定日期的图片
        pic_file_name = f"{strptime_temp}.png"
        pic_list = []
        for item in file_path.iterdir():
            if item.name.endswith(".png"):
                pic_list.append(item.name.split(".")[0])
        if strptime_temp not in pic_list:
            # 发送最接近时间的5条数据
            pic_list.sort(key=lambda x: abs((datetime.datetime.strptime(x, "%Y年%m月%d日") - datetime.datetime.strptime(
                search_time.result, "%Y.%m.%d")).days))
            pic_list = pic_list[:5]
            pic_list = "\n".join(pic_list)
            return await app.send_message(
                group,
                MessageChain(f"没有找到{strptime_temp}的数据,以下是最接近的5条数据:\n{pic_list}"),
                quote=source
            )
        img = Path(f"./data/battlefield/exchange/{pic_file_name}").read_bytes()
        return await app.send_message(group, MessageChain(
            Image(data_bytes=img), f"更新时间:{pic_file_name.split('.')[0]}"
        ), quote=source)
    # 发送缓存里最新的图片
    for day in range(int(len(list(file_path.iterdir()))) + 1):
        file_date = date_now - datetime.timedelta(days=day)
        pic_file_name = f"{file_date.year}年{file_date.month}月{file_date.day}日.png"
        if (file_path / pic_file_name).exists():
            img = Path(f"./data/battlefield/exchange/{pic_file_name}").read_bytes()
            await app.send_message(
                group,
                MessageChain(
                    Image(data_bytes=img),
                    f"更新时间:{pic_file_name.split('.')[0]}"
                ),
                quote=source
            )
            break
    # 获取gw api的数据,更新缓存
    result = await (await BF1DA.get_api_instance()).getOffers()
    if isinstance(result, str):
        return logger.error(f"查询交换出错!{result}")
    # 如果result和之前最新的json文件内容一样,则return
    if (file_path / f"{file_date.year}年{file_date.month}月{file_date.day}日.json").exists():
        with open(file_path / f"{file_date.year}年{file_date.month}月{file_date.day}日.json",
                  'r', encoding="utf-8") as file1:
            data = json.load(file1)
            if data.get("result") == result.get("result"):
                return logger.info("交换未更新~")
            else:
                logger.debug("正在更新交换~")
                # 将数据写入json文件
                with open(file_path / f"{date_now.year}年{date_now.month}月{date_now.day}日.json",
                          'w', encoding="utf-8") as file2:
                    json.dump(result, file2, ensure_ascii=False, indent=4)
                # 将数据制图
                _ = await Exchange(result).draw()
                return logger.success("成功更新交换缓存~")
    else:
        return logger.error(f"未找到交换数据文件{file_date.year}年{file_date.month}月{file_date.day}日.json")


# 战役
@listen(GroupMessage)
@dispatch(
    Twilight(
        [
            UnionMatch("-战役", "-行动", "-op").space(SpacePolicy.PRESERVE),
        ]
    )
)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level),
    Permission.user_require(Permission.User),
)
async def get_CampaignOperations(app: Ariadne, group: Group, source: Source):
    data = await (await BF1DA.get_api_instance()).getPlayerCampaignStatus()
    if not isinstance(data, dict):
        return await app.send_message(group, MessageChain(f"查询出错!{data}"), quote=source)
    if not data.get("result"):
        return await app.send_message(group, MessageChain(
            f"当前无进行战役信息!"
        ), quote=source)
    return_list = []
    from time import strftime, gmtime
    return_list.append(zhconv.convert(f"战役名称:{data['result']['name']}\n", "zh-cn"))
    return_list.append(zhconv.convert(f'战役描述:{data["result"]["shortDesc"]}\n', "zh-cn"))
    return_list.append('战役地点:')
    place_list = []
    for key in data["result"]:
        if key.startswith("op") and data["result"].get(key):
            place_list.append(zhconv.convert(f'{data["result"][key]["name"]} ', "zh-cn"))
    place_list = ','.join(place_list)
    return_list.append(place_list)
    return_list.append(strftime("\n剩余时间:%d天%H小时%M分", gmtime(data["result"]["minutesRemaining"] * 60)))
    return await app.send_message(group, MessageChain(
        return_list
    ), quote=source)
