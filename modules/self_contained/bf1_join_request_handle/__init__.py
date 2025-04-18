import asyncio
from pathlib import Path

from graia.ariadne.app import Ariadne
from graia.ariadne.event.message import GroupMessage
from graia.ariadne.event.mirai import MemberJoinEvent, MemberJoinRequestEvent
from graia.ariadne.message.chain import MessageChain
from graia.ariadne.message.element import At, Image
from graia.ariadne.model import Group, Member, MemberInfo
from graia.ariadne.util.interrupt import FunctionWaiter
from graia.ariadne.util.saya import listen
from graia.saya import Channel
from loguru import logger

from core.control import Permission
from core.models import response_model, saya_model
from utils.bf1.bf_utils import (
    bfban_checkBan,
    bfeac_checkBan,
    check_bind,
    get_personas_by_name,
    gt_get_player_id_by_pid,
)
from utils.bf1.database import BF1DB
from utils.bf1.default_account import BF1DA
from utils.bf1.draw import PlayerStatPic

module_controller = saya_model.get_module_controller()
account_controller = response_model.get_acc_controller()
channel = Channel.current()
channel.meta["name"] = "BF1入群审核"
channel.meta["description"] = "处理群加群审核，显示申请者战绩并在拒绝时显示理由"
channel.meta["author"] = "13"
channel.metadata = module_controller.get_metadata_from_path(Path(__file__))


async def check_verify(player_name, player_pid, qq) -> str:
    # 获取玩家生涯数据，如果时长为0则为无效，如果有效则查询eac
    player_stat = await (await BF1DA.get_api_instance()).detailedStatsByPersonaId(
        player_pid
    )
    if isinstance(player_stat, str):
        logger.error(player_stat)
        return "查询失败"
    else:
        player_stat = player_stat.get("result")
    timePlayed = player_stat.get("basicStats").get("timePlayed")
    if timePlayed == 0:
        return "有效橘子ID,但该ID没有游玩过BF1"
    eac_info = await bfeac_checkBan(player_name)
    if eac_info.get("stat") == "已封禁":
        ban_url = eac_info.get("url")
        verify = f"有效ID,但该ID已被EAC封禁!封禁地址:{ban_url}"
    else:
        verify = "有效ID"
        # 没有绑定就绑定
        if bind_info := await check_bind(qq):
            if isinstance(bind_info, str):
                return verify
            display_name = bind_info.get("displayName")
            # player_pid = bind_info.get("pid")
            if display_name.upper() != player_name.upper():
                return f"有效ID,但与其绑定ID不一致!绑定ID:{display_name}"
        else:
            await BF1DB.bf1account.bind_player_qq(qq, player_pid)
    return verify


