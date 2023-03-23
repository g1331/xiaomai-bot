import asyncio
import json
import os
import random
from typing import Union

import aiofiles
import aiohttp
import httpx
import zhconv
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


# 以下是重构内容
async def get_personas_by_name(player_name: str) -> Union[dict, None]:
    """根据玩家名称获取玩家信息"""
    player_info = await (await BF1DA.get_api_instance()).getPersonasByName(player_name)
    if not player_info.get("personas"):
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
            logger.error(e)
        return player_info


async def get_personas_by_player_pid(player_pid: int) -> Union[dict, str, None]:
    """根据玩家pid获取玩家信息"""
    player_info = await (await BF1DA.get_api_instance()).getPersonasByIds(player_pid)
    # 如果pid不存在,则返回错误信息
    if isinstance(player_info, str):
        return player_info
    if not player_info.get("result"):
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
            logger.error(e)
        return player_info


# 传入武器dict源数据，返回武器根据条件排序后的列表,封装成类，方便后续调用
class WeaponData:
    # 传入武器dict源数据初始化
    def __init__(self, weapon_data: dict):
        self.weapon_data: list = weapon_data.get("result")
        self.weapon_item_list: list = []
        """例:
        self.weapon_item_list = [
            {weapon_item},...
        ]
        默认分类:戰場裝備、輕機槍、步槍、配備、半自動步槍、手榴彈、制式步槍、霰彈槍、坦克/駕駛員、衝鋒槍、佩槍、近戰武器
        将制式步槍也归类到步槍中
        """
        for category in self.weapon_data:
            for weapon in category["weapons"]:
                if weapon.get("category") == "制式步槍":
                    weapon["category"] = "步槍"
                self.weapon_item_list.append(weapon)

    # 按照规则来排序
    def filter(self, rule: str = None, sort_type: str = "击杀"):
        weapon_list = []
        # 按照武器类别、兵种、击杀数来排序
        for weapon in self.weapon_item_list:
            if rule in ["精英兵"]:
                if weapon.get("category") == "戰場裝備" or weapon.get("guid") in [
                    "8A849EDD-AE9F-4F9D-B872-7728067E4E9F"
                ]:
                    weapon_list.append(weapon)
            elif rule in ["机枪", "轻机枪"]:
                if weapon.get("category") == "輕機槍":
                    weapon_list.append(weapon)
            elif rule in ["步枪", "狙击枪"]:
                if weapon.get("category") == "步槍":
                    weapon_list.append(weapon)
            elif rule in ["装备", "配备"]:
                if weapon.get("category") == "配備":
                    weapon_list.append(weapon)
            elif rule in ["半自动步枪", "半自动"]:
                if weapon.get("category") == "半自動步槍":
                    weapon_list.append(weapon)
            elif rule in ["手榴弹", "手雷", "投掷物"]:
                if weapon.get("category") == "手榴彈":
                    weapon_list.append(weapon)
            elif rule in ["霰弹枪", "散弹枪"]:
                if weapon.get("category") == "霰彈槍":
                    weapon_list.append(weapon)
            elif rule in ["驾驶员", "坦克驾驶员"]:
                if weapon.get("category") == "坦克/駕駛員":
                    weapon_list.append(weapon)
            elif rule in ["冲锋枪"]:
                if weapon.get("category") == "衝鋒槍":
                    weapon_list.append(weapon)
            elif rule in ["副武器", "佩枪", "手枪"]:
                if weapon.get("category") == "佩槍":
                    weapon_list.append(weapon)
            elif rule in ["近战"]:
                if weapon.get("category") == "近戰武器":
                    weapon_list.append(weapon)
            elif rule in ["突击兵", "土鸡兵", "土鸡", "突击"]:
                if weapon.get("category") in ["衝鋒槍", "霰彈槍"] or weapon.get("guid") in [
                    "245A23B1-53BA-4AB2-A416-224794F15FCB",  # M1911
                    "D8AEB334-58E2-4A52-83BA-F3C2107196F0",
                    "7085A5B9-6A77-4766-83CD-3666DA3EDF28",
                    "079D8793-073C-4332-A959-19C74A9D2A46",
                    "72CCBF3E-C0FE-4657-A1A7-EACDB2D11985",
                    "6DFD1536-BBBB-4528-917A-7E2821FB4B6B",
                    "BE041F1A-460B-4FD5-9E4B-F1C803C0F42F",
                    "AE96B513-1F05-4E63-A273-E98FA91EE4D0",
                ]:
                    weapon_list.append(weapon)
            elif rule in ["侦察兵", "侦察", "斟茶兵", "斟茶"]:
                if weapon.get("category") in ["步枪"] or weapon.get("guid") in [
                    "2543311A-B9BC-4F72-8E71-C9D32DCA9CFC",
                    "ADAD5F72-BD74-46EF-AB42-99F95D88DF8E",
                    "2D64B139-27C8-4EDB-AB14-734993A96008",
                    "EF1C7B9B-8912-4298-8FCB-29CC75DD0E7F",
                    "9CF9EA1C-39A1-4365-85A1-3645B9621901",
                    "033299D1-A8E6-4A5A-8932-6F2091745A9D",
                ]:
                    weapon_list.append(weapon)
            elif rule in ["医疗兵", "医疗"]:
                if weapon.get("category") in ["半自動步槍"] or weapon.get("guid") in [
                    "F34B3039-7B3A-0272-14E7-628980A60F06",
                    "03FDF635-8E98-4F74-A176-DB4960304DF5",
                    "165ED044-C2C5-43A1-BE04-8618FA5072D4",
                    "EBA4454E-EEB6-4AF1-9286-BD841E297ED4",
                    "670F817E-89A6-4048-B8B2-D9997DD97982",
                    "9BCDB1F5-5E1C-4C3E-824C-8C05CC0CE21A",
                    "245A23B1-53BA-4AB2-A416-224794F15FCB",
                    "4E317627-F7F8-4014-BB22-B0ABEB7E9141",
                ]:
                    weapon_list.append(weapon)
            elif rule in ["支援兵", "支援"]:
                if weapon.get("category") in ["輕機槍"] or weapon.get("guid") in [
                    "0CC870E0-7AAE-44FE-B9D8-5D90706AF38B",
                    "6CB23E70-F191-4043-951A-B43D6D2CF4A2",
                    "3DC12572-2D2F-4439-95CA-8DFB80BA17F5",
                    "2B421852-CFF9-41FF-B385-34580D5A9BF0",
                    "EBE043CB-8D37-4807-9260-E2DD7EFC4BD2",
                    "2B0EC5C1-81A5-424A-A181-29B1E9920DDA",
                    "19CB192F-1197-4EEB-A499-A2DA449BE811",
                    "52B19C38-72C0-4E0F-B051-EF11103F6220",
                    "C71A02C3-608E-42AA-9179-A4324A4D4539",
                    "8BD0FABD-DCCE-4031-8156-B77866FCE1A0",
                    "F59AA727-6618-4C1D-A5E2-007044CA3B89",
                    "95A5E9D8-E949-46C2-B5CA-36B3CA4C2E9D",
                    "60D24A79-BFD6-4C8F-B54F-D1AA6D2620DE",
                    "02D4481F-FBC3-4C57-AAAC-1B37DC92751E"
                ]:
                    weapon_list.append(weapon)
            else:
                weapon_list.append(weapon)
        # 按照击杀/爆头率/命中率/时长排序
        sort_type_dict = {
            "击杀": "kills",
            "爆头率": "headshots",
            "命中率": "accuracy",
            "时长": "seconds"
        }
        weapon_list.sort(
            key=lambda x: x.get("stats").get("values").get(sort_type_dict.get(sort_type, "kills")),
            reverse=True
        )
        return weapon_list

    # 根据武器名搜索武器信息
    def search_weapon(self, target_weapon_name):
        weapon_list = []
        for weapon in self.weapon_item_list:
            # 先将武器名转换为简体中文，再进行模糊匹配
            weapon_name = zhconv.convert(weapon.get("name"), 'zh-hans')
            # 非完全匹配，基于最佳的子串（substrings）进行匹配
            if fuzz.partial_ratio(target_weapon_name, weapon_name) > 70:
                weapon_list.append(weapon)
        return weapon_list
