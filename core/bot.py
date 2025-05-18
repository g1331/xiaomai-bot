import asyncio
import datetime
import os
import time
from abc import ABC
from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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
from graia.amnesia.builtins.uvicorn import UvicornService
from graia.ariadne.message.chain import MessageChain
from graia.ariadne.model import LogConfig, Group
from graia.broadcast import Broadcast
from graia.saya import Saya
from graia.saya.builtins.broadcast import BroadcastBehaviour
from graiax.playwright import PlaywrightService
from graiax.fastapi import FastAPIBehaviour, FastAPIService
from loguru import logger
from pydantic import BaseModel
from sqlalchemy import select, create_engine

from core.config import GlobalConfig
from core.models import response_model
from core.orm import orm, Base
from core.orm.tables import GroupPerm, MemberPerm
from utils.launch_time import LaunchTimeService, add_launch_time
from utils.self_upgrade import UpdaterService
from utils.timeout_manager import TimeoutManager

non_log = {
    GroupMessage,
    FriendMessage,
    TempMessage,
    StrangerMessage,
    ActiveMessage,
    ActiveGroupMessage,
    ActiveFriendMessage,
}
UMARU_BOT_LOGO = r"""
 ___  ___  _____ ______   ________  ________  ___  ___          ________  ________  _________
|\  \|\  \|\   _ \  _   \|\   __  \|\   __  \|\  \|\  \        |\   __  \|\   __  \|\___   ___\
\ \  \\\  \ \  \\\__\ \  \ \  \|\  \ \  \|\  \ \  \\\  \       \ \  \|\ /\ \  \|\  \|___ \  \_|
 \ \  \\\  \ \  \\|__| \  \ \   __  \ \   _  _\ \  \\\  \       \ \   __  \ \  \\\  \   \ \  \
  \ \  \\\  \ \  \    \ \  \ \  \ \  \ \  \\  \\ \  \\\  \       \ \  \|\  \ \  \\\  \   \ \  \
   \ \_______\ \__\    \ \__\ \__\ \__\ \__\\ _\\ \_______\       \ \_______\ \_______\   \ \__\
    \|_______|\|__|     \|__|\|__|\|__|\|__|\|__|\|_______|        \|_______|\|_______|    \|__|
"""


