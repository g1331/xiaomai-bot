from pathlib import Path

from creart import create
from graia.ariadne.app import Ariadne
from graia.ariadne.event.message import GroupMessage
from graia.ariadne.event.mirai import MemberLeaveEventQuit, MemberJoinEvent, MemberPermissionChangeEvent
from graia.ariadne.message.chain import MessageChain
from graia.ariadne.message.element import Image, Source
from graia.ariadne.message.parser.twilight import (
    Twilight,
    FullMatch,
    ParamMatch,
    UnionMatch,
    RegexResult,
    WildcardMatch
)
from graia.ariadne.model import Group, Member
from graia.ariadne.util.saya import listen, dispatch, decorate
from graia.saya import Channel, Saya
from sqlalchemy import select

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
from core.orm import orm
from core.orm.tables import MemberPerm, GroupPerm, GroupSetting
from utils.UI import *
from utils.image import get_user_avatar_url, get_img_base64_str
from utils.parse_messagechain import get_targets

config = create(GlobalConfig)
core = create(Umaru)

module_controller = saya_model.get_module_controller()
account_controller = response_model.get_acc_controller()

saya = Saya.current()
channel = Channel.current()
channel.name("PermissionManager")
channel.description("负责权限管理(必须插件)")
channel.author("13")
channel.metadata = module_controller.get_metadata_from_path(Path(__file__))


# >=64可修改当前群的用户权限
@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level, if_noticed=True),
    Permission.user_require(Permission.GroupOwner, if_noticed=True),
)
@dispatch(
    Twilight([
        FullMatch("修改权限"),
        "group_id" @ ParamMatch(optional=True),
        "perm" @ UnionMatch("64", "32", "16", "0"),
        "member_id" @ WildcardMatch()
        # 示例: 修改权限 群号 perm
    ])
)
async def change_user_perm(
        app: Ariadne, group: Group, event: GroupMessage,
        group_id: RegexResult,
        perm: RegexResult,
        member_id: RegexResult,
        source: Source
):
    """
    修改用户权限
    """
    group_id = int(group_id.result.display) if group_id.matched else group.id
    targets = get_targets(member_id.result)
    try:
        perm = int(perm.result.display)
    except:
        return await app.send_message(group, MessageChain(
            f"请检查输入的权限(64/32/16/0)"
        ), quote=source)
    # 修改其他群组的权限判假
    if group_id != group.id:
        user_level = await Permission.get_user_perm(event)
        if user_level < Permission.BotAdmin:
            return await app.send_message(event.sender.group, MessageChain(
                f"权限不足!(你的权限:{user_level}/需要权限:{Permission.BotAdmin})"
            ), quote=source)
        target_app, target_group = await account_controller.get_app_from_total_groups(group_id)
        if not (target_app and target_group):
            return await app.send_message(group, MessageChain(
                f"没有找到目标群:{group_id}"
            ), quote=source)
    else:
        target_app = app
        target_group = group
    error_targets = []
    for target in targets:
        if await Permission.get_user_perm(event) < (
                target_perm := await Permission.get_user_perm_byID(target_group.id, target)):
            error_targets.append((target, f"无法降级{target}({target_perm})"))
        elif await target_app.get_member(target_group, target) is None:
            error_targets.append((target, f"没有在群{target_group}找到群成员"))
        elif await Permission.get_user_perm_byID(target_group.id, target) == Permission.BotAdmin:
            error_targets.append((target, f"无法直接通过该指令修改BOT管理权限"))
        else:
            await orm.insert_or_update(
                table=MemberPerm,
                condition=[
                    MemberPerm.qq == target,
                    MemberPerm.group_id == target_group.id
                ],
                data={
                    "group_id": target_group.id,
                    "qq": target,
                    "perm": perm
                }
            )
    response_text = f"共解析{len(targets)}个目标\n其中{len(targets) - len(error_targets)}个执行成功,{len(error_targets)}个失败"
    if error_targets:
        response_text += "\n\n失败目标:"
        for i in error_targets:
            response_text += f"\n{i[0]}-{i[1]}"
    await app.send_message(group, response_text, quote=source)


