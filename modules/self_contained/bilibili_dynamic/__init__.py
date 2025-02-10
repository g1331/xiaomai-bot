import asyncio
import json
import re
import time
from pathlib import Path

from creart import create
from graia.ariadne.app import Ariadne
from graia.ariadne.event.lifecycle import ApplicationLaunched
from graia.ariadne.event.message import GroupMessage
from graia.ariadne.event.mirai import BotLeaveEventActive, BotLeaveEventKick
from graia.ariadne.message.chain import MessageChain
from graia.ariadne.message.element import Image, Plain, Source
from graia.ariadne.message.parser.twilight import (
    Twilight,
    FullMatch,
    RegexResult,
    WildcardMatch,
)
from graia.ariadne.model import Group
from graia.ariadne.util.saya import listen, decorate, dispatch
from graia.saya import Channel
from graia.saya.builtins.broadcast.schema import ListenerSchema
from graia.scheduler import timers
from graia.scheduler.saya.schema import SchedulerSchema
from graia.scheduler.timers import every_custom_seconds
from loguru import logger

from core.config import GlobalConfig
from core.control import (
    Permission,
    Function,
    FrequencyLimitation,
    Distribute
)
from core.models import saya_model, response_model
from utils.text2img import md2img
from .bilibili_request import get_status_info_by_uids
from .dynamic_shot import get_dynamic_screenshot
from .grpc.req import grpc_dyn_get

module_controller = saya_model.get_module_controller()
account_controller = response_model.get_acc_controller()
global_config = create(GlobalConfig)
channel = Channel.current()
channel.metadata = module_controller.get_metadata_from_path(Path(__file__))
channel.meta["name"] = "Bilibili推送"
channel.meta["description"] = "Bilibili直播、动态推送"
channel.meta["author"] = "十三"

HOME = Path(__file__).parent
DYNAMIC_OFFSET = {}
LIVE_STATUS = {}
NONE = False

head = {
    "user-agent": (
        "Mozilla/5.0 (Windows NT 6.1) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/41.0.2228.0 "
        "Safari/537.36"
    ),
    "Referer": "https://www.bilibili.com/",
}
dynamic_list_json = HOME.joinpath("dynamic_list.json")
if dynamic_list_json.exists():
    with dynamic_list_json.open("r") as f:
        dynamic_list = json.load(f)
else:
    with dynamic_list_json.open("w") as f:
        dynamic_list = {"subscription": {}}
        json.dump(dynamic_list, f, indent=2)

bot_master = global_config.Master


def get_group_sub(groupid):
    return sum(
        groupid in dynamic_list["subscription"][subuid]
        for subuid in dynamic_list["subscription"]
    )


def get_group_sublist(groupid):
    return [
        subuid
        for subuid in dynamic_list["subscription"]
        if groupid in dynamic_list["subscription"][subuid]
    ]


def get_subid_list():
    """获取所有的订阅"""
    return list(dynamic_list["subscription"])


async def add_uid(uid, groupid):
    pattern = re.compile("^[0-9]*$|com/([0-9]*)")
    if match := pattern.search(uid):
        uid = match[1] or match[0]
    else:
        return Plain("请输入正确的 UP UID 或 首页链接")

    r = await grpc_dyn_get(uid)
    if not r:
        return Plain(f"该UP（{uid}）未发布任何动态，订阅失败")
    up_name = r["list"][0]["modules"][0]["module_author"]["author"]["name"]
    uid_sub_group = dynamic_list["subscription"].get(uid, [])
    if groupid in uid_sub_group:
        return Plain(f"本群已订阅UP {up_name}（{uid}）")
    if uid not in dynamic_list["subscription"]:
        LIVE_STATUS[uid] = False
        dynamic_list["subscription"][uid] = []
        last_dynid = r["list"][0]["extend"]["dyn_id_str"]
        DYNAMIC_OFFSET[uid] = int(last_dynid)
    if get_group_sub(groupid) == 10:
        return Plain("每个群聊最多仅可订阅 10 个 UP")
    dynamic_list["subscription"][uid].append(groupid)
    with dynamic_list_json.open("w", encoding="utf-8") as file:
        json.dump(dynamic_list, file, indent=2)
    return Plain(f"成功在本群订阅UP {up_name}（{uid}）")


