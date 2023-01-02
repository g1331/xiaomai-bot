import time
from abc import ABC
from typing import Type, List

from creart import create, CreateTargetInfo, AbstractCreator, exists_module, add_creator
from graia.ariadne import Ariadne
from graia.ariadne.model import Member
from sqlalchemy import select

from core.orm import orm
from core.orm.tables import GroupSetting

res_data_instance = None


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
        self.deterministic_account = {}

    @staticmethod
    def get_response_type(group_id: int) -> str:
        if result := await orm.fetch_one(select(GroupSetting.response_type).where(
                GroupSetting.group_id == group_id)):
            return result[0]
        else:
            return "random"

    def get_response_account(self, group_id: int):
        if self.get_response_type(group_id) == "deterministic":
            return self.account_dict[group_id][self.deterministic_account[group_id]]
        return self.account_dict[group_id][time.time() % len(self.account_dict[group_id])]

    def check_initialization(self, group_id: int):
        if self.account_dict.get(group_id, {}) == {}:
            return False
        return True

    def init_group(self, group_id: int, member_list: List[Member], bot_account: int):
        self.account_dict[group_id] = {}
        self.account_dict[group_id][0] = bot_account
        self.deterministic_account[group_id] = 0
        for item in member_list:
            if item.id in Ariadne.service.connections:
                self.account_dict[group_id][len(self.account_dict[group_id])] = item.id
        await orm.insert_or_update(
            GroupSetting,
            {"group_id": group_id, "response_type": "random"},
            [
                GroupSetting.group_id == group_id,
            ]
        )

    def add_account(self, group_id: int, bot_account: int):
        for k in self.account_dict[group_id]:
            if self.account_dict[group_id][k] == bot_account:
                return
        self.account_dict[group_id][len(self.account_dict[group_id])] = bot_account

    def remove_account(self, group_id: int, bot_account: int):
        remove_keys = []
        for k in self.account_dict[group_id]:
            if self.account_dict[group_id][k] == bot_account:
                remove_keys.append(k)
        for k in remove_keys:
            del self.account_dict[group_id][k]


def get_acc_data():
    global res_data_instance
    if not res_data_instance:
        res_data_instance = create(AccountController)
    return res_data_instance


class AccountControllerClassCreator(AbstractCreator, ABC):
    targets = (CreateTargetInfo("core.models.response_model", "AccountController"),)

    @staticmethod
    def available() -> bool:
        return exists_module("core.models.response_model")

    @staticmethod
    def create(create_type: Type[AccountController]) -> AccountController:
        return AccountController()


add_creator(AccountControllerClassCreator)
