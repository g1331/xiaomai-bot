import asyncio
import datetime
import os
import time
from abc import ABC
from pathlib import Path
from typing import Dict, List, Type

from creart import create, add_creator, exists_module
from creart.creator import AbstractCreator, CreateTargetInfo
from graia.ariadne import Ariadne
from graia.ariadne.connection.config import (
    HttpClientConfig,
    WebsocketClientConfig,
    config,
)
from graia.ariadne.event.message import (
    GroupMessage,
    FriendMessage,
    TempMessage,
    StrangerMessage,
    ActiveMessage,
    ActiveGroupMessage,
    ActiveFriendMessage,
)
from graia.ariadne.message.chain import MessageChain
from graia.ariadne.model import LogConfig, Group
from graia.broadcast import Broadcast
from graia.saya import Saya
from graia.saya.builtins.broadcast import BroadcastBehaviour
from graiax.playwright import PlaywrightService
from loguru import logger
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import InternalError, ProgrammingError

from core.config import GlobalConfig
from core.models import response_model
from core.orm import orm
from core.orm.tables import (
    GroupPerm,
    MemberPerm
)

non_log = {
    GroupMessage,
    FriendMessage,
    TempMessage,
    StrangerMessage,
    ActiveMessage,
    ActiveGroupMessage,
    ActiveFriendMessage
}

logs = []


def set_log(log_str: str):
    logs.append(log_str.strip())


