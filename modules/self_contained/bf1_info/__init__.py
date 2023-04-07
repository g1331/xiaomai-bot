import asyncio
import datetime
import json
import random
import time
from pathlib import Path
from typing import List, Tuple

from creart import create
from graia.amnesia.message import MessageChain
from graia.ariadne.app import Ariadne
from graia.ariadne.event.lifecycle import ApplicationLaunched
from graia.ariadne.event.mirai import NudgeEvent
from graia.ariadne.event.message import GroupMessage, FriendMessage
from graia.ariadne.message.element import Source, Image, At
from graia.ariadne.message.parser.twilight import Twilight, UnionMatch, SpacePolicy, FullMatch, ParamMatch, \
    RegexResult, ArgumentMatch, ArgResult
from graia.ariadne.model import Group, Friend, Member
from graia.ariadne.util.saya import listen, dispatch, decorate
from graia.scheduler.saya.schema import SchedulerSchema
from graia.scheduler import timers
from graia.saya import Channel, Saya
from loguru import logger
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
from utils.bf1.data_handle import WeaponData, VehicleData, ServerData
from utils.bf1.default_account import BF1DA
from utils.bf1.draw import PlayerStatPic, PlayerVehiclePic, PlayerWeaponPic
from utils.bf1.gateway_api import api_instance
from utils.bf1.map_team_info import MapData
from utils.bf1.database import BF1DB
from utils.bf1.bf_utils import (
    get_personas_by_name, check_bind, BTR_get_recent_info,
    BTR_get_match_info, BTR_update_data, bfeac_checkBan, bfban_checkBan, gt_checkVban, gt_bf1_stat
)

config = create(GlobalConfig)
core = create(Umaru)
module_controller = saya_model.get_module_controller()

saya = Saya.current()
channel = Channel.current()
channel.name("Bf1Info")
channel.description("战地一战绩查询")
channel.author("十三")
channel.metadata = module_controller.get_metadata_from_path(Path(__file__))


# 当bot启动时自动检查默认账号信息
@listen(ApplicationLaunched)
async def check_default_account(app: Ariadne):
    logger.debug("正在检查默认账号信息")
    # 检查默认账号信息
    default_account_info = await BF1DA.read_default_account()
    # pid为空,则给Master发送提示
    if not default_account_info["pid"]:
        return await app.send_friend_message(
            config.Master,
            MessageChain("BF1默认查询账号信息不完整，请使用 '-设置默认账号 pid remid=xxx,sid=xxx' 命令设置默认账号信息")
        )
    else:
        # 登录默认账号
        await BF1DA.get_api_instance()
        # 更新默认账号信息
        account_info = await BF1DA.update_player_info()
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
    if isinstance(session, str):
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
    else:
        # 登录失败,返回错误信息
        return await app.send_friend_message(
            sender,
            MessageChain(f"登录默认账号{account_pid}失败，错误信息: {session}"),
            quote=source
        )


