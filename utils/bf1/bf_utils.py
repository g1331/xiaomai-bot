import asyncio
import datetime
import json
import platform
import time
from functools import wraps

import aiohttp
import httpx
import tiktoken
import urllib3
from bs4 import BeautifulSoup
from creart import create
from curl_cffi.requests import AsyncSession
from graia.ariadne import Ariadne
from graia.ariadne.message import Source
from graia.ariadne.message.chain import MessageChain
from graia.ariadne.message.parser.twilight import MatchResult
from graia.ariadne.model import Group, Member
from loguru import logger
from revChatGPT.V3 import Chatbot

from core.config import GlobalConfig
from core.control import Permission
from utils.bf1.blaze.BlazeClient import BlazeClientManagerInstance
from utils.bf1.blaze.BlazeSocket import BlazeSocket
from utils.bf1.data_handle import BlazeData
from utils.bf1.database import BF1DB
from utils.bf1.default_account import BF1DA
from utils.bf1.gateway_api import api_instance
from utils.bf1.map_team_info import MapData

if platform.system() == "Windows":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
urllib3.disable_warnings()

config = create(GlobalConfig)
proxy = config.proxy if config.proxy != "proxy" else ""


async def get_personas_by_name(player_name: str) -> dict | None:
    """根据玩家名称获取玩家信息
    :param player_name: 玩家名称
    :return: 成功返回dict，失败返回str信息，玩家不存在返回None
    """
    player_info = await (await BF1DA.get_api_instance()).getPersonasByName(player_name)
    if isinstance(player_info, str):
        return player_info
    elif not player_info.get("personas"):
        return None
    else:
        pid = player_info["personas"]["persona"][0]["personaId"]
        uid = player_info["personas"]["persona"][0]["pidId"]
        display_name = player_info["personas"]["persona"][0]["displayName"]
        name = player_info["personas"]["persona"][0]["name"]
        # dateCreated = player_info["personas"]["persona"][0]["dateCreated"]
        # lastAuthenticated = player_info["personas"]["persona"][0]["lastAuthenticated"]
        # 写入数据库
        try:
            await BF1DB.bf1account.update_bf1account(
                pid=pid,
                uid=uid,
                name=name,
                display_name=display_name,
            )
        except Exception as e:
            logger.error((e, player_info))
        return player_info


async def get_personas_by_player_pid(player_pid: int) -> dict | str | None:
    """根据玩家pid获取玩家信息
    :param player_pid: 玩家pid
    :return: 查询成功返回dict, 查询失败返回str, pid不存在返回None
    """
    player_info = await (await BF1DA.get_api_instance()).getPersonasByIds(player_pid)
    # 如果pid不存在,则返回错误信息
    if isinstance(player_info, str):
        return player_info
    elif not player_info.get("result"):
        return None
    else:
        try:
            display_name = player_info["result"][str(player_pid)]["displayName"]
            uid = player_info["result"][str(player_pid)]["nucleusId"]
            await BF1DB.bf1account.update_bf1account(
                pid=player_pid,
                uid=uid,
                display_name=display_name,
            )
        except Exception as e:
            logger.error((e, player_info))
        return player_info


async def check_bind(qq: int) -> dict | str | None:
    """检查玩家是否绑定
    :param qq: 玩家QQ
    :return: 返回玩家信息,如果未绑定则返回None,查询失败返回str信息"""
    player_pid = await BF1DB.bf1account.get_pid_by_qq(qq)
    if not player_pid:
        return None
    # 修改逻辑,先从数据库中获取,如果数据库中没有则从API中获取
    player_info = await BF1DB.bf1account.get_bf1account_by_pid(player_pid)
    if player_info:
        return {
            "displayName": player_info["displayName"],
            "pid": player_pid,
            "uid": player_info["uid"],
            "qq": qq,
        }
    player_info = await get_personas_by_player_pid(player_pid)
    if isinstance(player_info, str):
        return player_info
    elif not player_info:
        return None
    else:
        # 更新该pid的信息
        await BF1DB.bf1account.update_bf1account(
            pid=player_pid,
            uid=player_info["result"][str(player_pid)]["nucleusId"],
            display_name=player_info["result"][str(player_pid)]["displayName"],
        )
        displayName = player_info["result"][str(player_pid)]["displayName"]
        pid = player_info["result"][str(player_pid)]["personaId"]
        uid = player_info["result"][str(player_pid)]["nucleusId"]
        return {"displayName": displayName, "pid": pid, "uid": uid, "qq": qq}


async def BTR_get_recent_info(player_name: str) -> list[dict]:
    """
    从BTR获取最近的战绩
    :param player_name: 玩家名称
    :return: 返回一个列表，列表中的每个元素是一个字典，默认爬取全部数据，调用处决定取前几个
    """
    result = []
    # BTR玩家个人信息页面
    url = f"https://battlefieldtracker.com/bf1/profile/pc/{player_name}"
    header = {
        "Connection": "keep-alive",
        "User-Agent": "ProtoHttp 1.3/DS 15.1.2.1.0 (Windows)",
    }
    async with aiohttp.ClientSession(headers=header, proxy=proxy) as session:
        async with session.get(url) as response:
            html = await response.text()
            # 处理网页获取失败的情况
            if not html:
                return result
            soup = BeautifulSoup(html, "html.parser")
            # 从<div class="card-body player-sessions">获取对局数量，如果找不到则返回None
            if not soup.select("div.card-body.player-sessions"):
                return None
            sessions = soup.select("div.card-body.player-sessions")[0].select(
                "div.sessions"
            )
            # 每个sessions由标题和对局数据组成，标题包含时间和胜率，对局数据包含spm、kdr、kpm、btr、gs、tp
            for item in sessions:
                time_item = item.select("div.title > div.time > h4 > span")[0]
                # 此时time_item =  <span data-livestamp="2023-03-22T14:00:00.000Z"></span>
                # 提取UTC时间转换为本地时间的时间戳
                time_item = time_item["data-livestamp"]
                # 将时间戳转换为时间
                time_item = datetime.datetime.fromtimestamp(
                    time.mktime(time.strptime(time_item, "%Y-%m-%dT%H:%M:%S.000Z"))
                )
                # 将时间转换为字符串
                time_item = time_item.strftime("%Y年%m月%d日%H时")
                # 提取胜率
                win_rate = item.select("div.title > div.stat")[0].text
                # 提取spm、kdr、kpm、btr、gs、tp
                spm = item.select(
                    "div.session-stats > div:nth-child(1) > div:nth-child(1)"
                )[0].text.strip()
                kd = item.select(
                    "div.session-stats > div:nth-child(2) > div:nth-child(1)"
                )[0].text.strip()
                kpm = item.select(
                    "div.session-stats > div:nth-child(3) > div:nth-child(1)"
                )[0].text.strip()
                score = (
                    item.select("div.session-stats > div:nth-child(5)")[0]
                    .text.strip()
                    .replace("Game Score", "")
                )
                time_play = (
                    item.select("div.session-stats > div:nth-child(6)")[0]
                    .text.strip()
                    .replace("Time Played", "")
                )
                result.append(
                    {
                        "time": time_item.strip(),
                        "win_rate": win_rate.strip(),
                        "spm": spm.strip(),
                        "kd": kd.strip(),
                        "kpm": kpm.strip(),
                        "score": score.strip(),
                        "time_play": time_play.strip(),
                    }
                )
            return result


