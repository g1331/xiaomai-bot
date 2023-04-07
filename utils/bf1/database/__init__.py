from datetime import datetime
from typing import Union, List, Tuple, Dict, Any

from loguru import logger
from sqlalchemy import select, and_, not_

from utils.bf1.database.tables import orm, Bf1PlayerBind, Bf1Account, Bf1Server, Bf1Group, Bf1GroupBind, Bf1MatchCache, \
    Bf1ServerVip, Bf1ServerBan, Bf1ServerAdmin, Bf1ServerOwner, Bf1ServerPlayerCount


class bf1_db:

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
    async def get_bf1account_by_pid(pid: int) -> dict:
        """
        根据pid获取玩家信息
        :param pid: 玩家persona_id(pid)
        :return: 有结果时,返回dict,无结果时返回None
        """
        # 获取玩家persona_id、user_id、name、display_name
        if account := await orm.fetch_one(
                select(
                    Bf1Account.persona_id, Bf1Account.user_id, Bf1Account.name, Bf1Account.display_name,
                    Bf1Account.remid, Bf1Account.sid, Bf1Account.session
                ).where(
                    Bf1Account.persona_id == pid
                )
        ):
            return {
                "pid": account[0],
                "uid": account[1],
                "name": account[2],
                "display_name": account[3],
                "remid": account[4],
                "sid": account[5],
                "session": account[6]
            }
        else:
            return None

    @staticmethod
    async def get_session_by_pid(pid: int) -> str:
        if account := await orm.fetch_one(select(Bf1Account.session).where(Bf1Account.persona_id == pid)):
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
        await orm.insert_or_update(
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
        await orm.insert_or_update(
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
        if bind := await orm.fetch_one(select(Bf1PlayerBind.persona_id).where(Bf1PlayerBind.qq == qq)):
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
        if bind := await orm.fetch_all(select(Bf1PlayerBind.qq).where(Bf1PlayerBind.persona_id == pid)):
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
        await orm.insert_or_update(
            table=Bf1PlayerBind,
            data={
                "persona_id": pid,
                "qq": qq
            },
            condition=[
                Bf1PlayerBind.qq == qq
            ]
        )

    # TODO:
    #  服务器相关
    #  读:
    #  根据serverid/guid获取对应信息如gameid、
    #  写:
    #  从getFullServerDetails获取并写入服务器信息

    @staticmethod
    async def update_serverInfo(
            serverName: str, serverId: str, guid: str, gameId: int,
            createdDate: datetime, expirationDate: datetime, updatedDate: datetime
    ) -> bool:
        await orm.insert_or_update(
            table=Bf1Server,
            data={
                "serverName": serverName,
                "serverId": serverId,
                "persistedGameId": guid,
                "gameId": gameId,
                "createdDate": createdDate,
                "expirationDate": expirationDate,
                "updatedDate": updatedDate,
                "record_time": datetime.now()
            },
            condition=[
                Bf1Server.serverId == serverId
            ]
        )
        return True

    @staticmethod
    async def update_serverInfoList(
            server_info_list: List[Tuple[str, str, str, int, datetime, datetime, datetime]]
    ) -> bool:
        # 构造要插入或更新的记录列表
        info_records = []
        player_records = []
        for serverName, serverId, guid, gameId, createdDate, expirationDate, updatedDate, \
            playerCurrent, playerMax, playerQueue, playerSpectator in server_info_list:
            record = {
                "serverName": serverName,
                "serverId": serverId,
                "persistedGameId": guid,
                "gameId": gameId,
                "createdDate": createdDate,
                "expirationDate": expirationDate,
                "updatedDate": updatedDate,
                "record_time": datetime.now()
            }
            info_records.append(record)
            record = {
                "serverId": serverId,
                "playerCurrent": playerCurrent,
                "playerMax": playerMax,
                "playerQueue": playerQueue,
                "playerSpectator": playerSpectator,
                "time": datetime.now()
            }
            player_records.append(record)

        # 插入或更新记录
        await orm.insert_or_update_batch(
            table=Bf1Server,
            data_list=info_records,
            conditions_list=[(Bf1Server.serverId == record["serverId"],) for record in info_records]
        )
        await orm.add_batch(
            table=Bf1ServerPlayerCount,
            data_list=player_records
        )

    @staticmethod
    async def get_serverInfo(
            serverId: str
    ) -> Bf1Server:
        if server := await orm.fetch_one(select(
                Bf1Server.serverName, Bf1Server.serverId, Bf1Server.persistedGameId, Bf1Server.gameId,
        ).where(Bf1Server.serverId == serverId)):
            result = {

            }
            return result
        else:
            return None

    @staticmethod
    async def update_serverVip(
            serverId: str, persona_id: int, display_name: str
    ) -> bool:
        await orm.insert_or_update(
            table=Bf1ServerVip,
            data={
                "serverId": serverId,
                "persona_id": persona_id,
                "display_name": display_name,
                "time": datetime.now(),
            },
            condition=[
                Bf1ServerVip.serverId == serverId,
                Bf1ServerVip.personaId == persona_id
            ]
        )
        return True

    @staticmethod
    async def update_serverVipList(
            vip_dict: Dict[int, Dict[str, Any]]
    ) -> bool:
        update_list = []
        delete_list = []
        # 查询所有记录
        all_records = await orm.fetch_all(
            select(Bf1ServerVip.serverId, Bf1ServerVip.personaId, Bf1ServerVip.displayName).where(
                Bf1ServerVip.serverId.in_(vip_dict.keys())
            )
        )
        all_records = {f"{record[0]}-{record[1]}": record[2] for record in all_records}
        now_records = {f"{serverId}-{record['personaId']}": record["displayName"] for serverId, records in
                       vip_dict.items() for
                       record in records}
        # 如果数据库中的记录不在现在的记录中,则删除
        # 如果数据库中的记录在现在的记录中,则更新对应pid下变化的display_name
        for record in all_records:
            if record not in now_records:
                delete_list.append({
                    "serverId": record.split("-")[0],
                    "personaId": record.split("-")[1]
                })
            elif all_records[record] != now_records[record]:
                update_list.append({
                    "serverId": record.split("-")[0],
                    "personaId": record.split("-")[1],
                    "displayName": now_records[record],
                    "time": datetime.now(),
                })
        # 如果现在的记录不在数据库中,则插入
        for record in now_records:
            if record not in all_records:
                update_list.append({
                    "serverId": record.split("-")[0],
                    "personaId": record.split("-")[1],
                    "displayName": now_records[record],
                    "time": datetime.now(),
                })
        # 更新
        await orm.insert_or_update_batch(
            table=Bf1ServerVip,
            data_list=update_list,
            conditions_list=[
                (Bf1ServerVip.serverId == record["serverId"], Bf1ServerVip.personaId == record["personaId"]) for
                record in update_list]
        )
        # 删除
        await orm.delete_batch(
            table=Bf1ServerVip,
            conditions_list=[
                (Bf1ServerVip.serverId == record["serverId"], Bf1ServerVip.personaId == record["personaId"]) for
                record in delete_list]
        )

    @staticmethod
    async def update_serverBan(
            serverId: str, persona_id: int, display_name: str
    ) -> bool:
        await orm.insert_or_update(
            table=Bf1ServerBan,
            data={
                "serverId": serverId,
                "persona_id": persona_id,
                "display_name": display_name,
                "time": datetime.now(),
            },
            condition=[
                Bf1ServerBan.serverId == serverId,
                Bf1ServerBan.personaId == persona_id
            ]
        )
        return True

    @staticmethod
    async def update_serverBanList(
            ban_dict: Dict[int, Dict[str, Any]]
    ) -> bool:
        update_list = []
        delete_list = []
        # 查询所有记录
        all_records = await orm.fetch_all(
            select(Bf1ServerBan.serverId, Bf1ServerBan.personaId, Bf1ServerBan.displayName).where(
                Bf1ServerBan.serverId.in_(ban_dict.keys())
            )
        )
        all_records = {f"{record[0]}-{record[1]}": record[2] for record in all_records}
        now_records = {f"{serverId}-{record['personaId']}": record["displayName"] for serverId, records in
                       ban_dict.items() for
                       record in records}
        # 如果数据库中的记录不在现在的记录中,则删除
        # 如果数据库中的记录在现在的记录中,则更新对应pid下变化的display_name
        for record in all_records:
            if record not in now_records:
                delete_list.append({
                    "serverId": record.split("-")[0],
                    "personaId": record.split("-")[1]
                })
            elif all_records[record] != now_records[record]:
                update_list.append({
                    "serverId": record.split("-")[0],
                    "personaId": record.split("-")[1],
                    "displayName": now_records[record],
                    "time": datetime.now(),
                })
        # 如果现在的记录不在数据库中,则插入
        for record in now_records:
            if record not in all_records:
                update_list.append({
                    "serverId": record.split("-")[0],
                    "personaId": record.split("-")[1],
                    "displayName": now_records[record],
                    "time": datetime.now(),
                })
        # 更新
        await orm.insert_or_update_batch(
            table=Bf1ServerBan,
            data_list=update_list,
            conditions_list=[
                (Bf1ServerBan.serverId == record["serverId"], Bf1ServerBan.personaId == record["personaId"]) for
                record in update_list]
        )
        # 删除
        await orm.delete_batch(
            table=Bf1ServerBan,
            conditions_list=[
                (Bf1ServerBan.serverId == record["serverId"], Bf1ServerBan.personaId == record["personaId"]) for
                record in delete_list]
        )

    @staticmethod
    async def update_serverAdmin(
            serverId: str, persona_id: int, display_name: str
    ) -> bool:
        await orm.insert_or_update(
            table=Bf1ServerAdmin,
            data={
                "serverId": serverId,
                "persona_id": persona_id,
                "display_name": display_name,
                "time": datetime.now(),
            },
            condition=[
                Bf1ServerAdmin.serverId == serverId,
                Bf1ServerAdmin.personaId == persona_id
            ]
        )
        return True

    @staticmethod
    async def update_serverAdminList(
            admin_dict: Dict[int, Dict[str, Any]]
    ) -> bool:
        update_list = []
        delete_list = []
        # 查询所有记录
        all_records = await orm.fetch_all(
            select(Bf1ServerAdmin.serverId, Bf1ServerAdmin.personaId, Bf1ServerAdmin.displayName).where(
                Bf1ServerAdmin.serverId.in_(admin_dict.keys())
            )
        )
        all_records = {f"{record[0]}-{record[1]}": record[2] for record in all_records}
        now_records = {f"{serverId}-{record['personaId']}": record["displayName"] for serverId, records in
                       admin_dict.items() for
                       record in records}
        # 如果数据库中的记录不在现在的记录中,则删除
        # 如果数据库中的记录在现在的记录中,则更新对应pid下变化的display_name
        for record in all_records:
            if record not in now_records:
                delete_list.append({
                    "serverId": record.split("-")[0],
                    "personaId": record.split("-")[1]
                })
            elif all_records[record] != now_records[record]:
                update_list.append({
                    "serverId": record.split("-")[0],
                    "personaId": record.split("-")[1],
                    "displayName": now_records[record],
                    "time": datetime.now(),
                })
        # 如果现在的记录不在数据库中,则插入
        for record in now_records:
            if record not in all_records:
                update_list.append({
                    "serverId": record.split("-")[0],
                    "personaId": record.split("-")[1],
                    "displayName": now_records[record],
                    "time": datetime.now(),
                })
        # 更新
        await orm.insert_or_update_batch(
            table=Bf1ServerAdmin,
            data_list=update_list,
            conditions_list=[
                (Bf1ServerAdmin.serverId == record["serverId"], Bf1ServerAdmin.personaId == record["personaId"]) for
                record in update_list]
        )
        # 删除
        await orm.delete_batch(
            table=Bf1ServerAdmin,
            conditions_list=[
                (Bf1ServerAdmin.serverId == record["serverId"], Bf1ServerAdmin.personaId == record["personaId"]) for
                record in delete_list]
        )

    @staticmethod
    async def update_serverOwner(
            serverId: str, persona_id: int, display_name: str
    ) -> bool:
        await orm.insert_or_update(
            table=Bf1ServerOwner,
            data={
                "serverId": serverId,
                "persona_id": persona_id,
                "display_name": display_name,
                "time": datetime.now(),
            },
            condition=[
                Bf1ServerOwner.serverId == serverId,
                Bf1ServerOwner.personaId == persona_id
            ]
        )
        return True

    @staticmethod
    async def update_serverOwnerList(
            owner_dict: Dict[int, Dict[str, Any]]
    ) -> bool:
        update_list = []
        delete_list = []
        # 查询所有记录
        all_records = await orm.fetch_all(
            select(Bf1ServerOwner.serverId, Bf1ServerOwner.personaId, Bf1ServerOwner.displayName).where(
                Bf1ServerOwner.serverId.in_(owner_dict.keys())
            )
        )
        all_records = {f"{record[0]}-{record[1]}": record[2] for record in all_records}
        now_records = {
            f"{serverId}-{record['personaId']}": record["displayName"]
            for serverId, records in owner_dict.items() for record in records
        }
        # 如果数据库中的记录不在现在的记录中,则删除
        # 如果数据库中的记录在现在的记录中,则更新对应pid下变化的display_name
        for record in all_records:
            if record not in now_records:
                delete_list.append({
                    "serverId": record.split("-")[0],
                    "personaId": record.split("-")[1]
                })
            elif all_records[record] != now_records[record]:
                update_list.append({
                    "serverId": record.split("-")[0],
                    "personaId": record.split("-")[1],
                    "displayName": now_records[record],
                    "time": datetime.now(),
                })
        # 如果现在的记录不在数据库中,则插入
        for record in now_records:
            if record not in all_records:
                update_list.append({
                    "serverId": record.split("-")[0],
                    "personaId": record.split("-")[1],
                    "displayName": now_records[record],
                    "time": datetime.now(),
                })
        # 更新
        await orm.insert_or_update_batch(
            table=Bf1ServerOwner,
            data_list=update_list,
            conditions_list=[
                (Bf1ServerOwner.serverId == record["serverId"],
                 Bf1ServerOwner.personaId == record["personaId"])
                for record in update_list
            ]
        )
        # 删除
        await orm.delete_batch(
            table=Bf1ServerOwner,
            conditions_list=[
                (Bf1ServerOwner.serverId == record["serverId"], Bf1ServerOwner.personaId == record["personaId"]) for
                record in delete_list]
        )

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
        group_bind = await orm.fetch_one(
            select(Bf1GroupBind).where(Bf1GroupBind.qq_group_id == qq_group_id)
        )
        if group_bind:
            bf1_group = await orm.fetch_one(
                select(Bf1Group).where(Bf1Group.id == group_bind[0].bf1_group_id)
            )
            return bf1_group[0]
        return None

    @staticmethod
    async def get_bf1_server_by_guid(guid: str) -> Bf1Server:
        """根据guid获取服务器信息"""
        server = await orm.fetch_one(
            select(Bf1Server).where(Bf1Server.persistedGameId == guid)
        )
        if server:
            return server[0]
        return None

    @staticmethod
    async def bind_qq_group_to_bf1_group(qq_group_id: int, bf1_group_name: str) -> bool:
        """绑定qq群和bf1群组"""
        bf1_group = await orm.fetch_one(
            select(Bf1Group).where(Bf1Group.group_name == bf1_group_name)
        )
        if not bf1_group:
            return False
        else:
            bf1_group = bf1_group[0]
        await orm.insert_or_update(
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
        if match := await orm.fetch_all(
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
                ).where(Bf1MatchCache.display_name == display_name).order_by(-Bf1MatchCache.time).limit(5)
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
        await orm.insert_or_ignore(
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
