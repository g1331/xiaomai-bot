import asyncio
import time
from pathlib import Path

from creart import create
from graia.amnesia.message import MessageChain
from graia.ariadne.app import Ariadne
from graia.ariadne.event.lifecycle import ApplicationLaunched
from graia.ariadne.event.message import GroupMessage, FriendMessage
from graia.ariadne.message.element import Source, Image
from graia.ariadne.message.parser.twilight import Twilight, UnionMatch, SpacePolicy, FullMatch, ParamMatch, \
    RegexResult, ArgumentMatch, ArgResult
from graia.ariadne.model import Group, Friend, Member
from graia.ariadne.util.saya import listen, dispatch, decorate
from graia.saya import Channel, Saya
from loguru import logger

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
from utils.bf1.orm import BF1DB
from utils.bf1.bf_utils import get_personas_by_name, check_bind, \
    BTR_get_recent_info, BTR_get_match_info, BTR_update_data

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
        (await BF1DA.get_api_instance()).getVehiclesByPersonaId(player_pid)
    ]
    await asyncio.gather(*tasks)

    # 检查返回结果
    player_stat, player_weapon, player_vehicle = tasks[0].result(), tasks[1].result(), tasks[2].result()
    if isinstance(player_stat, str):
        logger.error(player_stat)
        return await app.send_message(
            group,
            MessageChain(f"查询出错!{player_stat}"),
            quote=source
        )
    else:
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
        return await app.send_message(
            group,
            MessageChain(
                f"玩家名字:{display_name}"
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
                "冲锋枪", "副武器", "佩枪", "手枪", "近战", "突击兵", "土鸡兵", "土鸡", "突击",
                "侦察兵", "侦察", "斟茶兵", "斟茶", "医疗兵", "医疗", "支援兵", "支援"
            ).space(SpacePolicy.PRESERVE) @ "weapon_type",
            ParamMatch(optional=True) @ "player_name",
            ArgumentMatch("-r", "-row", action="store_true", optional=True, type=int, default=4) @ "row",
            ArgumentMatch("-c", "-col", action="store_true", optional=True, type=int, default=1) @ "col",
            ArgumentMatch("-s", "-search", action="store_true", optional=True) @ "weapon_name",
            ArgumentMatch("-t", "-type", action="store_true", optional=True) @ "sort_type",
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
                rule=weapon_type.result.display if weapon_type.matched else None,
                sort_type=sort_type.result.display if sort_type.matched else None,
            )
        else:
            player_weapon: list = WeaponData(player_weapon).search_weapon(weapon_name.result.display)

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
        result = [f"玩家名字: {display_name}"]
        for weapon in player_weapon:
            result.append(
                f"{weapon['name']}\n"
                f"击杀: {weapon['kills']}\n"
            )

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
            ArgumentMatch("-s", "-search", action="store_true", optional=True) @ "vehicle_name",
            ArgumentMatch("-t", "-type", action="store_true", optional=True) @ "sort_type",
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
                rule=vehicle_type.result.display if vehicle_type.matched else None,
                sort_type=sort_type.result.display if sort_type.matched else None,
            )
        else:
            player_vehicle: list = VehicleData(player_vehicle).search_vehicle(vehicle_name.result.display)

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
        return await app.send_message(
            group,
            MessageChain(
                f"玩家名字:{display_name}"
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
        result = [f"玩家名字: {display_name}\n" + "=" * 15]
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
        result = [f"玩家名字: {display_name}\n" + "=" * 15]
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
                        f"得分: {player['score']}\tPM: {player['spm']}\n"
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
    server_info = await (await BF1DA.get_api_instance()).searchServers(server_name)
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
            f"创建时间: {time.strftime('%Y-%m-%d %H:%M:%S',time.localtime(int(rspInfo['server']['createdDate']) / 1000))}\n"
            f"到期时间: {time.strftime('%Y-%m-%d %H:%M:%S',time.localtime(int(rspInfo['server']['expirationDate']) / 1000))}\n"
            f"更新时间: {time.strftime('%Y-%m-%d %H:%M:%S',time.localtime(int(rspInfo['server']['updatedDate']) / 1000))}\n"
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