# >=128可修改群权限
@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level, if_noticed=True),
    Permission.user_require(Permission.BotAdmin, if_noticed=True),
)
@dispatch(
    Twilight([
        FullMatch("修改群权限"),
        "group_id" @ ParamMatch(optional=True),
        "perm" @ UnionMatch("3", "2", "1", "0"),
        # 示例: 修改权限 群号 perm
    ])
)
async def change_group_perm(
        app: Ariadne,
        group: Group,
        group_id: RegexResult,
        perm: RegexResult,
        source: Source
):
    group_id = int(group_id.result.display) if group_id.matched else group.id
    try:
        perm = int(perm.result.display)
    except:
        return await app.send_message(group, MessageChain(
            f"请检查输入的权限(3/2/1/0)"
        ), quote=source)
    target_app, target_group = await account_controller.get_app_from_total_groups(group_id)
    if not (target_app and target_group):
        return await app.send_message(group, MessageChain(
            f"没有找到目标群:{group_id}"
        ), quote=source)
    if target_group.id == config.test_group:
        return await app.send_message(group, MessageChain(
            f"无法通过该指令修改测试群({target_group.id})权限!"
        ), quote=source)
    await orm.insert_or_update(
        GroupPerm,
        {"group_id": target_group.id, "group_name": target_group.name, "active": True, "perm": perm},
        [
            GroupPerm.group_id == target_group.id
        ]
    )
    return await app.send_message(group, MessageChain(
        f"已修改群{target_group.name}({target_group.id})权限为{perm}"
    ), quote=source)


# >=128可修改群权限类型
@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level, if_noticed=True),
    Permission.user_require(Permission.BotAdmin, if_noticed=True),
)
@dispatch(
    Twilight([
        FullMatch("修改群权限类型"),
        "group_id" @ ParamMatch(optional=True),
        "permission_type" @ UnionMatch("admin", "default"),
        # 示例: 修改权限 群号 perm
    ])
)
async def change_group_perm(
        app: Ariadne,
        group: Group,
        group_id: RegexResult,
        permission_type: RegexResult,
        source: Source
):
    group_id = int(group_id.result.display) if group_id.matched else group.id
    permission_type = permission_type.result.display
    target_app, target_group = await account_controller.get_app_from_total_groups(group_id)
    if not (target_app and target_group):
        return await app.send_message(group, MessageChain(
            f"没有找到目标群:{group_id}"
        ), quote=source)
    await orm.insert_or_update(
        table=GroupSetting,
        data={"permission_type": permission_type},
        condition=[
            GroupSetting.group_id == target_group.id
        ]
    )
    if permission_type == "admin":
        for member in await target_app.get_member_list(target_group):
            if await Permission.get_user_perm_byID(target_group.id, member.id) < Permission.GroupAdmin:
                await orm.insert_or_update(
                    table=MemberPerm,
                    data={"qq": member.id, "group_id": group.id, "perm": Permission.GroupAdmin},
                    condition=[
                        MemberPerm.qq == member.id,
                        MemberPerm.group_id == group.id
                    ]
                )
    else:
        for member in await target_app.get_member_list(group):
            target_perm = Permission.member_permStr_dict[member.permission.name]
            now_perm = await Permission.get_user_perm_byID(target_group.id, member.id)
            if now_perm >= Permission.GroupOwner:
                continue
            if now_perm != target_perm:
                await orm.insert_or_update(
                    table=MemberPerm,
                    data={"qq": member.id,
                          "group_id": group.id,
                          "perm": target_perm},
                    condition=[
                        MemberPerm.qq == member.id,
                        MemberPerm.group_id == group.id
                    ]
                )
    return await app.send_message(group, MessageChain(
        f"已修改群{target_group.name}({target_group.id})权限类型为{permission_type}"
    ), quote=source)


# 查询VIP群
@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level, if_noticed=True),
    Permission.user_require(Permission.BotAdmin, if_noticed=True),
)
@dispatch(
    Twilight([
        FullMatch("VIP群列表"),
        # 示例: VIP群列表
    ])
)
async def get_vg_list(
        app: Ariadne,
        group: Group,
        source: Source
):
    vip_group_list = []
    if result := await orm.fetch_all(
            select(GroupPerm.group_id).where(
                GroupPerm.perm == 2,
            )
    ):
        for item in result:
            for k in core.total_groups:
                for Group_item in core.total_groups[k]:
                    Group_item: Group
                    if Group_item.id == item[0] and Group_item not in vip_group_list:
                        vip_group_list.append(Group_item)
    if not vip_group_list:
        return await app.send_message(group, MessageChain(
            f"当前没有VIP群~"
        ), quote=source)
    vg_group_list_column = [ColumnTitle(title="VIP群列表")]
    for Group_item in vip_group_list:
        vg_group_list_column.append(
            ColumnUserInfo(
                name=f"{Group_item.name}({Group_item.id})",
                avatar=get_img_base64_str(await Group_item.get_avatar())
            )
        )
    vg_group_list_column = [Column(elements=vg_group_list_column[i: i + 20]) for i in
                            range(0, len(vg_group_list_column), 20)]
    return await app.send_message(group, MessageChain(
        Image(data_bytes=await OneMockUI.gen(
            GenForm(columns=vg_group_list_column, color_type=get_color_type_follow_time())
        ))
    ), quote=source)


