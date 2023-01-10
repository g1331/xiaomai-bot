from pathlib import Path

from creart import create
from graia.ariadne.app import Ariadne
from graia.ariadne.event.message import GroupMessage
from graia.ariadne.message.chain import MessageChain
from graia.ariadne.message.element import Image, Source
from graia.ariadne.message.parser.twilight import (
    Twilight,
    FullMatch,
    ParamMatch,
    RegexResult, UnionMatch
)
from graia.ariadne.model import Group, Member
from graia.ariadne.util.saya import listen, dispatch, decorate
from graia.saya import Channel, Saya

from core.bot import Umaru
from core.config import GlobalConfig
from core.control import (
    Permission,
    Function,
    FrequencyLimitation,
    Distribute
)
from core.models import (
    saya_model,
    response_model
)
from utils.UI import *
from utils.image import get_user_avatar_url, get_img_base64_str

config = create(GlobalConfig)
core = create(Umaru)

module_controller = saya_model.get_module_controller()
account_controller = response_model.get_acc_controller()

saya = Saya.current()
channel = Channel.current()
channel.name("ResponseManager")
channel.description("负责响应管理(必须插件)")
channel.author("13")
channel.metadata = module_controller.get_metadata_from_path(Path(__file__))


# 查询拥有多个BOT的群，以及BOT列表
@listen(GroupMessage)
@decorate(
    Permission.user_require(Permission.BotAdmin, if_noticed=True),
    Permission.group_require(channel.metadata.level, if_noticed=True),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Distribute.require()
)
@dispatch(
    Twilight([
        FullMatch("在线BOT"),
        "group_id" @ ParamMatch(optional=True),
        # 示例: 在线BOT 000
    ])
)
async def get_response_BOT(app: Ariadne, group: Group, group_id: RegexResult, source: Source):
    group_id = int(group_id.result.display) if group_id.matched else group.id
    if group_id != group.id:
        target_app, target_group = await account_controller.get_app_from_total_groups(group_id)
        if not (target_app and target_group):
            return await app.send_message(group, MessageChain(
                f"没有找到目标群:{group_id}"
            ), quote=source)
    else:
        target_app = app
        target_group = group
    bot_member: Member = await target_app.get_member(target_group, target_app.account)
    type_now = await account_controller.get_response_type(group_id)
    if type_now == "random":
        type_now = "随机"
    else:
        response_bot = await account_controller.get_response_account(target_group.id)
        type_now = f"指定({response_bot})"

    bot_list_column = [
        ColumnUserInfo(
            name=f"{target_group.name}({target_group.id})",
            description=f"响应类型:{type_now}",
            avatar=get_img_base64_str(await target_group.get_avatar())
        ),
        ColumnTitle(title="BOT列表"),
        ColumnUserInfo(
            name=f"{bot_member.name}({bot_member.id})",
            description=f"{bot_member.permission}",
            avatar=await get_user_avatar_url(bot_member.id)
        )
    ]
    member_list = await target_app.get_member_list(target_group)
    for member_item in member_list:
        if member_item.id in Ariadne.service.connections:
            online_status = "" if account_controller.check_account_available(member_item.id) else "[未连接]"
            bot_list_column.append(
                ColumnUserInfo(
                    name=f"{member_item.name}({member_item.id}){online_status}",
                    description=f"{member_item.permission}",
                    avatar=await get_user_avatar_url(member_item.id)
                )
            )
    return await app.send_message(group, MessageChain(
        Image(data_bytes=await OneMockUI.gen(
            GenForm(columns=[Column(elements=bot_list_column)], color_type=get_color_type_follow_time())
        ))
    ), quote=source)


