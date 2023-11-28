import asyncio
from pathlib import Path

from creart import create
from graia.ariadne.app import Ariadne
from graia.ariadne.event.message import GroupMessage, MessageEvent
from graia.ariadne.event.mirai import BotInvitedJoinGroupRequestEvent
from graia.ariadne.message.chain import MessageChain
from graia.ariadne.message.element import At, Source
from graia.ariadne.message.parser.twilight import (
    Twilight,
    UnionMatch,
    SpacePolicy,
    ElementMatch,
    FullMatch,
    ElementResult, ArgumentMatch, MatchResult, ParamMatch, RegexResult
)
from graia.ariadne.model import Group, Member
from graia.ariadne.util.interrupt import FunctionWaiter
from graia.ariadne.util.saya import listen, decorate, dispatch
from graia.saya import Channel, Saya
from loguru import logger

from core.config import GlobalConfig
from core.control import (
    Permission,
    Function,
    FrequencyLimitation,
    Distribute,
    QuoteReply
)
from core.models import (
    saya_model,
    response_model
)

module_controller = saya_model.get_module_controller()
account_controller = response_model.get_acc_controller()
global_config = create(GlobalConfig)
saya = Saya.current()
channel = Channel.current()
#channel.name("QQ群管")
#channel.description("简易的qq群管理功能")
#channel.author("13")
channel.metadata = module_controller.get_metadata_from_path(Path(__file__))


# 处理BOT被邀请加群事件
@listen(BotInvitedJoinGroupRequestEvent)
async def invited_event(app: Ariadne, event: BotInvitedJoinGroupRequestEvent):
    """处理邀请
    """
    if (event.supplicant in await Permission.get_BotAdminsList()) or event.supplicant == global_config.Master:
        await event.accept('已同意您的邀请~')
        return await app.send_message(await app.get_group(global_config.test_group), MessageChain(
            f"成员{event.nickname}({event.supplicant})邀请bot加入群:\n{event.group_name}({event.source_group})\n"
            f'已自动同意该管理的邀请'
        ))
    group = await app.get_group(global_config.test_group)
    if group is None:
        member = await app.get_friend(global_config.Master)
        bot_message = await app.send_message(member, MessageChain(
            f"成员{event.nickname}({event.supplicant})邀请bot加入群:\n{event.group_name}({event.source_group})\n"
            f'是否同意该申请，请在1小时内回复“y”或“n”'
        ))
    else:
        bot_message = await app.send_message(group, MessageChain(
            f"成员{event.nickname}({event.supplicant})邀请bot加入群:\n{event.group_name}({event.source_group})\n"
            f'是否同意该申请，请在1小时内回复“y”或“n”'
        ))

    async def waiter(waiter_member: Member, waiter_message: MessageChain, waiter_group: Group,
                     event_waiter: GroupMessage):
        if await Permission.require_user_perm(waiter_group.id, waiter_member.id,
                                              Permission.GroupAdmin) and group.id == waiter_group.id \
                and event_waiter.quote and event_waiter.quote.id == bot_message.id:
            saying = waiter_message.replace(At(app.account), "").display.strip()
            if saying == 'y':
                return True, waiter_member.id
            elif saying == 'n':
                return False, waiter_member.id
            elif saying.startswith("n"):
                saying.replace("n", "")
                return False, waiter_member.id

    try:
        result, admin = await FunctionWaiter(waiter, [GroupMessage]).wait(timeout=3600)
    except asyncio.exceptions.TimeoutError:
        await event.reject("拒绝了你的入群邀请!")
        return await app.send_message(group, MessageChain(
            f'处理 {event.nickname}({event.supplicant}) 的入群邀请已自动拒绝'))

    if result:
        await event.accept('已同意您的邀请~')  # 同意入群
        await app.send_message(group, MessageChain(
            f'已同意 {event.nickname}({event.supplicant}) 的入群邀请'))
    else:
        await event.reject(f'BOT拒绝了你的入群邀请!')  # 拒绝
        await app.send_message(group, MessageChain(
            f'已拒绝 {event.nickname}({event.supplicant}) 的入群邀请'))


# 添加群精华消息
@listen(GroupMessage)
@decorate(
    Distribute.require(),
    QuoteReply.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.user_require(Permission.GroupAdmin, if_noticed=True),
    Permission.group_require(channel.metadata.level, if_noticed=True),
)
@dispatch(
    Twilight([
        "at" @ ElementMatch(At, optional=True).space(SpacePolicy.PRESERVE),
        UnionMatch("加精", "设精")
    ])
)
async def set_essence(app: Ariadne, group: Group, event: MessageEvent, source: Source):
    target_app, target_group = await account_controller.get_app_from_total_groups(group.id, ["Administrator", "Owner"])
    if not (target_app and target_group):
        return await app.send_message(
            group, MessageChain("bot权限不足!/获取群权限信息失败!"), quote=source
        )
    app = target_app
    group = target_group
    quote_id = event.quote.id
    try:
        await app.set_essence(quote_id)
    except Exception as e:
        logger.error(e)
        return await app.send_message(group, MessageChain("出错力!"), quote=source)

    return await app.send_message(group, MessageChain("加精成功"), quote=source)


