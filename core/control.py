import contextlib
from typing import Union

import sqlalchemy.exc
from creart import create
from graia.amnesia.message import MessageChain
from graia.ariadne import Ariadne
from graia.ariadne.message import Source
from graia.ariadne.model import Member, Group, Friend
from graia.broadcast import ExecutionStop
from graia.broadcast.builtin.decorators import Depend
from sqlalchemy import select

from core.config import GlobalConfig
from core.orm import orm
from core.orm.tables import MemberPerm, GroupPerm
from core.saya_modules import get_module_data

config = create(GlobalConfig)


class Permission(object):
    """
    判断权限的类

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
    Admin = 128
    GroupOwner = 64
    GroupAdmin = 32
    User = 16
    Black = 0
    GlobalBlack = -1

    InactiveGroup = 0
    ActiveGroup = 1
    VipGroup = 2
    TestGroup = 3

    @classmethod
    async def get_user_perm(cls, sender: Member, group: Union[Group, Friend]) -> int:
        """
        根据传入的qq号与群号来判断该用户的权限等级
        """
        # 判断是群还是好友
        group_id = group.id if isinstance(group, Group) else None
        if not group_id:
            # 查询是否在全局黑当中
            result = await orm.fetch_one(
                select(MemberPerm.perm).where(
                    MemberPerm.qq == sender.id,
                    MemberPerm.group_id == 0
                )
            )
            # 如果有查询到数据，则返回用户的权限等级
            if result:
                return result[0]
            else:
                if sender.id == config.Master:
                    return Permission.Master
                elif sender.id in config.Admins:
                    return Permission.Admin
                else:
                    return Permission.User
        # 查询数据库
        result = await orm.fetch_one(
            select(MemberPerm.perm).where(
                MemberPerm.group_id == group_id, MemberPerm.qq == sender.id
            )
        )
        # 如果有查询到数据，则返回用户的权限等级
        if result:
            return result[0]
        # 如果没有查询到数据，则返回16（群员）,并写入初始权限
        if not result:
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
                        "perm": Permission.User
                    }
                )
                return Permission.User

    @classmethod
    def user_require(cls, perm: int = User, if_noticed: bool = False):
        """
        指定perm及以上的等级才能执行
        :param perm: 设定权限等级
        :param if_noticed: 是否发送权限不足的消息通知
        """

        async def wrapper(app: Ariadne, sender: Union[Member, Friend], group: Union[Group, Friend],
                          src: Source or None):
            # 通过get来获取用户的权限等级
            user_level = await cls.get_user_perm(sender, group)
            if user_level >= perm:
                return Depend(wrapper)
            elif user_level < perm:
                if if_noticed:
                    await app.send_message(group, MessageChain(
                        f"权限不足！需要权限:{perm}，你的权限:{user_level}/"
                    ), quote=src)
            raise ExecutionStop

        return Depend(wrapper)

    @classmethod
    async def get_group_perm(cls, group: Group) -> int:
        """
        根据传入的群号获取群权限
        """
        # 查询数据库
        result = await orm.fetch_one(select(GroupPerm.perm).where(GroupPerm.group_id == group.id))
        # 如果有查询到数据，则返回群的权限等级
        if result:
            return result[0]
        # 如果没有查询到数据，则返回1（活跃群）,并写入初始权限1
        if not result:
            if group.id in config.black_group:
                perm = 0
            elif group.id in config.vip_group:
                perm = 2
            elif group.id == config.test_group:
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

        async def wrapper(app: Ariadne, group: Group, src: Source or None):
            # 通过get来获取群的权限等级
            group_perm = await cls.get_group_perm(group)
            if group_perm >= perm:
                return Depend(wrapper)
            elif group_perm < perm:
                if if_noticed:
                    await app.send_message(group, MessageChain(
                        f"权限不足！需要权限:{perm}，当前群({group.id})权限:{group_perm}。"
                    ), quote=src)
            raise ExecutionStop

        return Depend(wrapper)


class Function(object):
    """
    判断功能的类
    """

    @classmethod
    def require(cls, module_name):
        # 如果module_name不在modules_list里面就添加
        modules_data = get_module_data()
        if module_name not in modules_data.modules:
            modules_data.add(module_name)


temp_dict = {}


class Distribute(object):

    @classmethod
    def require(cls):
        """
        用于消息分发
        :return: Depend
        """

        async def wrapper(group: Union[Group, Friend], app: Ariadne, source: Source):
            global temp_dict
            if type(group) == Friend:
                return Depend(wrapper)
            # 第一次要获取群列表，然后添加bot到groupid字典，编号
            # 然后对messageId取余，对应编号bot响应
            if group.id not in temp_dict:
                member_list = await app.get_member_list(group)
                temp_dict[group.id] = {}
                temp_dict[group.id][0] = app.account
                for item in member_list:
                    if item.id in Ariadne.service.connections:
                        temp_dict[group.id][len(temp_dict[group.id])] = item.id
            if temp_dict[group.id][source.id % len(temp_dict[group.id])] != app.account:
                raise ExecutionStop
            # 防止bot中途掉线/风控造成无响应
            if temp_dict[group.id][source.id % len(temp_dict[group.id])] not in Ariadne.service.connections:
                temp_dict.pop(group.id)
            return Depend(wrapper)

        return Depend(wrapper)