class Umaru(object):
    apps: List[Ariadne]
    config: GlobalConfig
    base_path: str or Path
    launch_time: datetime.datetime
    sent_count: int = 0
    received_count: int = 0
    initialized: bool = False

    def __init__(self, g_config: GlobalConfig, base_path: str or Path):
        self.total_groups = {}
        """
        total_groups = {
            bot_account:[Group1, Group2]
        }
        """
        self.launch_time = datetime.datetime.now()
        self.config = create(GlobalConfig)
        self.base_path = base_path if isinstance(base_path, Path) else Path(base_path)
        self.apps = [Ariadne(
            config(
                bot_account,
                str(g_config.verify_key),
                HttpClientConfig(host=g_config.mirai_host),
                WebsocketClientConfig(host=g_config.mirai_host),
            ),
            log_config=LogConfig(lambda x: None if type(x) in non_log else "INFO"),
        ) for bot_account in self.config.bot_accounts]
        if self.config.default_account:
            Ariadne.config(default_account=self.config.default_account)
        Ariadne.launch_manager.add_service(
            PlaywrightService(
                "chromium",
                proxy={"server": self.config.proxy} if self.config.proxy != "proxy" else None
            )
        )
        self.config_check()
        self.initialized_app_list: list[int] = []
        self.initialized_group_list: list[int] = []

    async def initialize(self):
        if self.initialized:
            return
        self.initialized = True
        self.set_logger()
        logger.info("bot????????????...")
        bcc = create(Broadcast)
        saya = create(Saya)
        saya.install_behaviours(BroadcastBehaviour(bcc))
        try:
            _ = await orm.init_check()
        except (AttributeError, InternalError, ProgrammingError):
            _ = await orm.create_all()
        # ??????????????????:
        await orm.update(GroupPerm, {"active": False}, [])
        admin_list = []
        if result := await orm.fetch_all(
                select(MemberPerm.qq).where(
                    MemberPerm.perm == 128,
                )
        ):
            for item in result:
                if item[0] not in admin_list:
                    admin_list.append(item[0])
        time_start = int(time.mktime(self.launch_time.timetuple()))
        Timeout = 10 * len(self.config.bot_accounts)
        while (time.time() - time_start) < Timeout and len(self.initialized_app_list) != len(self.apps):
            for app in self.apps:
                if app.account in self.initialized_app_list:
                    continue
                if not app.connection.status.available:
                    logger.warning(f"{app.account}????????????,??????????????????")
                    continue
                group_list = await app.get_group_list()
                self.total_groups[app.account] = group_list
                # ??????????????????
                for group in group_list:
                    if group.id not in self.initialized_group_list:
                        self.initialized_group_list.append(group.id)
                        if group.id == self.config.test_group:
                            perm = 3
                        elif await orm.fetch_one(
                                select(GroupPerm.group_id).where(
                                    GroupPerm.perm == 2,
                                    GroupPerm.group_id == group.id
                                )
                        ):
                            perm = 2
                        else:
                            perm = 1
                        await orm.insert_or_update(
                            GroupPerm,
                            {"group_id": group.id, "group_name": group.name, "active": True, "perm": perm},
                            [
                                GroupPerm.group_id == group.id
                            ]
                        )
                        # ??????Master??????
                        try:
                            await app.get_member(group, self.config.Master)
                            await orm.insert_or_update(
                                table=MemberPerm,
                                data={"qq": self.config.Master, "group_id": group.id, "perm": 256},
                                condition=[
                                    MemberPerm.qq == self.config.Master,
                                    MemberPerm.group_id == group.id
                                ]
                            )
                        except:
                            await orm.delete(
                                table=MemberPerm,
                                condition=[
                                    MemberPerm.qq == self.config.Master,
                                    MemberPerm.group_id == group.id
                                ]
                            )
                        # ??????BotAdmin??????
                        for admin in admin_list:
                            try:
                                await app.get_member(group, admin)
                                await orm.insert_or_update(
                                    table=MemberPerm,
                                    data={"qq": admin, "group_id": group.id, "perm": 128},
                                    condition=[
                                        MemberPerm.qq == admin,
                                        MemberPerm.group_id == group.id
                                    ]
                                )
                            except:
                                await orm.delete(
                                    table=MemberPerm,
                                    condition=[
                                        MemberPerm.qq == admin,
                                        MemberPerm.group_id == group.id,
                                    ]
                                )
                self.initialized_app_list.append(app.account)
                logger.info(f"??????????????????{len(self.initialized_app_list)}/{len(self.config.bot_accounts)}")
            if len(self.initialized_app_list) != len(self.apps):
                await asyncio.sleep(5)
        logger.info("?????????????????????????????????")
        for account, group_list in self.total_groups.items():
            for group in group_list:
                logger.info(f"Bot??????: {str(account).ljust(14)}???ID: {str(group.id).ljust(14)}??????: {group.name}")
        # ?????????????????????
        await response_model.get_acc_controller().init_all_group()
        init_result = f"bot?????????????????????~??????:{(time.time() - time_start):.2f}???" \
                      f"???????????????{len(self.initialized_app_list)}????????????{len(self.initialized_group_list)}?????????"
        logger.success(init_result)
        if Ariadne.current(self.config.default_account).connection.status.available:
            try:
                await Ariadne.current(self.config.default_account).send_friend_message(
                    self.config.Master,
                    MessageChain(init_result)
                )
            except:
                pass

    async def init_group(self, app: Ariadne, group: Group):
        """
        ??????????????????
        """
        group_list = await app.get_group_list()
        self.total_groups[app.account] = group_list
        # ??????????????????
        if group.id == self.config.test_group:
            perm = 3
        elif await orm.fetch_one(
                select(GroupPerm.group_id).where(
                    GroupPerm.perm == 2,
                    GroupPerm.group_id == group.id
                )
        ):
            perm = 2
        else:
            perm = 1
        await orm.insert_or_update(
            GroupPerm,
            {"group_id": group.id, "group_name": group.name, "active": True, "perm": perm},
            [
                GroupPerm.group_id == group.id
            ]
        )
        self.initialized_app_list.append(app.account)
        # ??????????????????
        member_list = [member.id for member in await app.get_member_list(group)]
        if self.config.Master in member_list:
            await orm.insert_or_update(
                table=MemberPerm,
                data={"qq": self.config.Master, "group_id": group.id, "perm": 256},
                condition=[
                    MemberPerm.qq == self.config.Master,
                    MemberPerm.group_id == group.id
                ]
            )
        if result := await orm.fetch_all(
                select(MemberPerm.qq).where(
                    MemberPerm.perm == 128,
                )
        ):
            admin_list = [item[0] for item in result]
            for admin in admin_list:
                await orm.insert_or_update(
                    table=MemberPerm,
                    data={"qq": admin, "group_id": group.id, "perm": 128},
                    condition=[
                        MemberPerm.qq == admin,
                        MemberPerm.group_id == group.id,
                    ]
                )
        await response_model.get_acc_controller().init_group(group.id, member_list, app.account)
        if group.id not in self.initialized_group_list:
            self.initialized_group_list.append(group.id)
        if Ariadne.current(self.config.default_account).connection.status.available:
            await Ariadne.current(self.config.default_account).send_message(
                await Ariadne.current(self.config.default_account).get_group(self.config.test_group),
                MessageChain(f"??????:{app.account}??????????????????:{group.name}({group.id})")
            )
        logger.success(f"??????????????????:{group.name}({group.id})")

    # ??????admins??????
    async def update_admins_permission(self, admin_list: list[int] = None):
        if not admin_list:
            if result := await orm.fetch_all(
                    select(MemberPerm.qq).where(
                        MemberPerm.perm == 128,
                    )
            ):
                admin_list = [item[0] for item in result]
            else:
                return
        for bot_account in self.total_groups:
            for group in self.total_groups[bot_account]:
                for admin in admin_list:
                    await orm.insert_or_update(
                        table=MemberPerm,
                        data={"qq": admin, "group_id": group.id, "perm": 128},
                        condition=[
                            MemberPerm.qq == admin,
                            MemberPerm.group_id == group.id,
                        ]
                    )

    def set_logger(self):
        logger.add(
            Path.cwd() / "log" / "{time:YYYY-MM-DD}" / "common.log",
            level="INFO",
            retention=f"{self.config.log_related['common_retention']} days",
            encoding="utf-8",
            rotation=datetime.time(),
        )
        logger.add(
            Path.cwd() / "log" / "{time:YYYY-MM-DD}" / "error.log",
            level="ERROR",
            retention=f"{self.config.log_related['error_retention']} days",
            encoding="utf-8",
            rotation=datetime.time(),
        )
        logger.add(set_log)

    def config_check(self) -> None:
        """????????????"""
        required_key = ("bot_accounts", "default_account", "host_qq", "mirai_host", "verify_key")
        logger.info("??????????????????\n" + "-" * 50)
        father_properties = tuple(dir(BaseModel))
        properties = [
            _
            for _ in dir(self.config)
            if _ not in father_properties and not _.startswith("_")
        ]
        for key in properties:
            value = self.config.__getattribute__(key)
            if key in required_key and key == value:
                logger.error(f"Required initial value not changed detected: {key} - {value}")
                exit(0)
            elif isinstance(value, dict):
                logger.success(f"{key}:")
                self.dict_check(value)
            elif key == value:
                logger.warning(f"Unchanged initial value detected: {key} - {value}")
            else:
                logger.success(f"{key} - {value}")
        logger.info("??????????????????\n" + "-" * 50)

    @staticmethod
    def dict_check(dictionary: dict, indent: int = 4) -> None:
        for key in dictionary:
            if isinstance(dictionary[key], dict):
                logger.success(f"{' ' * indent}{key}:")
                Umaru.dict_check(dictionary[key], indent + 4)
            elif dictionary[key] == key:
                logger.warning(f"{' ' * indent}Unchanged initial value detected: {key} - {dictionary[key]}")
            else:
                logger.success(f"{' ' * indent}{key} - {dictionary[key]}")

    @staticmethod
    def install_modules(base_path: str or Path, recursion_install: bool = False) -> Dict[str, Exception]:
        """?????? base_path ????????????

        Args:
            base_path(str pr Path): ?????????????????????????????????????????????bot???????????????????????????????????????????????????main.py????????????????????????, ??? Path("module") / "saya"
            recursion_install(bool): ???????????? base_path ???????????? installable ?????????????????????????????????????????????????????????base_path?????????????????????????????????????????????????????????

        Returns:
            ????????????????????????????????????????????????????????????, example: {"module.test", ImportError}

        """
        if isinstance(base_path, str):
            base_path = Path(base_path)
        saya = create(Saya)
        module_base_path = base_path.as_posix().replace("/", ".")
        exceptions = {}
        ignore = {"__pycache__", "__init__.py"}
        with saya.module_context():
            for module in os.listdir(str(base_path)):
                if module in ignore:
                    continue
                try:
                    if (base_path / module).is_dir():
                        if (base_path / module / "__init__.py").exists():
                            saya.require(f"{module_base_path}.{module}")
                        elif recursion_install:
                            Umaru.install_modules(base_path / module, recursion_install)
                    elif (base_path / module).is_file():
                        saya.require(f"{module_base_path}.{module.split('.')[0]}")
                except Exception as e:
                    logger.exception("")
                    exceptions[str(base_path / module.split('.')[0])] = e
        return exceptions

    @staticmethod
    def launch():
        Ariadne.launch_blocking()


class UmaruClassCreator(AbstractCreator, ABC):
    targets = (CreateTargetInfo("core.bot", "Umaru"),)

    @staticmethod
    def available() -> bool:
        return exists_module("core.bot")

    @staticmethod
    def create(create_type: Type[Umaru]) -> Umaru:
        return Umaru(create(GlobalConfig), Path.cwd())


add_creator(UmaruClassCreator)
