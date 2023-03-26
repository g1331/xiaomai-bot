import asyncio
import datetime
import json
import os
import random
import re
import time
from typing import Union

import aiofiles
import aiohttp
import httpx
import zhconv
from bs4 import BeautifulSoup
from loguru import logger
from rapidfuzz import fuzz

from utils.bf1.default_account import BF1DA
from utils.bf1.orm import BF1DB

widths = [
    (126, 1), (159, 0), (687, 1), (710, 0), (711, 1),
    (727, 0), (733, 1), (879, 0), (1154, 1), (1161, 0),
    (4347, 1), (4447, 2), (7467, 1), (7521, 0), (8369, 1),
    (8426, 0), (9000, 1), (9002, 2), (11021, 1), (12350, 2),
    (12351, 1), (12438, 2), (12442, 0), (19893, 2), (19967, 1),
    (55203, 2), (63743, 1), (64106, 2), (65039, 1), (65059, 0),
    (65131, 2), (65279, 1), (65376, 2), (65500, 1), (65510, 2),
    (120831, 1), (262141, 2), (1114109, 1),
]

true = True
false = False
null = ''


def get_width(o):
    """Return the screen column width for unicode ordinal o."""
    global widths
    if o == 0xe or o == 0xf:
        return 0
    for num, wid in widths:
        if o <= num:
            return wid
    return 1


# 下载武器图片
async def PicDownload(url):
    file_name = "./data/battlefield/pic/weapons" + url[url.rfind('/'):]
    # noinspection PyBroadException
    try:
        fp = open(file_name, 'rb')
        fp.close()
        return file_name
    except Exception as e:
        logger.warning(e)
        i = 0
        while i < 3:
            async with aiohttp.ClientSession() as session:
                # noinspection PyBroadException
                try:
                    async with session.get(url, timeout=5, verify_ssl=False) as resp:
                        pic = await resp.read()
                        fp = open(file_name, 'wb')
                        fp.write(pic)
                        fp.close()
                        return file_name
                except Exception as e:
                    logger.error(e)
                    i += 1
        return "./data/battlefield/pic/weapons/play.jpg"


# 下载头像图片
async def playerPicDownload(url, name):
    file_name = "./data/battlefield/pic/avatar" + url[url.rfind('/')] + name + ".jpg"
    # noinspection PyBroadException
    try:
        fp = open(file_name, 'rb')
        fp.close()
        return file_name
    except Exception as e:
        logger.warning(f"未找到玩家{name}头像,开始下载:{e}")
        i = 0
        while i < 3:
            async with aiohttp.ClientSession() as session:
                # noinspection PyBroadException
                try:
                    async with session.get(url, timeout=5, verify_ssl=False) as resp:
                        pic = await resp.read()
                        fp = open(file_name, 'wb')
                        fp.write(pic)
                        fp.close()
                        return file_name
                except Exception as e:
                    logger.error(e)
                    i += 1
        return "./data/battlefield/pic/avatar/play.jpg"


# 选取背景图
async def pic_custom(player_id):
    path = './data/battlefield/pic/bg/'
    file_name_list = os.listdir(path)
    for item in file_name_list:
        if str(player_id) in item:
            file_nums = len(os.listdir(path + item + '/'))
            return "./data/battlefield/pic/bg/" + item + "/" + str(random.randint(1, file_nums)) + ".png"
    else:
        return "./data/battlefield/pic/bg/" + str(random.randint(1, 10)) + ".png"


# 选取背景图2
async def pic_custom2(player_id):
    path = './data/battlefield/pic/bg2/'
    file_name_list = os.listdir(path)
    for item in file_name_list:
        if str(player_id) in item:
            file_nums = len(os.listdir(path + item + '/'))
            return "./data/battlefield/pic/bg2/" + item + "/" + str(random.randint(1, file_nums)) + ".png"
    else:
        return "./data/battlefield/pic/bg2/" + str(random.randint(1, 10)) + ".png"