async def get_match_detail(session, match_url: str) -> list[dict]:
    # 网络请求，返回网页源码
    try:
        async with session.get(match_url) as resp:
            html = await resp.text()
            # 处理网页获取失败的情况
            return html or None
    except Exception as e:
        logger.error(f"获取对局详情失败{e}")
        return None


async def bfeac_checkBan(player_name: str) -> dict:
    """
    检查玩家bfeac信息
    :param player_name: 玩家名称
    :return: {"stat": "状态", "url": "案件链接"}
    """
    check_eacInfo_url = f"https://api.bfeac.com/case/EAID/{player_name}"
    header = {
        "Connection": "keep-alive",
        "apikey": config.functions.get("bf1", {}).get("apikey", ""),
    }
    eac_stat_dict = {
        0: "未处理",
        1: "已封禁",
        2: "证据不足",
        3: "自证通过",
        4: "自证中",
        5: "刷枪",
    }
    result = {"stat": None, "url": None}
    try:
        async with aiohttp.ClientSession(headers=header) as session:
            async with session.get(check_eacInfo_url, proxy=proxy) as response:
                response = await response.json()
        if response.get("data"):
            data = response["data"][0]
            eac_status = eac_stat_dict[data["current_status"]]
            if data.get("case_id"):
                case_id = data["case_id"]
                case_url = f"https://bfeac.com/#/case/{case_id}"
                result["url"] = case_url
            result["stat"] = eac_status
        return result
    except Exception as e:
        logger.error(f"bfeac_checkBan: {e}")
        return result


async def bfban_checkBan(player_pid: str) -> dict:
    """
    检查玩家bfban信息
    :param player_pid: 玩家pid
    :return: {"stat": "状态", "url": "案件链接"}
    """
    player_pid = player_pid
    bfban_url = f"https://api.gametools.network/bfban/checkban?personaids={player_pid}"
    header = {"Connection": "keep-alive"}
    result = {"stat": None, "url": None}
    try:
        async with aiohttp.ClientSession(headers=header) as session:
            async with session.get(bfban_url) as response:
                response = await response.json()
    except Exception as e:
        logger.error(f"联ban查询出错! {e}")
        return result
    if response.get(player_pid):
        data = response[player_pid]
        if not data.get("status"):
            return result
        bfban_stat_dict = {
            "0": "未处理",
            "1": "实锤",
            "2": "嫌疑再观察",
            "3": "认为没开",
            "4": "未处理",
            "5": "回复讨论中",
            "6": "待管理确认",
            "8": "刷枪",
        }
        bfban_status = bfban_stat_dict[data["status"]]
        if data.get("url"):
            case_url = data["url"]
            result["url"] = case_url
        result["stat"] = bfban_status
    return result


async def gt_checkVban(player_pid) -> int:
    url = f"https://api.gametools.network/manager/checkban?playerid={player_pid}&platform=pc&skip_battlelog=false"
    header = {
        "Accept": "application/json",
    }
    try:
        async with aiohttp.ClientSession(headers=header) as session:
            async with session.get(url, proxy=proxy) as response:
                response = await response.json()
        return len(response["vban"])
    except Exception as e:
        logger.error(f"gt_checkVban: {e}")
        return 0


async def gt_bf1_stat() -> str:
    url = "https://api.gametools.network/bf1/status/?platform=pc"
    header = {"Connection": "Keep-Alive"}
    # noinspection PyBroadException
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=header, proxy=proxy) as response:
                html = await response.json()
        if html.get("errors"):
            # {'errors': ['Error connecting to the database']}
            return f"{html['errors'][0]}"
        data: dict = html["regions"].get("ALL")
    except Exception as e:
        logger.error(f"gt_bf1_stat: {e}")
        data = None
    if data:
        return (
            f"当前在线:{data.get('amounts').get('soldierAmount')}"
            f"\n服务器数:{data.get('amounts').get('serverAmount')}"
            f"\n排队总数:{data.get('amounts').get('queueAmount')}"
            f"\n观众总数:{data.get('amounts').get('spectatorAmount')}\n"
            + "="
            * 13
            + f"\n私服(官服):"
            f"\n服务器:{data.get('amounts').get('communityServerAmount', 0)}({data.get('amounts').get('diceServerAmount', 0)})"
            f"\n人数:{data.get('amounts').get('communitySoldierAmount', 0)}({data.get('amounts').get('diceSoldierAmount', 0)})"
            f"\n排队:{data.get('amounts').get('communityQueueAmount', 0)}({data.get('amounts').get('diceQueueAmount', 0)})"
            f"\n观众:{data.get('amounts').get('communitySpectatorAmount', 0)}({data.get('amounts').get('diceSpectatorAmount', 0)})\n"
            + "="
            * 13
            + f"\n征服:{data.get('modes').get('Conquest', 0)}\t行动:{data.get('modes').get('BreakthroughLarge', 0)}"
            f"\n前线:{data.get('modes').get('TugOfWar', 0)}\t突袭:{data.get('modes').get('Rush', 0)}"
            f"\n抢攻:{data.get('modes').get('Domination', 0)}\t闪击行动:{data.get('modes').get('Breakthrough', 0)}"
            f"\n团队死斗:{data.get('modes').get('TeamDeathMatch', 0)}\t战争信鸽:{data.get('modes').get('Possession', 0)}"
            f"\n空中突袭:{data.get('modes').get('AirAssault', 0)}\n空降补给:{data.get('modes').get('ZoneControl', 0)}\n"
            + "="
            * 13
        )
    return "获取数据失败"


async def gt_get_player_id_by_name(player_name: str) -> dict | None:
    url = f"https://api.gametools.network/bf1/player/?name={player_name}&platform=pc&skip_battlelog=false"
    headers = {"accept": "application/json"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, proxy=proxy) as response:
                response = await response.json()
        if response.get("errors"):
            logger.error(f"{player_name}|gt_get_player_id: {response['errors']}")
            return None
    except Exception as e:
        logger.error(f"gt_get_player_id: {e}")
        return None
    return response


