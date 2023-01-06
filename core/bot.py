import datetime
import os
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
from graia.ariadne.model import LogConfig
from graia.broadcast import Broadcast
from graia.saya import Saya
from graia.saya.builtins.broadcast import BroadcastBehaviour
from graiax.playwright import PlaywrightService
from loguru import logger
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import InternalError, ProgrammingError

from core.config import GlobalConfig, load_config
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

    async def initialize(self):
        if self.initialized:
            return
        self.initialized = True
        self.set_logger()
        logger.info("bot初始化中...")
        bcc = create(Broadcast)
        saya = create(Saya)
        saya.install_behaviours(BroadcastBehaviour(bcc))
        try:
            _ = await orm.init_check()
        except (AttributeError, InternalError, ProgrammingError):
            _ = await orm.create_all()
        # 检查活动群组:
        await orm.update(GroupPerm, {"active": False}, [])
        for app in self.apps:
            group_list = await app.get_group_list()
            self.total_groups[app.account] = group_list
            # 更新群组权限
            for group in group_list:
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
            # 更新成员权限
            await self.update_host_permission()
            await self.update_admins_permission()
        logger.info("本次启动活动群组如下：")
        for account, group_list in self.total_groups.items():
            for group in group_list:
                logger.info(f"Bot账号: {str(account).ljust(14)}群ID: {str(group.id).ljust(14)}群名: {group.name}")
        logger.success("bot初始化完成~")

    # 更新master权限
    async def update_host_permission(self):
        g_config = load_config()
        for bot_account in self.total_groups:
            for group in self.total_groups[bot_account]:
                member_list = await Ariadne.current(bot_account).get_member_list(group)
                member_list = [member.id for member in member_list]
                if g_config.Master in member_list:
                    await orm.insert_or_update(
                        table=MemberPerm,
                        data={"qq": g_config.Master, "group_id": group.id, "perm": 256},
                        condition=[
                            MemberPerm.qq == g_config.Master,
                            MemberPerm.group_id == group.id
                        ]
                    )
                else:
                    await orm.delete(
                        table=MemberPerm,
                        condition=[
                            MemberPerm.qq == g_config.Master,
                            MemberPerm.group_id == group.id
                        ]
                    )

    # 更新admins权限
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
                member_list = await Ariadne.current(bot_account).get_member_list(group)
                member_list = [member.id for member in member_list]
                for admin in admin_list:
                    if admin in member_list:
                        await orm.insert_or_update(
                            table=MemberPerm,
                            data={"qq": admin, "group_id": group.id, "perm": 128},
                            condition=[
                                MemberPerm.qq == admin,
                                MemberPerm.group_id == group.id,
                            ]
                        )
                    else:
                        await orm.delete(
                            table=MemberPerm,
                            condition=[
                                MemberPerm.qq == admin,
                                MemberPerm.group_id == group.id
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
        """配置检查"""
        required_key = ("bot_accounts", "default_account", "host_qq", "mirai_host", "verify_key")
        logger.info("开始检测配置\n" + "-" * 50)
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
        logger.info("检查配置完成\n" + "-" * 50)

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
        """加载 base_path 中的模块

        Args:
            base_path(str pr Path): 要进行加载的文件夹路径，只支持bot文件夹下的文件夹，使用相对路径（从main.py所在文件夹开始）, 如 Path("module") / "saya"
            recursion_install(bool): 是否加载 base_path 内的所有 installable 的模块（包括所有单文件模块、包模块以及base_path下属所有文件夹内的单文件模块、包模块）

        Returns:
            一个包含模块路径和加载时产生的错误的字典, example: {"module.test", ImportError}

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