@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level, if_noticed=True),
    Permission.user_require(Permission.GroupAdmin, if_noticed=True),
)
@dispatch(
    Twilight([
        UnionMatch("perm list", "权限列表"),
        "group_id" @ ParamMatch(optional=True),
        # 示例: perm list
    ])
)
async def get_perm_list(app: Ariadne, group: Group, group_id: RegexResult, source: Source, event: GroupMessage):
    group_id = int(group_id.result.display) if group_id.matched else group.id
    if group_id != group.id:
        user_level = await Permission.get_user_perm(event)
        if user_level < Permission.BotAdmin:
            return await app.send_message(event.sender.group, MessageChain(
                f"权限不足!(你的权限:{user_level}/需要权限:{Permission.BotAdmin})"
            ), quote=source)
        if group_id not in account_controller.total_groups:
            return await app.send_message(event.sender.group, MessageChain(
                f"没有找到群{group_id}~"
            ), quote=source)
        target_app, target_group = await account_controller.get_app_from_total_groups(group_id)
        if not (target_app and target_group):
            return await app.send_message(group, MessageChain(
                f"没有找到目标群:{group_id}"
            ), quote=source)
    else:
        target_app = app
        target_group = group
    # 查询权限组-当权限>=128时 可以查询其他群的
    """
    [ (perm, qq) ]
    """
    perm_list = await Permission.get_users_perm_byID(group_id)
    perm_dict = {}
    member_list = await target_app.get_member_list(group_id)
    for item in perm_list:
        if item[1] in [member.id for member in member_list]:
            perm_dict[item[1]] = item[0]
    for member in member_list:
        if member.id not in perm_dict and Permission.member_permStr_dict[member.permission.name] != 16:
            perm_dict[member.id] = Permission.member_permStr_dict[member.permission.name]
    perm_dict = dict(sorted(perm_dict.items(), key=lambda x: x[1], reverse=True))
    """
    perm_dict = {
        qq: perm
    }
    """
    perm_list_column = [
        ColumnUserInfo(
            name=f"{target_group.name}({target_group.id})",
            description=f"群权限为{await Permission.get_group_perm(target_group)}:"
                        f"{Permission.group_str_dict[await Permission.get_group_perm(target_group)]}",
            avatar=get_img_base64_str(await target_group.get_avatar())
        ),
        ColumnTitle(title="权限列表")
    ]
    for member_id in perm_dict:
        if perm_dict[member_id] == 16:
            continue
        try:
            member_item = await target_app.get_member(target_group, member_id)
        except:
            member_item = None
        perm_list_column.append(
            ColumnUserInfo(
                name=f"{member_item.name}({member_id})" if member_item else member_id,
                description=f"{perm_dict[member_id]}——"
                            f"{Permission.user_str_dict[perm_dict[member_id]]}",
                avatar=await get_user_avatar_url(member_id)
            )
        )
    perm_list_column = [Column(elements=perm_list_column[i: i + 20]) for i in range(0, len(perm_list_column), 20)]
    return await app.send_message(group, MessageChain(
        Image(data_bytes=await OneMockUI.gen(
            GenForm(columns=perm_list_column, color_type=get_color_type_follow_time())
        ))
    ), quote=source)