async def gt_get_player_id_by_pid(player_pid: str) -> dict | None:
    url = f"https://api.gametools.network/bf1/player/?playerid={player_pid}&platform=pc&skip_battlelog=false"
    headers = {"accept": "application/json"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, proxy=proxy) as response:
                response = await response.json()
            if response.get("errors"):
                logger.error(f"{player_pid}|gt_get_player_id: {response['errors']}")
                return None
    except Exception as e:
        logger.error(f"gt_get_player_id: {e}")
        return None
    return response


async def check_vban(player_pid) -> str | dict:
    """
    vban_num = len(vban_info["vban"])
    :param player_pid:
    :return:
    """
    url = f"https://api.gametools.network/manager/checkban?playerid={player_pid}&platform=pc&skip_battlelog=false"
    header = {"Accept": "application/json", "Connection": "Keep-Alive"}
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=header, timeout=5, proxy=proxy)
        try:
            return eval(response.text)
        except SyntaxError:
            logger.error(f"check_vban: {response.text}")
            return "获取出错!"
    except Exception as e:
        logger.error(f"check_vban: {e}")
        return "网络出错!"


async def record_api(player_pid) -> dict | None:
    record_url = "https://record.ainios.com/getReport"
    data = {"personaId": player_pid}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(record_url, json=data, proxy=proxy) as response:
                response = await response.json()
        return response
    except Exception as e:
        logger.error(f"record_api: {e}")
        return None


# 下载交换皮肤
async def download_skin(url):
    file_name = "./data/battlefield/pic/skins/" + url[url.rfind("/") + 1 :]
    # noinspection PyBroadException
    try:
        fp = open(file_name, "rb")
        fp.close()
        return file_name
    except Exception as e:
        logger.warning(e)
        i = 0
        while i < 3:
            async with aiohttp.ClientSession() as session:
                # noinspection PyBroadException
                try:
                    async with session.get(
                        url, timeout=5, verify_ssl=False, proxy=proxy
                    ) as resp:
                        pic = await resp.read()
                        with open(file_name, "wb") as fp:
                            fp.write(pic)
                        return file_name
                except Exception as e:
                    logger.error(e)
                    i += 1
        return None


# 通过接口获取玩家列表
async def get_playerList_byGameid(server_gameid: str | int | list) -> str | dict | None:
    """
    :param server_gameid: 服务器gameid
    :return: 成功返回字典,失败返回信息
    """
    header = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/86.0.4240.193 Safari/537.36",
        "Content-Type": "json",
    }
    api_url = "https://delivery.easb.cc/games/get_server_status"
    data = {
        "gameIds": [server_gameid]
        if isinstance(server_gameid, str | int)
        else server_gameid
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                api_url, headers=header, json=data, timeout=5, proxy=proxy
            ) as response:
                response = await response.json()
    except TimeoutError as e:
        logger.error(f"get_playerList_byGameid: {e}")
        return "网络超时!"
    if isinstance(server_gameid, list):
        return response["data"]
    if str(server_gameid) in response["data"]:
        return (
            response["data"][str(server_gameid)]
            if response["data"][str(server_gameid)] != ""
            else "服务器信息为空!"
        )
    else:
        return f"获取服务器信息失败:{response}"