# 查询BOT列表
@listen(GroupMessage)
@decorate(
    Permission.user_require(Permission.BotAdmin, if_noticed=True),
    Permission.group_require(channel.metadata.level, if_noticed=True),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Distribute.require()
)
@dispatch(
    Twilight([
        FullMatch("BOT列表"),
        # 示例: BOT列表
    ])
)
async def get_bot_list(app: Ariadne, group: Group, source: Source):
    bot_list_column = [ColumnTitle(
        title=f"BOT列表:"
              f"{len([app_item for app_item in core.apps if Ariadne.current(app_item.account).connection.status.available])}"
              f"/"
              f"{len(config.bot_accounts)}"
    )]
    for bot_account in config.bot_accounts:
        if account_controller.check_account_available(bot_account):
            bot_list_column.append(
                ColumnUserInfo(
                    name=f"{(await Ariadne.current(bot_account).get_bot_profile()).nickname}({bot_account})",
                    description=f"已加入{len(await Ariadne.current(bot_account).get_group_list())}个群",
                    avatar=await get_user_avatar_url(bot_account)
                )
            )
        else:
            bot_list_column.append(
                ColumnUserInfo(
                    name=f"{bot_account}[未连接]",
                    avatar=await get_user_avatar_url(bot_account)
                )
            )
    return await app.send_message(group, MessageChain(
        Image(data_bytes=await OneMockUI.gen(
            GenForm(columns=[Column(elements=bot_list_column)], color_type=get_color_type_follow_time())
        ))
    ), quote=source)


# 设定响应 group_id 随机/指定
@listen(GroupMessage)
@decorate(
    Permission.user_require(Permission.BotAdmin, if_noticed=True),
    Permission.group_require(channel.metadata.level, if_noticed=True),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Distribute.require()
)
@dispatch(
    Twilight([
        FullMatch("设定响应"),
        "group_id" @ ParamMatch(optional=True),
        "target_type" @ UnionMatch("随机", "指定"),
    ])
)
async def change_group_responseType(app: Ariadne, group: Group, source: Source,
                                    target_type: RegexResult, group_id: RegexResult):
    target_type = target_type.result.display
    if target_type == "随机":
        target_type = "random"
    else:
        target_type = "deterministic"
    group_id = int(group_id.result.display) if group_id.matched else group.id
    if group_id != group.id:
        target_app, target_group = await account_controller.get_app_from_total_groups(group_id)
        if not (target_app and target_group):
            return await app.send_message(group, MessageChain(
                f"没有找到目标群:{group_id}"
            ), quote=source)
    else:
        target_group = group
    type_now = await account_controller.get_response_type(target_group.id)
    if type_now == target_type:
        return await app.send_message(group, MessageChain("响应模式与当前相同!"), quote=source)
    await account_controller.change_response_type(
        group_id=target_group.id, response_type=target_type
    )
    return await app.send_message(group, MessageChain("修改成功~"), quote=source)


# 指定BOT bot_account
@listen(GroupMessage)
@decorate(
    Permission.user_require(Permission.BotAdmin, if_noticed=True),
    Permission.group_require(channel.metadata.level, if_noticed=True),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Distribute.require()
)
@dispatch(
    Twilight([
        "group_id" @ ParamMatch(optional=True),
        FullMatch("指定BOT"),
        "bot_account" @ ParamMatch(),
    ])
)
async def choose_response_bot(app: Ariadne, group: Group, source: Source,
                              group_id: RegexResult, bot_account: RegexResult):
    group_id = int(group_id.result.display) if group_id.matched else group.id
    try:
        bot_account = int(bot_account.result.display)
    except:
        return await app.send_message(group, MessageChain(
            f"请检查指定的BOT账号!"
        ), quote=source)
    if not account_controller.check_account_available(bot_account):
        return await app.send_message(group, MessageChain(
            f"该BOT账号不在线!"
        ), quote=source)
    if group_id != group.id:
        target_app, target_group = await account_controller.get_app_from_total_groups(group_id)
        if not (target_app and target_group):
            return await app.send_message(group, MessageChain(
                f"没有找到目标群:{group_id}"
            ), quote=source)
    else:
        target_group = group
    for index in account_controller.account_dict[target_group.id]:
        if account_controller.account_dict[target_group.id][index] == bot_account:
            await account_controller.change_response_type(
                group_id=target_group.id, response_type="deterministic"
            )
            account_controller.deterministic_account[target_group.id] = index
            return await app.send_message(group, MessageChain(f"已成功设定群指定响应BOT为{bot_account}"), quote=source)
    return await app.send_message(group, MessageChain("设定失败,没有找到对应信息!"), quote=source)