# 下载交换皮肤
async def download_skin(url):
    file_name = './data/battlefield/pic/skins/' + url[url.rfind('/') + 1:]
    # noinspection PyBroadException
    try:
        fp = open(file_name, 'rb')
        fp.close()
        return file_name
    except Exception as e:
        logger.warning(e)
        i = 0
        while i < 3:
            async with aiohttp.ClientSession() as session:
                # noinspection PyBroadException
                try:
                    async with session.get(url, timeout=5, verify_ssl=False) as resp:
                        pic = await resp.read()
                        fp = open(file_name, 'wb')
                        fp.write(pic)
                        fp.close()
                        return file_name
                except Exception as e:
                    logger.error(e)
                    i += 1
        return None


# 下载百科图片
async def download_wiki_pic(url):
    file_name = './data/battlefield/pic/百科/' + url[url.rfind('/') + 1:]
    # noinspection PyBroadException
    try:
        fp = open(file_name, 'rb')
        fp.close()
        return file_name
    except Exception as e:
        logger.warning(e)
        i = 0
        while i < 3:
            async with aiohttp.ClientSession() as session:
                # noinspection PyBroadException
                try:
                    async with session.get(url, timeout=5, verify_ssl=False) as resp:
                        pic = await resp.read()
                        fp = open(file_name, 'wb')
                        fp.write(pic)
                        fp.close()
                        return file_name
                except Exception as e:
                    logger.error(e)
                    i += 1
        return None


async def player_stat_bfban_api(player_pid) -> dict:
    bfban_url = 'https://api.gametools.network/bfban/checkban?personaids=' + str(player_pid)
    bfban_head = {
        "Connection": "keep-alive",
    }
    # noinspection PyBroadException
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(bfban_url, headers=bfban_head, timeout=3)
    except Exception as e:
        logger.error(e)
        # await app.send_message(group, MessageChain(
        #     # At(sender.id),
        #     "获取玩家bfban信息出错,请稍后再试!"
        # ), quote=message[Source][0])
        return "获取玩家bfban信息出错,请稍后再试!"
    bf_html = response.text
    if bf_html == "timed out":
        return "获取玩家bfban信息出错,请稍后再试!"
    elif bf_html == {}:
        return "获取玩家bfban信息出错,请稍后再试!"
    return eval(bf_html)


async def tyc_waterGod_api(player_pid):
    url1 = 'https://api.s-wg.net/ServersCollection/getPlayerAll?PersonId=' + str(player_pid)
    header = {
        "Connection": "keep-alive"
    }
    async with httpx.AsyncClient() as client:
        response = await client.get(url1, headers=header, timeout=10)
    return response


async def tyc_record_api(player_pid):
    record_url = "https://record.ainios.com/getReport"
    data = {
        "personaId": player_pid
    }
    header = {
        "Connection": "keep-alive"
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(record_url, headers=header, data=data, timeout=5)
    return response


async def tyc_bfban_api(player_pid):
    bfban_url = 'https://api.gametools.network/bfban/checkban?personaids=' + str(player_pid)
    header = {"Connection": "keep-alive"}
    async with httpx.AsyncClient() as client:
        response = await client.get(bfban_url, headers=header, timeout=3)
    return response


async def tyc_bfeac_api(player_name):
    check_eacInfo_url = f"https://api.bfeac.com/case/EAID/{player_name}"
    header = {
        "Connection": "keep-alive"
    }
    async with httpx.AsyncClient() as client:
        response = await client.get(check_eacInfo_url, headers=header, timeout=10)
    return response


async def tyc_check_vban(player_pid) -> dict or str:
    url = f"https://api.gametools.network/manager/checkban?playerid={player_pid}&platform=pc&skip_battlelog=false"
    head = {
        'accept': 'application/json',
        "Connection": "Keep-Alive"
    }
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=head, timeout=5)
        try:
            return eval(response.text)
        except:
            return "获取出错!"
    except:
        return '网络出错!'