class BattlefieldTracker:
    """
    玩家不存在时的返回:
    {
        "errors": [
            {
                "code": "CollectorResultStatus::NotFound",
                "message": "We could not find the player sdawdjasd on Origin.",
                "data": {}
            }
        ]
    }
    header:
    Host:api.tracker.gg
    Accept-Encoding:gzip
    Content-Type:application/json
    User-Agent:Tracker Network App/3.22.9
    x-app-version:3.22.9

    获取对局的步骤:
    1. 查询对局列表
    2. 遍历对局列表，如果对局id有效，就放到获取对局详情的task中
    3. 并发执行获取对局详情的task
    4. 根据对局详情，处理数据，如果对局无效，就将id写入数据库
    """

    url_root = "https://api.tracker.gg/api/v2/bf1/standard/"
    header = {
        "Host": "api.tracker.gg",
        "Connection": "keep-alive",
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "Content-Type": "application/json",
        "User-Agent": "Tracker Network App/3.22.9",
        "x-app-version": "3.22.9",
    }

    @staticmethod
    async def get_player_profile(player_name: str) -> dict | str | None:
        route = "profile/origin/"
        url = f"{BattlefieldTracker.url_root}{route}{player_name}?forceCollect=true"
        try:
            async with AsyncSession() as session:
                response = await session.get(url, headers=BattlefieldTracker.header)
                response = response.json()
            if response.get("errors"):
                return response["errors"][0]["message"]
            return response
        except Exception as e:
            logger.error(f"get_player_profile: {e}")
            return None

    @staticmethod
    async def get_match_list(player_name: str) -> dict | str | None:
        """
        获取玩家对局列表
        :param player_name: 玩家名称
        :return:
        {
        "data": {
            "matches": [
                {
                    "attributes": {
                        "id": "5-1708888840270100224",
                        "mapKey": "MP_MountainFort",
                        "gamemodeKey": "Conquest0"
                    },
                    "metadata": {
                        "timestamp": "2023-10-02T16:57:13+00:00",
                        "mapName": "Monte Grappa",
                        "mapImageUrl": "https://trackercdn.com/cdn/battlefieldtracker.com/bf1/maps/MP_MountainFort.jpg",
                        "gamemodeName": "Conquest",
                        "isRanked": true,
                        "serverName": "HOT01 noobMAX/lv<145 kill<60 kd<2.5 kp<2/ ban hack qq:781495553"
                    },
                    "segments": [],
                    "streams": null,
                    "expiryDate": "0001-01-01T00:00:00+00:00"
                },...
            ],
            "metadata": {
                "next": "1690897905"
            },
            "paginationType": "Next",
            "requestingPlayerAttributes": {
                "platformId": 5,
                "platformUserIdentifier": "shlsan13"
            },
            "expiryDate": "2023-12-02T13:23:44.783425+00:00"
        }
        """
        route = "matches/origin/"
        url = f"{BattlefieldTracker.url_root}{route}{player_name}"
        try:
            async with AsyncSession() as session:
                response = await session.get(url, headers=BattlefieldTracker.header)
                response = response.json()
            if response.get("errors"):
                return response["errors"][0]["message"]
            return response
        except Exception as e:
            logger.error(f"get_match_list: {e}")
            return None

    @staticmethod
    async def get_match_detail(match_id: str) -> dict | str | None:
        route = "matches/"
        url = f"{BattlefieldTracker.url_root}{route}{match_id}"
        try:
            async with AsyncSession() as session:
                response = await session.get(url, headers=BattlefieldTracker.header)
                response = response.json()
            if response.get("errors"):
                return response["errors"][0]["message"]
            return response
        except Exception as e:
            logger.error(f"get_match_detail: {e}")
            return None

    @staticmethod
    async def handle_match_detail(match_detail: dict) -> dict | None:
        """
        处理对局详情
        :param match_detail: 对局详情
        :return:
        """
        # 从对局详情中提取数据
        # 服务器信息
        match_id = match_detail["data"]["attributes"]["id"]
        server_name = match_detail["data"]["metadata"]["serverName"]
        map_name = match_detail["data"]["attributes"]["mapKey"]
        map_name = MapData.MapTeamDict.get(map_name, {}).get("Chinese", map_name)
        mode_name = MapData.ModeDict.get(
            match_detail["data"]["attributes"]["gamemodeKey"][:-1],
            match_detail["data"]["attributes"]["gamemodeKey"][:-1],
        )
        match_time = match_detail["data"]["metadata"][
            "timestamp"
        ]  # "2023-10-02T16:57:13+00:00"
        # 转成datetime
        match_time = datetime.datetime.fromisoformat(match_time)
        # 转换成北京时间（UTC+8）
        match_time = match_time + datetime.timedelta(hours=8)
        team_win = match_detail["data"]["metadata"]["winner"]
        # 不记录对局时间小于30秒的对局
        duration = match_detail["data"]["metadata"]["duration"]
        if duration < 30:
            await BF1DB.bf1_match_cache.update_bf1_match_id_cache(match_id)
            return
        players = match_detail["data"]["segments"]
        # 处理数据
        players_data = []
        for player in players:
            if player["type"] != "player":
                continue
            player_name = player["metadata"]["playerName"]
            player_pid: str = player["attributes"]["playerId"]
            if player_name == "Unknown":
                continue
            # 队伍信息
            team_id = player["attributes"]["teamId"]
            # kills = player["stats"].get("kills", {}).get("value", 0)
            # squadKillsAssistAsKills = player["stats"].get("squadKillsAssistAsKills", {}).get("value", 0)
            # killsAssistAsKills = player["stats"].get("killsAssistAsKills", {}).get("value", 0)
            rushArtilleryDefenseKills = (
                player["stats"].get("rushArtilleryDefenseKills", {}).get("value", 0)
            )
            # rushArtilleryDefenseKills = kills + squadKillsAssistAsKills + killsAssistAsKills
            # 这里的rushArtilleryDefenseKills是总击杀,不再自己计算
            kills = rushArtilleryDefenseKills
            deaths = player["stats"].get("deaths", {}).get("value", 0)
            kd = kills / deaths if deaths else kills
            kd = round(kd, 2)
            # btr原生kpm不准
            # kpm = round(player["stats"].get("killsPerMinute", {}).get("value", 0), 2)
            score = player["stats"].get("roundScore", {}).get("value", 0)
            if score == 0:
                continue
            # spm = round(player["stats"].get("scorePerMinute", {}).get("value", 0), 2)
            headshotsPercentage = f"{player['stats'].get('headshotsPercentage', {}).get('value', 0)}%"  # 百分比，使用时直接添加%即可
            shotAccuracy = f"{player['stats'].get('shotAccuracy', {}).get('value', 0)}%"  # 百分比，使用时直接添加%即可
            time_played = player["stats"].get("time", {}).get("value", 0)  # 秒
            if time_played <= 60:
                continue
            kpm = round(kills / (time_played / 60), 2)
            spm = round(score / (time_played / 60), 2)
            if time_played >= 3600:
                time_played = f"{time_played // 3600:.0f}小时{(time_played % 3600) // 60:.0f}分{time_played % 60:.0f}秒"
            else:
                time_played = f"{time_played // 60:.0f}分{time_played % 60:.0f}秒"
            await BF1DB.bf1_match_cache.update_btr_match_cache(
                match_id=match_id,
                server_name=server_name,
                map_name=map_name,
                mode_name=mode_name,
                time=match_time,
                team_name=team_id,
                team_win=team_win,
                display_name=player_name,
                persona_id=player_pid,
                kills=kills,
                deaths=deaths,
                kd=kd,
                kpm=kpm,
                score=score,
                spm=spm,
                accuracy=shotAccuracy,
                headshots=headshotsPercentage,
                time_played=time_played,
            )
            players_data.append(
                {
                    "player_name": player_name,
                    "team_name": team_id,
                    "team_win": team_win,
                    "kills": kills,
                    "deaths": deaths,
                    "kd": kd,
                    "kpm": kpm,
                    "score": score,
                    "spm": spm,
                    "headshots": headshotsPercentage,
                    "accuracy": shotAccuracy,
                    "time_played": time_played,
                }
            )
        return {
            "game_info": {
                "server_name": server_name,
                "map_name": map_name,
                "mode_name": mode_name,
                "game_time": match_time,
                "match_id": match_id,
                "team_win": team_win,
            },
            "players": players_data,
        }

    # 更新玩家对局数据
    #     1. 查询对局列表
    #     2. 遍历对局列表，如果对局id有效，就放到获取对局详情的task中
    #     3. 并发执行获取对局详情的task
    #     4. 根据对局详情，处理数据，如果对局无效，就将id写入数据库
    @staticmethod
    async def update_match_data(player_name: str, player_pid: int):
        _ = await BattlefieldTracker.get_player_profile(player_name)
        logger.debug(f"开始更新玩家{player_name}的对局数据")
        # 获取对局列表
        match_list = await BattlefieldTracker.get_match_list(player_name)
        if not isinstance(match_list, dict):
            logger.error(f"获取对局列表失败: {match_list}")
            return
        match_list = match_list.get("data").get("matches")
        if not match_list:
            logger.error(f"获取对局列表失败: {match_list}")
            return
        # 获取对局详情
        tasks = []
        # 只获取最前n场数据
        for match in match_list[:7]:
            match_id = match.get("attributes").get("id")
            # 跳过无效对局id
            if await BF1DB.bf1_match_cache.check_bf1_match_id_cache(match_id):
                continue
            # 跳过已缓存过的玩家对局
            if await BF1DB.bf1_match_cache.check_bf1_match_id_cache_by_pid(
                player_pid, match_id
            ):
                continue
            tasks.append(
                asyncio.ensure_future(BattlefieldTracker.get_match_detail(match_id))
            )
        if not tasks:
            logger.debug(f"玩家{player_name}没有新的对局数据")
            return
        try:
            logger.debug(f"正在更新玩家{player_name}的{len(tasks)}场对局数据")
            match_detail_list = await asyncio.gather(*tasks)
        except Exception as e:
            logger.error(f"获取对局详情失败: {e}")
            return
        # 处理对局详情
        for match_detail in match_detail_list:
            if not isinstance(match_detail, dict):
                continue
            if match_detail.get("errors"):
                logger.error(
                    f"获取对局详情失败: {match_detail['errors'][0]['message']}"
                )
                continue
            # 从对局详情中提取数据,并写入数据库
            _ = await BattlefieldTracker.handle_match_detail(match_detail)

    @staticmethod
    async def get_player_match_data(
        player_pid: int, match_num: int | None = None
    ) -> list | None:
        """
        获取玩家对局数据
        :param player_pid: 玩家pid
        :param match_num: 获取对局数量
        :return: 返回一个列表，包含对局信息和玩家信息
        """
        # 先从数据库查询数据,如果数据库中有数据则直接返回
        if matches := await BF1DB.bf1_match_cache.get_btr_match_by_pid(
            player_pid, match_num
        ):
            result = []
            for data in matches:
                server_name = data["server_name"]
                map_name = data["map_name"]
                mode_name = data["mode_name"]
                game_time = data["time"]
                match_id = data["match_id"]
                team_win = data["team_win"]
                match_result = {
                    "game_info": {
                        "server_name": server_name,
                        "map_name": map_name,
                        "mode_name": mode_name,
                        "game_time": game_time,
                        "match_id": match_id,
                        "team_win": team_win,
                    },
                    "player": {
                        "player_name": data["display_name"],
                        "team_name": data["team_name"],
                        "kills": data["kills"],
                        "deaths": data["deaths"],
                        "kd": data["kd"],
                        "kpm": data["kpm"],
                        "score": data["score"],
                        "spm": data["spm"],
                        "headshots": data["headshots"],
                        "accuracy": data["accuracy"],
                        "time_played": data["time_played"],  # 秒
                    },
                }
                result.append(match_result)
            return result
        return None


