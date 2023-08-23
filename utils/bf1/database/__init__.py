import datetime
from typing import Union, List, Tuple, Dict, Any

from loguru import logger
from sqlalchemy import select, func

from utils.bf1.database.tables import (
    orm,
    Bf1PlayerBind,
    Bf1Account,
    Bf1Server,
    Bf1Group,
    Bf1MatchCache,
    Bf1ServerVip,
    Bf1ServerBan,
    Bf1ServerAdmin,
    Bf1ServerOwner,
    Bf1ServerPlayerCount,
    Bf1GroupBind,
    Bf1PermGroupBind,
    Bf1PermMemberInfo, Bf1ManagerLog, Bf1ServerManagerVip,
)


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
    class bf1account:

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
                        Bf1Account.persona_id,
                        Bf1Account.user_id,
                        Bf1Account.name,
                        Bf1Account.display_name,
                        Bf1Account.remid,
                        Bf1Account.sid,
                        Bf1Account.session,
                    ).where(Bf1Account.persona_id == pid)
            ):
                return {
                    "pid": account[0],
                    "uid": account[1],
                    "name": account[2],
                    "displayName": account[3],
                    "remid": account[4],
                    "sid": account[5],
                    "session": account[6],
                }
            else:
                return {}

        @staticmethod
        async def get_session_by_pid(pid: int) -> str:
            if account := await orm.fetch_one(
                    select(Bf1Account.session).where(Bf1Account.persona_id == pid)
            ):
                return account[0]
            else:
                return None

        @staticmethod
        async def update_bf1account(
                pid: int,
                display_name: str,
                uid: int = None,
                name: str = None,
                remid: str = None,
                sid: str = None,
                session: str = None,
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
                table=Bf1Account, data=data, condition=[Bf1Account.persona_id == pid]
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
                table=Bf1Account, data=data, condition=[Bf1Account.persona_id == pid]
            )
            return True

        @staticmethod
        async def get_manager_account_info(pid=None) -> Union[List[dict], None]:
            """
            获取所有session非空的即服管帐号
            :return: 有结果时,返回list,无结果时返回None,每个元素为dict,包含pid,uid,name,display_name,remid,sid,session
            """
            if not pid:
                if (
                        accounts := await orm.fetch_all(
                            select(
                                Bf1Account.persona_id,
                                Bf1Account.user_id,
                                Bf1Account.name,
                                Bf1Account.display_name,
                                Bf1Account.remid,
                                Bf1Account.sid,
                                Bf1Account.session,
                            ).where(Bf1Account.session is not None)
                        )
                ):
                    return [
                        {
                            "pid": account[0],
                            "uid": account[1],
                            "name": account[2],
                            "display_name": account[3],
                            "remid": account[4],
                            "sid": account[5],
                            "session": account[6],
                        }
                        for account in accounts
                        if account[6]
                    ]
            if not (
                    account := await orm.fetch_one(
                        select(
                            Bf1Account.persona_id,
                            Bf1Account.user_id,
                            Bf1Account.name,
                            Bf1Account.display_name,
                            Bf1Account.remid,
                            Bf1Account.sid,
                            Bf1Account.session,
                        ).where((Bf1Account.persona_id == pid))
                    )
            ):
                return None
            if account[6]:
                return {
                    "pid": account[0],
                    "uid": account[1],
                    "name": account[2],
                    "display_name": account[3],
                    "remid": account[4],
                    "sid": account[5],
                    "session": account[6],
                }
            else:
                return None

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
            if bind := await orm.fetch_one(
                    select(Bf1PlayerBind.persona_id).where(Bf1PlayerBind.qq == qq)
            ):
                return bind[0]
            else:
                return None

        @staticmethod
        async def get_qq_by_pid(pid: int) -> list:
            """
            根据pid获取绑定的qq
            :param pid: 玩家persona_id(pid)
            :return: 返回一个list,里面是绑定的qq号,没有绑定时返回[]
            """
            if bind := await orm.fetch_all(
                    select(Bf1PlayerBind.qq).where(Bf1PlayerBind.persona_id == pid)
            ):
                return [i[0] for i in bind]
            else:
                return []

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
                data={"persona_id": pid, "qq": qq},
                condition=[Bf1PlayerBind.qq == qq],
            )

        @staticmethod
        async def get_players_info_by_qqs(qqs: list[int]) -> dict:
            # 获取每个qq对应绑定的pid，获取每个pid对应的玩家信息
            # 返回{
            #   qq1:{
            #       pid:xxx,
            #       uid:xxx,
            #       name:xxx,
            #       display_name:xxx,
            #       remid:xxx,
            #       sid:xxx,
            #       session:xxx,
            #   }
            # }
            players_info = {}
            # 批量查询
            for bind in await orm.fetch_all(
                    select(Bf1PlayerBind.qq, Bf1PlayerBind.persona_id).where(Bf1PlayerBind.qq.in_(qqs))
            ):
                if result := await orm.fetch_one(
                    select(
                        Bf1Account.persona_id, Bf1Account.user_id, Bf1Account.name,
                        Bf1Account.display_name, Bf1Account.remid, Bf1Account.sid, Bf1Account.session
                    ).where(Bf1Account.persona_id == bind[1])
                ):
                    players_info[bind[0]] = {
                        "pid": result[0],
                        "uid": result[1],
                        "name": result[2],
                        "display_name": result[3],
                        "remid": result[4],
                        "sid": result[5],
                        "session": result[6],
                    }
            return players_info

    # TODO:
    #  服务器相关
    #  读:
    #  根据serverid/guid获取对应信息如gameid、
    #  写:
    #  从getFullServerDetails获取并写入服务器信息

    class server:

        @staticmethod
        async def update_serverInfo(
                serverName: str,
                serverId: str,
                guid: str,
                gameId: int,
                createdDate: datetime.datetime,
                expirationDate: datetime.datetime,
                updatedDate: datetime.datetime,
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
                    "record_time": datetime.datetime.now(),
                },
                condition=[Bf1Server.serverId == serverId],
            )
            return True

        @staticmethod
        async def update_serverInfoList(
                server_info_list: List[
                    Tuple[
                        str,
                        str,
                        str,
                        int,
                        datetime.datetime,
                        datetime.datetime,
                        datetime.datetime,
                    ]
                ]
        ) -> bool:
            # 构造要插入或更新的记录列表
            info_records = []
            player_records = []
            for (
                    serverName,
                    serverId,
                    guid,
                    gameId,
                    serverBookmarkCount,
                    createdDate,
                    expirationDate,
                    updatedDate,
                    playerCurrent,
                    playerMax,
                    playerQueue,
                    playerSpectator,
            ) in server_info_list:
                record = {
                    "serverName": serverName,
                    "serverId": serverId,
                    "persistedGameId": guid,
                    "gameId": gameId,
                    "createdDate": createdDate,
                    "expirationDate": expirationDate,
                    "updatedDate": updatedDate,
                    "record_time": datetime.datetime.now(),
                }
                info_records.append(record)
                record = {
                    "serverId": serverId,
                    "playerCurrent": playerCurrent,
                    "playerMax": playerMax,
                    "playerQueue": playerQueue,
                    "playerSpectator": playerSpectator,
                    "time": datetime.datetime.now(),
                    "serverBookmarkCount": serverBookmarkCount,
                }
                player_records.append(record)

            # 插入或更新记录
            await orm.insert_or_update_batch(
                table=Bf1Server,
                data_list=info_records,
                conditions_list=[
                    (Bf1Server.serverId == record["serverId"],) for record in info_records
                ],
            )
            await orm.add_batch(table=Bf1ServerPlayerCount, data_list=player_records)

        @staticmethod
        async def get_serverInfo_byServerId(serverId: str) -> Bf1Server:
            if server := await orm.fetch_one(
                    select(
                        Bf1Server.serverName,
                        Bf1Server.serverId,
                        Bf1Server.persistedGameId,
                        Bf1Server.gameId,
                    ).where(Bf1Server.serverId == serverId)
            ):
                return {}
            else:
                return None

        @staticmethod
        async def get_all_serverInfo() -> list:
            if servers := await orm.fetch_all(
                    select(
                        Bf1Server.serverId,
                        Bf1Server.expirationDate,
                    )
            ):
                return [{} for _ in servers]
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
                    "time": datetime.datetime.now(),
                },
                condition=[
                    Bf1ServerVip.serverId == serverId,
                    Bf1ServerVip.personaId == persona_id,
                ],
            )
            return True

        @staticmethod
        async def get_playerVip(persona_id: int) -> int:
            """
            查询玩家的VIP数量
            :param persona_id: 玩家persona_id(pid)
            :return: VIP数量
            """
            if result := await orm.fetch_all(
                    select(Bf1ServerVip.serverId).where(Bf1ServerVip.personaId == persona_id)
            ):
                return len([i[0] for i in result])
            else:
                return 0

        @staticmethod
        async def get_playerVipServerList(persona_id: int) -> list:
            """
            查询玩家的VIP服务器列表
            :param persona_id: 玩家persona_id(pid)
            :return: VIP服务器列表
            """
            if not (
                    result := await orm.fetch_all(
                        select(Bf1ServerVip.serverId).where(
                            Bf1ServerVip.personaId == persona_id
                        )
                    )
            ):
                return []
            server_list = []
            # 根据serverId查询serverName
            for item in result:
                serverId = item[0]
                if server := await orm.fetch_one(
                        select(Bf1Server.serverName).where(Bf1Server.serverId == serverId)
                ):
                    server_list.append(server[0])
            return server_list

        @staticmethod
        async def get_allServerPlayerVipList() -> list:
            """
            查询所有玩家拥有的VIP数量
            :return: 服务器VIP列表
            """
            # 查询整个表
            if not (
                    result := await orm.fetch_all(
                        select(
                            Bf1ServerVip.serverId,
                            Bf1ServerVip.personaId,
                            Bf1ServerVip.displayName,
                        )
                    )
            ):
                return []
            # 挑选出所有的pid和对应dName,放在list中,然后按照server_list的数量排序
            # data = [
            #     {
            #         "pid": 123,
            #         "displayName": "xxx",
            #         "server_list": []
            #     }
            # ]
            data = []
            for item in result:
                serverId = item[0]
                pid = item[1]
                dName = item[2]
                # 如果data中已经存在该pid,则直接添加serverId
                if pid in [i["pid"] for i in data]:
                    for i in data:
                        if i["pid"] == pid:
                            i["server_list"].append(serverId)
                else:
                    data.append(
                        {"pid": pid, "displayName": dName, "server_list": [serverId]}
                    )
            # 按照server_list的数量排序
            data.sort(key=lambda x: len(x["server_list"]), reverse=True)
            return data

        @staticmethod
        async def update_serverVipList(vip_dict: Dict[int, Dict[str, Any]]) -> bool:
            update_list = []
            delete_list = []
            # 查询所有记录
            all_records = await orm.fetch_all(
                select(
                    Bf1ServerVip.serverId, Bf1ServerVip.personaId, Bf1ServerVip.displayName
                ).where(Bf1ServerVip.serverId.in_(vip_dict.keys()))
            )
            all_records = {f"{record[0]}-{record[1]}": record[2] for record in all_records}
            now_records = {
                f"{serverId}-{record['personaId']}": record["displayName"]
                for serverId, records in vip_dict.items()
                for record in records
            }
            # 如果数据库中的记录不在现在的记录中,则删除
            # 如果数据库中的记录在现在的记录中,则更新对应pid下变化的display_name
            for record, value in all_records.items():
                if record not in now_records:
                    delete_list.append(
                        {
                            "serverId": record.split("-")[0],
                            "personaId": record.split("-")[1],
                        }
                    )
                elif value != now_records[record]:
                    update_list.append(
                        {
                            "serverId": record.split("-")[0],
                            "personaId": record.split("-")[1],
                            "displayName": now_records[record],
                            "time": datetime.datetime.now(),
                        }
                    )
            # 如果现在的记录不在数据库中,则插入
            update_list.extend(
                {
                    "serverId": record.split("-")[0],
                    "personaId": record.split("-")[1],
                    "displayName": value_,
                    "time": datetime.datetime.now(),
                }
                for record, value_ in now_records.items()
                if record not in all_records
            )
            # 更新
            await orm.insert_or_update_batch(
                table=Bf1ServerVip,
                data_list=update_list,
                conditions_list=[
                    (
                        Bf1ServerVip.serverId == record["serverId"],
                        Bf1ServerVip.personaId == record["personaId"],
                    )
                    for record in update_list
                ],
            )
            # 删除
            await orm.delete_batch(
                table=Bf1ServerVip,
                conditions_list=[
                    (
                        Bf1ServerVip.serverId == record["serverId"],
                        Bf1ServerVip.personaId == record["personaId"],
                    )
                    for record in delete_list
                ],
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
                    "time": datetime.datetime.now(),
                },
                condition=[
                    Bf1ServerBan.serverId == serverId,
                    Bf1ServerBan.personaId == persona_id,
                ],
            )
            return True

        @staticmethod
        async def get_playerBan(persona_id: int) -> int:
            """
            查询玩家的Ban数量
            :param persona_id: 玩家persona_id(pid)
            :return: Ban数量
            """
            if result := await orm.fetch_all(
                    select(Bf1ServerBan.serverId).where(Bf1ServerBan.personaId == persona_id)
            ):
                return len([i[0] for i in result])
            else:
                return 0

        @staticmethod
        async def get_playerBanServerList(persona_id: int) -> list:
            """
            查询玩家的Ban服务器列表
            :param persona_id: 玩家persona_id(pid)
            :return: Ban服务器列表
            """
            if not (
                    result := await orm.fetch_all(
                        select(Bf1ServerBan.serverId).where(
                            Bf1ServerBan.personaId == persona_id
                        )
                    )
            ):
                return []
            server_list = []
            # 根据serverId查询serverName
            for item in result:
                serverId = item[0]
                if server := await orm.fetch_one(
                        select(Bf1Server.serverName).where(Bf1Server.serverId == serverId)
                ):
                    server_list.append(server[0])
            return server_list

        @staticmethod
        async def get_allServerPlayerBanList() -> list:
            """
            获取所有服务器的玩家Ban列表
            :return: {"pid": pid, "displayName": displayName, "server_list": [serverId, serverId]}
            """
            if not (
                    result := await orm.fetch_all(
                        select(
                            Bf1ServerBan.serverId,
                            Bf1ServerBan.personaId,
                            Bf1ServerBan.displayName,
                        )
                    )
            ):
                return []
            data = {}
            for item in result:
                serverId = item[0]
                pid = item[1]
                displayName = item[2]
                if pid not in data:
                    data[pid] = {"displayName": displayName, "server_list": [serverId]}
                else:
                    data[pid]["server_list"].append(serverId)
            # 按照server_list的数量排序
            data = [{"pid": pid, **value} for pid, value in data.items()]
            data.sort(key=lambda x: len(x["server_list"]), reverse=True)
            return data

        @staticmethod
        async def update_serverBanList(ban_dict: Dict[int, Dict[str, Any]]) -> bool:
            update_list = []
            delete_list = []
            # 查询所有记录
            all_records = await orm.fetch_all(
                select(
                    Bf1ServerBan.serverId, Bf1ServerBan.personaId, Bf1ServerBan.displayName
                ).where(Bf1ServerBan.serverId.in_(ban_dict.keys()))
            )
            all_records = {f"{record[0]}-{record[1]}": record[2] for record in all_records}
            now_records = {
                f"{serverId}-{record['personaId']}": record["displayName"]
                for serverId, records in ban_dict.items()
                for record in records
            }
            # 如果数据库中的记录不在现在的记录中,则删除
            # 如果数据库中的记录在现在的记录中,则更新对应pid下变化的display_name
            for record, value in all_records.items():
                if record not in now_records:
                    delete_list.append(
                        {
                            "serverId": record.split("-")[0],
                            "personaId": record.split("-")[1],
                        }
                    )
                elif value != now_records[record]:
                    update_list.append(
                        {
                            "serverId": record.split("-")[0],
                            "personaId": record.split("-")[1],
                            "displayName": now_records[record],
                            "time": datetime.datetime.now(),
                        }
                    )
            # 如果现在的记录不在数据库中,则插入
            update_list.extend(
                {
                    "serverId": record.split("-")[0],
                    "personaId": record.split("-")[1],
                    "displayName": value_,
                    "time": datetime.datetime.now(),
                }
                for record, value_ in now_records.items()
                if record not in all_records
            )
            # 更新
            await orm.insert_or_update_batch(
                table=Bf1ServerBan,
                data_list=update_list,
                conditions_list=[
                    (
                        Bf1ServerBan.serverId == record["serverId"],
                        Bf1ServerBan.personaId == record["personaId"],
                    )
                    for record in update_list
                ],
            )
            # 删除
            await orm.delete_batch(
                table=Bf1ServerBan,
                conditions_list=[
                    (
                        Bf1ServerBan.serverId == record["serverId"],
                        Bf1ServerBan.personaId == record["personaId"],
                    )
                    for record in delete_list
                ],
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
                    "time": datetime.datetime.now(),
                },
                condition=[
                    Bf1ServerAdmin.serverId == serverId,
                    Bf1ServerAdmin.personaId == persona_id,
                ],
            )
            return True

        @staticmethod
        async def get_playerAdmin(persona_id: int) -> int:
            """
            查询玩家的Admin数量
            :param persona_id: 玩家persona_id(pid)
            :return: Admin数量
            """
            if result := await orm.fetch_all(
                    select(Bf1ServerAdmin.serverId).where(
                        Bf1ServerAdmin.personaId == persona_id
                    )
            ):
                return len([i[0] for i in result])
            else:
                return 0

        @staticmethod
        async def get_playerAdminServerList(persona_id: int) -> list:
            """
            查询玩家的Admin服务器列表
            :param persona_id: 玩家persona_id(pid)
            :return: Admin服务器列表
            """
            if not (
                    result := await orm.fetch_all(
                        select(Bf1ServerAdmin.serverId).where(
                            Bf1ServerAdmin.personaId == persona_id
                        )
                    )
            ):
                return []
            server_list = []
            # 根据serverId查询serverName
            for item in result:
                serverId = item[0]
                if server := await orm.fetch_one(
                        select(Bf1Server.serverName).where(Bf1Server.serverId == serverId)
                ):
                    server_list.append(server[0])
            return server_list

        @staticmethod
        async def get_allServerPlayerAdminList() -> list:
            """
            查询所有服务器的玩家Admin列表
            :return: 所有服务器的玩家Admin列表
            """
            if not (
                    result := await orm.fetch_all(
                        select(
                            Bf1ServerAdmin.serverId,
                            Bf1ServerAdmin.personaId,
                            Bf1ServerAdmin.displayName,
                        )
                    )
            ):
                return []
            data = []
            for item in result:
                serverId = item[0]
                pid = item[1]
                dName = item[2]
                # 如果data中已经存在该pid,则直接添加serverId
                if pid in [i["pid"] for i in data]:
                    for i in data:
                        if i["pid"] == pid:
                            i["server_list"].append(serverId)
                else:
                    data.append(
                        {"pid": pid, "displayName": dName, "server_list": [serverId]}
                    )
            # 按照server_list的数量排序
            data.sort(key=lambda x: len(x["server_list"]), reverse=True)
            return data

        @staticmethod
        async def update_serverAdminList(admin_dict: Dict[int, Dict[str, Any]]) -> bool:
            update_list = []
            delete_list = []
            # 查询所有记录
            all_records = await orm.fetch_all(
                select(
                    Bf1ServerAdmin.serverId,
                    Bf1ServerAdmin.personaId,
                    Bf1ServerAdmin.displayName,
                ).where(Bf1ServerAdmin.serverId.in_(admin_dict.keys()))
            )
            all_records = {f"{record[0]}-{record[1]}": record[2] for record in all_records}
            now_records = {
                f"{serverId}-{record['personaId']}": record["displayName"]
                for serverId, records in admin_dict.items()
                for record in records
            }
            # 如果数据库中的记录不在现在的记录中,则删除
            # 如果数据库中的记录在现在的记录中,则更新对应pid下变化的display_name
            for record, value in all_records.items():
                if record not in now_records:
                    delete_list.append(
                        {
                            "serverId": record.split("-")[0],
                            "personaId": record.split("-")[1],
                        }
                    )
                elif value != now_records[record]:
                    update_list.append(
                        {
                            "serverId": record.split("-")[0],
                            "personaId": record.split("-")[1],
                            "displayName": now_records[record],
                            "time": datetime.datetime.now(),
                        }
                    )
            # 如果现在的记录不在数据库中,则插入
            update_list.extend(
                {
                    "serverId": record.split("-")[0],
                    "personaId": record.split("-")[1],
                    "displayName": value_,
                    "time": datetime.datetime.now(),
                }
                for record, value_ in now_records.items()
                if record not in all_records
            )
            # 更新
            await orm.insert_or_update_batch(
                table=Bf1ServerAdmin,
                data_list=update_list,
                conditions_list=[
                    (
                        Bf1ServerAdmin.serverId == record["serverId"],
                        Bf1ServerAdmin.personaId == record["personaId"],
                    )
                    for record in update_list
                ],
            )
            # 删除
            await orm.delete_batch(
                table=Bf1ServerAdmin,
                conditions_list=[
                    (
                        Bf1ServerAdmin.serverId == record["serverId"],
                        Bf1ServerAdmin.personaId == record["personaId"],
                    )
                    for record in delete_list
                ],
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
                    "time": datetime.datetime.now(),
                },
                condition=[
                    Bf1ServerOwner.serverId == serverId,
                    Bf1ServerOwner.personaId == persona_id,
                ],
            )
            return True

        @staticmethod
        async def get_playerOwner(persona_id: int) -> int:
            """
            查询玩家的Owner数量
            :param persona_id: 玩家persona_id(pid)
            :return: Owner数量
            """
            if result := await orm.fetch_all(
                    select(Bf1ServerOwner.serverId).where(
                        Bf1ServerOwner.personaId == persona_id
                    )
            ):
                return len([i[0] for i in result])
            else:
                return 0

        @staticmethod
        async def get_playerOwnerServerList(persona_id: int) -> list:
            """
            查询玩家的Owner服务器列表
            :param persona_id: 玩家persona_id(pid)
            :return: Owner服务器列表
            """
            if not (
                    result := await orm.fetch_all(
                        select(Bf1ServerOwner.serverId).where(
                            Bf1ServerOwner.personaId == persona_id
                        )
                    )
            ):
                return []
            server_list = []
            # 根据serverId查询serverName
            for item in result:
                serverId = item[0]
                if server := await orm.fetch_one(
                        select(Bf1Server.serverName).where(Bf1Server.serverId == serverId)
                ):
                    server_list.append(server[0])
            return server_list

        @staticmethod
        async def get_allServerPlayerOwnerList() -> list:
            """
            查询所有服务器的Owner列表
            :return: 所有服务器的Owner列表
            """
            if not (
                    result := await orm.fetch_all(
                        select(
                            Bf1ServerOwner.serverId,
                            Bf1ServerOwner.personaId,
                            Bf1ServerOwner.displayName,
                        )
                    )
            ):
                return []
            data = []
            for item in result:
                serverId = item[0]
                pid = item[1]
                dName = item[2]
                # 如果data中已经存在该pid,则直接添加serverId
                if pid in [i["pid"] for i in data]:
                    for i in data:
                        if i["pid"] == pid:
                            i["server_list"].append(serverId)
                else:
                    data.append(
                        {"pid": pid, "displayName": dName, "server_list": [serverId]}
                    )
            # 按照server_list的数量排序
            data.sort(key=lambda x: len(x["server_list"]), reverse=True)
            return data

        @staticmethod
        async def update_serverOwnerList(owner_dict: Dict[int, Dict[str, Any]]) -> bool:
            update_list = []
            delete_list = []
            # 查询所有记录
            all_records = await orm.fetch_all(
                select(
                    Bf1ServerOwner.serverId,
                    Bf1ServerOwner.personaId,
                    Bf1ServerOwner.displayName,
                ).where(Bf1ServerOwner.serverId.in_(owner_dict.keys()))
            )
            all_records = {f"{record[0]}-{record[1]}": record[2] for record in all_records}
            now_records = {
                f"{serverId}-{record['personaId']}": record["displayName"]
                for serverId, records in owner_dict.items()
                for record in records
            }
            # 如果数据库中的记录不在现在的记录中,则删除
            # 如果数据库中的记录在现在的记录中,则更新对应pid下变化的display_name
            for record, value in all_records.items():
                if record not in now_records:
                    delete_list.append(
                        {
                            "serverId": record.split("-")[0],
                            "personaId": record.split("-")[1],
                        }
                    )
                elif value != now_records[record]:
                    update_list.append(
                        {
                            "serverId": record.split("-")[0],
                            "personaId": record.split("-")[1],
                            "displayName": now_records[record],
                            "time": datetime.datetime.now(),
                        }
                    )
            # 如果现在的记录不在数据库中,则插入
            update_list.extend(
                {
                    "serverId": record.split("-")[0],
                    "personaId": record.split("-")[1],
                    "displayName": value_,
                    "time": datetime.datetime.now(),
                }
                for record, value_ in now_records.items()
                if record not in all_records
            )
            # 更新
            await orm.insert_or_update_batch(
                table=Bf1ServerOwner,
                data_list=update_list,
                conditions_list=[
                    (
                        Bf1ServerOwner.serverId == record["serverId"],
                        Bf1ServerOwner.personaId == record["personaId"],
                    )
                    for record in update_list
                ],
            )
            # 删除
            await orm.delete_batch(
                table=Bf1ServerOwner,
                conditions_list=[
                    (
                        Bf1ServerOwner.serverId == record["serverId"],
                        Bf1ServerOwner.personaId == record["personaId"],
                    )
                    for record in delete_list
                ],
            )

        @staticmethod
        async def get_server_bookmark() -> list:
            """
            获取所有服务器的bookmark数
            :return: [{serverName: serverName, bookmark: bookmark}]
            """
            # 查询max(time) - 1s的时间
            time_temp = await orm.fetch_one(select(func.max(Bf1ServerPlayerCount.time)))
            time_temp = time_temp[0] - datetime.timedelta(seconds=1)
            if not time_temp:
                return []
            if not (
                    result := await orm.fetch_all(
                        select(
                            Bf1ServerPlayerCount.serverId,
                            Bf1ServerPlayerCount.serverBookmarkCount,
                        ).where(Bf1ServerPlayerCount.time >= time_temp)
                    )
            ):
                return []
            # 根据serverId查询serverName
            server_list = []
            for item in result:
                serverId = item[0]
                if server := await orm.fetch_one(
                        select(Bf1Server.serverName).where(Bf1Server.serverId == serverId)
                ):
                    server_list.append({"serverName": server[0], "bookmark": item[1]})
            # 按bookmark降序排序
            server_list.sort(key=lambda x: x["bookmark"], reverse=True)
            return server_list

    class server_manager:
        """
        bf1_server_manager_vip表的字段:
        服务器serverId
        serverId = Column(BIGINT, ForeignKey("bf1_server.serverId"), nullable=False)
        玩家pid
        personaId = Column(BIGINT, ForeignKey("bf1_account.persona_id"), nullable=False)
        玩家displayName
        displayName = Column(String, nullable=False)
        vip过期时间，如果为空则表示永久
        expire_time = Column(DateTime, default=None)
        是否生效，行动模式下未check的时候是未生效的状态
        valid = Column(Boolean, default=True)
        创建时间
        time = Column(DateTime)
        """

        @staticmethod
        async def update_server_vip(server_full_info: dict):
            """
            如果玩家信息不在表中就添加到表中且到期时间为无限，
            如果在表中且缓存中的valid为False(未生效)则更新为True(已生效),不更新expire_time,
            如果玩家在表中但是不在服务器则考虑valid,如果是valid则删除
            :param server_full_info:
            :return:
            """
            rsp_info = server_full_info["rspInfo"]
            vipList = rsp_info["vipList"]
            serverId = rsp_info["server"]["serverId"]

            vip_cache = await bf1_db.server_manager.get_server_vip_list(serverId=serverId)
            vip_cache_dict = {str(item["personaId"]): item for item in vip_cache}
            pid_cache = [str(item["personaId"]) for item in vip_cache]

            pid_list = [str(item["personaId"]) for item in vipList]
            displayName_dict = {item["personaId"]: item["displayName"] for item in vipList}
            for vip in vipList:
                # 如果玩家不在表中则添加到表中
                if str(vip["personaId"]) not in pid_cache:
                    await bf1_db.server_manager.update_vip(
                        serverId=serverId,
                        personaId=vip["personaId"],
                        displayName=vip["displayName"],
                        expire_time=None,
                    )
                    logger.debug(f"服务器{serverId}新增vip源{vip['displayName']}({vip['personaId']})")
                # 如果玩家在表中且缓存中的valid为False(未生效)则更新为True(已生效),不更新expire_time
                elif vip_cache_dict[str(vip["personaId"])]["valid"] is False:
                    await bf1_db.server_manager.update_vip(
                        serverId=serverId,
                        personaId=vip["personaId"],
                        displayName=vip["displayName"],
                        expire_time=vip_cache_dict[vip["personaId"]]["expire_time"],
                        valid=True,
                    )
            for vip in vip_cache:
                # 如果玩家在表中但是不在服务器则考虑valid,如果valid为True则删除
                if (str(vip["personaId"]) not in pid_list) and vip["valid"]:
                    await bf1_db.server_manager.delete_vip(
                        serverId=serverId, personaId=vip["personaId"]
                    )
                    logger.debug(f"服务器{serverId}删除vip源{vip['displayName']}({vip['personaId']})")
                # 更新displayName
                if str(vip["personaId"]) in displayName_dict:
                    await bf1_db.server_manager.update_vip(
                        serverId=serverId,
                        personaId=vip["personaId"],
                        displayName=displayName_dict[str(vip["personaId"])],
                        expire_time=vip["expire_time"],
                        valid=vip["valid"],
                    )

        # 查询指定serverId的vip列表
        @staticmethod
        async def get_server_vip_list(serverId: int) -> list:
            """
            查询指定serverId的vip列表
            :param serverId: [int] 服务器id
            :return:
            [{serverId: serverId, personaId: personaId, displayName: displayName, expire_time: expire_time, valid: bool},...]
            expire_time为None表示永久,否则为过期时间,datetime类型
            """
            if not (query_result := await orm.fetch_all(
                    select(
                        Bf1ServerManagerVip.serverId,
                        Bf1ServerManagerVip.personaId,
                        Bf1ServerManagerVip.displayName,
                        Bf1ServerManagerVip.expire_time,
                        Bf1ServerManagerVip.valid,
                        Bf1ServerManagerVip.time,
                    ).where(Bf1ServerManagerVip.serverId == serverId)
            )):
                return []
            return [
                {
                    "serverId": item[0],
                    "personaId": item[1],
                    "displayName": item[2],
                    "expire_time": item[3],
                    "valid": item[4],
                    "time": item[5],
                }
                for item in query_result
            ]

        # 修改vip信息
        @staticmethod
        async def update_vip(
                serverId: int, personaId: int, displayName: str,
                expire_time: Union[datetime.datetime, None] = None, valid: bool = True
        ) -> bool:
            """
            修改vip信息
            :param serverId: [int] 服务器id
            :param personaId: [int] 玩家id
            :param displayName: [str] 玩家名
            :param expire_time: [datetime.datetime, None] 过期时间
            :param valid: [bool] 是否已经生效
            :return:
            """
            await orm.insert_or_update(
                table=Bf1ServerManagerVip,
                data={
                    "serverId": serverId,
                    "personaId": personaId,
                    "displayName": displayName,
                    "expire_time": expire_time,
                    "time": datetime.datetime.now(),
                    "valid": valid,
                },
                condition=(
                    Bf1ServerManagerVip.serverId == serverId,
                    Bf1ServerManagerVip.personaId == personaId,
                ),
            )
            return True

        @staticmethod
        async def delete_vip(serverId: int, personaId: int):
            """
            删除vip信息
            :param serverId: [int] 服务器id
            :param personaId: [int] 玩家pid
            :return:
            """
            await orm.delete(
                table=Bf1ServerManagerVip,
                condition=(
                    Bf1ServerManagerVip.serverId == serverId,
                    Bf1ServerManagerVip.personaId == personaId,
                ),
            )

    # TODO:
    #   bf群组相关
    #   读:
    #   根据qq来获取对应绑定的群组
    #   根据对应guid获取服务器信息
    #   增删改查
    #   写:
    #   绑定qq群和群组名

    class bf1group:

        @staticmethod
        async def get_bf1_group_by_qq(qq_group_id: int):
            """根据qq群号获取对应绑定的bf1群组"""
            group = await orm.fetch_one(
                select(Bf1Group).where(Bf1Group.qq_group_id == qq_group_id)
            )
            return group[0] if group else None

        @staticmethod
        async def get_bf1_server_by_guid(guid: str) -> Bf1Server:
            """根据guid获取服务器信息"""
            server = await orm.fetch_one(
                select(Bf1Server).where(Bf1Server.persistedGameId == guid)
            )
            return server[0] if server else None

        @staticmethod
        async def get_all_bf1_group() -> list:
            """获取所有bf1群组的名字"""
            result = await orm.fetch_all(select(Bf1Group.group_name))
            return [item[0] for item in result]

        @staticmethod
        async def check_bf1_group(group_name: str) -> bool:
            """查找某个群组,大小写不敏感,如果群组存在则返回True,否则False"""
            result = await orm.fetch_one(
                select(Bf1Group).where(
                    func.lower(Bf1Group.group_name) == group_name.lower()
                )
            )
            return bool(result)

        @staticmethod
        async def get_bf1_group_info(group_name: str) -> dict:
            """获取bf1群组的信息"""
            result = await orm.fetch_one(
                select(
                    Bf1Group.id,
                    Bf1Group.group_name,
                    Bf1Group.bind_ids,
                ).where(Bf1Group.group_name == group_name)
            )
            if result:
                return {
                    "id": result[0],
                    "group_name": result[1],
                    "bind_ids": result[2],
                }
            return {}

        @staticmethod
        async def create_bf1_group(group_name: str) -> bool:
            """创建bf1群组"""
            await orm.insert_or_update(
                table=Bf1Group,
                data={"group_name": group_name, "bind_ids": [None for _ in range(30)]},
                condition=[Bf1Group.group_name == group_name],
            )
            return True

        @staticmethod
        async def delete_bf1_group(group_name: str) -> bool:
            """删除bf1群组"""
            await orm.delete(table=Bf1Group, condition=[Bf1Group.group_name == group_name])
            return True

        # 绑定群组信息
        @staticmethod
        async def bind_bf1_group_id(
                group_name: str,
                index: int,
                guid: str,
                gameId: str,
                serverId: str,
                account_pid: str = None,
        ) -> bool:
            """绑定bf1群组和guid
            index为下标,从0开始,最大为29
            """
            # 格式: {
            #   ids:[
            #       {
            #           "guid": "guid",
            #           "gameId": "gameId",
            #           "serverId": "serverId",
            #           "account": "account",
            #       },
            #       {}/None, # 可为空来占位
            #   ],
            # }
            # 必须符合上述格式
            # 不能重复绑定
            bf1_group = await orm.fetch_one(
                select(Bf1Group.id, Bf1Group.group_name, Bf1Group.bind_ids).where(
                    Bf1Group.group_name == group_name
                )
            )
            if not bf1_group:
                return False
            ids = bf1_group[2]
            ids[index] = {
                "guid": guid,
                "gameId": gameId,
                "serverId": serverId,
                "account": account_pid,
            }
            await orm.insert_or_update(
                table=Bf1Group,
                data={"bind_ids": ids},
                condition=[Bf1Group.group_name == group_name],
            )

        @staticmethod
        async def unbind_bf1_group_id(group_name: str, index: int) -> bool:
            """解绑bf1群组和guid"""
            bf1_group = await orm.fetch_one(
                select(Bf1Group.id, Bf1Group.group_name, Bf1Group.bind_ids).where(
                    Bf1Group.group_name == group_name
                )
            )
            if not bf1_group:
                return False
            ids = bf1_group[2]
            ids[index] = None
            await orm.insert_or_update(
                table=Bf1Group,
                data={"bind_ids": ids},
                condition=[Bf1Group.group_name == group_name],
            )
            return True

        # 修改某个群组的名字
        @staticmethod
        async def modify_bf1_group_name(old_group_name: str, new_group_name: str) -> bool:
            """修改bf1群组的名字"""
            await orm.insert_or_update(
                table=Bf1Group,
                data={
                    "group_name": new_group_name,
                },
                condition=[Bf1Group.group_name == old_group_name],
            )
            return True

        # 获取所有群组
        @staticmethod
        async def get_all_bf1_group_info() -> list:
            """获取所有bf1群组的信息"""
            result = await orm.fetch_all(
                select(Bf1Group.id, Bf1Group.group_name, Bf1Group.bind_ids)
            )
            return (
                [
                    {
                        "group_name": item[1],
                        "bind_ids": item[2],
                    }
                    for item in result
                ]
                if result
                else []
            )

        # 绑定QQ群
        @staticmethod
        async def bind_bf1_group_qq_group(group_name: str, qq_group_id: int) -> bool:
            """绑定bf1群组和QQ群
            一个群只能绑定一个群组
            """
            group_id = await orm.fetch_one(
                select(Bf1Group.id).where(Bf1Group.group_name == group_name)
            )
            if not group_id:
                return False
            group_id = group_id[0]
            await orm.insert_or_update(
                table=Bf1GroupBind,
                data={"group_id": group_id, "qq_group": qq_group_id},
                condition=[Bf1GroupBind.qq_group == qq_group_id],
            )
            return True

        @staticmethod
        async def unbind_bf1_group_qq_group(qq_group_id: int) -> bool:
            """解绑bf1群组和QQ群"""
            if result := await orm.fetch_one(
                    select(Bf1GroupBind.id).where(Bf1GroupBind.qq_group == qq_group_id)
            ):
                await orm.delete(table=Bf1GroupBind, condition=[Bf1GroupBind.id == result[0]])
                return True
            return False

        @staticmethod
        async def get_bf1_group_by_qq_group(qq_group_id: int) -> Union[dict, None]:
            """获取bf1群组绑定的QQ群"""
            group_id = await orm.fetch_one(
                select(Bf1GroupBind.group_id).where(Bf1GroupBind.qq_group == qq_group_id)
            )
            if not group_id:
                return None
            group_id = group_id[0]
            group_name = await orm.fetch_one(
                select(Bf1Group.group_name, Bf1Group.bind_ids).where(Bf1Group.id == group_id)
            )
            return (
                {
                    "group_name": group_name[0],
                    "bind_ids": group_name[1],
                }
                if group_name
                else None
            )

        @staticmethod
        async def get_bf1_group_by_name(group_name: str) -> Union[dict, None]:
            """获取bf1群组绑定的QQ群"""
            group_name = await orm.fetch_one(
                select(Bf1Group.group_name, Bf1Group.bind_ids).where(Bf1Group.group_name == group_name)
            )
            return (
                {
                    "group_name": group_name[0],
                    "bind_ids": group_name[1],
                }
                if group_name
                else None
            )

        @staticmethod
        async def get_bf1_group_bindInfo_byIndex(group_name: str, index: int) -> Union[dict, None]:
            """根据群组名和index获取绑定信息"""
            bf1_group = await orm.fetch_one(
                select(Bf1Group.id, Bf1Group.group_name, Bf1Group.bind_ids).where(
                    Bf1Group.group_name == group_name
                )
            )
            if not bf1_group:
                return None
            ids = bf1_group[2]
            return ids[index]

    # TODO
    #   btr对局缓存
    #   读:
    #   根据玩家pid获取对应的btr对局信息
    #   写:
    #   写入btr对局信息

    class bf1_match_cache:

        @staticmethod
        async def get_btr_match_by_displayName(display_name: str) -> Union[list, None]:
            """根据pid获取对应的btr对局信息"""
            # 根据时间获取该display_name最新的10条记录
            if match := await orm.fetch_all(
                    select(
                        Bf1MatchCache.match_id,
                        Bf1MatchCache.server_name,
                        Bf1MatchCache.map_name,
                        Bf1MatchCache.mode_name,
                        Bf1MatchCache.time,
                        Bf1MatchCache.team_name,
                        Bf1MatchCache.team_win,
                        Bf1MatchCache.persona_id,
                        Bf1MatchCache.display_name,
                        Bf1MatchCache.kills,
                        Bf1MatchCache.deaths,
                        Bf1MatchCache.kd,
                        Bf1MatchCache.kpm,
                        Bf1MatchCache.score,
                        Bf1MatchCache.spm,
                        Bf1MatchCache.accuracy,
                        Bf1MatchCache.headshots,
                        Bf1MatchCache.time_played,
                    ).where(Bf1MatchCache.display_name == display_name).order_by(-Bf1MatchCache.time).limit(5)
            ):
                result = []
                for match_item in match:
                    temp = {
                        "match_id": match_item[0],
                        "server_name": match_item[1],
                        "map_name": match_item[2],
                        "mode_name": match_item[3],
                        "time": match_item[4],
                        "team_name": match_item[5],
                        "team_win": match_item[6],
                        "persona_id": match_item[7],
                        "display_name": match_item[8],
                        "kills": match_item[9],
                        "deaths": match_item[10],
                        "kd": match_item[11],
                        "kpm": match_item[12],
                        "score": match_item[13],
                        "spm": match_item[14],
                        "accuracy": match_item[15],
                        "headshots": match_item[16],
                        "time_played": match_item[17],
                    }
                    result.append(temp)
                return result
            return None

        @staticmethod
        async def update_btr_match_cache(
                match_id: int,
                server_name: str,
                map_name: str,
                mode_name: str,
                time: datetime.datetime,
                team_name: str,
                team_win: bool,
                display_name: str,
                kills: int,
                deaths: int,
                kd: float,
                kpm: float,
                score: int,
                spm: float,
                accuracy: str,
                headshots: str,
                time_played: int,
                persona_id: int = 0,
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
                    "time_played": time_played,
                },
                condition=[
                    Bf1MatchCache.match_id == match_id,
                    Bf1MatchCache.display_name == display_name,
                ],
            )

    # TODO
    #   权限组
    #   读:
    #   根据QQ群号获取权限组
    #   根据QQ号判断是否在指定权限组内
    #   写:
    #   添加权限组
    #   删除权限组
    #   添加QQ号到权限组
    #   从权限组删除QQ号
    #   修改QQ号在权限组的权限
    #   修改权限组名称

    class bf1_permission_group:
        # 创建权限组
        # 删除权限组
        # 修改权限组名称
        # 都为对应BF1GROUP表的操作

        # 将QQ群绑定一个权限组
        @staticmethod
        async def bind_permission_group(group_name: str, qq_group_id: int) -> bool:
            """
            一个QQ群只能绑定一个权限组
            :param group_name:
            :param qq_group_id:
            :return:
            """
            if not await orm.fetch_one(select(Bf1Group.group_name).where(Bf1Group.group_name == group_name)):
                return False
            await orm.insert_or_update(
                table=Bf1PermGroupBind,
                data={
                    "bf1_group_name": group_name,
                    "qq_group_id": qq_group_id,
                },
                condition=[
                    Bf1PermGroupBind.qq_group_id == qq_group_id,
                ],
            )
            return True

        # 将QQ群解绑一个权限组
        @staticmethod
        async def unbind_permission_group(qq_group_id: int) -> bool:
            if not await orm.fetch_one(
                    select(Bf1PermGroupBind.qq_group_id).where(Bf1PermGroupBind.qq_group_id == qq_group_id)):
                return False
            await orm.delete(table=Bf1PermGroupBind, condition=[Bf1PermGroupBind.qq_group_id == qq_group_id])
            return True

        # 获取QQ群绑定的权限组
        @staticmethod
        async def get_permission_group(qq_group_id: int) -> str:
            """
            根据QQ群号获取权限组
            :param qq_group_id: QQ群号
            :return: 权限组名称
            """
            result = await orm.fetch_one(
                select(Bf1PermGroupBind.group_name).where(Bf1PermGroupBind.qq_group_id == qq_group_id))
            return result[0] if result else None

        # 获取权限组绑定的QQ群
        @staticmethod
        async def get_permission_group_bind(group_name: str) -> list:
            result = await orm.fetch_all(
                select(Bf1PermGroupBind.qq_group_id).where(Bf1PermGroupBind.group_name == group_name))
            return [item[0] for item in result] if result else None

        # 获取权限组列表
        @staticmethod
        async def get_permission_group_list() -> list:
            result = await orm.fetch_all(select(Bf1Group.group_name))
            return [item[0] for item in result] if result else None

        # 添加/修改QQ号到权限组
        @staticmethod
        async def update_qq_to_permission_group(bf1_group_name: str, qq_id: int, perm: int) -> bool:
            if not await orm.fetch_one(
                    select(Bf1Group.group_name).where(Bf1Group.group_name == bf1_group_name)):
                return False
            await orm.insert_or_update(
                table=Bf1PermMemberInfo,
                data={
                    "bf1_group_name": bf1_group_name,
                    "qq_id": qq_id,
                    "perm": perm,
                },
                condition=[
                    Bf1PermMemberInfo.bf1_group_name == bf1_group_name,
                    Bf1PermMemberInfo.qq_id == qq_id,
                ],
            )
            return True

        # 从权限组删除QQ号
        @staticmethod
        async def delete_qq_from_permission_group(bf1_group_name: str, qq_id: int) -> bool:
            if not await orm.fetch_one(
                    select(Bf1Group.group_name).where(Bf1Group.group_name == bf1_group_name)):
                return False
            await orm.delete(
                table=Bf1PermMemberInfo,
                condition=[
                    Bf1PermMemberInfo.bf1_group_name == bf1_group_name,
                    Bf1PermMemberInfo.qq_id == qq_id,
                ],
            )
            return True

        # 获取权限组内的QQ号和权限
        @staticmethod
        async def get_qq_from_permission_group(bf1_group_name: str) -> Union[dict, None]:
            query = await orm.fetch_all(select(Bf1PermMemberInfo.qq_id, Bf1PermMemberInfo.perm).where(
                Bf1PermMemberInfo.bf1_group_name == bf1_group_name))
            result = {item[0]: item[1] for item in query}
            return result or None

        # 判断QQ号是否在权限组内
        @staticmethod
        async def is_qq_in_permission_group(bf1_group_name: str, qq_id: int) -> bool:
            result = await orm.fetch_all(select(Bf1PermMemberInfo.qq_id).where(
                Bf1PermMemberInfo.bf1_group_name == bf1_group_name and Bf1PermMemberInfo.qq_id == qq_id))
            if result:
                for item in result:
                    if item[0] == qq_id:
                        return True
            return False

        # 获取QQ号在权限组内的权限
        @staticmethod
        async def get_qq_perm_in_permission_group(bf1_group_name: str, qq_id: int) -> int:
            result = await orm.fetch_all(select(Bf1PermMemberInfo.qq_id, Bf1PermMemberInfo.perm).where(
                Bf1PermMemberInfo.bf1_group_name == bf1_group_name and Bf1PermMemberInfo.qq_id == qq_id))
            return next((item[1] for item in result if item[0] == qq_id), -1)

        @staticmethod
        async def delete_permission_group(group_name: str) -> bool:
            if not await orm.fetch_one(select(Bf1PermMemberInfo.bf1_group_name).where(
                    Bf1PermMemberInfo.bf1_group_name == group_name)):
                return False
            await orm.delete(table=Bf1PermMemberInfo, condition=[Bf1PermMemberInfo.bf1_group_name == group_name])
            return True

        @staticmethod
        async def rename_permission_group(old_group_name: str, new_group_name: str) -> bool:
            if not await orm.fetch_one(select(Bf1PermMemberInfo.bf1_group_name).where(
                    Bf1PermMemberInfo.bf1_group_name == old_group_name)):
                return False
            await orm.update(
                table=Bf1PermMemberInfo,
                data={
                    "bf1_group_name": new_group_name,
                },
                condition=[
                    Bf1PermMemberInfo.bf1_group_name == old_group_name,
                ],
            )
            return True

    # TODO
    #   服管操作日志
    #   记录
    #   查询
    # manager log 表的字段:
    #     # 操作者的qq
    #     operator_qq = Column(BIGINT)
    #     # 服务器信息
    #     serverId = Column(BIGINT)
    #     persistedGameId = Column(String)
    #     gameId = Column(BIGINT, nullable=False)
    #     # 固定
    #     persona_id = Column(BIGINT)
    #     # 变化
    #     display_name = Column(String)
    #     # 操作
    #     action = Column(String)
    #     # 信息
    #     info = Column(String)
    #     # 时间
    #     time = Column(DateTime)

    class manager_log:
        @staticmethod
        async def record(
                serverId: int, persistedGameId: str, gameId: int,
                operator_qq: int, pid: int, display_name: str, action: str, info: str = None
        ):
            await orm.add(
                table=Bf1ManagerLog,
                data={
                    "operator_qq": operator_qq,
                    "serverId": serverId,
                    "persistedGameId": persistedGameId,
                    "gameId": gameId,
                    "persona_id": pid,
                    "display_name": display_name,
                    "action": action,
                    "info": info,
                    "time": datetime.datetime.now(),
                },
            )


BF1DB = bf1_db()