async def remove_uid(uid, groupid):
    pattern = re.compile("^[0-9]*$|com/([0-9]*)")
    if match := pattern.search(uid):
        uid = match[1] or match[0]
    else:
        return Plain("请输入正确的 UP UID 或 首页链接")

    uid_sub_group = dynamic_list["subscription"].get(uid, [])
    if groupid not in uid_sub_group:
        return Plain(f"本群未订阅该UP（{uid}）")
    dynamic_list["subscription"][uid].remove(groupid)
    if not dynamic_list["subscription"][uid]:
        del dynamic_list["subscription"][uid]
    with open(str(Path(__file__).parent / "dynamic_list.json"), "w", encoding="utf-8") as file:
        json.dump(dynamic_list, file, indent=2)
    r = await grpc_dyn_get(uid)
    up_name = r["list"][0]["modules"][0]["module_author"]["author"]["name"] if r else ""
    return Plain(f"退订{up_name}（{uid}）成功")


def delete_uid(uid):
    del dynamic_list["subscription"][uid]
    with open(str(Path(__file__).parent / "dynamic_list.json"), "w", encoding="utf-8") as file:
        json.dump(dynamic_list, file, indent=2)


@channel.use(ListenerSchema(listening_events=[ApplicationLaunched]))
async def init():
    global NONE

    subid_list = get_subid_list()
    sub_num = len(subid_list)
    if sub_num == 0:
        NONE = True
        await asyncio.sleep(1)
        logger.info("[BiliBili推送] 由于未订阅任何账号，本次初始化结束")
        return
    await asyncio.sleep(1)
    logger.info(f"[BiliBili推送] 将对 {sub_num} 个账号进行监控")
    info_msg = [f"[BiliBili推送] 将对 {sub_num} 个账号进行监控"]
    data = {"uids": subid_list}
    r = await get_status_info_by_uids(data)
    for uid_statu in r["data"]:
        LIVE_STATUS[uid_statu] = r["data"][uid_statu]["live_status"] == 1
    i = 1
    for counter, up_id in enumerate(subid_list):
        res = None
        for _ in range(3):
            res = await grpc_dyn_get(up_id)
            if res:
                break
            await asyncio.sleep(10)
        if not res:
            app = Ariadne.current(global_config.default_account)
            master = await app.get_friend(bot_master)
            await app.send_message(
                master,
                MessageChain("哔哩哔哩推送初始化失败!"),
            )
            return logger.error("[BiliBili推送] 寄！")
        last_dynid = res["list"][0]["extend"]["dyn_id_str"]
        DYNAMIC_OFFSET[up_id] = int(last_dynid)
        up_name = res["list"][0]["modules"][0]["module_author"]["author"]["name"]
        if len(str(i)) == 1:
            si = f"  {i}"
        elif len(str(i)) == 2:
            si = f" {i}"
        else:
            si = i
        live_status = " > 已开播" if LIVE_STATUS.get(up_id, False) else ""
        info_msg.append(f"    ● {si}  ---->  {up_name}({up_id}){live_status}")
        logger.info(f"[BiliBili推送] 正在初始化  ● {si}  ---->  {up_name}({up_id}){live_status}")
        i += 1
        if (counter+1) % 25 == 0:
            await asyncio.sleep(300)
        else:
            await asyncio.sleep(1)

    NONE = True
    await asyncio.sleep(1)

    if i - 1 != sub_num:
        info_msg.append(f"[BiliBili推送] 共有 {sub_num - i + 1} 个账号无法获取最近动态，暂不可进行监控，已从列表中移除")
    for msg in info_msg:
        logger.info(msg)

    image = await md2img(
        "\n\n".join(info_msg),
        page_option={
            "viewport": {
                "width": 600,
                "height": 10},
            "device_scale_factor": 1.5,
            "color_scheme": "dark"}
    )
    app = Ariadne.current(global_config.default_account)
    master = await app.get_friend(bot_master)
    await app.send_message(
        master,
        MessageChain([Image(data_bytes=image)]),
    )