class EACUtils:
    def __init__(self):
        self.tvbot_list = {"result": [], "time": time.time()}

    # EAC举报接口
    @staticmethod
    async def report_interface(
        report_qq: int, player_name: str, report_reason: str, apikey: str
    ):
        report_url = "https://api.bfeac.com/inner_api/case_report"
        headers = {"apikey": apikey}
        body = {
            "target_EAID": player_name,
            "case_body": report_reason,
            "game_type": 1,
            "report_by": {"report_platform": "qq", "user_id": report_qq},
        }
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    report_url, headers=headers, json=body, timeout=10
                )
            logger.debug(response.text)
            return response.json()
        except Exception as e:
            logger.error(e)
            return None

    # 使用gpt3.5进行预审核
    @staticmethod
    async def report_precheck(report_reason: str) -> dict:
        """
        使用gpt3.5进行预审核
        :param report_reason: 举报理由
        :return: {"valid": bool, "reason": str}
        """
        result = {"valid": True, "reason": None}
        api_key = create(GlobalConfig).functions.get("ChatGPT", {}).get("api_key")
        if api_key:
            try:
                ENCODER = tiktoken.encoding_for_model("gpt-3.5-turbo")
                preset = """ 你是一个专业的信息审核系统，用于检查和验证用户提交的关于游戏玩家作弊的举报信息。你的任务是确保每条信息都符合以下标准并以正确的JSON格式回复：
        1. 内容必须专注于举报的相关事宜，如提及玩家武器/生涯数据异常、使用非法辅助工具等。
        2. 不得包含与举报无关的信息。
        3. 如果举报不符合要求，请在reason给出具体的说明。
        4. 合法关键词包含但不限于：命中率(acc)、爆头率(hs)、效率、KD、KPM、FPS游戏常见的武器/载具名，
        常见作弊方式如锁头、锁身子、透视、魔法子弹、改伤等，举报平台包含bfban(联ban)、bfeac、gt、vban等。
        5. 回复必须是一个JSON对象，包含两个关键字："valid"（布尔值，表示举报信息是否符合要求）和 "reason"（字符串，解释审核结果的原因）。

        请根据以上规则审核以下举报信息，并以正确的JSON格式回复是否符合要求以及原因。

        示例：
        输入信息："该玩家在游戏中使用非法辅助工具，导致比赛不公平。"
        输出应为：{"valid": true, "reason": "举报理由符合要求。"}
        """
                gpt = Chatbot(
                    api_key=api_key,
                    engine="gpt-3.5-turbo",
                    system_prompt=preset,
                    max_tokens=len(ENCODER.encode(preset)) + 1000,
                )
                result = await gpt.ask_async(report_reason)
                # 检查gpt的返回是否为json格式
                result = json.loads(result)
            except Exception as e:
                logger.warning(f"gpt3.5预审核举报时出错: {e}")
        return result

    # 获取小电视机器人list
    async def get_22tvbot_list(self) -> list:
        """
        元素为：
        {
            "name": "bot_btv15",
            "personaId": 1006388664805,
            "valid": 1,
            "lastUsed": "2024/2/17 18:01:26",
            "lastUpdated": "2024/2/3 13:58:05",
            "userId": 1013223064805,
            "features": [
                "bfeac"
            ],
            "flags": [
                "bf1Gateway"
            ]
        }
        """
        # 每小时更新一次
        if (
            self.tvbot_list["result"]
            and time.time() - self.tvbot_list["time"] < 60 * 60
        ):
            return self.tvbot_list["result"]
        url = "https://ea-api.2788.pro/account/list/bfeac"
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, timeout=5)
            response = response.json()
            if isinstance(response, list):
                self.tvbot_list["result"] = response
                self.tvbot_list["time"] = time.time()
                return response
        except Exception as e:
            logger.error(e)
            return []


