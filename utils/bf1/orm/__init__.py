import asyncio
import datetime
from typing import Union

from loguru import logger
from sqlalchemy import select
from sqlalchemy.exc import InternalError, ProgrammingError

from utils.bf1.orm.tables import bf1_orm, Bf1PlayerBind, Bf1Account, Bf1Server, Bf1Group, Bf1GroupBind, Bf1MatchCache


class bf1_db:
    @staticmethod
    async def db_check():
        logger.debug("正在检查bf1数据库")
        try:
            await bf1_orm.init_check()
            logger.success("bf1数据库初始化成功")
        except (AttributeError, InternalError, ProgrammingError):
            logger.debug("bf1数据库初始化失败，正在重建数据库")
            await bf1_orm.create_all()
            logger.success("bf1数据库重建成功")

    def __init__(self):
        asyncio.run(self.db_check())

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
    async def get_bf1account_by_pid(pid: int) -> tuple:
        """
        根据pid获取玩家信息
        :param pid: 玩家persona_id(pid)
        :return: 有结果时,返回一个tuple,依次为pid、uid、name、display_name、remid、sid、session,没有结果时返回None
        """
        # 获取玩家persona_id、user_id、name、display_name
        if account := await bf1_orm.fetch_one(
                select(
                    Bf1Account.persona_id, Bf1Account.user_id, Bf1Account.name, Bf1Account.display_name,
                    Bf1Account.remid, Bf1Account.sid, Bf1Account.session
                ).where(
                    Bf1Account.persona_id == pid
                )
        ):
            return account
        else:
            return None

    @staticmethod
    async def get_session_by_pid(pid: int) -> str:
        if account := await bf1_orm.fetch_one(select(Bf1Account.session).where(Bf1Account.persona_id == pid)):
            return account[0]
        else:
            return None

    @staticmethod
    async def update_bf1account(
            pid: int, display_name: str, uid: int = None, name: str = None,
            remid: str = None, sid: str = None, session: str = None
    ) -> bool:
        if not pid:
            logger.error("pid不能为空!")
            return False
        data = {
            "persona_id": pid,
        }
        if uid:
            data["user_id"] = uid
        if name:
            data["name"] = name
        if display_name:
            data["display_name"] = display_name
        if remid:
            data["remid"] = remid
        if sid:
            data["sid"] = sid
        if session:
            data["session"] = session
        await bf1_orm.insert_or_update(
            table=Bf1Account,
            data=data,
            condition=[
                Bf1Account.persona_id == pid
            ]
        )
        return True

    @staticmethod
    async def update_bf1account_loginInfo(
            pid: int, remid: str = None, sid: str = None, session: str = None
    ) -> bool:
        """
        根据pid写入remid和sid、session
        :param pid: 玩家persona_id(pid)
        :param remid: cookie中的remid
        :param sid: cookie中的sid
        :param session: 登录后的session
        :return: None
        """
        data = {"persona_id": pid}
        if remid:
            data["remid"] = remid
        if sid:
            data["sid"] = sid
        if session:
            data["session"] = session
        await bf1_orm.insert_or_update(
            table=Bf1Account,
            data=data,
            condition=[
                Bf1Account.persona_id == pid
            ]
        )
        return True

    # TODO:
    #  绑定相关
    #  读:
    #  根据qq获取绑定的pid
    #  根据pid获取绑定的qq
    #  写:
    #  写入绑定信息 qq-pid

    @staticmethod
    async def get_pid_by_qq(qq: int) -> int:
        """
        根据qq获取绑定的pid
        :param qq: qq号
        :return: 绑定的pid,没有绑定时返回None
        """
        if bind := await bf1_orm.fetch_one(select(Bf1PlayerBind.persona_id).where(Bf1PlayerBind.qq == qq)):
            return bind[0]
        else:
            return None

    @staticmethod
    async def get_qq_by_pid(pid: int) -> list:
        """
        根据pid获取绑定的qq
        :param pid: 玩家persona_id(pid)
        :return: 返回一个list,里面是绑定的qq号,没有绑定时返回None
        """
        if bind := await bf1_orm.fetch_all(select(Bf1PlayerBind.qq).where(Bf1PlayerBind.persona_id == pid)):
            return [i[0] for i in bind]
        else:
            return None

    @staticmethod
    async def bind_player_qq(qq: int, pid: int) -> bool:
        """
        写入绑定信息 qq-pid
        :param qq: qq号
        :param pid: 玩家persona_id(pid)
        :return: True
        """
        await bf1_orm.insert_or_update(
            table=Bf1PlayerBind,
            data={
                "persona_id": pid,
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
        if server := await bf1_orm.fetch_one(select(Bf1Server).where(Bf1Server.persistedGameId == guid)):
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
                "persistedGameId": guid,
                "serverId": serverId,
                "createdDate": createdDate,
                "expirationDate": expirationDate,
                "updatedDate": updatedDate
            },
            condition=[
                Bf1Server.persistedGameId == guid
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
            select(Bf1Server).where(Bf1Server.persistedGameId == guid)
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

    # TODO
    #   btr对局缓存
    #   读:
    #   根据玩家pid获取对应的btr对局信息
    #   写:
    #   写入btr对局信息
    @staticmethod
    async def get_btr_match_by_displayName(display_name: str) -> Union[list, None]:
        """根据pid获取对应的btr对局信息"""
        # 根据时间获取该display_name最新的10条记录
        if match := await bf1_orm.fetch_all(
                select(
                    Bf1MatchCache.match_id, Bf1MatchCache.server_name,
                    Bf1MatchCache.map_name, Bf1MatchCache.mode_name,
                    Bf1MatchCache.time, Bf1MatchCache.team_name,
                    Bf1MatchCache.team_win, Bf1MatchCache.persona_id,
                    Bf1MatchCache.display_name, Bf1MatchCache.kills,
                    Bf1MatchCache.deaths, Bf1MatchCache.kd, Bf1MatchCache.kpm,
                    Bf1MatchCache.score, Bf1MatchCache.spm,
                    Bf1MatchCache.accuracy, Bf1MatchCache.headshots,
                    Bf1MatchCache.time_played
                ).where(Bf1MatchCache.display_name == display_name).order_by(Bf1MatchCache.time).limit(10)
        ):
            result = []
            for match_item in match:
                temp = {"match_id": match_item[0], "server_name": match_item[1], "map_name": match_item[2],
                        "mode_name": match_item[3], "time": match_item[4], "team_name": match_item[5],
                        "team_win": match_item[6], "persona_id": match_item[7], "display_name": match_item[8],
                        "kills": match_item[9], "deaths": match_item[10], "kd": match_item[11], "kpm": match_item[12],
                        "score": match_item[13], "spm": match_item[14], "accuracy": match_item[15],
                        "headshots": match_item[16], "time_played": match_item[17]}
                result.append(temp)
            return result
        return None

    @staticmethod
    async def update_btr_match_cache(
            match_id: int, server_name: str, map_name: str, mode_name: str, time: datetime,
            team_name: str, team_win: bool, display_name: str, kills: int,
            deaths: int, kd: float, kpm: float, score: int, spm: float, accuracy: str,
            headshots: str, time_played: int, persona_id: int = 0,
    ) -> bool:
        await bf1_orm.insert_or_update(
            table=Bf1MatchCache,
            data={
                "match_id": match_id,
                "server_name": server_name,
                "map_name": map_name,
                "mode_name": mode_name,
                "time": time,
                "team_name": team_name,
                "team_win": team_win,
                "persona_id": persona_id,
                "display_name": display_name,
                "kills": kills,
                "deaths": deaths,
                "kd": kd,
                "kpm": kpm,
                "score": score,
                "spm": spm,
                "accuracy": accuracy,
                "headshots": headshots,
                "time_played": time_played
            },
            condition=[
                Bf1MatchCache.match_id == match_id,
                Bf1MatchCache.display_name == display_name
            ]
        )


BF1DB = bf1_db()