class Umaru:
    apps: list[Ariadne]
    config: GlobalConfig
    base_path: str | Path
    launch_time: datetime.datetime
    sent_count: int = 0
    received_count: int = 0
    initialized: bool = False
    logs: list[str] = []

    def __init__(self, g_config: GlobalConfig, base_path: str | Path):
        logger.opt(colors=True).info(f"<fg 227,122,80>{UMARU_BOT_LOGO}</>")
        self.total_groups: dict[int, list[Group]] = {}
        """
        total_groups = {
            bot_account:[Group1, Group2]
        }
        """
        self.launch_time = datetime.datetime.now()
        self.config = create(GlobalConfig)
        self.base_path = base_path if isinstance(base_path, Path) else Path(base_path)
        self.apps = [
            Ariadne(
                config(
                    bot_account["account"]
                    if isinstance(bot_account, dict)
                    else int(bot_account),
                    str(g_config.verify_key),
                    HttpClientConfig(host=g_config.mirai_host),
                    WebsocketClientConfig(host=g_config.mirai_host),
                ),
                log_config=LogConfig(lambda x: None if type(x) in non_log else "INFO"),
            )
            for bot_account in self.config.bot_accounts
        ]
        if self.config.default_account:
            Ariadne.config(default_account=self.config.default_account)
        Ariadne.launch_manager.add_service(
            PlaywrightService(
                "chromium",
                proxy={"server": self.config.proxy}
                if self.config.proxy != "proxy"
                else None,
            )
        )
        if self.config.web_manager_api:
            Ariadne.launch_manager.add_service(
                UvicornService(
                    host="0.0.0.0" if self.config.api_expose else "127.0.0.1",
                    port=self.config.api_port,
                )
            )
            fastapi = FastAPI()
            fastapi.add_middleware(
                CORSMiddleware,
                allow_origins=["*"],
                allow_credentials=True,
                allow_methods=["*"],
                allow_headers=["*"],
            )
            create(Saya).install_behaviours(FastAPIBehaviour(fastapi))
            Ariadne.launch_manager.add_service(FastAPIService(fastapi))
        # 推后导入，避免循环导入
        from utils.alembic import AlembicService

        Ariadne.launch_manager.add_service(AlembicService())
        Ariadne.launch_manager.add_service(UpdaterService())
        Ariadne.launch_manager.add_service(LaunchTimeService())
        self.config_check()
        self.initialized_app_list: list[int] = []
        self.initialized_group_list: list[int] = []

    async def initialize(self):
        if self.initialized:
            return
        self.initialized = True
        self.set_logger()
        logger.debug("等待账号初始化")
        await asyncio.sleep(len(self.apps) if len(self.apps) <= 5 else 5)
        logger.debug("BOT初始化开始...")
        logger.debug(f"预计初始化{len(self.apps)}个账号")
        bcc = create(Broadcast)
        saya = create(Saya)
        saya.install_behaviours(BroadcastBehaviour(bcc))
        # 检查活动群组:
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
        timeout = TimeoutManager.calculate_timeout(len(self.apps))
        logger.debug(f"账号初始化超时时间设置为: {timeout}秒")

        last_progress = 0
        while ((time.time() - time_start) < timeout) and (
            len(self.initialized_app_list) != len(self.apps)
        ):
            # 记录初始化进度
            current_progress = TimeoutManager.get_progress(
                len(self.initialized_app_list), len(self.apps)
            )
            if current_progress != last_progress:
                logger.info(f"初始化进度: {current_progress}%")
                last_progress = current_progress
            tasks = []
            for app in self.apps:
                tasks.append(self.init_app(app))
            await asyncio.gather(*tasks)
            logger.debug(
                f"已初始化账号{len(self.initialized_app_list)}/{len(self.config.bot_accounts)}"
            )
            if len(self.initialized_app_list) != len(self.apps):
                await asyncio.sleep(3)
        # 更新多账户响应
        await response_model.get_acc_controller().init_all_group()
        logger.success("成功初始化多账户响应!")
        # 更新权限
        await self.update_master_permission()
        logger.success("成功更新master权限!")
        await self.update_admins_permission(admin_list)
        logger.success("成功更新admins权限!")
        from core.control import Distribute

        Distribute.distribute_initialize()
        if self.initialized_app_list:
            logger.info("本次启动活动群组如下：")
            for account, group_list in self.total_groups.items():
                for group in group_list:
                    logger.info(
                        f"Bot账号: {str(account).ljust(14)}群ID: {str(group.id).ljust(14)}群名: {group.name}"
                    )
            init_result = (
                f"BOT账号初始化完成!\n"
                f"耗时:{(time.time() - time_start):.2f}秒\n"
                f"成功初始化{len(self.initialized_app_list)}/{len(self.apps)}个账户、{len(self.initialized_group_list)}个群组"
            )
            logger.success(init_result.replace("\n", "\\n"))
            # 向主人发送启动完成的信息
            if Ariadne.current(self.config.default_account).connection.status.available:
                try:
                    await Ariadne.current(
                        self.config.default_account
                    ).send_friend_message(self.config.Master, MessageChain(init_result))
                except Exception:
                    pass
        else:
            logger.critical(
                f"BOT账号初始化失败!"
                f"耗时:{(time.time() - time_start):.2f}秒\n"
                f"初始化了{len(self.initialized_app_list)}/{len(self.apps)}个账户、{len(self.initialized_group_list)}个群组\n"
                f"超时时间: {timeout}秒"
            )

    async def init_app(self, app):
        if not app.connection.status.available:
            logger.warning(f"{app.account}失去连接,已跳过初始化")
            return
        if app.account in self.initialized_app_list:
            return
        logger.debug(f"账号{app.account}初始化ing")
        group_list = [
            group
            for group in await app.get_group_list()
            if group.id not in self.initialized_group_list
        ]
        self.total_groups[app.account] = group_list
        # 更新群组权限
        group_init_counter = 0
        for group in group_list:
            if group.id not in self.initialized_group_list:
                # 更新Group权限和活动状态
                perm = await self.get_init_group_perm(group)
                active = await self.get_init_group_active(group)
                await orm.insert_or_update(
                    GroupPerm,
                    {
                        "group_id": group.id,
                        "group_name": group.name,
                        "active": active,
                        "perm": perm,
                    },
                    [GroupPerm.group_id == group.id],
                )
                self.initialized_group_list.append(group.id)
                group_init_counter += 1
        if app.account not in self.initialized_app_list:
            self.initialized_app_list.append(app.account)
            logger.debug(
                f"账号{app.account}初始化完成,初始化群组{group_init_counter}个"
            )

    async def get_init_group_perm(self, group: Group) -> int:
        # 更新群组权限
        if group.id == self.config.test_group:
            perm = 3
        elif await orm.fetch_one(
            select(GroupPerm.group_id).where(
                GroupPerm.perm == 2, GroupPerm.group_id == group.id
            )
        ):
            perm = 2
        else:
            perm = 1
        return perm

    @staticmethod
    async def get_init_group_active(group: Group) -> bool:
        if result := await orm.fetch_one(
            select(GroupPerm.active).where(GroupPerm.group_id == group.id)
        ):
            return result[0]
        else:
            await orm.insert_or_update(
                GroupPerm,
                {"group_id": group.id, "group_name": group.name, "active": True},
                [GroupPerm.group_id == group.id],
            )
            return True

    async def init_group(self, app: Ariadne, group: Group):
        """
        初始化指定群
        """
        group_list = await app.get_group_list()
        self.total_groups[app.account] = group_list
        perm = await self.get_init_group_perm(group)
        active = await self.get_init_group_active(group)
        await orm.insert_or_update(
            GroupPerm,
            {
                "group_id": group.id,
                "group_name": group.name,
                "active": active,
                "perm": perm,
            },
            [GroupPerm.group_id == group.id],
        )
        self.initialized_app_list.append(app.account)
        # 更新成员权限
        member_list = await app.get_member_list(group)
        if self.config.Master in [member.id for member in member_list]:
            await orm.insert_or_update(
                table=MemberPerm,
                data={"qq": self.config.Master, "group_id": group.id, "perm": 256},
                condition=[
                    MemberPerm.qq == self.config.Master,
                    MemberPerm.group_id == group.id,
                ],
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
                    ],
                )
        await response_model.get_acc_controller().init_group(
            group.id, member_list, app.account
        )
        if group.id not in self.initialized_group_list:
            self.initialized_group_list.append(group.id)
        if Ariadne.current(self.config.default_account).connection.status.available:
            await Ariadne.current(self.config.default_account).send_message(
                await Ariadne.current(self.config.default_account).get_group(
                    self.config.test_group
                ),
                MessageChain(
                    f"账号:{app.account}成功初始化群:{group.name}({group.id})"
                ),
            )
        logger.success(f"成功初始化群:{group.name}({group.id})")

    # 更新master权限
    async def update_master_permission(self):
        group_id_list = [
            group.id
            for bot_account in self.total_groups
            for group in self.total_groups[bot_account]
        ]
        group_id_list = list(set(group_id_list))
        await orm.insert_or_update_batch(
            table=MemberPerm,
            data_list=[
                {"qq": self.config.Master, "group_id": group_id, "perm": 256}
                for group_id in group_id_list
            ],
            conditions_list=[
                [MemberPerm.qq == self.config.Master, MemberPerm.group_id == group_id]
                for group_id in group_id_list
            ],
        )

    # 更新admins权限
    async def update_admins_permission(self, admin_list: list[int] | None = None):
        if not admin_list:
            if result := await orm.fetch_all(
                select(MemberPerm.qq).where(
                    MemberPerm.perm == 128,
                )
            ):
                admin_list = [item[0] for item in result]
            else:
                return
        group_id_list = [
            group.id
            for bot_account in self.total_groups
            for group in self.total_groups[bot_account]
        ]
        # 去重
        admin_list = list(set(admin_list))
        group_id_list = list(set(group_id_list))
        await orm.insert_or_update_batch(
            table=MemberPerm,
            data_list=[
                {"qq": admin, "group_id": group_id, "perm": 128}
                for group_id in group_id_list
                for admin in admin_list
            ],
            conditions_list=[
                [
                    MemberPerm.qq == admin,
                    MemberPerm.group_id == group_id,
                ]
                for group_id in group_id_list
                for admin in admin_list
            ],
        )

    def set_log(self, log_str: str):
        self.logs.append(log_str.strip())

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
        logger.add(self.set_log)

    def config_check(self) -> None:
        """配置检查"""
        required_key = (
            "bot_accounts",
            "default_account",
            "host_qq",
            "mirai_host",
            "verify_key",
        )
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
                logger.error(
                    f"Required initial value not changed detected: {key} - {value}"
                )
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
                logger.warning(
                    f"{' ' * indent}Unchanged initial value detected: {key} - {dictionary[key]}"
                )
            else:
                logger.success(f"{' ' * indent}{key} - {dictionary[key]}")

    @staticmethod
    def install_modules(
        base_path: str | Path, recursion_install: bool = False
    ) -> dict[str, Exception]:
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
                    start = datetime.datetime.now()
                    if (base_path / module).is_dir():
                        if (base_path / module / "__init__.py").exists():
                            saya.require(f"{module_base_path}.{module}")
                        elif recursion_install:
                            Umaru.install_modules(base_path / module, recursion_install)
                    elif (base_path / module).is_file():
                        saya.require(f"{module_base_path}.{module.split('.')[0]}")
                    add_launch_time(
                        f"{module_base_path}.{module}",
                        (datetime.datetime.now() - start).total_seconds(),
                        0,
                    )
                except Exception as e:
                    logger.exception("")
                    exceptions[str(base_path / module.split(".")[0])] = e
                    add_launch_time(
                        f"{module_base_path}.{module}",
                        (datetime.datetime.now() - start).total_seconds(),
                        1,
                    )
        return exceptions

    async def alembic(self):
        alembic_path = Path.cwd() / "alembic"

        # 检查是否存在alembic目录，如果不存在则初始化
        if not alembic_path.exists():
            logger.info("未检测到alembic目录，进行初始化")
            os.system("alembic init alembic")

            # 从statics目录复制alembic环境内容
            with open(Path.cwd() / "statics" / "alembic_env_py_content.txt") as r:
                alembic_env_py_content = r.read()
            with open(alembic_path / "env.py", "w") as w:
                w.write(alembic_env_py_content)

            # 在alembic.ini中更新数据库链接
            db_link = self.config.db_link
            formatted_db_link = (
                db_link.split(":")[0].split("+")[0]
                + ":"
                + ":".join(db_link.split(":")[1:])
            )
            logger.warning(
                f"尝试自动更改 sqlalchemy.url 为 {formatted_db_link}，若出现报错请自行修改"
            )
            alembic_ini_path = Path.cwd() / "alembic.ini"
            lines = alembic_ini_path.read_text(encoding="utf-8").split("\n")
            for i, line in enumerate(lines):
                if line.startswith("sqlalchemy.url"):
                    lines[i] = line.replace(
                        "driver://user:pass@localhost/dbname", formatted_db_link
                    )
                    break
            alembic_ini_path.write_text("\n".join(lines))

        alembic_version_path = alembic_path / "versions"

        # 确保versions目录存在
        if not alembic_version_path.exists():
            alembic_version_path.mkdir()

        # 检查当前模型与数据库之间是否存在差异
        sync_db_link = orm.get_sync_db_link(
            self.config.db_link
        )  # 异步驱动映射为同步驱动,因为alembic不支持异步驱动
        sync_engine = create_engine(sync_db_link)
        conn = sync_engine.connect()
        context = MigrationContext.configure(conn)
        diff = compare_metadata(context, Base.metadata)

        if diff:
            # logger.debug("检测到模型和数据库之间存在差异，正在尝试自动更新数据库")
            # cfg = Config(file_="alembic.ini", ini_section="alembic")
            # try:
            #     revision(cfg, message="update", autogenerate=True)
            #     upgrade(cfg, "head")
            #     # os.system("alembic revision --autogenerate -m 'update'")
            #     # os.system("alembic upgrade head")
            #     logger.success("数据库更新成功")
            # except (CommandError, ResolutionError):
            #     logger.warning("数据库更新失败，正在重置数据库")
            #     _ = await orm.reset_version()
            #     shutil.rmtree(alembic_version_path)
            #     alembic_version_path.mkdir()
            #     revision(cfg, message="update", autogenerate=True)
            #     upgrade(cfg, "head")
            # finally:
            #     conn.close()
            logger.warning("检测到模型和数据库之间存在差异，请手动更新数据库!")
        else:
            logger.debug("您的数据库定义没有差异，无需更新")

    @staticmethod
    def launch():
        Ariadne.launch_blocking()


class UmaruClassCreator(AbstractCreator, ABC):
    targets = (CreateTargetInfo("core.bot", "Umaru"),)

    @staticmethod
    def available() -> bool:
        return exists_module("core.bot")

    @staticmethod
    def create(create_type: type[Umaru]) -> Umaru:
        return Umaru(create(GlobalConfig), Path.cwd())


add_creator(UmaruClassCreator)
