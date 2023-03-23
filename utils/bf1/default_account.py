import asyncio
import json
from pathlib import Path

from loguru import logger

from utils.bf1.gateway_api import api_instance
from utils.bf1.orm import BF1DB


class DefaultAccount:
    """
    获取默认账号实例、写入默认账号信息、从默认账号文件读取信息
    默认账号不仅写入了数据库，还写入了文件，以便在重启机器人后，仍然可以使用默认账号
    """

    def __init__(self):
        self.account_path: Path = Path(__file__).parent / 'default_account.json'
        self.account_instance: api_instance = None
        self.pid = None
        self.uid = None
        self.name = None
        self.display_name = None
        self.remid = None
        self.sid = None
        self.session = None
        # 初始化时，从文件读取默认账号信息
        asyncio.run(self.read_default_account())
        # 初始化时，自动登录默认账号
        asyncio.run(self.get_api_instance())

    async def get_api_instance(self) -> api_instance:
        if self.account_instance is None:
            if self.pid:
                self.account_instance = api_instance.get_api_instance(self.pid)
                self.account_instance.session = self.session
                self.account_instance.remid = self.remid
                self.account_instance.sid = self.sid
                if self.remid and self.sid:
                    # 如果session过期，自动登录覆写信息
                    data = await self.account_instance.Companion_isLoggedIn()
                    if not data.get('result').get('isLoggedIn'):
                        logger.debug("正在登录默认账号")
                        await self.account_instance.login(self.remid, self.sid)
                        if await self.account_instance.get_session():
                            session = await self.account_instance.get_session()
                            if isinstance(session, str):
                                self.session = session
                                # 写入session
                                await BF1DB.update_bf1account_loginInfo(
                                    pid=self.pid,
                                    remid=self.remid,
                                    sid=self.sid,
                                    session=self.session
                                )
                                # 更新玩家信息
                                player_info = await self.account_instance.getPersonasByIds(personaIds=self.pid)
                                self.display_name = player_info.get("result").get(str(self.pid)).get("displayName")
                                await self.write_default_account(
                                    pid=self.pid,
                                    uid=self.uid,
                                    name=self.name,
                                    display_name=self.display_name,
                                    remid=self.remid,
                                    sid=self.sid,
                                    session=self.session
                                )
                                logger.success(f"成功登录更新默认账号: {self.display_name}({self.pid})")
                    else:
                        logger.success("成功获取到默认账号session")
            else:
                logger.error("请先配置默认账号pid信息!")
        if not self.account_instance.check_login:
            logger.warning("当前默认查询账户未登录!session过期后将尝试自动登录刷新!")
        return self.account_instance

    async def write_default_account(self, pid, uid, name, display_name, remid, sid, session):
        self.pid = pid
        self.uid = uid
        self.name = name
        self.display_name = display_name
        self.remid = remid
        self.sid = sid
        self.session = session
        # 写入数据库
        await BF1DB.update_bf1account(
            pid=self.pid,
            uid=self.uid,
            name=self.name,
            display_name=self.display_name,
            remid=self.remid,
            sid=self.sid,
            session=self.session
        )
        # 写入文件
        with open(self.account_path, 'w', encoding='utf-8') as f:
            json.dump({
                "pid": self.pid,
                "uid": self.uid,
                "name": self.name,
                "display_name": self.display_name,
                "remid": self.remid,
                "sid": self.sid,
                "session": self.session
            }, f, indent=4, ensure_ascii=False)

    # 从文件读取默认账号信息
    async def read_default_account(self):
        if self.account_path.exists():
            with open(self.account_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self.pid = data["pid"]
                self.uid = data["uid"]
                self.name = data["name"]
                self.display_name = data["display_name"]
                self.remid = data["remid"]
                self.sid = data["sid"]
                self.session = data["session"]
            # 写入数据库
            await BF1DB.update_bf1account(
                pid=self.pid,
                uid=self.uid,
                name=self.name,
                display_name=self.display_name,
                remid=self.remid,
                sid=self.sid,
                session=self.session
            )
            logger.debug(
                f"已从默认账号文件读取到默认账号信息, pid={self.pid}, uid={self.uid}, name={self.name}, display_name={self.display_name}, remid={self.remid}, sid={self.sid}, session={self.session}")
        else:
            with open(self.account_path, 'w', encoding='utf-8') as f:
                json.dump({
                    "pid": self.pid,
                    "uid": self.uid,
                    "name": self.name,
                    "display_name": self.display_name,
                    "remid": self.remid,
                    "sid": self.sid,
                    "session": self.session
                }, f, indent=4, ensure_ascii=False)
            logger.debug("没有找到默认账号文件，已自动创建文件")


default_account = DefaultAccount()
