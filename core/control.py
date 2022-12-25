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
from loguru import logger
from sqlalchemy import select

from core.config import GlobalConfig
from core.orm import orm
from core.orm.tables import MemberPerm, GroupPerm

config = create(GlobalConfig)


class Permission(object):
    """
    判断权限的类

    成员权限:
    -1为全局黑
    0为单群黑
    16为群员
    32为管理
    64为群主
    128为Admin
    256为Master

    群权限:
    0为非活动群组
    1为正常活动群组
    2为vip群组
    3为测试群组
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
        result = await orm.fetch_one(
            select(GroupPerm.perm).where(
                GroupPerm.group_id == group.id
            )
        )
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