async def report_Interface(player_name, report_reason, report_qq, apikey):
    report_url = "https://api.bfeac.com/inner_api/case_report"
    headers = {
        "apikey": apikey
    }
    body = {
        "target_EAID": player_name,
        "case_body": report_reason,
        "game_type": 1,
        "report_by": {
            "report_platform": "qq",
            "user_id": report_qq
        }
    }
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(report_url, headers=headers, data=json.dumps(body), timeout=10)
        # logger.warning(response)
        logger.warning(response.text)
        return response.text
    except Exception as e:
        logger.error(e)
        return e


async def get_record_counter(file_path):
    record_counters = 0
    try:
        async with aiofiles.open(file_path, 'r', encoding='utf-8') as file_temp:
            file_content = await file_temp.read()
            data = json.loads(file_content)
            record_counters += len(data.get("bind", {}).get("history", []))
            record_counters += len(data.get("weapon", {}).get("history", []))
            record_counters += len(data.get("vehicle", {}).get("history", []))
            record_counters += len(data.get("stat", {}).get("history", []))
            record_counters += len(data.get("recent", {}).get("history", []))
            record_counters += len(data.get("matches", {}).get("history", []))
            record_counters += len(data.get("tyc", {}).get("history", []))
            record_counters += len(data.get("report", {}).get("history", []))
    except:
        pass
    return record_counters


async def get_record_counters(bind_path):
    record_counters = 0
    bind_path_list = [item for item in os.listdir(bind_path)]
    tasks = []
    for item in bind_path_list:
        file_path = f"{bind_path}/{item}/record.json"
        if os.path.exists(file_path):
            tasks.append(asyncio.create_task(get_record_counter(file_path)))
            if len(tasks) >= 4000:
                results = await asyncio.gather(*tasks)
                for result in results:
                    record_counters += result
                tasks = []
    if tasks:
        results = await asyncio.gather(*tasks)
        for result in results:
            record_counters += result
    return record_counters


async def get_stat_by_name(player_name: str) -> dict:
    url = f"https://api.gametools.network/bf1/stats/?format_values=true&name={player_name}&platform=pc"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            return await response.json()


async def get_stat_by_pid(player_pid: str) -> dict:
    url = f"https://api.gametools.network/bf1/stats/?format_values=true&playerid={player_pid}&platform=pc"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            return await response.json()


# TODO 以下是重构内容
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


async def get_recent_info(player_name: str) -> list[dict]:
    """
    从BTR获取最近的战绩
    :param player_name: 玩家名称
    :return: 返回一个列表，列表中的每个元素是一个字典，默认爬取全部数据，调用处决定取前几个
    """
    url = "https://battlefieldtracker.com/bf1/profile/pc/" + player_name
    header = {
        "Connection": "keep-alive",
        "User-Agent": "ProtoHttp 1.3/DS 15.1.2.1.0 (Windows)",
    }
    result = []
    async with aiohttp.ClientSession(headers=header) as session:
        async with session.get(url) as response:
            html = await response.text()
            # 处理网页超时
            if html == "timed out":
                raise Exception
            elif html == {}:
                raise Exception
            soup = BeautifulSoup(html, "html.parser")
            # 从<div class="card-body player-sessions">获取对局数量，如果找不到则返回None
            if not soup.select('div.card-body.player-sessions'):
                return None
            sessions = soup.select('div.card-body.player-sessions')[0].select('div.sessions')
            # 每个sessions由标题和对局数据组成，标题包含时间和胜率，对局数据包含spm、kdr、kpm、btr、gs、tp
            for item in sessions:
                # time的文字由 int 单位 ago组成，如 3 days ago，需要转换为时间戳
                # 提取出数字和单位，转换成秒，然后由当前时间减去，得到时间戳，再转换成字符串如xxxx年x月x日x时x分,注意当数字为1时，其文字为an
                time_item = item.select('div.title > div.time > h4 > span')[0]
                # 此时time_item =  <span data-livestamp="2023-03-22T14:00:00.000Z"></span>
                # 提取将UTC时间转换为本地时间的时间戳
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