# 主动推送主程序
@channel.use(SchedulerSchema(timers.every_custom_seconds(45)))
async def main_update_scheduled():
    if not NONE:
        logger.info("[BiliBili推送] 初始化未完成，终止本次更新")
        return
    elif len(dynamic_list["subscription"]) == 0:
        logger.info("[BiliBili推送] 由于未订阅任何账号，本次更新已终止")
        return

    sub_list = dynamic_list["subscription"].copy()
    sub_id_list = get_subid_list()
    post_data = {"uids": sub_id_list}
    logger.info(f"[BiliBili推送] 开始本轮检测,预计检测{len(sub_list)}位UP主")
    time_start = time.time()
    logger.info("[BiliBili推送] 正在检测直播更新")
    live_status = await get_status_info_by_uids(post_data)
    # 推送直播
    for up_id in live_status["data"]:
        title = live_status["data"][up_id]["title"]
        room_id = live_status["data"][up_id]["room_id"]
        room_area = (
                live_status["data"][up_id]["area_v2_parent_name"]
                + " / "
                + live_status["data"][up_id]["area_v2_name"]
        )
        up_name = live_status["data"][up_id]["uname"]
        cover_from_user = live_status["data"][up_id]["cover_from_user"]

        if live_status["data"][up_id]["live_status"] == 1:
            if up_id not in LIVE_STATUS:
                LIVE_STATUS[up_id] = False
            if not LIVE_STATUS[up_id]:
                LIVE_STATUS[up_id] = True
                logger.info(f"[BiliBili推送] {up_name} 开播了 - {room_area} - {title}")
                for groupid in sub_list[up_id]:
                    target_app, target_group = await account_controller.get_app_from_total_groups(groupid)
                    if not (target_app and target_group):
                        remove_list = []
                        for subid in get_group_sublist(groupid):
                            # await remove_uid(subid, groupid)
                            remove_list.append(subid)
                        logger.info(
                            f"[BiliBili推送] 推送失败，找不到该群 {groupid}，已跳过该群订阅的 {len(remove_list)} 个UP"
                        )
                    else:
                        if module_controller.if_module_switch_on(channel.module, target_group):
                            await target_app.send_group_message(
                                target_group,
                                MessageChain(
                                    f"本群订阅的UP:{up_name}(UID:{up_id})开播啦 ！\n"
                                    f"分区:{room_area}\n"
                                    f"标题:{title}\n",
                                    Image(url=cover_from_user),
                                    Plain(f"\nhttps://live.bilibili.com/{room_id}"),
                                ),
                            )
                        await asyncio.sleep(1)

        elif LIVE_STATUS[up_id]:
            LIVE_STATUS[up_id] = False
            logger.info(f"[BiliBili推送] {up_name} 已下播")
            for groupid in sub_list[up_id]:
                target_app, target_group = await account_controller.get_app_from_total_groups(groupid)
                if not (target_app and target_group):
                    remove_list = []
                    for subid in get_group_sublist(groupid):
                        # remove_uid(subid, groupid)
                        remove_list.append(subid)
                    logger.info(
                        f"[BiliBili推送] 推送失败，找不到该群 {groupid}，已跳过该群订阅的 {len(remove_list)} 个UP"
                    )
                else:
                    if module_controller.if_module_switch_on(channel.module, target_group):
                        await target_app.send_group_message(
                            target_group,
                            MessageChain(f"本群订阅的UP {up_name}（{up_id}）已下播！"),
                        )
    logger.info("[BiliBili推送] 直播检测完成")

    # 推送动态
    logger.info("[BiliBili推送] 正在检测动态更新")
    for up_id in sub_list:
        if r := await grpc_dyn_get(up_id):
            up_name = r["list"][0]["modules"][0]["module_author"]["author"]["name"]
            up_last_dynid = r["list"][0]["extend"]["dyn_id_str"]
            # logger.debug(f"[BiliBili推送] {up_name}(UID:{up_id})检测完成")
            if int(up_last_dynid) > DYNAMIC_OFFSET[up_id]:
                logger.info(f"[BiliBili推送] {up_name} 更新了动态 {up_last_dynid}")
                shot_image = await get_dynamic_screenshot(up_last_dynid)
                if shot_image:
                    for groupid in sub_list[up_id]:
                        target_app, target_group = await account_controller.get_app_from_total_groups(groupid)
                        if not (target_app and target_group):
                            remove_list = []
                            for subid in get_group_sublist(groupid):
                                # remove_uid(subid, groupid)
                                remove_list.append(subid)
                            logger.info(
                                f"[BiliBili推送] 推送失败，找不到该群 {groupid}，已跳过该群订阅的 {len(remove_list)} 个UP"
                            )
                            continue
                        try:
                            if module_controller.if_module_switch_on(channel.module, target_group):
                                await target_app.send_group_message(
                                    target_group,
                                    MessageChain(
                                        [
                                            Plain(f"本群订阅的UP {up_name}（{up_id}）更新动态啦！\n"),
                                            Image(data_bytes=shot_image),
                                            Plain(f"\nhttps://t.bilibili.com/{up_last_dynid}"),
                                        ]
                                    ),
                                )
                            await asyncio.sleep(1)
                        except Exception as e:
                            logger.info(f"[BiliBili推送] 推送失败，未知错误 {type(e)}")
                    DYNAMIC_OFFSET[up_id] = int(up_last_dynid)
                else:
                    logger.error(f"[BiliBili推送] {up_name} 动态截图尝试 3 次后仍失败，将在下次循环中重试")
            await asyncio.sleep(1)
        else:
            logger.warning("动态更新失败超过 3 次，已终止本次更新")
            break
    logger.info("[BiliBili推送] 动态检测完成")

    logger.info(f"[BiliBili推送] 本轮检测完成,耗时{(time.time() - time_start):.2f}秒")