# 增删全局黑名单
@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level, if_noticed=True),
    Permission.user_require(Permission.BotAdmin),
)
@dispatch(
    Twilight([
        "action" @ UnionMatch("添加", "删除"),
        FullMatch("全局黑"),
        WildcardMatch() @ "member_id"
        # 示例: 添加/删除 全局黑 000
    ])
)
async def change_globalBlack(app: Ariadne, group: Group, action: RegexResult, member_id: RegexResult, source: Source):
    action = action.result.display
    targets = get_targets(member_id.result)
    global_black_list = await Permission.get_GlobalBlackList()
    error_targets = []
    for target in targets:
        if action == "添加":
            if target in global_black_list:
                error_targets.append((target, f"{target}已经在全局黑名单内!"))
            else:
                await orm.insert_or_update(
                    table=MemberPerm,
                    data={
                        "qq": target,
                        "group_id": 0,
                        "perm": -1
                    },
                    condition=[
                        MemberPerm.qq == target
                    ]
                )
        else:
            if target not in global_black_list:
                error_targets.append((target, f"{target}不在全局黑名单内!"))
            else:
                await orm.delete(
                    table=MemberPerm,
                    condition=[
                        MemberPerm.qq == target,
                        MemberPerm.group_id == 0
                    ]
                )
    response_text = f"共解析{len(targets)}个目标\n其中{len(targets) - len(error_targets)}个执行成功,{len(error_targets)}个失败"
    if error_targets:
        response_text += "\n\n失败目标:"
        for i in error_targets:
            response_text += f"\n{i[0]}-{i[1]}"
    return await app.send_message(group, response_text, quote=source)


@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level, if_noticed=True),
    Permission.user_require(Permission.GroupAdmin, if_noticed=True),
)
@dispatch(Twilight([
    FullMatch("全局黑名单列表"),
    # 示例: 全局黑名单列表
]))
async def get_globalBlack_list(app: Ariadne, group: Group, source: Source):
    perm_list_column = [ColumnTitle(title="全局黑名单列表")]
    global_black_list = await Permission.get_GlobalBlackList()
    if len(global_black_list) == 0:
        return await app.send_message(group, MessageChain("全局黑名单为空哦~"), quote=source)
    for member_id in global_black_list:
        try:
            member_item = await app.get_member(group, member_id)
        except:
            member_item = None
        perm_list_column.append(
            ColumnUserInfo(
                name=f"{member_item.name}({member_id})" if member_item else member_id,
                avatar=await get_user_avatar_url(member_id)
            )
        )
    perm_list_column = [Column(elements=perm_list_column[i: i + 20]) for i in range(0, len(perm_list_column), 20)]
    return await app.send_message(group, MessageChain(
        Image(data_bytes=await OneMockUI.gen(
            GenForm(columns=perm_list_column, color_type=get_color_type_follow_time())
        ))
    ), quote=source)


# 增删bot管理
@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level, if_noticed=True),
    Permission.user_require(Permission.Master),
)
@dispatch(
    Twilight([
        "action" @ UnionMatch("添加", "删除"),
        FullMatch("BOT管理"),
        WildcardMatch() @ "member_id"
        # 示例: 添加/删除 BOT管理 000
    ])
)
async def change_botAdmin(app: Ariadne, group: Group, action: RegexResult, member_id: RegexResult, source: Source):
    action = action.result.display
    targets = get_targets(member_id.result)
    admin_list = await Permission.get_BotAdminsList()
    error_targets = []
    for target in targets:
        if action == "添加":
            if target in admin_list:
                error_targets.append((target, f"{target}已经是BOT管理啦!"))
            else:
                await core.update_admins_permission([target])
        else:
            if target not in admin_list:
                error_targets.append((target, f"{target}还不是BOT管理哦!"))
            else:
                await orm.delete(
                    table=MemberPerm,
                    condition=[
                        MemberPerm.qq == target,
                    ]
                )
                await core.update_admins_permission()
    response_text = f"共解析{len(targets)}个目标\n其中{len(targets) - len(error_targets)}个执行成功,{len(error_targets)}个失败"
    if error_targets:
        response_text += "\n\n失败目标:"
        for i in error_targets:
            response_text += f"\n{i[0]}-{i[1]}"
    return await app.send_message(group, response_text, quote=source)