class BF1GROUP:
    @staticmethod
    async def create(group_name: str) -> str:
        # 群组的名字必须为英文，且不区分大小写，也就是说不能同时存在ABC和abc，返回str
        # 查询群组是否存在
        if await BF1DB.bf1group.check_bf1_group(group_name):
            return f"群组[{group_name}]已存在"
        # 创建群组
        await BF1DB.bf1group.create_bf1_group(group_name)
        return f"BF1群组[{group_name}]创建成功\n默认权限组[{group_name}]创建成功"

    @staticmethod
    async def delete(group_name: str) -> str:
        # 删除群组，返回str
        # 查询群组是否存在
        if not await BF1DB.bf1group.check_bf1_group(group_name):
            return f"群组[{group_name}]不存在"
        # 删除群组
        await BF1DB.bf1group.delete_bf1_group(group_name)
        _ = await BF1GROUPPERM.del_permission_group(group_name)
        return f"BF1群组[{group_name}]删除成功"

    @staticmethod
    async def get_info(group_name: str) -> str | dict:
        return (
            await BF1DB.bf1group.get_bf1_group_info(group_name)
            if await BF1DB.bf1group.check_bf1_group(group_name)
            else f"群组[{group_name}]不存在"
        )

    @staticmethod
    async def rename(group_name: str, new_name: str) -> str:
        # 查询群组是否存在
        if not await BF1DB.bf1group.check_bf1_group(group_name):
            return f"群组[{group_name}]不存在"
        # 查询新名字是否存在
        if await BF1DB.bf1group.check_bf1_group(new_name):
            return f"群组[{new_name}]已存在"
        # 修改群组名字
        result = await BF1DB.bf1group.modify_bf1_group_name(group_name, new_name)
        _ = await BF1GROUPPERM.rename_permission_group(group_name, new_name)
        return (
            f"BF1群组[{group_name}]已改名为[{new_name}]"
            if result
            else f"BF1群组[{group_name}]修改失败"
        )

    @staticmethod
    async def bind_ids(
        group_name: str,
        index: int,
        guid: str,
        gameId: str,
        serverId: str,
        account_pid: str = None,
    ) -> str:
        """

        :param group_name:
        :param index: index只能在1-30以内(非下标)
        :param guid:
        :param gameId:
        :param serverId:
        :param account_pid:
        :return:
        """
        # 绑定玩家id，返回str
        # 查询群组是否存在
        if not await BF1DB.bf1group.check_bf1_group(group_name):
            return f"群组[{group_name}]不存在"
        # 绑定到对应的序号
        # index只能在1-30以内
        if index < 1 or index > 30:
            return "序号只能在1-30以内"
        # 绑定到对应序号上
        await BF1DB.bf1group.bind_bf1_group_id(
            group_name, index - 1, guid, gameId, serverId, account_pid
        )
        account_info = await BF1DB.bf1account.get_bf1account_by_pid(account_pid)
        display_name = account_info.get("displayName") if account_info else ""
        manager_account = (
            f"服管账号:{display_name} ({account_pid})"
            if display_name
            else "未识别到服管账号,请手动绑定!"
        )
        return (
            f"群组[{group_name}]绑定{index}服成功!\n"
            f"guid:{guid}\n"
            f"gameId:{gameId}\n"
            f"serverId:{serverId}\n" + manager_account
        )

    @staticmethod
    async def unbind_ids(group_name: str, index: int) -> str:
        # 解绑玩家id，返回str
        # 查询群组是否存在
        if not await BF1DB.bf1group.check_bf1_group(group_name):
            return f"群组[{group_name}]不存在"
        # 解绑对应的序号
        # index只能在1-30以内
        if index < 1 or index > 30:
            return "序号只能在1-30以内"
        # 解绑对应序号
        await BF1DB.bf1group.unbind_bf1_group_id(group_name, index - 1)
        return f"群组[{group_name}]解绑{index}服成功!"

    @staticmethod
    async def bind_qq_group(group_name: str, group_id: int) -> str:
        # 绑定群组，返回str
        # 查询群组是否存在
        if not await BF1DB.bf1group.check_bf1_group(group_name):
            return f"群组[{group_name}]不存在"
        # 绑定群组
        await BF1DB.bf1group.bind_bf1_group_qq_group(group_name, group_id)
        return f"群组[{group_name}]绑定群[{group_id}]成功"

    @staticmethod
    async def unbind_qq_group(group_id: int) -> str:
        # 解绑群组，返回str
        if await BF1DB.bf1group.unbind_bf1_group_qq_group(group_id):
            return f"{group_id}解绑群组成功"
        return f"{group_id}未绑定群组"

    @staticmethod
    async def get_bindInfo_byIndex(group_name: str, index: int) -> dict | str | None:
        # 查询群组是否存在
        if not await BF1DB.bf1group.check_bf1_group(group_name):
            return f"群组[{group_name}]不存在"
        # 查询对应序号的绑定信息
        # index只能在1-30以内
        if index < 1 or index > 30:
            return "序号只能在1-30以内"
        # 查询对应序号的绑定信息
        return await BF1DB.bf1group.get_bf1_group_bindInfo_byIndex(
            group_name, index - 1
        )

    @staticmethod
    async def get_bf1Group_byQQ(group_id: int) -> dict | None:
        # 获取群组信息
        group_info = await BF1DB.bf1group.get_bf1_group_by_qq_group(group_id)
        return group_info or None

    @staticmethod
    async def get_bf1Group_byName(group_name: str) -> dict | None:
        # 获取群组信息
        group_info = await BF1DB.bf1group.get_bf1_group_by_name(group_name)
        return group_info or None

    @staticmethod
    async def get_group_bindList(app: Ariadne, group) -> list:
        group_member_list_temp = await app.get_member_list(group.id)
        group_member_list = [item.name.upper() for item in group_member_list_temp]
        bind_infos = await BF1DB.bf1account.get_players_info_by_qqs(
            [item.id for item in group_member_list_temp]
        )
        group_member_list.extend(
            [bind_infos[key].get("display_name").upper() for key in bind_infos]
        )
        group_member_list = list(set(group_member_list))
        return group_member_list


