import contextlib
from typing import Union, Dict

import sqlalchemy.exc
from creart import create
from graia.amnesia.message import MessageChain
from graia.ariadne import Ariadne
from graia.ariadne.event.message import GroupMessage, FriendMessage
from graia.ariadne.message import Source
from graia.ariadne.model import Group, Friend
from graia.broadcast import ExecutionStop
from graia.broadcast.builtin.decorators import Depend
from sqlalchemy import select

from core.config import GlobalConfig
from core.models import (
    saya_model,
    frequency_model,
    response_model
)
from core.orm import orm
from core.orm.tables import MemberPerm, GroupPerm, GroupSetting

global_config = create(GlobalConfig)


class Permission(object):
    """权限判断

    成员权限:
    -1      全局黑
    0       单群黑
    16      群员
    32      管理
    64      群主
    128     Admin
    256     Master

    群权限:
    0       非活动群组
    1       正常活动群组
    2       vip群组
    3       测试群组
    """
    Master = 256
    BotAdmin = 128
    GroupOwner = 64
    GroupAdmin = 32
    User = 16
    GroupBlack = 0
    GlobalBlack = -1

    InactiveGroup = 0
    ActiveGroup = 1
    VipGroup = 2
    TestGroup = 3

    Member = 16
    Administrator = 32
    Owner = 64

    member_permStr_dict = {
        "Member": 16,  # 普通成员
        "Administrator": 32,  # 管理员
        "Owner": 64  # 群主
    }

    user_str_dict = {
        256: "Master",
        128: "BotAdmin",
        64: "GroupOwner",
        32: "GroupAdmin",
        16: "User",
        0: "GroupBlack",
        -1: "GlobalBlack"
    }

    group_str_dict = {
        0: "InactiveGroup",
        1: "ActiveGroup",
        2: "VipGroup",
        3: "TestGroup"
    }

    @staticmethod
    async def get_user_perm_byID(group_id: int, member_id: int) -> int:
        if result := await orm.fetch_one(
                select(MemberPerm.perm).where(MemberPerm.group_id == group_id, MemberPerm.qq == member_id)
        ):
            return result[0]
        else:
            return Permission.User

    @staticmethod
    async def get_users_perm_byID(group_id: int) -> list[int]:
        return await orm.fetch_all(
            select(MemberPerm.perm, MemberPerm.qq).where(MemberPerm.group_id == group_id)
        )

    @staticmethod
    async def get_BotAdminsList() -> list[int]:
        admin_list = []
        if result := await orm.fetch_all(
                select(MemberPerm.qq).where(
                    MemberPerm.perm == Permission.BotAdmin,
                )
        ):
            for item in result:
                if item[0] not in admin_list:
                    admin_list.append(item[0])
        return admin_list

    @staticmethod
    async def get_group_perm_type(group_id: int) -> str:
        if result := await orm.fetch_one(
                select(GroupSetting.permission_type).where(GroupSetting.group_id == group_id)
        ):
            return result[0]
        else:
            return "default"

    @staticmethod
    async def require_user_perm(group_id: int, member_id: int, perm: int) -> bool:
        if result := await orm.fetch_one(
                select(MemberPerm.perm).where(MemberPerm.group_id == group_id, MemberPerm.qq == member_id)
        ):
            return result[0] >= perm
        else:
            return Permission.User >= perm

    @staticmethod
    async def require_group_perm(group_id: int, perm: int) -> bool:
        if result := await orm.fetch_one(select(GroupPerm.perm).where(
                GroupPerm.group_id == group_id)):
            return result[0] >= perm
        else:
            return Permission.ActiveGroup >= perm

    @classmethod
    async def get_user_perm(cls, event: Union[GroupMessage, FriendMessage]) -> int:
        """
        根据传入的消息事件(群消息事件/好友消息事件)
        :return: 查询到的权限
        """
        sender = event.sender
        # 判断是群还是好友
        group_id = event.sender.group.id if isinstance(event, GroupMessage) else None
        if not group_id:
            # 查询是否在全局黑当中
            # 如果有查询到数据，则返回用户的权限等级
            if result := await orm.fetch_one(
                    select(MemberPerm.perm).where(
                        MemberPerm.qq == sender.id,
                        MemberPerm.group_id == 0
                    )
            ):
                return result[0]
            else:
                if sender.id == global_config.Master:
                    return Permission.Master
                elif sender.id in cls.get_BotAdminsList():
                    return Permission.BotAdmin
                else:
                    return Permission.User
        # 如果有查询到数据，则返回用户的权限等级
        if result := await orm.fetch_one(
                select(MemberPerm.perm).where(MemberPerm.group_id == group_id, MemberPerm.qq == sender.id)
        ):
            return result[0]
        # 如果没有查询到数据，则写入初始权限
        else:
            perm = cls.member_permStr_dict[event.sender.permission.name]
            with contextlib.suppress(sqlalchemy.exc.IntegrityError):
                await orm.insert_or_ignore(
                    table=MemberPerm,
                    condition=[
                        MemberPerm.qq == sender.id,
                        MemberPerm.group_id == group_id
                    ],
                    data={
                        "group_id": group_id,
                        "qq": sender.id,
                        "perm": perm
                    }
                )
            return perm

    @classmethod
    def user_require(cls, perm: int = User, if_noticed: bool = True):
        """
        指定perm及以上的等级才能执行
        :param perm: 设定权限等级
        :param if_noticed: 是否发送权限不足的消息通知
        """

        async def wrapper(app: Ariadne, event: Union[GroupMessage, FriendMessage], source: Source or None = None):
            # 获取并判断用户的权限等级
            user_level = await cls.get_user_perm(event)
            if user_level < perm:
                if user_level == Permission.GlobalBlack:
                    raise ExecutionStop
                if if_noticed:
                    await app.send_message(event.sender.group, MessageChain(
                        f"权限不足!(你的权限:{user_level}/需要权限:{perm})"
                    ), quote=source)
                raise ExecutionStop
            return Depend(wrapper)

        return Depend(wrapper)

    @classmethod
    async def get_group_perm(cls, group: Group) -> int:
        """
        根据传入的群实例获取群权限
        :return: 查询到的权限
        """
        # 查询数据库
        # 如果有查询到数据，则返回群的权限等级
        if result := await orm.fetch_one(select(GroupPerm.perm).where(
                GroupPerm.group_id == group.id)):
            return result[0]
        # 如果没有查询到数据，则返回1（活跃群）,并写入初始权限1
        else:
            if group.id == global_config.test_group:
                perm = 3
            else:
                perm = 1
            with contextlib.suppress(sqlalchemy.exc.IntegrityError):
                await orm.insert_or_update(
                    GroupPerm,
                    {"group_id": group.id, "group_name": group.name, "active": True, "perm": perm},
                    [
                        GroupPerm.group_id == group.id
                    ]
                )
                return Permission.ActiveGroup

    @classmethod
    def group_require(cls, perm: int = ActiveGroup, if_noticed: bool = False):
        """
        指定perm及以上的等级才能执行
        :param perm: 设定权限等级
        :param if_noticed: 是否通知
        """

        async def wrapper(app: Ariadne, event: GroupMessage, src: Source):
            # 获取并判断群的权限等级
            group = event.sender.group
            group_perm = await cls.get_group_perm(group)
            if group_perm < perm:
                if if_noticed:
                    await app.send_message(group, MessageChain(
                        f"权限不足!(当前群权限:{group_perm}/需要权限:{perm})"
                    ), quote=src)
                raise ExecutionStop
            return Depend(wrapper)

        return Depend(wrapper)


