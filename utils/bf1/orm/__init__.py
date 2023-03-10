import asyncio

from sqlalchemy import select
from sqlalchemy.exc import InternalError, ProgrammingError

from utils.bf1.orm.tables import bf1_orm, Bf1PlayerBind, Bf1Account, Bf1Server, Bf1Group, Bf1GroupBind


class bf1_db:
    @staticmethod
    async def db_init():
        try:
            # 执行异步函数的代码
            await bf1_orm.init_check()
        except (AttributeError, InternalError, ProgrammingError):
            await bf1_orm.create_all()

    def __init__(self):
        asyncio.create_task(self.db_init())

    # TODO:
    #  BF1账号相关
    #  读：
    #  根据pid获取玩家信息
    #  根据pid获取session
    #  写：
    #  初始化写入玩家pid
    #  根据pid写入remid和sid
    #  根据pid写入session
    @staticmethod
    async def get_bf1account_by_pid(pid: int) -> Bf1Account:
        if account := await bf1_orm.fetch_one(select(Bf1Account).where(Bf1Account.pid == pid)):
            return account[0]
        else:
            return None

    @staticmethod
    async def get_session_by_pid(pid: int) -> str:
        if account := await bf1_orm.fetch_one(select(Bf1Account.session).where(Bf1Account.pid == pid)):
            return account[0]
        else:
            return None

    @staticmethod
    async def update_bf1account(
            pid: int, display_name: str, uid: int = None, name: str = None,
            remid: str = None, sid: str = None, session: str = None
    ):
        await bf1_orm.insert_or_update(
            table=Bf1Account,
            data={
                "pid": pid,
                "uid": uid,
                "name": name,
                "display_name": display_name,
                "remid": remid,
                "sid": sid,
                "session": session
            },
            condition=[
                Bf1Account.pid == pid
            ]
        )

    @staticmethod
    async def update_bf1account_loginInfo(pid: int, remid: str = None, sid: str = None, session: str = None):
        await bf1_orm.insert_or_update(
            table=Bf1Account,
            data={
                "pid": pid,
                "remid": remid,
                "sid": sid,
                "session": session
            },
            condition=[
                Bf1Account.pid == pid
            ]
        )

    # TODO:
    #  绑定相关
    #  读:
    #  根据qq获取绑定的pid
    #  根据pid获取绑定的qq
    #  写:
    #  写入绑定信息 qq-pid

    @staticmethod
    async def get_pid_by_qq(qq: int):
        if bind := await bf1_orm.fetch_one(select(Bf1PlayerBind.pid).where(Bf1PlayerBind.qq == qq)):
            return bind[0]
        else:
            return None

    @staticmethod
    async def get_qq_by_pid(pid: int):
        if bind := await bf1_orm.fetch_all(select(Bf1PlayerBind.qq).where(Bf1PlayerBind.pid == pid)):
            return bind
        else:
            return None

    @staticmethod
    async def bind_player_qq(qq: int, pid: int) -> bool:
        await bf1_orm.insert_or_update(
            table=Bf1PlayerBind,
            data={
                "personaId": pid,
                "qq": qq
            },
            condition=[
                Bf1PlayerBind.qq == qq
            ]
        )
        return True

    # TODO:
    #  服务器相关
    #  读:
    #  根据serverid/guid获取对应信息如gameid、
    #  写:
    #  从getFullServerDetails获取并写入服务器信息
    @staticmethod
    async def get_server_by_guid(guid: str) -> Bf1Server:
        if server := await bf1_orm.fetch_one(select(Bf1Server).where(Bf1Server.guid == guid)):
            return server[0]
        else:
            return None

    @staticmethod
    async def update_serverInfo(
            gameId: int, guid: str, serverId: int, createdDate: int,
            expirationDate: int, updatedDate: int = None
    ) -> bool:
        await bf1_orm.insert_or_update(
            table=Bf1Server,
            data={
                "gameId": gameId,
                "guid": guid,
                "serverId": serverId,
                "createdDate": createdDate,
                "expirationDate": expirationDate,
                "updatedDate": updatedDate
            },
            condition=[
                Bf1Server.guid == guid
            ]
        )
        return True

    # TODO:
    #   bf群组相关
    #   读:
    #   根据qq来获取对应绑定的群组
    #   根据对应guid获取服务器信息
    #   写:
    #   绑定qq群和群组名

    @staticmethod
    async def get_bf1_group_by_qq(qq_group_id: int) -> Bf1Group:
        """根据qq群号获取对应绑定的bf1群组"""
        group_bind = await bf1_orm.fetch_one(
            select(Bf1GroupBind).where(Bf1GroupBind.qq_group_id == qq_group_id)
        )
        if group_bind:
            bf1_group = await bf1_orm.fetch_one(
                select(Bf1Group).where(Bf1Group.id == group_bind[0].bf1_group_id)
            )
            return bf1_group[0]
        return None

    @staticmethod
    async def get_bf1_server_by_guid(guid: str) -> Bf1Server:
        """根据guid获取服务器信息"""
        server = await bf1_orm.fetch_one(
            select(Bf1Server).where(Bf1Server.guid == guid)
        )
        if server:
            return server[0]
        return None

    @staticmethod
    async def bind_qq_group_to_bf1_group(qq_group_id: int, bf1_group_name: str) -> bool:
        """绑定qq群和bf1群组"""
        bf1_group = await bf1_orm.fetch_one(
            select(Bf1Group).where(Bf1Group.group_name == bf1_group_name)
        )
        if not bf1_group:
            return False
        else:
            bf1_group = bf1_group[0]
        await bf1_orm.insert_or_update(
            table=Bf1GroupBind,
            data={
                "qq_group_id": qq_group_id,
                "bf1_group_id": bf1_group.id
            },
            condition=[
                Bf1PlayerBind.qq == qq_group_id
            ]
        )
        return True
