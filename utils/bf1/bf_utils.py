import asyncio
import datetime
import time
import aiohttp
from loguru import logger
from typing import Union
from bs4 import BeautifulSoup
from utils.bf1.data_handle import BTRMatchesData
from utils.bf1.default_account import BF1DA
from utils.bf1.orm import BF1DB


async def get_personas_by_name(player_name: str) -> Union[dict, None]:
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
            await BF1DB.update_bf1account(
                pid=pid,
                uid=uid,
                name=name,
                display_name=display_name,
            )
        except Exception as e:
            logger.error((e, player_info))
        return player_info


async def get_personas_by_player_pid(player_pid: int) -> Union[dict, str, None]:
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
            display_name = player_info['result'][str(player_pid)]['displayName']
            uid = player_info['result'][str(player_pid)]['nucleusId']
            await BF1DB.update_bf1account(
                pid=player_pid,
                uid=uid,
                display_name=display_name,
            )
        except Exception as e:
            logger.error((e, player_info))
        return player_info


async def check_bind(qq: int) -> Union[dict, str, None]:
    """检查玩家是否绑定
    :param qq: 玩家QQ
    :return: 返回玩家信息,如果未绑定则返回None,查询失败返回str信息"""
    player_pid = await BF1DB.get_pid_by_qq(qq)
    if not player_pid:
        return None
    # 修改逻辑,先从数据库中获取,如果数据库中没有则从API中获取
    player_info = await BF1DB.get_bf1account_by_pid(player_pid)
    if player_info:
        return {"displayName": player_info["display_name"], "pid": player_pid, "uid": player_info["uid"], "qq": qq}
    else:
        player_info = await get_personas_by_player_pid(player_pid)
        if isinstance(player_info, str):
            return player_info
        elif not player_info:
            return None
        else:
            # 更新该pid的信息
            await BF1DB.update_bf1account(
                pid=player_pid,
                uid=player_info['result'][str(player_pid)]['nucleusId'],
                display_name=player_info['result'][str(player_pid)]['displayName'],
            )
            displayName = player_info['result'][str(player_pid)]['displayName']
            pid = player_info['result'][str(player_pid)]['personaId']
            uid = player_info['result'][str(player_pid)]['nucleusId']
            return {"displayName": displayName, "pid": pid, "uid": uid, "qq": qq}


async def BTR_get_recent_info(player_name: str) -> list[dict]:
    """
    从BTR获取最近的战绩
    :param player_name: 玩家名称
    :return: 返回一个列表，列表中的每个元素是一个字典，默认爬取全部数据，调用处决定取前几个
    """
    result = []
    # BTR玩家个人信息页面
    url = "https://battlefieldtracker.com/bf1/profile/pc/" + player_name
    header = {
        "Connection": "keep-alive",
        "User-Agent": "ProtoHttp 1.3/DS 15.1.2.1.0 (Windows)",
    }
    async with aiohttp.ClientSession(headers=header) as session:
        async with session.get(url) as response:
            html = await response.text()
            # 处理网页获取失败的情况
            if not html:
                return result
            soup = BeautifulSoup(html, "html.parser")
            # 从<div class="card-body player-sessions">获取对局数量，如果找不到则返回None
            if not soup.select('div.card-body.player-sessions'):
                return None
            sessions = soup.select('div.card-body.player-sessions')[0].select('div.sessions')
            # 每个sessions由标题和对局数据组成，标题包含时间和胜率，对局数据包含spm、kdr、kpm、btr、gs、tp
            for item in sessions:
                time_item = item.select('div.title > div.time > h4 > span')[0]
                # 此时time_item =  <span data-livestamp="2023-03-22T14:00:00.000Z"></span>
                # 提取UTC时间转换为本地时间的时间戳
                time_item = time_item['data-livestamp']
                # 将时间戳转换为时间
                time_item = datetime.datetime.fromtimestamp(
                    time.mktime(time.strptime(time_item, "%Y-%m-%dT%H:%M:%S.000Z")))
                # 将时间转换为字符串
                time_item = time_item.strftime('%Y年%m月%d日%H时%M分')
                # 提取胜率
                win_rate = item.select('div.title > div.stat')[0].text
                # 提取spm、kdr、kpm、btr、gs、tp
                spm = item.select('div.session-stats > div:nth-child(1) > div:nth-child(1)')[0].text.strip()
                kd = item.select('div.session-stats > div:nth-child(2) > div:nth-child(1)')[0].text.strip()
                kpm = item.select('div.session-stats > div:nth-child(3) > div:nth-child(1)')[0].text.strip()
                score = item.select('div.session-stats > div:nth-child(5)')[0].text.strip().replace('Game Score', '')
                time_play = item.select('div.session-stats > div:nth-child(6)')[0].text.strip().replace('Time Played',
                                                                                                        '')
                result.append({
                    'time': time_item.strip(),
                    'win_rate': win_rate.strip(),
                    'spm': spm.strip(),
                    'kd': kd.strip(),
                    'kpm': kpm.strip(),
                    'score': score.strip(),
                    'time_play': time_play.strip()
                })
            return result