class Function(object):
    """功能判断"""

    @classmethod
    def require(cls, module_name: str, notice: bool = True):
        async def judge(app: Ariadne, group: Group or None = None, source: Source or None = None):
            # 如果module_name不在modules_list里面就添加
            module_controller = saya_model.get_module_controller()
            if module_name not in module_controller.modules:
                module_controller.add_module(module_name)
            if not group:
                return
            # 如果group不在modules里面就添加
            if str(group.id) not in module_controller.modules[module_name]:
                module_controller.add_group(group)
            module_meta = module_controller.get_metadata_from_module_name(module_name)
            # 如果在维护就停止
            if not module_controller.if_module_available(module_name):
                if notice and module_controller.if_module_notice_on(module_name, group):
                    await app.send_message(group, MessageChain(
                        f"{module_meta.display_name or module_name}插件正在维护~"
                    ), quote=source)
                raise ExecutionStop
            else:
                # 如果群未打开开关就停止
                if not module_controller.if_module_switch_on(module_name, group):
                    if notice and module_controller.if_module_notice_on(module_name, group):
                        await app.send_message(group, MessageChain(
                            f"{module_meta.display_name or module_name}插件已关闭\n请使用‘-开启 插件编号’来打开插件\n插件编号请使用‘帮助’获取"
                        ), quote=source)
                    raise ExecutionStop
            return

        return Depend(judge)