@listen(GroupMessage)
@dispatch(
    Twilight([FullMatch("-订阅"), "anything" @ WildcardMatch(optional=True)])
)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level),
    Permission.user_require(Permission.GroupAdmin, if_noticed=True),
)
async def add_sub(group: Group, anything: RegexResult, app: Ariadne):
    if anything.matched:
        add = await add_uid(anything.result.display, group.id)
        await app.send_message(
            group,
            MessageChain(add),
        )


@listen(GroupMessage)
@dispatch(
    Twilight([FullMatch("-退订"), "anything" @ WildcardMatch(optional=True)])
)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level),
    Permission.user_require(Permission.GroupAdmin, if_noticed=True),
)
async def remove_sub(group: Group, anything: RegexResult, app: Ariadne):
    if anything.matched:
        await app.send_message(
            group,
            MessageChain([await remove_uid(anything.result.display, group.id)]),
        )


@listen(GroupMessage)
@dispatch(
    Twilight(FullMatch("-本群订阅列表"))
)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level),
    Permission.user_require(Permission.User, if_noticed=True),
)
async def get_sub_list(group: Group, app: Ariadne, source: Source):
    sublist = list(get_group_sublist(group.id))
    sublist_count = len(sublist)
    i = 1
    info_msg = [f"本群共订阅 {sublist_count} 个 UP"]
    for up_id in sublist:
        res = await grpc_dyn_get(up_id)
        if not res:
            logger.error("[BiliBili推送] 寄！")
            return
        last_dynid = res["list"][0]["extend"]["dyn_id_str"]
        DYNAMIC_OFFSET[up_id] = int(last_dynid)
        up_name = res["list"][0]["modules"][0]["module_author"]["author"]["name"]
        if len(str(i)) == 1:
            si = f"  {i}"
        elif len(str(i)) == 2:
            si = f" {i}"
        else:
            si = i
        live_status = " > 已开播" if LIVE_STATUS.get(up_id, False) else ""
        info_msg.append(f"{si}. {up_name}({up_id}){live_status}")
        i += 1
    sorted(info_msg)
    if sublist_count == 0:
        await app.send_message(group, MessageChain([Plain("本群未订阅任何 UP")]))
    else:
        await app.send_message(
            group,
            MessageChain(
                "\n".join(info_msg)
            ),
            quote=source
        )


@channel.use(ListenerSchema(listening_events=[BotLeaveEventActive, BotLeaveEventKick]))
async def bot_leave(group: Group):
    remove_list = []
    for subid in get_group_sublist(group.id):
        await remove_uid(subid, group.id)
        remove_list.append(subid)
    logger.info(
        f"[BiliBili推送] 检测到退群事件 > {group.name}({group.id})，已删除该群订阅的 {len(remove_list)} 个UP"
    )


@listen(GroupMessage)
@dispatch(
    Twilight([FullMatch("-查看动态"), "anything" @ WildcardMatch()])
)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level),
    Permission.user_require(Permission.User, if_noticed=True),
)
async def vive_dyn(group: Group, anything: RegexResult, app: Ariadne, src: Source):
    if not anything.matched:
        return
    pattern = re.compile("^[0-9]*$|com/([0-9]*)")
    if match := pattern.search(anything.result.display):
        uid = match[1] or match[0]
    else:
        return await app.send_message(
            group, MessageChain([Plain("请输入正确的 UP UID 或 首页链接")]), quote=src
        )

    res = await grpc_dyn_get(uid)
    if res:
        await app.send_message(
            group, MessageChain("查询ing"), quote=src
        )
        shot_image = await get_dynamic_screenshot(res["list"][0]["extend"]["dyn_id_str"])
        await app.send_message(
            group, MessageChain(
                Image(data_bytes=shot_image),
                Plain(f'\nhttps://t.bilibili.com/{res["list"][0]["extend"]["dyn_id_str"]}')
            ),
            quote=src
        )
    else:
        await app.send_message(group, MessageChain([Plain("该UP未发布任何动态")]), quote=src)