async def get_match_detail(session, match_url: str) -> list[dict]:
    # 网络请求，返回网页源码
    try:
        async with session.get(match_url) as resp:
            html = await resp.text()
            # 处理网页获取失败的情况
            if not html:
                return None
            return html
    except Exception as e:
        logger.error(f"获取对局详情失败{e}")
        return None


async def BTR_get_match_info(player_name: str) -> list[dict]:
    """
    从BTR获取最近的对局信息
    :param player_name: 玩家名称
    :return: 返回一个字典，包含对局信息和玩家信息
    """
    result = []
    # 先从数据库查询数据,如果数据库中有数据则直接返回
    if matches := await BF1DB.get_btr_match_by_displayName(player_name):
        for data in matches:
            server_name = data['server_name']
            map_name = data['map_name']
            mode_name = data['mode_name']
            game_time = data['time']
            match_result = {
                "game_info": {
                    "server_name": server_name,
                    "map_name": map_name,
                    "mode_name": mode_name,
                    "game_time": game_time,
                },
                "players": [{
                    "player_name": data['display_name'],
                    "team_name": data['team_name'],
                    "team_win": data['team_win'],
                    "kills": data['kills'],
                    "deaths": data['deaths'],
                    "kd": data['kd'],
                    "kpm": data['kpm'],
                    "score": data['score'],
                    "spm": data['spm'],
                    "headshots": data['headshots'],
                    "accuracy": data['accuracy'],
                    "time_played": data['time_played'],
                }]}
            result.append(match_result)
    return result


async def BTR_update_data(player_name: str) -> None:
    """
    更新BTR对局数据
    :param player_name: 玩家名称
    :return: None
    """
    logger.debug(f"开始更新BTR对局数据")
    result = []
    # BTR玩家最近对局列表页面
    header = {
        "Connection": "keep-alive",
        "User-Agent": "ProtoHttp 1.3/DS 15.1.2.1.0 (Windows)",
    }
    matches_url = 'https://battlefieldtracker.com/bf1/profile/pc/' + player_name + '/matches'
    # 网络请求
    async with aiohttp.ClientSession(headers=header) as session:
        async with session.get(matches_url) as resp:
            matches_list = await resp.text()
            if not matches_list:
                return result
            # 解析网页，结合上面html代码
            soup = BeautifulSoup(matches_list, 'lxml')
            # 每一个对局都在div card matches中,每次最多能获取到30个，这里只获取前10个对局的信息，每个对局的链接都在a标签中的href属性中
            # 如果找不到card matches，说明没有对局
            if not soup.select('div.card.matches'):
                return result
            matches_url_list = []
            match_id_list = []
            # 获取每个对局的链接
            for match in soup.select('div.card.matches')[0].select('a.match'):
                match_url = match['href']
                # match_url: bf1/matches/pc/1639959006078647616?context=playerName
                # 只取?context=playerName前面的部分
                match_url = match_url.split('?')[0]
                match_url = 'https://battlefieldtracker.com' + match_url
                matches_url_list.append(match_url)
                match_id_list.append(match_url.split('pc/')[1].split('?')[0])

            # 并发获取每个对局的详细信息
            tasks = [asyncio.ensure_future(get_match_detail(session, match_url)) for match_url in matches_url_list[:5]]
            if not tasks:
                return result
            matches_result = await asyncio.gather(*tasks)

            # 处理每个对局的详细信息
            matches_info_list = await BTRMatchesData(matches_result).handle()
            for i, match_info in enumerate(matches_info_list):
                result_temp = match_info
                # 写入数据库
                if match_info['players']:
                    for player in match_info['players']:
                        player_name_item = player['player_name']
                        player_kills = player['kills']
                        player_deaths = player['deaths']
                        kd = player['kd']
                        kpm = player['kpm']
                        player_score = player['score']
                        spm = player['spm']
                        player_headshots = player['headshots']
                        player_accuracy = player['accuracy']
                        player_time = player['time_played']
                        team_win = player['team_win']
                        await BF1DB.update_btr_match_cache(
                            # 服务器信息
                            match_id=match_id_list[i],
                            server_name=match_info['game_info']['server_name'],
                            map_name=match_info['game_info']['map_name'],
                            mode_name=match_info['game_info']['mode_name'],
                            time=match_info['game_info']['game_time'],
                            # 队伍信息
                            team_name=match_info['players'][0]['team_name'],
                            team_win=team_win,
                            # 基本信息
                            display_name=player_name_item,
                            kills=player_kills,
                            deaths=player_deaths,
                            kd=kd,
                            kpm=kpm,
                            # 得分
                            score=player_score,
                            spm=spm,
                            # 其他
                            headshots=player_headshots,
                            accuracy=player_accuracy,
                            time_played=player_time
                        )
                        result.append(result_temp)

            return result