@listen(MemberJoinRequestEvent)
async def join_handle(app: Ariadne, event: MemberJoinRequestEvent):
    """
    :param app: 实例
    :param event: 有人申请加群
    :return:
    """
    group = await app.get_group(event.source_group)
    if not module_controller.if_module_switch_on(
        "modules.self_contained.bf1_join_request_handle", group
    ):
        return
    if app.account != await account_controller.get_response_account(group.id):
        return
    # 先解析加群信息
    application_message = event.message
    application_answer = (
        application_message[application_message.find("答案：") + 3 :]
        if application_message.find("答案：") != -1
        else None
    )
    verify = ""
    if application_answer and (
        application_answer < "\u4e00" or application_answer > "\u9fff"
    ):
        # 查询玩家信息
        player_name = application_answer
        player_info = await get_personas_by_name(player_name)
        if isinstance(player_info, str):
            return await app.send_message(
                group,
                MessageChain(
                    f"收到来自{event.nickname}({event.supplicant})的加群申请，"
                    f"但是查询玩家信息时出错了，错误信息:{player_info}"
                ),
            )

        if not player_info:
            verify = "无效ID"
            application_answer = f"{application_message}({verify})"
        else:
            player_pid = player_info["personas"]["persona"][0]["personaId"]
            display_name = player_info["personas"]["persona"][0]["displayName"]
            verify = await check_verify(display_name, player_pid, event.supplicant)
            application_answer = f"{application_message}({verify})"

            # 如果是有效ID，获取并展示玩家战绩
            if verify == "有效ID" or verify.startswith("有效ID,但"):
                try:
                    # 获取玩家数据
                    api_instance = await BF1DA.get_api_instance()

                    # 并行获取所有需要的数据
                    player_weapon_task = api_instance.getWeaponsByPersonaId(player_pid)
                    player_vehicle_task = api_instance.getVehiclesByPersonaId(
                        player_pid
                    )
                    player_stat_task = api_instance.detailedStatsByPersonaId(player_pid)
                    player_persona_task = api_instance.getPersonasByIds(player_pid)
                    bfeac_info_task = bfeac_checkBan(player_pid)
                    bfban_info_task = bfban_checkBan(player_pid)
                    server_playing_info_task = api_instance.getServersByPersonaIds(
                        player_pid
                    )
                    platoon_info_task = api_instance.getActivePlatoon(player_pid)
                    skin_info_task = api_instance.getPresetsByPersonaId(player_pid)
                    gt_id_info_task = gt_get_player_id_by_pid(player_pid)

                    # 等待所有任务完成
                    tasks = await asyncio.gather(
                        player_persona_task,
                        player_stat_task,
                        player_weapon_task,
                        player_vehicle_task,
                        bfeac_info_task,
                        bfban_info_task,
                        server_playing_info_task,
                        platoon_info_task,
                        skin_info_task,
                        gt_id_info_task,
                    )

                    # 解包结果
                    (
                        player_persona,
                        player_stat,
                        player_weapon,
                        player_vehicle,
                        bfeac_info,
                        bfban_info,
                        server_playing_info,
                        platoon_info,
                        skin_info,
                        gt_id_info,
                    ) = tasks

                    # 确保玩家名称正确
                    player_stat["result"]["displayName"] = display_name

                    # 生成战绩图片
                    start_time = asyncio.get_event_loop().time()
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
                        gt_id_info=gt_id_info,
                    ).draw()

                    # 计算耗时
                    time_used = round(asyncio.get_event_loop().time() - start_time, 2)
                    logger.debug(f"生成玩家战绩图片耗时: {time_used}秒")

                    # 准备战绩图片和额外信息
                    # 如果有BFEAC或BFBAN信息，添加到消息中
                    bfeac_msg = (
                        f"\nBFEAC状态: {bfeac_info.get('stat')}\n案件地址: {bfeac_info.get('url')}"
                        if bfeac_info and bfeac_info.get("stat")
                        else ""
                    )

                    bfban_msg = (
                        f"\nBFBAN状态: {bfban_info.get('status')}\n案件地址: {bfban_info.get('url')}"
                        if bfban_info and bfban_info.get("status") != "正常"
                        else ""
                    )

                    # 保存战绩图片路径，稍后在申请消息中使用
                    stats_image_path = player_stat_img
                    stats_info = f"\n\n申请者BF1战绩数据（耗时: {time_used}秒）"
                    ban_info = ""
                    if bfeac_msg or bfban_msg:
                        ban_info = (
                            f"\n申请者BF1账号存在以下记录：{bfeac_msg}{bfban_msg}"
                        )
                except Exception as e:
                    logger.error(f"获取申请者战绩时出错: {e}")
                    await app.send_message(
                        group,
                        MessageChain(f"获取申请者战绩时出错: {str(e)}"),
                    )

    # 如果有application_answer且verify为有效ID且开启了自动过审则自动同意
    if (
        application_answer
        and verify == "有效ID"
        and module_controller.if_module_switch_on(
            "modules.self_contained.auto_agree_join_request", group
        )
    ):
        await event.accept()

        # 准备自动审核通过的消息内容
        auto_accept_content = [
            f"收到来自{event.nickname}({event.supplicant})的加群申请,信息如下:"
            f"{application_answer}\n"
            f"已自动审核通过有效ID"
        ]

        # 如果有战绩图片，添加到消息中
        if "stats_image_path" in locals():
            auto_accept_content.append(stats_info)
            auto_accept_content.append(Image(path=stats_image_path))

            # 如果有封禁信息，也添加到消息中
            if "ban_info" in locals() and ban_info:
                auto_accept_content.append(ban_info)

        return await app.send_message(
            group,
            MessageChain(auto_accept_content),
        )

    # 否则发送消息到群里,如果bot有群管理权限则用waiter，超时时间为20分钟，发送申请消息
    message_content = [
        f"收到来自{event.nickname}({event.supplicant})的加群申请,信息如下:"
        f"\n{application_answer if application_answer else application_message}"
    ]

    # 如果有战绩图片，添加到消息中
    if "stats_image_path" in locals():
        message_content.append(stats_info)
        message_content.append(Image(path=stats_image_path))

        # 如果有封禁信息，也添加到消息中
        if "ban_info" in locals() and ban_info:
            message_content.append(ban_info)

    # 添加操作指引
    message_content.append(
        "\n'回复'本消息'y'可同意该申请"
        "\n'回复'本消息其他文字可作为理由拒绝"
        "\n请在20分钟内处理"
    )

    bot_msg = await app.send_message(
        group,
        MessageChain(message_content),
    )

    async def waiter(
        waiter_member: Member,
        waiter_message: MessageChain,
        waiter_group: Group,
        event_waiter: GroupMessage,
    ):
        try:
            await app.get_member(waiter_group, event.supplicant)
            join_judge = True
        except Exception:
            join_judge = False
        if not join_judge:
            if (
                event.source_group == waiter_group.id
                and event_waiter.quote
                and event_waiter.quote.id == bot_msg.id
                and await Permission.require_user_perm(
                    waiter_group.id, waiter_member.id, Permission.GroupAdmin
                )
            ):
                saying = waiter_message.replace(At(app.account), "").display.strip()
                if saying == "y":
                    return True, None
                else:
                    return False, saying

    # 接收回复消息，如果为y则同意，如果不为y则以该消息拒绝
    try:
        return_info = await FunctionWaiter(waiter, [GroupMessage]).wait(timeout=1200)
    except asyncio.exceptions.TimeoutError:
        try:
            return await app.get_member(group, event.supplicant)
        except Exception as e:
            logger.error(f"处理加群请求时出错了!错误信息:{e}")
            return await app.send_message(
                group,
                MessageChain(
                    f"注意:由于超时未审核，处理 {event.nickname}({event.supplicant}) 的入群请求已失效"
                ),
            )

    if return_info:
        result, reason = return_info
    else:
        result = reason = None
    if result:
        await event.accept()  # 同意入群
        return await app.send_message(
            group,
            MessageChain(f"已同意 {event.nickname}({event.supplicant}) 的入群请求"),
        )
    elif result is False:
        # 拒绝入群并显示拒绝理由
        reject_reason = reason if reason else ""
        await event.reject(reject_reason)  # 拒绝入群
        return await app.send_message(
            group,
            MessageChain(
                f"已拒绝 {event.nickname}({event.supplicant}) 的入群请求"
                + (f"\n拒绝理由: {reject_reason}" if reject_reason else "")
            ),
        )
    else:
        pass


@listen(MemberJoinEvent)
async def auto_modify(app: Ariadne, event: MemberJoinEvent):
    """
    自动修改名片为橘子id
    """
    member = event.member
    group = event.member.group
    if not module_controller.if_module_switch_on(channel.module, group):
        return
    target_app, target_group = await account_controller.get_app_from_total_groups(
        group.id, ["Administrator", "Owner"]
    )
    if not (target_app and target_group):
        return
    if app.account != target_app.account:
        return
    app = target_app
    group = target_group
    if bind_info := await check_bind(event.member.id):
        try:
            if isinstance(bind_info, str):
                return logger.error(f"查询绑定信息时出错了!错误信息:{bind_info}")
            display_name = bind_info.get("displayName")
            await app.modify_member_info(member, MemberInfo(name=display_name))
            return await app.send_message(
                group,
                MessageChain(At(member), f" 已自动将你的名片修改为{display_name}"),
            )
        except Exception as e:
            logger.error(f"自动修改名片时出错了!错误信息:{e}")