class BF1GROUPPERM:
    ADMIN = 1
    OWNER = 2

    # 绑定权限组
    @staticmethod
    async def bind_group(group_name: str, group_id: int) -> bool:
        """
        绑定权限组
        :param group_name: BF1群组名
        :param group_id: QQ群号
        :return: bool
        """
        return await BF1DB.bf1_permission_group.bind_permission_group(
            group_name=group_name, qq_group_id=group_id
        )

    # 解绑权限组
    @staticmethod
    async def unbind_group(group_id: int) -> bool:
        """
        解绑权限组
        :param group_id: QQ群号
        :return: bool
        """
        return await BF1DB.bf1_permission_group.unbind_permission_group(
            qq_group_id=group_id
        )

    # 获取QQ群绑定的权限组名
    @staticmethod
    async def get_group_name(group_id: int) -> str | None:
        """
        获取QQ群绑定的权限组名
        :param group_id: QQ群号
        :return: str or None
        """
        return await BF1DB.bf1_permission_group.get_permission_group(
            qq_group_id=group_id
        )

    # 获取权限组绑定的QQ群
    @staticmethod
    async def get_permission_group_bind(group_name: str) -> list | None:
        """
        获取权限组绑定的QQ群
        :param group_name: BF1群组名
        :return: list or None
        """
        return await BF1DB.bf1_permission_group.get_permission_group_bind(
            group_name=group_name
        )

    # 添加/修改QQ号到权限组
    @staticmethod
    async def add_permission(group_name: str, qq: int, permission: int) -> bool:
        """
        添加/修改QQ号到权限组
        :param group_name: BF1群组名
        :param qq: QQ号
        :param permission: 权限,0为管理员,1为服主
        :return: bool
        """
        if permission in {0, 1}:
            return await BF1DB.bf1_permission_group.update_qq_to_permission_group(
                bf1_group_name=group_name, qq_id=qq, perm=permission
            )
        return False

    # 删除QQ号到权限组
    @staticmethod
    async def del_permission(group_name: str, qq: int) -> bool:
        """
        删除QQ号到权限组
        :param group_name: BF1群组名
        :param qq: QQ号
        :return: bool
        """
        return await BF1DB.bf1_permission_group.delete_qq_from_permission_group(
            bf1_group_name=group_name, qq_id=qq
        )

    @staticmethod
    async def del_permission_batch(group_name: str, qq_list: list) -> bool:
        """
        批量删除QQ号到权限组
        :param group_name: BF1群组名
        :param qq_list: QQ号列表
        :return: bool
        """
        return await BF1DB.bf1_permission_group.delete_qq_from_permission_group_batch(
            bf1_group_name=group_name, qq_id_list=qq_list
        )

    # 获取QQ号在权限组的权限
    @staticmethod
    async def get_permission(group_name: str, qq: int) -> int | None:
        """
        获取QQ号在权限组的权限
        :param group_name: BF1群组名
        :param qq: QQ号
        :return: int or None
        """
        return await BF1DB.bf1_permission_group.get_qq_perm_in_permission_group(
            bf1_group_name=group_name, qq_id=qq
        )

    # 获取权限组内的QQ号和权限
    @staticmethod
    async def get_permission_group(group_name: str) -> dict | None:
        """
        获取权限组内的QQ号和权限
        :param group_name: BF1群组名
        :return: dict or None, 结果为{qq: perm}
        """
        return await BF1DB.bf1_permission_group.get_qq_from_permission_group(
            bf1_group_name=group_name
        )

    # 判断QQ号是否在权限组内
    @staticmethod
    async def check_permission(group_name: str, qq: int) -> bool:
        """
        判断QQ号是否在权限组内
        :param group_name: BF1群组名
        :param qq: QQ号
        :return: bool
        """
        return await BF1DB.bf1_permission_group.is_qq_in_permission_group(
            bf1_group_name=group_name, qq_id=qq
        )

    # 删除权限组
    @staticmethod
    async def del_permission_group(group_name: str) -> bool:
        """
        删除权限组
        :param group_name: BF1群组名
        :return: bool
        """
        return await BF1DB.bf1_permission_group.delete_permission_group(
            group_name=group_name
        )

    # 改名
    @staticmethod
    async def rename_permission_group(old_group_name: str, new_group_name: str) -> bool:
        """
        改名
        :param old_group_name: BF1群组名
        :param new_group_name: BF1群组名
        :return: bool
        """
        return await BF1DB.bf1_permission_group.rename_permission_group(
            old_group_name=old_group_name, new_group_name=new_group_name
        )


class BF1ManagerAccount:
    """BF1服管账号相关操作"""

    # accounts_file_path = Path("./data/battlefield/accounts.json")
    # if not accounts_file_path.exists():
    #     accounts_file_path.touch()
    #     accounts_file_path.write_text(json.dumps({"accounts": []}, indent=4, ensure_ascii=False))

    @staticmethod
    async def get_accounts() -> list | None:
        """获取所有服管账号
        有结果时,返回list,无结果时返回None,每个元素为dict,包含pid,uid,name,display_name,remid,sid,session"""
        return await BF1DB.bf1account.get_manager_account_info()

    @staticmethod
    async def get_account(player_pid: int) -> dict | None:
        """获取服管账号
        元素为dict,包含pid,uid,name,display_name,remid,sid,session
        """
        return await BF1DB.bf1account.get_manager_account_info(pid=player_pid)

    @staticmethod
    async def login(player_pid: int, remid: str, sid: str) -> api_instance | None:
        """登录"""
        account_instance = api_instance.get_api_instance(
            pid=player_pid, remid=remid, sid=sid
        )
        account_instance.remid = remid
        account_instance.sid = sid
        await account_instance.login(
            remid=account_instance.remid, sid=account_instance.sid
        )
        return account_instance

    @staticmethod
    async def del_account(player_pid: int) -> bool:
        """删除账号cookie信息"""
        return await BF1DB.bf1account.update_bf1account(pid=player_pid)

    @staticmethod
    async def get_manager_account_instance(player_pid) -> api_instance:
        account_instance = api_instance.get_api_instance(pid=player_pid)
        if not account_instance.remid:
            account_info = await BF1ManagerAccount.get_account(player_pid=player_pid)
            if account_info:
                account_instance.remid = account_info["remid"]
                account_instance.sid = account_info["sid"]
                account_instance.session = account_info["session"]
            await account_instance.get_session()
        return account_instance


class BF1Log:
    @staticmethod
    async def record(
        serverId: int,
        persistedGameId: str,
        gameId: int,
        operator_qq: int,
        pid: int,
        display_name: str,
        action: str,
        info: str = None,
    ):
        await BF1DB.manager_log.record(
            operator_qq=operator_qq,
            serverId=serverId,
            persistedGameId=persistedGameId,
            gameId=gameId,
            pid=pid,
            display_name=display_name,
            action=action,
            info=info,
        )

    # 将传入server_id_list、action(可选)、operator_qq(可选)、pid(可选)、display_name(可选)、action_time(可选)
    @staticmethod
    async def get_log_by_server_id_list(server_id_list: list = None) -> list:
        """

        :param server_id_list:
        :return:
        [
            {
                "operator_qq": item[0],
                "serverId": item[1],
                "persistedGameId": item[2],
                "gameId": item[3],
                "persona_id": item[4],
                "display_name": item[5],
                "action": item[6],
                "info": item[7],
                "time": item[8],
            },
            ...
        ]
        """
        return await BF1DB.manager_log.get_log_by_server_id_list(
            server_id_list=server_id_list
        )