# TODO 撤回 quote.id   recall
@listen(GroupMessage)
@decorate(
    Distribute.require(),
    QuoteReply.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.user_require(Permission.GroupAdmin, if_noticed=True),
    Permission.group_require(channel.metadata.level, if_noticed=True),
)
@dispatch(
    Twilight([
        "at" @ ElementMatch(At, optional=True).space(SpacePolicy.PRESERVE),
        FullMatch("撤回")
    ])
)
async def recall(app: Ariadne, group: Group, event: GroupMessage, source: Source):
    target_app, target_group = await account_controller.get_app_from_total_groups(group.id, ["Administrator", "Owner"])
    if not (target_app and target_group):
        return await app.send_message(group, MessageChain("bot权限不足!"), quote=source)
    quote_id = event.quote.id
    app: Ariadne = target_app
    group: Group = target_group
    try:
        await app.recall_message(quote_id)
    except Exception as e:
        logger.error(e)
        return await app.send_message(group, MessageChain(
            f"执行出错/bot权限不足!"
        ), quote=source)


# TODO 禁言 @qq 禁言
@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.user_require(Permission.GroupAdmin, if_noticed=True),
    Permission.group_require(channel.metadata.level, if_noticed=True),
)
@dispatch(
    Twilight([
        "at" @ ElementMatch(At, optional=True).space(SpacePolicy.PRESERVE),
        FullMatch("禁言"),
        "expire_time" @ ArgumentMatch("-t", "--time", type=int, default=2, optional=True)
    ])
)
async def mute(app: Ariadne, group: Group, event: GroupMessage, source: Source, at: ElementResult,
               expire_time: MatchResult):
    expire_time = expire_time.result * 60
    if expire_time > 30 * 24 * 60 * 60 or expire_time <= 0:
        return await app.send_message(
            group,
            MessageChain("时间非法!范围(分钟): `0 < time <= 43200`"),
            quote=source,
        )
    target_app, target_group = await account_controller.get_app_from_total_groups(group.id, ["Administrator", "Owner"])
    if not (target_app and target_group):
        return await app.send_message(group, MessageChain("bot权限不足!"), quote=source)
    app: Ariadne = target_app
    group: Group = target_group
    if at.matched:
        _target: At = at.result
        _target = _target.target
        if await Permission.require_user_perm(group.id, _target, 32):
            return await app.send_message(
                group, MessageChain("bot权限不足!(目标权限>=32)"), quote=source
            )
        if _target == app.account:
            return await app.send_message(
                group, MessageChain("禁言bot?给你一棒槌!"), quote=source
            )
        try:
            await app.mute_member(group, _target, expire_time)
            return await app.send_message(group, MessageChain(
                f"已设置【{_target}】{expire_time // 60}分钟的禁言!" if expire_time >= 60 else
                f"已设置【{_target}】{expire_time}秒的禁言!"
            ))
        except Exception as e:
            logger.error(e)
            return await app.send_message(group, MessageChain("设置禁言出错啦!"), quote=source)
    if event.quote:
        target_id = event.quote.sender_id
        if target_id == app.account:
            return await app.send_message(
                group, MessageChain("禁言bot?给你一棒槌!"), quote=source
            )
        if await Permission.require_user_perm(group.id, target_id, 32):
            return await app.send_message(
                group, MessageChain("bot权限不足!(目标权限>=32)"), quote=source
            )
        try:
            await app.mute_member(group, event.quote.sender_id, expire_time)
            return await app.send_message(group, MessageChain(
                f"已设置【{target_id}】{expire_time // 60}分钟的禁言!" if expire_time >= 60 else
                f"已设置【{target_id}】{expire_time}秒的禁言!"
            ), quote=source)
        except Exception as e:
            logger.error(e)
            return await app.send_message(group, MessageChain("设置禁言出错啦!"), quote=source)
    return