@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level, if_noticed=True),
    Permission.user_require(Permission.GroupAdmin, if_noticed=True),
)
@dispatch(Twilight([
    FullMatch("BOT管理列表"),
    # 示例: BOT管理列表
]))
async def get_botAdmins_list(app: Ariadne, group: Group, source: Source):
    perm_list_column = [ColumnTitle(title="BOT管理列表")]
    admin_list = await Permission.get_BotAdminsList()
    if len(admin_list) == 0:
        return await app.send_message(group, MessageChain("当前还没有BOT管理哦~"), quote=source)
    for member_id in admin_list:
        try:
            member_item = await app.get_member(group, member_id)
        except:
            member_item = None
        perm_list_column.append(
            ColumnUserInfo(
                name=f"{member_item.name}({member_id})" if member_item else member_id,
                avatar=await get_user_avatar_url(member_id)
            )
        )
    perm_list_column = [Column(elements=perm_list_column[i: i + 20]) for i in range(0, len(perm_list_column), 20)]
    return await app.send_message(group, MessageChain(
        Image(data_bytes=await OneMockUI.gen(
            GenForm(columns=perm_list_column, color_type=get_color_type_follow_time())
        ))
    ), quote=source)


# 自动删除退群的权限
@listen(MemberLeaveEventQuit)
async def auto_del_perm(app: Ariadne, group: Group, member: Member):
    if app.account != await account_controller.get_response_account(group.id):
        return
    target_perm = await Permission.get_user_perm_byID(group.id, member.id)
    await orm.delete(
        table=MemberPerm,
        condition=[
            MemberPerm.qq == member.id,
            MemberPerm.group_id == group.id
        ]
    )
    if Permission.GroupOwner >= target_perm >= Permission.GroupAdmin:
        return await app.send_message(group, f"已自动删除退群成员{member.name}({member.id})的权限")


# 自动添加管理群的权限
@listen(MemberJoinEvent)
async def auto_del_perm(app: Ariadne, group: Group, member: Member):
    if app.account != await account_controller.get_response_account(group.id):
        return
    permission_type = "default"
    if result := await orm.fetch_one(
            select(GroupSetting.permission_type).where(GroupSetting.group_id == group.id)
    ):
        permission_type = result[0]
    if permission_type == "admin":
        await orm.insert_or_update(
            table=MemberPerm,
            data={"qq": member.id, "group_id": group.id, "perm": 32},
            condition=[
                MemberPerm.qq == member.id,
                MemberPerm.group_id == group.id
            ]
        )
        return await app.send_message(group, f"已自动修改成员{member.name}({member.id})的权限为32")


# 自动添加进群的Master/admins
@listen(MemberJoinEvent)
async def auto_add_perm(event: MemberJoinEvent):
    if event.member.id == config.Master:
        return await orm.insert_or_update(
            table=MemberPerm,
            data={"qq": event.member.id, "group_id": event.member.group.id, "perm": Permission.Master},
            condition=[
                MemberPerm.qq == event.member.id,
                MemberPerm.group_id == event.member.group.id
            ]
        )
    elif event.member.id in await Permission.get_BotAdminsList():
        await orm.insert_or_update(
            table=MemberPerm,
            data={"qq": event.member.id, "group_id": event.member.group.id, "perm": Permission.BotAdmin},
            condition=[
                MemberPerm.qq == event.member.id,
                MemberPerm.group_id == event.member.group.id,
            ]
        )


# 自动修改群管理权限
@listen(MemberPermissionChangeEvent)
async def auto_change_admin_perm(app: Ariadne, event: MemberPermissionChangeEvent):
    if app.account != await account_controller.get_response_account(event.member.group.id):
        return
    target_member = event.member
    target_group = event.member.group
    admin_list = await Permission.get_BotAdminsList()
    # 跳过bot管理和master
    if (target_member.id in admin_list) or target_member.id == config.Master:
        return
    # 跳过管理组
    permission_type = "default"
    if result := await orm.fetch_one(
            select(GroupSetting.permission_type).where(GroupSetting.group_id == target_group.id)
    ):
        permission_type = result[0]
    if permission_type == "admin":
        return
    if event.current.name == "Owner":
        target_perm = Permission.Owner
    elif event.current.name == "Administrator":
        target_perm = Permission.GroupAdmin
    else:
        target_perm = Permission.User
    await orm.insert_or_update(
        table=MemberPerm,
        data={"qq": event.member.id, "group_id": event.member.group.id, "perm": target_perm},
        condition=[
            MemberPerm.qq == event.member.id,
            MemberPerm.group_id == event.member.group.id
        ]
    )
    return await app.send_message(
        target_group,
        MessageChain(f"检测到群管理权限变动\n已自动修改{target_member.name}({target_member.id})权限为{target_perm}")
    )
