import random
import time
from abc import ABC

from creart import AbstractCreator, CreateTargetInfo, add_creator, create, exists_module
from graia.ariadne import Ariadne
from graia.ariadne.model import Group, Member
from loguru import logger
from sqlalchemy import select

from core.config import GlobalConfig
from core.orm import orm
from core.orm.tables import GroupSetting

account_controller_instance = None
config = create(GlobalConfig)


class AccountController:
    """账户控制器

    account_dict = {
        group_id:{
            0: 123123,
            1: 321321
        }
    }

    deterministic_account = {
        group_id: 0
    }
    """

    def __init__(self):
        self.account_dict = {}
        """
        account_dict = {
            group_id:{
                0: 123
            }
        }
        """
        self.deterministic_account = {}
        """
        deterministic_account = {
            group.id: index
        }
        """
        self.total_groups: dict = {}
        """
        total_groups = {
            group.id: {
                bot_account: Ariadne
            }
        }
        """
        self.public_groups: dict = {}
        """
        public_groups = {
            group.id: {
                bot_account1: Ariadne,
                bot_account2: Ariadne
            }
        }
        """
        self.initialized_bot_list = []
        self.all_initialized = False

    @staticmethod
    async def get_response_type(group_id: int) -> str:
        if result := await orm.fetch_one(
            select(GroupSetting.response_type).where(GroupSetting.group_id == group_id)
        ):
            return result[0]
        else:
            return "random"

    @staticmethod
    async def change_response_type(group_id: int, response_type: str):
        if response_type in {"random", "deterministic"}:
            return await orm.insert_or_update(
                table=GroupSetting,
                data={"group_id": group_id, "response_type": response_type},
                condition=[GroupSetting.group_id == group_id],
            )
        else:
            return

    async def get_response_account(
        self, group_id: int, source_id: int = time.time()
    ) -> int:
        if group_id not in self.total_groups:
            return 0
        if group_id in self.account_dict:
            return self.account_dict[group_id][
                round(source_id) % len(self.account_dict[group_id])
            ]
        if await self.get_response_type(group_id) == "deterministic":
            return self.account_dict[group_id][self.deterministic_account[group_id]]
        return self.account_dict[group_id][
            round(source_id) % len(self.account_dict[group_id])
        ]

    async def get_app_from_total_groups(
        self, group_id: int, require_perm=None, bot_id: int = None
    ) -> tuple[Ariadne, Group]:
        """
        从指定群号和bot权限获取对应Ariadne实例和Group
        @param group_id: 群号
        @param require_perm: 权限名字: Member、Administrator、Owner或列表
        @param bot_id: bot账号
        @return: (Ariadne, Group) 或者(None, None)
        """
        if group_id not in self.total_groups:
            return None, None
        if bot_id:
            if bot_id not in self.total_groups[group_id]:
                return None, None
            app: Ariadne = self.total_groups[group_id][bot_id]
            group = await app.get_group(group_id)
        else:
            app: Ariadne = self.total_groups[group_id][
                random.choice(list(self.total_groups[group_id].keys()))
            ]
            group = await app.get_group(group_id)
        if group_id not in self.total_groups:
            return None, None
        if require_perm:
            member_list = await app.get_member_list(group_id)
            bot_member = await app.get_member(group_id, app.account)
            if bot_member.permission.name in require_perm:
                return self.total_groups[group_id][app.account], group
            for member in member_list:
                member: Member
                if (
                    member.id in self.total_groups[group_id]
                    and member.permission.name in require_perm
                ):
                    group = await Ariadne.current(member.id).get_group(group_id)
                    return self.total_groups[group_id][member.id], group
            return None, None
        return app, group

    def check_initialization(self, group_id: int, bot_account: int):
        """检查群、对应账号是否初始化
        如果已初始化则返回True否则返回False
        """
        if self.account_dict.get(group_id, {}) == {}:
            return False
        return any(
            self.account_dict[group_id][k] == bot_account
            for k in self.account_dict[group_id]
        )

    async def init_group(
        self, group_id: int, member_list: list[Member], bot_account: int
    ):
        self.account_dict[group_id] = {0: bot_account}
        self.deterministic_account[group_id] = 0
        if group_id not in self.total_groups:
            self.total_groups[group_id] = {}
        self.total_groups[group_id][bot_account] = Ariadne.current(bot_account)
        for member in member_list:
            if self.check_account_available(member.id):
                self.account_dict[group_id][len(self.account_dict[group_id])] = (
                    member.id
                )
        if await self.get_response_type(group_id) != "random":
            return
        await orm.insert_or_update(
            GroupSetting,
            {"group_id": group_id, "response_type": "random"},
            [
                GroupSetting.group_id == group_id,
            ],
        )

    async def init_all_group(self):
        if self.all_initialized:
            return
        for bot_account in config.bot_accounts:
            await self.init_account(
                bot_account["account"] if isinstance(bot_account, dict) else bot_account
            )
        self.all_initialized = True

    async def init_account(self, bot_account: int):
        if not self.check_account_available(bot_account):
            return
        app = Ariadne.current(bot_account)
        group_list = await app.get_group_list()
        for group in group_list:
            if group.id not in self.total_groups:
                self.total_groups[group.id] = {}
            self.total_groups[group.id][bot_account] = Ariadne.current(bot_account)
            if len(self.total_groups[group.id].keys()) > 1:
                self.public_groups[group.id] = self.total_groups[group.id]
            try:
                member_list = await app.get_member_list(group.id)
            except Exception as e:
                logger.error(f"获取群成员列表失败: {e}")
                continue
            self.account_dict[group.id] = {0: bot_account}
            self.deterministic_account[group.id] = 0
            for member in member_list:
                if self.check_account_available(member.id):
                    self.add_account(group.id, member.id)
            if await self.get_response_type(group.id) != "random":
                continue
            await orm.insert_or_update(
                GroupSetting,
                {"group_id": group.id, "response_type": "random"},
                [
                    GroupSetting.group_id == group.id,
                ],
            )
        self.initialized_bot_list.append(bot_account)

    @staticmethod
    def check_account_available(bot_account: int):
        return bool(
            (bot_account in Ariadne.service.connections)
            and Ariadne.current(bot_account).connection.status.available
        )

    def add_account(self, group_id: int, bot_account: int):
        for k in self.account_dict[group_id]:
            if self.account_dict[group_id][k] == bot_account:
                return
        self.account_dict[group_id][len(self.account_dict[group_id])] = bot_account

    def remove_account(self, group_id: int, bot_account: int):
        if (
            self.deterministic_account.get(group_id)
            and self.account_dict[self.deterministic_account[group_id]] == bot_account
        ):
            del self.deterministic_account[group_id]
        temp: dict = self.account_dict[group_id]
        self.account_dict[group_id] = {}
        bots_list = [temp[k] for k in temp if temp[k] != bot_account]
        for index in range(len(bots_list)):
            self.account_dict[group_id][index] = bots_list[index]


def get_acc_controller() -> AccountController:
    global account_controller_instance
    if not account_controller_instance:
        account_controller_instance = create(AccountController)
    return account_controller_instance


class AccountControllerClassCreator(AbstractCreator, ABC):
    targets = (CreateTargetInfo("core.models.response_model", "AccountController"),)

    @staticmethod
    def available() -> bool:
        return exists_module("core.models.response_model")

    @staticmethod
    def create(create_type: type[AccountController]) -> AccountController:
        return AccountController()


add_creator(AccountControllerClassCreator)
