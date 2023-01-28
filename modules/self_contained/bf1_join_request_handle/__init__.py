import asyncio
from pathlib import Path

from graia.ariadne.app import Ariadne
from graia.ariadne.event.message import GroupMessage
from graia.ariadne.event.mirai import MemberJoinRequestEvent
from graia.ariadne.message.chain import MessageChain
from graia.ariadne.message.element import At
from graia.ariadne.model import Group, Member
from graia.ariadne.util.interrupt import FunctionWaiter
from graia.ariadne.util.saya import listen
from graia.saya import Channel
from loguru import logger

from core.control import (
    Permission
)
from core.models import saya_model, response_model
from .utils import getPid_byName, tyc_bfeac_api

account_controller = response_model.get_acc_controller()
module_controller = saya_model.get_module_controller()
channel = Channel.current()
channel.name("BF1入群审核")
channel.description("处理群加群审核")
channel.author("13")
channel.metadata = module_controller.get_metadata_from_path(Path(__file__))


@listen(MemberJoinRequestEvent)
async def join_handle(app: Ariadne, event: MemberJoinRequestEvent):
    """
    :param app: 实例
    :param event: 有人申请加群
    :return:
    """
    group = await app.get_group(event.source_group)
    if not module_controller.if_module_switch_on(channel.module, group):
        return
    if app.account != await account_controller.get_response_account(group.id):
        return
    # 先解析加群信息
    application_message = event.message
    application_answer = application_message[application_message.find("答案：") + 3:] \
        if application_message.find("答案：") != -1 else None
    verify = ""
    if application_answer and (application_answer < u'\u4e00' or application_answer > u'\u9fff'):
        player_info = await getPid_byName(application_answer)
        if player_info['personas'] == {}:
            verify = "无效ID"
        else:
            eac_stat_dict = {
                0: "未处理",
                1: "已封禁",
                2: "证据不足",
                3: "自证通过",
                4: "自证中",
                5: "刷枪",
            }
            player_name = player_info['personas']['persona'][0]['displayName']
            try:
                eac_response = eval((await tyc_bfeac_api(player_name)).text)
                if eac_response["data"] != "":
                    data = eac_response["data"][0]
                    eac_status = eac_stat_dict[data["current_status"]]
                    if eac_status == "已封禁":
                        verify = "该ID已被实锤"
                    else:
                        verify = "有效ID" if player_name else "无效ID"
                else:
                    verify = "有效ID" if player_name else "无效ID"
            except Exception as e:
                logger.error(f"查询eac信息时出错!{e}")
                verify = "有效ID" if player_name else "查询失败"
        application_answer = f"{application_message}({verify})"

    # 如果有application_answer且verify为有效ID且开启了自动过审则自动同意
    if application_answer and verify == "有效ID" and \
            module_controller.if_module_switch_on("modules.self_contained.auto_agree_join_request", group):
        await event.accept()
        return await app.send_message(
            group,
            MessageChain(
                f"收到来自{event.nickname}({event.supplicant})的加群申请,信息如下:"
                f"{application_answer}\n"
                f"已自动审核通过有效ID"
            )
        )

    # 然后发送消息到群里,如果bot有群管理权限则用waiter，超时时间为20分钟，发送申请消息
    bot_msg = await app.send_message(
        group,
        MessageChain(f"收到来自{event.nickname}({event.supplicant})的加群申请,信息如下:"
                     f"\n{application_answer if application_answer else application_message}"
                     f"\n‘回复’本消息‘y’可同意该申请"
                     f"\n‘回复’本消息其他文字可作为理由拒绝"
                     f"\n请在十分钟内处理")
    )

    async def waiter(
            waiter_member: Member, waiter_message: MessageChain, waiter_group: Group, event_waiter: GroupMessage
    ):
        try:
            await app.get_member(waiter_group, event.supplicant)
            join_judge = True
        except:
            join_judge = False
        if not join_judge:
            if event.source_group == waiter_group.id and event_waiter.quote and event_waiter.quote.id == bot_msg.id \
                    and await Permission.require_user_perm(waiter_group.id, waiter_member.id, Permission.GroupAdmin):
                saying = waiter_message.replace(At(app.account), "").display.strip()
                if saying == 'y':
                    return True, None
                else:
                    return False, saying

    # 接收回复消息，如果为y则同意，如果不为y则以该消息拒绝
    try:
        return_info = await FunctionWaiter(waiter, [GroupMessage]).wait(timeout=600)
    except asyncio.exceptions.TimeoutError:
        try:
            return await app.get_member(group, event.supplicant)
        except:
            return await app.send_message(
                group,
                MessageChain(f'注意:由于超时未审核，处理 {event.nickname}({event.supplicant}) 的入群请求已失效')
            )

    if return_info:
        result, reason = return_info
    else:
        result = reason = None
    if result:
        await event.accept()  # 同意入群
        return await app.send_message(group, MessageChain(
            f'已同意 {event.nickname}({event.supplicant}) 的入群请求'), )
    elif result is False:
        await event.reject(reason if reason else "")  # 拒绝入群
        return await app.send_message(group, MessageChain(
            f'已拒绝 {event.nickname}({event.supplicant}) 的入群请求'
        ))
    else:
        pass