class BF1ServerVipManager:
    @staticmethod
    async def update_server_vip(server_full_info: dict):
        """更新服务器VIP信息"""
        return await BF1DB.server_manager.update_server_vip(
            server_full_info=server_full_info
        )

    # 从表里获取一个玩家在指定服务器的VIP信息
    @staticmethod
    async def get_server_vip(server_id: int, player_pid: int) -> dict | None:
        """获取一个玩家在指定服务器的VIP信息"""
        vip_list = await BF1DB.server_manager.get_server_vip_list(serverId=server_id)
        return next(
            (vip for vip in vip_list if str(vip["personaId"]) == str(player_pid)),
            None,
        )

    # 更新一个玩家在指定服务器的VIP信息
    @staticmethod
    async def update_server_vip_by_pid(
        server_id: int,
        player_pid: int,
        displayName: str,
        expire_time: datetime.datetime,
        valid: bool,
        should_update_time=True,
    ) -> bool:
        """更新一个玩家在指定服务器的VIP信息"""
        return await BF1DB.server_manager.update_vip(
            serverId=server_id,
            personaId=player_pid,
            displayName=displayName,
            expire_time=expire_time,
            valid=valid,
            should_update_time=should_update_time,
        )

    # 获取指定服务器的VIP列表
    @staticmethod
    async def get_server_vip_list(server_id: int) -> list:
        return await BF1DB.server_manager.get_server_vip_list(serverId=server_id)

    # 删除一个玩家在指定服务器的VIP信息
    @staticmethod
    async def del_server_vip_by_pid(server_id: int, player_pid: int) -> bool:
        return await BF1DB.server_manager.delete_vip(
            serverId=server_id, personaId=player_pid
        )


class BF1BlazeManager:
    @staticmethod
    async def init_socket(pid: str | int, remid: str, sid: str) -> BlazeSocket | None:
        pid = int(pid)
        if pid in BlazeClientManagerInstance.clients_by_pid:
            blaze_socket = BlazeClientManagerInstance.clients_by_pid[pid]
            if blaze_socket.authenticated:
                return await BlazeClientManagerInstance.get_socket_for_pid(pid)
            else:
                await BlazeClientManagerInstance.remove_client(pid)
        # 连接blaze
        blaze_socket = await BlazeClientManagerInstance.get_socket_for_pid(pid)
        if not blaze_socket:
            logger.error("无法获取到BlazeSocket")
            return None
        # 1.获取账号实例
        bf1_account = api_instance.get_api_instance(pid=pid, remid=remid, sid=sid)
        # 2.获取BlazeAuthcode
        auth_code = await bf1_account.getBlazeAuthcode()
        logger.success(f"获取到Blaze AuthCode: {auth_code}")
        # 3.Blaze登录
        login_packet = {
            "method": "Authentication.login",
            "type": "Command",
            "id": 0,
            "length": 28,
            "data": {"AUTH 1": auth_code, "EXTB 2": "", "EXTI 0": 0},
        }
        response = await blaze_socket.send(login_packet)
        try:
            name = response["data"]["DSNM"]
            pid = response["data"]["PID"]
            uid = response["data"]["UID"]
            CGID = response["data"]["CGID"][2]
            logger.success(
                f"Blaze登录成功: Name:{name} Pid:{pid} Uid:{uid} CGID:{CGID}"
            )
            blaze_socket.authenticated = True
            BlazeClientManagerInstance.clients_by_pid[pid] = blaze_socket
            return blaze_socket
        except Exception as e:
            logger.error(f"Blaze登录失败: {response}, {e}")
            return None

    @staticmethod
    async def get_player_list(
        game_ids: list[int], origin: bool = False, platoon: bool = False
    ) -> dict | None | str:
        """获取玩家列表"""
        # 检查game_ids类型
        if not isinstance(game_ids, list):
            game_ids = [game_ids]
        game_ids = [int(game_id) for game_id in game_ids]
        blaze_socket = await BF1BlazeManager.init_socket(
            BF1DA.pid, BF1DA.remid, BF1DA.sid
        )
        if not blaze_socket:
            return "BlazeClient初始化出错!"
        packet = {
            "method": "GameManager.getGameDataFromId",
            "type": "Command",
            "data": {
                "DNAM 1": "csFullGameList",
                "GLST 40": game_ids,
            },
        }
        try:
            response = await blaze_socket.send(packet)
        except TimeoutError:
            await blaze_socket.close()
            logger.error("Blaze后端超时!")
            return "Blaze后端超时!"
        if origin:
            return response
        response = BlazeData.player_list_handle(response)
        if not isinstance(response, dict):
            blaze_socket.authenticated = False
            return response
        if platoon:
            bf1_account = await BF1DA.get_api_instance()
            for game_id in game_ids:
                if game_id in response:
                    pid_list = [
                        player["pid"] for player in response[game_id]["players"]
                    ]
                    platoon_task = [
                        bf1_account.getActivePlatoon(pid) for pid in pid_list
                    ]
                    try:
                        platoon_list = await asyncio.gather(*platoon_task)
                    except Exception as e:
                        logger.error(f"获取玩家战排信息失败: {e}")
                        platoon_list = []
                    platoons = []
                    for i, platoon in enumerate(platoon_list):
                        if isinstance(platoon, dict):
                            platoon = platoon["result"]
                            if not platoon:
                                continue
                            if platoon not in platoons:
                                platoons.append(platoon)
                            response[game_id]["players"][i]["platoon"] = platoon
                        else:
                            response[game_id]["players"][i]["platoon"] = {}
                    response[game_id]["platoons"] = platoons
        return response


async def perm_judge(bf_group_name: str, group: Group, sender: Member) -> bool:
    group_perm = await Permission.get_user_perm_byID(group.id, sender.id)
    over_perm = group_perm >= Permission.BotAdmin
    in_group = await BF1DB.bf1_permission_group.is_qq_in_permission_group(
        bf_group_name, sender.id
    )
    return bool(in_group or over_perm)


def bf1_perm_check():
    def decorator(fn):
        @wraps(fn)
        async def wrapper(
            app: Ariadne,
            sender: Member,
            group: Group,
            source: Source,
            server_rank: MatchResult,
            bf_group_name: MatchResult,
        ):
            server_rank = server_rank.result.display
            bf_group_name = (
                bf_group_name.result.display
                if bf_group_name and bf_group_name.matched
                else None
            )
            if not server_rank.isdigit():
                return await app.send_message(
                    group, MessageChain("请输入正确的服务器序号"), quote=source
                )
            server_rank = int(server_rank)
            if server_rank < 1 or server_rank > 30:
                return await app.send_message(
                    group, MessageChain("服务器序号只能在1~30内"), quote=source
                )

            # 获取群组信息
            if not bf_group_name:
                bf1_group_info = await BF1GROUP.get_bf1Group_byQQ(group.id)
                if not bf1_group_info:
                    return await app.send_message(
                        group, MessageChain("请先绑定BF1群组"), quote=source
                    )
                bf_group_name = bf1_group_info.get("group_name")

            # 权限判断
            return (
                await fn(app, sender, group, source, server_rank, bf_group_name)
                if await perm_judge(bf_group_name, group, sender)
                else await app.send_message(
                    group,
                    MessageChain(f"您不是群组[{bf_group_name}]的成员"),
                    quote=source,
                )
            )

        return wrapper

    return decorator


async def dummy_coroutine():
    return None