@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.user_require(Permission.GroupAdmin, if_noticed=True),
    Permission.group_require(channel.metadata.level, if_noticed=True),
)
@dispatch(
    Twilight([
        "at" @ ElementMatch(At, optional=True).space(SpacePolicy.PRESERVE),
        FullMatch("解禁")
    ])
)
async def unmute(app: Ariadne, group: Group, event: GroupMessage, source: Source, at: ElementResult):
    target_app, target_group = await account_controller.get_app_from_total_groups(group.id, ["Administrator", "Owner"])
    if not (target_app and target_group):
        return await app.send_message(group, MessageChain("bot权限不足!"), quote=source)
    app: Ariadne = target_app
    group: Group = target_group
    if at.matched:
        _target: At = at.result
        _target = _target.target
        try:
            await app.unmute_member(group, _target)
            return await app.send_message(group, MessageChain(f"已解禁{_target}!"), quote=source)
        except Exception as e:
            logger.error(e)
            return await app.send_message(group, MessageChain("设置禁言出错啦!"), quote=source)
    if event.quote:
        target_id = event.quote.sender_id
        try:
            await app.unmute_member(group, target_id)
            return await app.send_message(group, MessageChain(f"已解禁{target_id}!"), quote=source)
        except Exception as e:
            logger.error(e)
            return await app.send_message(group, MessageChain("处理禁言出错啦!"), quote=source)
    return


@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.user_require(Permission.GroupAdmin, if_noticed=True),
    Permission.group_require(channel.metadata.level, if_noticed=True),
)
@dispatch(
    Twilight([
        FullMatch("全体禁言")
    ])
)
async def mute_all(app: Ariadne, group: Group, sender: Member, source: Source):
    if sender.permission.name == "Member":
        return await app.send_message(
            group, MessageChain("只有群管理员/群主才能操作哦~"), quote=source
        )
    target_app, target_group = await account_controller.get_app_from_total_groups(group.id, ["Administrator", "Owner"])
    if not (target_app and target_group):
        return await app.send_message(group, MessageChain("bot权限不足!"), quote=source)
    app: Ariadne = target_app
    group: Group = target_group
    try:
        await app.mute_all(group)
        return await app.send_message(group, MessageChain(
            "开启全体禁言成功!"
        ), quote=source)
    except Exception as e:
        logger.error(e)
        return await app.send_message(group, MessageChain("设置禁言出错啦!"), quote=source)


@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.user_require(Permission.GroupAdmin, if_noticed=True),
    Permission.group_require(channel.metadata.level, if_noticed=True),
)
@dispatch(
    Twilight([
        FullMatch("关闭全体禁言")
    ])
)
async def unmute_all(app: Ariadne, group: Group, sender: Member, source: Source):
    if sender.permission.name == "Member":
        return await app.send_message(
            group, MessageChain("只有群管理员/群主才能操作哦~"), quote=source
        )
    target_app, target_group = await account_controller.get_app_from_total_groups(group.id, ["Administrator", "Owner"])
    if not (target_app and target_group):
        return await app.send_message(group, MessageChain("bot权限不足!"), quote=source)
    app: Ariadne = target_app
    group: Group = target_group
    try:
        await app.unmute_all(group)
        return await app.send_message(group, MessageChain(
            "关闭全体禁言成功!"
        ), quote=source)
    except Exception as e:
        logger.error(e)
        return await app.send_message(group, MessageChain(
            f"处理出错啦!"
        ), quote=source)


# 指定BOT退群
@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.user_require(Permission.BotAdmin, if_noticed=True),
    Permission.group_require(channel.metadata.level, if_noticed=False),
)
@dispatch(
    # 指令为: -quit group_id bot_id
    Twilight([
        FullMatch("-quit"),
        ParamMatch(optional=False).space(SpacePolicy.FORCE) @ "group_id",
        ParamMatch(optional=False).space(SpacePolicy.PRESERVE) @ "bot_id"
    ])
)
async def quit_group(
        app: Ariadne, group: Group, source: Source,
        group_id: RegexResult, bot_id: RegexResult
):
    group_id = group_id.result.display
    if not group_id.isdigit():
        return await app.send_message(group, MessageChain(
            f"群号必须为数字!"
        ), quote=source)
    else:
        group_id = int(group_id)
    bot_id = bot_id.result.display
    if not bot_id.isdigit():
        return await app.send_message(group, MessageChain(
            f"BOT账号必须为数字!"
        ), quote=source)
    else:
        bot_id = int(bot_id)
    # 获取目标群和目标BOT
    target_app, target_group = await account_controller.get_app_from_total_groups(group_id, bot_id=bot_id)
    if not (target_app and target_group):
        return await app.send_message(group, MessageChain(
            f"没有找到目标群和BOT!"
        ), quote=source)
    try:
        _ = await target_app.quit_group(target_group)
        return await app.send_message(group, MessageChain(
            f"BOT{target_app.account}已退出群{target_group.id}!"
        ), quote=source)
    except Exception as e:
        logger.error(e)
        return await app.send_message(group, MessageChain(
            f"退出群失败!"
        ), quote=source)