class Distribute(object):

    @classmethod
    def require(cls):
        """
        群内有多个bot时随机/指定bot响应
        :return: Depend
        """

        async def wrapper(group: Group or Friend, app: Ariadne):
            if isinstance(group, Friend):
                return Depend(wrapper)
            group_id = group.id
            account_controller = response_model.get_acc_controller()
            bot_account = app.account
            if len(Ariadne.service.connections.keys()) == 1:
                return
            if not account_controller.check_initialization(group_id, bot_account):
                await account_controller.init_group(group_id, await app.get_member_list(group_id), bot_account)
                raise ExecutionStop
            res_acc = await account_controller.get_response_account(group_id)
            if not Ariadne.current(res_acc).connection.status.available:
                account_controller.account_dict.pop(group_id)
                raise ExecutionStop
            if bot_account != await account_controller.get_response_account(group_id):
                raise ExecutionStop
            return Depend(wrapper)

        return Depend(wrapper)


class FrequencyLimitation(object):
    """频率限制"""

    @classmethod
    def require(
            cls,
            module_name: str,
            weight: int = 2,
            total_weights: int = 15,
            override_perm: int = Permission.GroupAdmin
    ):
        """
        :param module_name:插件名字
        :param weight:增加权重
        :param total_weights:总权重
        :param override_perm:越级权限
        """

        async def judge(app: Ariadne, event: Union[GroupMessage, FriendMessage], src: Source):
            if isinstance(event, FriendMessage):
                return
            group_id = event.sender.group.id
            sender_id = event.sender.id
            if frequency_limitation_switch := await orm.fetch_one(
                    select(GroupSetting.frequency_limitation).where(GroupSetting.group_id == group_id)
            ):
                frequency_limitation_switch = frequency_limitation_switch[0]
            if not frequency_limitation_switch:
                return
            if await Permission.get_user_perm(event) >= override_perm:
                return
            frequency_controller = frequency_model.get_frequency_controller()
            frequency_controller.add_weight(module_name, group_id, sender_id, weight)
            # 如果已经在黑名单则返回
            if frequency_controller.blacklist_judge(group_id, sender_id):
                if not frequency_controller.blacklist_noticed_judge(group_id, sender_id):
                    await app.send_message(
                        event.sender.group,
                        MessageChain(f"检测到大量请求,加入黑名单5分钟!"),
                        quote=src
                    )
                    frequency_controller.blacklist_notice(group_id, sender_id)
                raise ExecutionStop
            current_weight = frequency_controller.get_weight(module_name, group_id, sender_id)
            if (current_weight + weight) >= total_weights:
                await app.send_message(
                    event.sender.group,
                    MessageChain(f"超过频率调用限制!({current_weight + weight}/{total_weights})\n"
                                 f"休息一下吧~继续高频访问会被加入临时黑名单哦~"),
                    quote=src,
                )
                raise ExecutionStop

        return Depend(judge)


class Config(object):
    """配置检查"""

    @classmethod
    def require(cls, key_string):
        async def check_config(app: Ariadne, event: Union[GroupMessage, FriendMessage], source: Source or None = None):
            paths = key_string.split(".")
            current: GlobalConfig = global_config
            for path in paths:
                if isinstance(current, (GlobalConfig, Dict)):
                    if isinstance(current, Dict):
                        # 如果 current 是字典类型，则尝试使用 current.get 获取值
                        current = current.get(path, "缺少配置:{}".format(key_string))
                        if isinstance(current, Dict):
                            continue
                        elif (not isinstance(current, Dict)) and current != path:
                            return
                    elif isinstance(current, GlobalConfig):
                        # 如果 current 不是字典类型，则尝试使用 getattr 获取属性值
                        current = getattr(current, path, "缺少配置:{}".format(key_string))
                        if isinstance(current, Dict):
                            continue
                        elif (not isinstance(current, Dict)) and current != path:
                            return
                    elif (not isinstance(current, Dict)) and current != path:
                        return
                    else:
                        return
                else:
                    # 如果 current 既不是 GlobalConfig 也不是字典，则说明已经遍历到了最后一个 key
                    return
            # 如果遍历完所有的 key 后 current 仍然不是值类型，说明配置信息不存在，返回 "缺少配置: {}"
            await app.send_message(event.sender.group, MessageChain(
                "缺少配置:{}".format(key_string)
            ), quote=source)
            raise ExecutionStop

        return Depend(check_config)


class QuoteReply(object):
    @classmethod
    def require(cls):
        async def wrapper(event: GroupMessage):
            if not event.quote:
                raise ExecutionStop

        return Depend(wrapper)