# 绑定
@listen(GroupMessage)
@dispatch(
    Twilight(
        [
            FullMatch("-绑定"),
            ParamMatch() @ "player_name",
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
        await BF1DB.bind_player_qq(sender.id, pid)
        if old_display_name and (old_pid != pid):
            result = f"绑定ID变更!\n" \
                     f"displayName: {old_display_name} -> {display_name}\n" \
                     f"pid: {old_pid} -> {pid}\n" \
                     f"uid: {old_uid} -> {uid}"
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
            MessageChain(f"绑定失败!"),
            quote=source
        )


# 查询玩家信息
@listen(GroupMessage)
@dispatch(
    Twilight(
        [
            FullMatch("-信息"),
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
        if bind_info := await check_bind(sender.id):
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
            return await app.send_message(
                group,
                MessageChain(f"你还没有绑定!请使用'-绑定 玩家名'进行绑定!"),
                quote=source
            )
    # 如果有参数，查询玩家信息
    else:
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
            UnionMatch("-stat", "-生涯", "-战绩").space(SpacePolicy.PRESERVE),
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
async def player_stat_pic(
        app: Ariadne,
        sender: Member,
        group: Group,
        source: Source,
        player_name: RegexResult
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

    await app.send_message(group, MessageChain(f"查询ing"), quote=source)

    # 并发获取生涯、武器、载具信息
    tasks = [
        (await BF1DA.get_api_instance()).detailedStatsByPersonaId(player_pid),
        (await BF1DA.get_api_instance()).getWeaponsByPersonaId(player_pid),
        (await BF1DA.get_api_instance()).getVehiclesByPersonaId(player_pid),
        bfeac_checkBan(display_name)
    ]
    tasks = await asyncio.gather(*tasks)

    # 检查返回结果
    player_stat, player_weapon, player_vehicle, eac_info = tasks[0], tasks[1], tasks[2], tasks[3]
    if isinstance(player_stat, str):
        logger.error(player_stat)
        return await app.send_message(
            group,
            MessageChain(f"查询出错!{player_stat}"),
            quote=source
        )
    else:
        player_stat: dict
        player_stat["result"]["displayName"] = display_name
    if isinstance(player_weapon, str):
        logger.error(player_weapon)
        return await app.send_message(
            group,
            MessageChain(f"查询出错!{player_weapon}"),
            quote=source
        )
    else:
        player_weapon: list = WeaponData(player_weapon).filter()
    if isinstance(player_vehicle, str):
        logger.error(player_vehicle)
        return await app.send_message(
            group,
            MessageChain(f"查询出错!{player_vehicle}"),
            quote=source
        )
    else:
        player_vehicle: list = VehicleData(player_vehicle).filter()

    # 生成图片
    player_stat_img = await PlayerStatPic(player_stat, player_weapon, player_vehicle).draw()
    if player_stat_img:
        return await app.send_message(
            group,
            MessageChain(Image(data_bytes=player_stat_img)),
            quote=source
        )
    else:
        # 发送文字
        # 包含等级、游玩时长、击杀、死亡、KD、胜局、败局、胜率、KPM、SPM、步战KD、载具KD、技巧值、最远爆头距离
        # 协助击杀、最高连杀、复活数、治疗数、修理数、狗牌数
        player_info = player_stat["result"]
        rank = player_info.get('basicStats').get('rank')
        # 转换成xx小时xx分钟
        time_seconds = player_info.get('basicStats').get('timePlayed')
        time_played = f"{time_seconds // 3600}小时{time_seconds % 3600 // 60}分钟"
        kills = player_info.get('basicStats').get('kills')
        deaths = player_info.get('basicStats').get('deaths')
        kd = round(kills / deaths, 2) if deaths else kills
        wins = player_info.get('basicStats').get('wins')
        losses = player_info.get('basicStats').get('losses')
        win_rate = round(wins / (wins + losses) if (wins + losses) else wins, 2)
        kpm = player_info.get('basicStats').get('kpm')
        spm = player_info.get('basicStats').get('spm')
        vehicle_kill = 0
        for item in player_info["vehicleStats"]:
            vehicle_kill += item["killsAs"]
        infantry_kill = player_info['basicStats']['kills'] - vehicle_kill
        infantry_kd = round(infantry_kill / deaths, 2) if deaths else infantry_kill
        vehicle_kd = round(vehicle_kill / deaths, 2) if deaths else vehicle_kill
        skill = player_info.get('basicStats').get('skill')
        longest_headshot = player_info.get('longestHeadShot')
        killAssists = int(player_info.get('killAssists'))
        highestKillStreak = int(player_info.get('highestKillStreak'))
        revives = int(player_info.get('revives'))
        heals = int(player_info.get('heals'))
        repairs = int(player_info.get('repairs'))
        dogtagsTaken = int(player_info.get('dogtagsTaken'))
        if eac_info.get("stat"):
            eac_info = f'{eac_info.get("stat")}\n案件地址:{eac_info.get("url")}\n'
        else:
            eac_info = "未查询到EAC信息\n"
        result = [
            f"玩家:{display_name}\n"
            f"等级:{rank if rank else 0}\n"
            f"游玩时长:{time_played}\n"
            f"击杀:{kills}  死亡:{deaths}  KD:{kd}\n"
            f"胜局:{wins}  败局:{losses}  胜率:{win_rate}%\n"
            f"KPM:{kpm}  SPM:{spm}\n"
            f"步战KD:{infantry_kd}  载具KD:{vehicle_kd}\n"
            f"技巧值:{skill}\n"
            f"最远爆头距离:{longest_headshot}米\n"
            f"协助击杀:{killAssists}  最高连杀:{highestKillStreak}\n"
            f"复活数:{revives}   治疗数:{heals}\n"
            f"修理数:{repairs}   狗牌数:{dogtagsTaken}\n"
            f"EAC状态:{eac_info}" + "=" * 20
        ]
        weapon = player_weapon[0]
        name = zhconv.convert(weapon.get('name'), 'zh-hans')
        kills = int(weapon["stats"]["values"]["kills"])
        seconds = weapon["stats"]["values"]["seconds"]
        kpm = "{:.2f}".format(kills / seconds * 60) if seconds != 0 else kills
        acc = round(weapon["stats"]["values"]["hits"] / weapon["stats"]["values"]["shots"] * 100, 2) \
            if weapon["stats"]["values"]["shots"] * 100 != 0 else 0
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
            + "=" * 15
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
            + "=" * 15
        )
        result = "\n".join(result)

        return await app.send_message(
            group,
            MessageChain(
                result
            ),
            quote=source
        )


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
            ArgumentMatch("-r", "-row", action="store_true", optional=True, type=int, default=4) @ "row",
            ArgumentMatch("-c", "-col", action="store_true", optional=True, type=int, default=1) @ "col",
            ArgumentMatch("-n", "-name", optional=True) @ "weapon_name",
            ArgumentMatch("-s", "-sort", optional=True) @ "sort_type",
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
        sort_type: ArgResult
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

    await app.send_message(group, MessageChain(f"查询ing"), quote=source)

    # 获取武器信息
    player_weapon = await (await BF1DA.get_api_instance()).getWeaponsByPersonaId(player_pid)
    if isinstance(player_weapon, str):
        logger.error(player_weapon)
        return await app.send_message(
            group,
            MessageChain(f"查询出错!{player_weapon}"),
            quote=source
        )
    else:
        if not weapon_name.matched:
            player_weapon: list = WeaponData(player_weapon).filter(
                rule=weapon_type.result.display if weapon_type.matched else "",
                sort_type=sort_type.result.display if sort_type.matched else "",
            )
        else:
            player_weapon: list = WeaponData(player_weapon).search_weapon(
                weapon_name.result.display,
                sort_type=sort_type.result.display if sort_type.matched else "",
            )
            if not player_weapon:
                return await app.send_message(
                    group,
                    MessageChain(f"没有找到武器[{weapon_name.result.display}]哦~"),
                    quote=source
                )

    # 生成图片
    player_weapon_img = await PlayerWeaponPic(weapon_data=player_weapon).draw(
        display_name, row.result, col.result
    ) if not weapon_name.matched else await PlayerWeaponPic(weapon_data=player_weapon).draw_search(
        display_name, row.result, col.result)
    if player_weapon_img:
        return await app.send_message(
            group,
            MessageChain(Image(data_bytes=player_weapon_img)),
            quote=source
        )
    else:
        # 发送文字数据
        result = [f"玩家: {display_name}\n" + "=" * 20]
        for weapon in player_weapon:
            if not weapon.get("stats").get('values'):
                continue
            name = zhconv.convert(weapon.get('name'), 'zh-hans')
            kills = int(weapon["stats"]["values"]["kills"])
            seconds = weapon["stats"]["values"]["seconds"]
            kpm = "{:.2f}".format(kills / seconds * 60) if seconds != 0 else kills
            acc = round(weapon["stats"]["values"]["hits"] / weapon["stats"]["values"]["shots"] * 100, 2) \
                if weapon["stats"]["values"]["shots"] * 100 != 0 else 0
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
                + "=" * 15
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
                "载具", "vehicle", "vc", "坦克", "地面", "飞机", "飞船", "飞艇", "空中", "海上", "定点"
            ).space(SpacePolicy.PRESERVE) @ "vehicle_type",
            ParamMatch(optional=True) @ "player_name",
            ArgumentMatch("-r", "-row", action="store_true", optional=True) @ "row",
            ArgumentMatch("-c", "-col", action="store_true", optional=True) @ "col",
            ArgumentMatch("-n", "-name", optional=True) @ "vehicle_name",
            ArgumentMatch("-s", "-sort", optional=True) @ "sort_type",
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
        sort_type: ArgResult
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

    await app.send_message(group, MessageChain(f"查询ing"), quote=source)

    # 获取载具信息
    player_vehicle = await (await BF1DA.get_api_instance()).getVehiclesByPersonaId(player_pid)
    if isinstance(player_vehicle, str):
        logger.error(player_vehicle)
        return await app.send_message(
            group,
            MessageChain(f"查询出错!{player_vehicle}"),
            quote=source
        )
    else:
        if not vehicle_name.matched:
            player_vehicle: list = VehicleData(player_vehicle).filter(
                rule=vehicle_type.result.display if vehicle_type.matched else "",
                sort_type=sort_type.result.display if sort_type.matched else "",
            )
        else:
            player_vehicle: list = VehicleData(player_vehicle).search_vehicle(
                target_vehicle_name=vehicle_name.result.display,
                sort_type=sort_type.result.display if sort_type.matched else "",
            )
            if not player_vehicle:
                return await app.send_message(
                    group,
                    MessageChain(f"没有找到载具[{vehicle_name.result.display}]哦~"),
                    quote=source
                )

    # 生成图片
    player_vehicle_img = await PlayerVehiclePic(vehicle_data=player_vehicle).draw(
        display_name, row.result, col.result
    ) if not vehicle_name.matched else await PlayerVehiclePic(vehicle_data=player_vehicle).draw_search(
        display_name, row.result, col.result)
    if player_vehicle_img:
        return await app.send_message(
            group,
            MessageChain(Image(data_bytes=player_vehicle_img)),
            quote=source
        )
    else:
        # 发送文字数据
        result = [f"玩家: {display_name}\n" + "=" * 20]
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
                + "=" * 15
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
            UnionMatch("-最近").space(SpacePolicy.PRESERVE),
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
    if not player_name.matched:
        if bind_info := await check_bind(sender.id):
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
                group,
                MessageChain(f"你还没有绑定!请使用'-绑定 玩家名'进行绑定!"),
                quote=source
            )
    else:
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
        # player_pid = player_info["personas"]["persona"][0]["personaId"]
        display_name = player_info["personas"]["persona"][0]["displayName"]

    await app.send_message(group, MessageChain(f"查询ing"), quote=source)

    # 从BTR获取数据
    try:
        player_recent = await BTR_get_recent_info(display_name)
        if not player_recent:
            return await app.send_message(
                group,
                MessageChain(f"没有查询到最近记录哦~"),
                quote=source
            )
        result = [f"玩家: {display_name}\n" + "=" * 15]
        for item in player_recent[:3]:
            result.append(
                f"{item['time']}\n"
                f"得分: {item['score']}\nSPM: {item['spm']}\n"
                f"KD: {item['kd']}  KPM: {item['kpm']}\n"
                f"游玩时长: {item['time_play']}\n局数: {item['win_rate']}\n"
                + "=" * 15
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
            MessageChain(f"查询出错!"),
            quote=source
        )


# 对局数据
@listen(GroupMessage)
@dispatch(
    Twilight(
        [
            UnionMatch("-对局").space(SpacePolicy.PRESERVE),
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
    if not player_name.matched:
        if bind_info := await check_bind(sender.id):
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
                group,
                MessageChain(f"你还没有绑定!请使用'-绑定 玩家名'进行绑定!"),
                quote=source
            )
    else:
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
        # player_pid = player_info["personas"]["persona"][0]["personaId"]
        display_name = player_info["personas"]["persona"][0]["displayName"]

    await app.send_message(group, MessageChain(f"查询ing"), quote=source)

    # 从BTR获取数据
    try:
        player_match = await BTR_get_match_info(display_name)
        if not player_match:
            return await app.send_message(
                group,
                MessageChain(f"没有查询到对局记录哦~"),
                quote=source
            )
        result = [f"玩家: {display_name}\n" + "=" * 15]
        # 处理数据
        for item in player_match:
            players = item.get("players")
            for player in players:
                if player.get("player_name").upper() == display_name.upper():
                    game_info = item.get("game_info")
                    # 如果得为0则跳过
                    if player["score"] == 0:
                        continue
                    map_name = game_info['map_name']
                    team_name = MapData.MapTeamDict.get(map_name, {}).get(f"Team{player['team_name']}", "No Team")
                    team_win = "🏆" if player['team_win'] else "🏳"
                    result.append(
                        f"服务器: {game_info['server_name'][:20]}\n"
                        f"时间: {game_info['game_time'].strftime('%Y年%m月%d日 %H:%M:%S')}\n"
                        f"地图: {game_info['map_name']}-{game_info['mode_name']}\n"
                        f"队伍: {team_name}  {team_win}\n"
                        f"击杀: {player['kills']}\t死亡: {player['deaths']}\n"
                        f"KD: {player['kd']}\tKPM: {player['kpm']}\n"
                        f"得分: {player['score']}\tSPM: {player['spm']}\n"
                        f"命中率: {player['accuracy']}\t爆头: {player['headshots']}\n"
                        f"游玩时长: {player['time_played']}\n"
                        + "=" * 15
                    )
        result = result[:4]
        result = "\n".join(result)
        await app.send_message(
            group,
            MessageChain(result),
            quote=source
        )
    except Exception as e:
        logger.error(e)
        return await app.send_message(
            group,
            MessageChain(f"查询出错!"),
            quote=source
        )
    finally:
        await BTR_update_data(display_name)


# 搜服务器
@listen(GroupMessage)
@dispatch(
    Twilight(
        [
            UnionMatch("-搜服务器", "-ss").space(SpacePolicy.PRESERVE),
            ParamMatch(optional=False) @ "server_name",
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

    # 处理数据
    server_list = ServerData(server_info).sort()
    if not server_list:
        return await app.send_message(
            group,
            MessageChain(f"没有搜索到服务器哦~"),
            quote=source
        )
    else:
        result = []
        # 只显示前10个
        if len(server_list) > 10:
            result.append(f"搜索到{len(server_list)}个服务器,显示前10个\n" + "=" * 20)
            server_list = server_list[:10]
        else:
            result.append(f"搜索到{len(server_list)}个服务器\n" + "=" * 20)
        for server in server_list:
            result.append(
                f"{server.get('name')[:25]}\n"
                f"人数: {server.get('SoldierCurrent')}/{server.get('SoldierMax')}"
                f"[{server.get('QueueCurrent')}]({server.get('SpectatorCurrent')})\n"
                f"地图: {server.get('map_name')}-{server.get('mode_name')}\n"
                f"GameId: {server.get('game_id')}\n"
                + "=" * 20
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
            MessageChain(f"GameId必须为数字!"),
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
        f"服务器: {Info.get('name')}\n"
        f"人数: {Info.get('slots').get('Soldier').get('current')}/{Info.get('slots').get('Soldier').get('max')}"
        f"[{Info.get('slots').get('Queue').get('current')}]({Info.get('slots').get('Spectator').get('current')})\n"
        f"地图: {Info.get('mapNamePretty')}-{Info.get('mapModePretty')}\n"
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
            f"服务器拥有者: {rspInfo.get('owner').get('name')}\n"
            f"Pid: {rspInfo.get('owner').get('pid')}\n"
            + "=" * 20
        )
    if platoonInfo := server_info.get("platoonInfo"):
        result.append(
            f"战队: [{platoonInfo.get('tag')}]{platoonInfo.get('name')}\n"
            f"人数: {platoonInfo.get('soldierCount')}\n"
            f"简介: {platoonInfo.get('description')}\n"
            + "=" * 20
        )
    result = "\n".join(result)
    return await app.send_message(
        group,
        MessageChain(result),
        quote=source
    )


# 定时服务器详细信息收集，每20分钟执行一次
@channel.use(SchedulerSchema(timers.every_custom_minutes(20)))
async def server_info_collect():
    time_start = time.time()
    #   搜索获取私服game_id
    tasks = []
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
    for _ in range(50):
        tasks.append((await BF1DA.get_api_instance()).searchServers(filter_dict=filter_dict))
    logger.debug("开始更新私服数据")
    results = await asyncio.gather(*tasks)
    for result in results:
        if isinstance(result, str):
            continue
        result: list = result["result"]
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
    await BF1DB.update_serverInfoList(server_info_list)
    logger.debug(f"更新服务器信息完成，耗时{round(time.time() - start_time, 2)}秒")
    start_time = time.time()
    await BF1DB.update_serverVipList(vip_dict)
    logger.debug(f"更新服务器VIP完成，耗时{round(time.time() - start_time, 2)}秒")
    start_time = time.time()
    await BF1DB.update_serverBanList(ban_dict)
    logger.debug(f"更新服务器封禁完成，耗时{round(time.time() - start_time, 2)}秒")
    await BF1DB.update_serverAdminList(admin_dict)
    start_time = time.time()
    logger.debug(f"更新服务器管理员完成，耗时{round(time.time() - start_time, 2)}秒")
    await BF1DB.update_serverOwnerList(owner_dict)
    logger.debug(f"更新服务器所有者完成，耗时{round(time.time() - start_time, 2)}秒")
    logger.success(f"共更新{len(serverId_list)}个私服详细信息，耗时{round(time.time() - time_start, 2)}秒")


# 天眼查
@listen(GroupMessage)
@dispatch(
    Twilight(
        [
            UnionMatch("-天眼查").space(SpacePolicy.PRESERVE),
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
async def tyc(
        app: Ariadne,
        sender: Member,
        group: Group,
        source: Source,
        player_name: RegexResult,
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

    await app.send_message(group, MessageChain(f"查询ing"), quote=source)
    send = [f'玩家名:{display_name}\n玩家Pid:{player_pid}\n' + "=" * 20 + '\n']
    # 查询最近游玩、vip/admin/owner/ban数、bfban信息、bfeac信息、正在游玩
    tasks = [
        (await BF1DA.get_api_instance()).mostRecentServers(player_pid),
        bfeac_checkBan(display_name),
        bfban_checkBan(player_pid),
        gt_checkVban(player_pid),
        (await BF1DA.get_api_instance()).getServersByPersonaIds(player_pid),
    ]
    tasks = await asyncio.gather(*tasks)

    # 最近游玩
    recent_play_data = tasks[0]
    if not isinstance(recent_play_data, str):
        recent_play_data: dict = recent_play_data
        send.append("最近游玩:\n")
        for data in recent_play_data["result"][:3]:
            send.append(f'{data["name"][:25]}\n')
        send.append("=" * 20 + '\n')

    vip_count = await BF1DB.get_playerVip(player_pid)
    admin_count = await BF1DB.get_playerAdmin(player_pid)
    owner_count = await BF1DB.get_playerOwner(player_pid)
    ban_count = await BF1DB.get_playerBan(player_pid)
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
        send.append(f'状态:{bfban_data["status"]}\n' + f"案件地址:{bfban_data['url']}\n" if bfban_data.get("url") else "")
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

    # 正在游玩
    playing_data = tasks[4]
    if not isinstance(playing_data, str):
        playing_data: dict = playing_data["result"]
        send.append("正在游玩:\n")
        if not playing_data[f"{player_pid}"]:
            send.append("玩家未在线/未进入服务器游玩")
        else:
            send.append(playing_data[f"{player_pid}"])
        send.append("=" * 20 + '\n')

    return await app.send_message(group, MessageChain(f"{''.join(send)}"), quote=source)


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
                "你知道吗,小埋最初的灵感来自于胡桃-by水神",
                f"当武器击杀达到40⭐图片会发出白光,60⭐时为紫光,当达到100⭐之后会发出耀眼的金光~",
            ]
            send = random.choice(bf_dic)
        await app.send_message(event.group_id, MessageChain([At(event.supplicant), f"{send}"]))


# 战地一私服情况
@listen(GroupMessage)
@dispatch(
    Twilight(
        [
            UnionMatch("-bf1", "-bfstat").space(SpacePolicy.PRESERVE),
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
async def bf1_server_info_check(app: Ariadne, group: Group, source: Source):
    result = await gt_bf1_stat()
    if not isinstance(result, str):
        return await app.send_message(group, MessageChain(f"查询出错!{result}"), quote=source)
    return await app.send_message(group, MessageChain(f"{result}"), quote=source)
