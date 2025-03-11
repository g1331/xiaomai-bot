import asyncio
from pathlib import Path

from graia.ariadne.app import Ariadne
from graia.ariadne.event.message import GroupMessage
from graia.ariadne.event.mirai import MemberJoinEvent, MemberJoinRequestEvent
from graia.ariadne.message.chain import MessageChain
from graia.ariadne.message.element import At
from graia.ariadne.model import Group, Member, MemberInfo
from graia.ariadne.util.interrupt import FunctionWaiter
from graia.ariadne.util.saya import listen
from graia.saya import Channel
from loguru import logger

from core.control import Permission
from core.models import response_model, saya_model
from utils.bf1.bf_utils import bfeac_checkBan, check_bind, get_personas_by_name
from utils.bf1.database import BF1DB
from utils.bf1.default_account import BF1DA

module_controller = saya_model.get_module_controller()
account_controller = response_model.get_acc_controller()
channel = Channel.current()
channel.meta["name"] = "BF1入群审核"
channel.meta["description"] = "处理群加群审核"
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
        else:
            player_pid = player_info["personas"]["persona"][0]["personaId"]
            display_name = player_info["personas"]["persona"][0]["displayName"]
            verify = await check_verify(display_name, player_pid, event.supplicant)

        application_answer = f"{application_message}({verify})"

    # 如果有application_answer且verify为有效ID且开启了自动过审则自动同意
    if (
        application_answer
        and verify == "有效ID"
        and module_controller.if_module_switch_on(
            "modules.self_contained.auto_agree_join_request", group
        )
    ):
        await event.accept()
        return await app.send_message(
            group,
            MessageChain(
                f"收到来自{event.nickname}({event.supplicant})的加群申请,信息如下:"
                f"{application_answer}\n"
                f"已自动审核通过有效ID"
            ),
        )

    # 否则发送消息到群里,如果bot有群管理权限则用waiter，超时时间为20分钟，发送申请消息
    bot_msg = await app.send_message(
        group,
        MessageChain(
            f"收到来自{event.nickname}({event.supplicant})的加群申请,信息如下:"
            f"\n{application_answer if application_answer else application_message}"
            f"\n‘回复’本消息‘y’可同意该申请"
            f"\n‘回复’本消息其他文字可作为理由拒绝"
            f"\n请在20分钟内处理"
        ),
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
        except Exception as e:
            logger.error(f"获取成员信息失败: {e}")
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
            logger.error(f"获取成员信息失败: {e}")
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
        await event.reject(reason if reason else "")  # 拒绝入群
        return await app.send_message(
            group,
            MessageChain(f"已拒绝 {event.nickname}({event.supplicant}) 的入群请求"),
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
                group, MessageChain(At(member), f"已自动将你的名片修改为{display_name}")
            )
        except Exception as e:
            logger.error(f"自动修改名片时出错了!错误信息:{e}")
