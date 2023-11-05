import datetime
import re
import time
from typing import Union

from bs4 import BeautifulSoup
from loguru import logger
from rapidfuzz import fuzz
from zhconv import zhconv


class WeaponData:
    """传入武器dict源数据，返回武器根据条件排序后的列表,封装成类，方便后续调用"""

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
                weapon["categoryId"] = category["categoryId"]
                self.weapon_item_list.append(weapon)

    # 按照规则来排序
    def filter(self, rule: str = None, sort_type: str = "击杀") -> list:
        """对武器进行分类排序"""
        weapon_list = []
        # 按照武器类别、兵种、击杀数来过滤
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
            elif rule in ["佩枪", "手枪"]:
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
                if weapon.get("category") in ["步槍"] or weapon.get("guid") in [
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
            "KILLS": "kills",
            "KILL": "kills",
            "时长": "seconds",
            "TIME": "seconds",
        }
        if sort_type.upper() in ["爆头率", "爆头", "HS"]:
            weapon_list.sort(
                key=lambda x: round(
                    x["stats"]["values"].get("headshots", 0) / x["stats"]["values"].get("kills", 0) * 100, 2
                ) if x["stats"]["values"].get("kills", 0) != 0 else 0,
                reverse=True
            )
        elif sort_type.upper() in ["命中率", "命中", "ACC"]:
            weapon_list.sort(
                key=lambda x: round(
                    x["stats"]["values"].get("hits", 0) / x["stats"]["values"].get("shots", 0) * 100, 2
                ) if x["stats"]["values"].get("shots", 0) != 0 else 0,
                reverse=True
            )
        elif sort_type.upper() in ["KPM"]:
            weapon_list.sort(
                key=lambda x: round(
                    x["stats"]["values"].get("kills", 0) / x["stats"]["values"].get("seconds", 0) * 60, 2
                ) if x["stats"]["values"].get("seconds", 0) != 0 else x["stats"]["values"].get("kills", 0),
                reverse=True
            )
        else:
            weapon_list.sort(
                key=lambda x: x.get("stats").get("values").get(sort_type_dict.get(sort_type.upper(), "kills"), 0),
                reverse=True
            )
        return weapon_list

    # 根据武器名搜索武器信息
    def search_weapon(self, target_weapon_name: str, sort_type: str = "击杀") -> list:
        """根据武器名搜索武器信息"""
        target_weapon_name = target_weapon_name.upper()
        weapon_list = []
        for weapon in self.weapon_item_list:
            # 先将武器名转换为简体中文，再进行模糊匹配
            weapon_name = zhconv.convert(weapon.get("name"), 'zh-hans').upper().replace("-", "")
            # 非完全匹配，基于最佳的子串（substrings）进行匹配
            if (target_weapon_name in weapon_name) or (fuzz.partial_ratio(target_weapon_name, weapon_name) > 90):
                weapon_list.append(weapon)
        # 按照击杀/爆头率/命中率/时长排序
        sort_type_dict = {
            "击杀": "kills",
            "KILLS": "kills",
            "KILL": "kills",
            "时长": "seconds",
            "TIME": "seconds",
        }
        if sort_type.upper() in ["爆头率", "爆头", "HS"]:
            weapon_list.sort(
                key=lambda x: round(
                    x["stats"]["values"].get("headshots", 0) / x["stats"]["values"].get("hits", 0) * 100, 2
                ) if x["stats"]["values"].get("hits", 0) != 0 else 0,
                reverse=True
            )
        elif sort_type.upper() in ["命中率", "命中", "ACC"]:
            weapon_list.sort(
                key=lambda x: round(
                    x["stats"]["values"].get("hits", 0) / x["stats"]["values"].get("shots", 0) * 100, 2
                ) if x["stats"]["values"].get("shots", 0) != 0 else 0,
                reverse=True
            )
        else:
            weapon_list.sort(
                key=lambda x: x.get("stats").get("values").get(sort_type_dict.get(sort_type.upper(), "kills"), 0),
                reverse=True
            )
        return weapon_list


class VehicleData:
    """传入载具dict源数据，根据条件返回排序后的载具列表"""

    # 初始化
    def __init__(self, vehicle_data: dict):
        self.vehicle_data: list = vehicle_data.get("result")
        self.vehicle_item_list: list = []
        """
        载具的分类:
            重型坦克、巡航坦克、輕型坦克、火砲裝甲車、攻擊坦克、突擊裝甲車、
            攻擊機、轟炸機、戰鬥機、重型轟炸機、
            飛船、
            地面載具、
            船隻、驅逐艦、
            定點武器、
            機械巨獸(火车、飞艇、char 2c、无畏舰)、
            馬匹
        """
        for category in self.vehicle_data:
            for vehicle in category["vehicles"]:
                vehicle["category"] = category["name"]
                vehicle["sortOrder"] = category["sortOrder"]
                if vehicle["sortOrder"] == 8:
                    # 攻擊坦克
                    vehicle["sortOrder"] = "20"
                elif vehicle["sortOrder"] == 7:
                    # 火砲裝甲車
                    vehicle["sortOrder"] = "15"
                elif vehicle["sortOrder"] == 5:
                    # 重型坦克
                    vehicle["sortOrder"] = "17"
                elif vehicle["sortOrder"] == 4:
                    # 巡航坦克
                    vehicle["sortOrder"] = "12"
                elif vehicle["sortOrder"] == 6:
                    # 輕型坦克
                    vehicle["sortOrder"] = "14"
                elif vehicle["sortOrder"] == 9:
                    # 突擊裝甲車
                    vehicle["sortOrder"] = "22"
                # elif vehicle["sortOrder"] == 0:
                #     # 攻擊機
                #     vehicle["sortOrder"] = "0"
                elif vehicle["sortOrder"] == 1:
                    # 轟炸機
                    vehicle["sortOrder"] = "16"
                elif vehicle["sortOrder"] == 2:
                    # 重型轰炸机
                    vehicle["sortOrder"] = "21"
                elif vehicle["sortOrder"] == 3:
                    # 戰鬥機
                    vehicle["sortOrder"] = "14"
                elif vehicle["name"] == "飛船":
                    # 飛船
                    vehicle["sortOrder"] = "24"
                elif vehicle["sortOrder"] == 13:
                    # 船隻
                    vehicle["sortOrder"] = ""
                elif vehicle["name"] == "驅逐艦":
                    # 驅逐艦
                    vehicle["sortOrder"] = "23"
                else:
                    vehicle["sortOrder"] = ""
                self.vehicle_item_list.append(vehicle)

    # 排序
    def filter(self, rule: str = None, sort_type: str = "击杀") -> list:
        vehicle_list = []
        # 按照载具类别、击杀数来过滤
        for vehicle in self.vehicle_item_list:
            if rule in ["坦克"]:
                if vehicle.get("category") in ["重型坦克", "巡航坦克", "輕型坦克", "攻擊坦克", "突擊裝甲車"]:
                    vehicle_list.append(vehicle)
            elif rule in ["地面"]:
                if vehicle.get("category") in [
                    "重型坦克", "巡航坦克", "輕型坦克", "火砲裝甲車", "攻擊坦克", "突擊裝甲車", "地面載具", "馬匹",
                    "定點武器"
                ] or vehicle.get("guid") in [
                    "A3ED808E-1525-412B-8E77-9EB6902A55D2",  # 装甲列车
                    "BBFC5A91-B2FC-48D2-8913-658C08072E6E"  # Char 2C
                ]:
                    vehicle_list.append(vehicle)
            elif rule in ["飞机"]:
                if vehicle.get("category") in ["攻擊機", "轟炸機", "戰鬥機", "重型轟炸機"]:
                    vehicle_list.append(vehicle)
            elif rule in ["飞船", "飞艇"]:
                if vehicle.get("category") in ["飛船"] or vehicle.get("guid") in [
                    "1A7DEECF-4F0E-E343-9644-D6D91DCAEC12",  # 飞艇
                ]:
                    vehicle_list.append(vehicle)
            elif rule in ["空中"]:
                if vehicle.get("category") in ["攻擊機", "轟炸機", "戰鬥機", "重型轟炸機", "飛船"] or vehicle.get(
                        "guid") in [
                    "1A7DEECF-4F0E-E343-9644-D6D91DCAEC12",  # 飞艇
                ]:
                    vehicle_list.append(vehicle)
            elif rule in ["海上"]:
                if vehicle.get("category") in ["船隻", "驅逐艦"] or vehicle.get("guid") in [
                    "003FCC0A-2758-8508-4774-78E66FA1B5E3",  # 无畏舰
                ]:
                    vehicle_list.append(vehicle)
            elif rule in ["定点"]:
                if vehicle.get("category") in ["定點武器"]:
                    vehicle_list.append(vehicle)
            elif rule in ["机械巨兽", "巨兽"]:
                if vehicle.get("category") in ["機械巨獸"]:
                    vehicle_list.append(vehicle)
            else:
                vehicle_list.append(vehicle)

        # 按照击杀/时长/摧毁数
        sort_type_dict = {
            "击杀": "kills",
            "时长": "seconds",
            "摧毁": "destroyed",
            "TIME": "seconds",
        }
        if sort_type.upper() in ["KPM"]:
            vehicle_list.sort(
                key=lambda x: x.get("stats").get("values").get("kills", 0) / x.get("stats").get("values").get("seconds",
                                                                                                              0)
                if x.get("stats").get("values").get("seconds", 0) != 0 else x["stats"]["values"].get("kills", 0),
                reverse=True
            )
        else:
            vehicle_list.sort(
                key=lambda x: x.get("stats").get("values").get(sort_type_dict.get(sort_type.upper(), "kills"), 0),
                reverse=True
            )
        return vehicle_list

    # 搜索载具
    def search_vehicle(self, target_vehicle_name: str, sort_type: str = "击杀") -> list:
        """根据载具名搜索载具信息"""
        target_vehicle_name = target_vehicle_name.upper()
        vehicle_list = []
        for vehicle in self.vehicle_item_list:
            # 先将载具名转换为简体中文，再进行模糊匹配
            vehicle_name = zhconv.convert(vehicle.get("name"), 'zh-hans').upper().replace("-", "")
            # 非完全匹配，基于最佳的子串（substrings）进行匹配
            if (target_vehicle_name in vehicle_name) or (fuzz.partial_ratio(target_vehicle_name, vehicle_name) > 90):
                vehicle_list.append(vehicle)
        # 按照击杀/时长/摧毁数
        sort_type_dict = {
            "击杀": "kills",
            "时长": "seconds",
            "摧毁": "destroyed"
        }
        vehicle_list.sort(
            key=lambda x: x.get("stats").get("values").get(sort_type_dict.get(sort_type, "kills"), 0),
            reverse=True
        )
        return vehicle_list


class BTRMatchesData:
    """传入BTR对局数据，返回BTR对局列表"""

    def __init__(self, btr_matches_data: list):
        self.btr_matches_data: list = btr_matches_data

    async def handle(self) -> list[dict]:
        result = []
        # 处理每个对局的详细信息
        for i, match in enumerate(self.btr_matches_data):
            result_temp = {}
            # 获取详细数据
            soup = BeautifulSoup(match, 'lxml')
            # 游戏地图、模式、时间在 <div class="match-info">标签,如下所示
            """
            <div class="match-info">
                <div class="activity-details">
                    <h2 class="map-name">Fort De Vaux <small class="hidden-sm hidden-xs">[202]#1 Hotmap  kd&amp;kpm&gt;2 kill&gt;60kb&amp;zh=kick qq608458191</small></h2>
                    <span class="type">Conquest</span>
                    <span class="date">3/26/2023 7:16:20 AM</span>
                </div>
            </div>
            """
            # 获取地图名并将地图名字翻译成中文
            # <h2 class="map-name">地图名<small class="hidden-sm hidden-xs">服务器名</small></h2>
            try:
                map_name = re.findall(re.compile(r'<h2 class="map-name">(.*?)<small'), str(match))[0]
            except IndexError:
                try:
                    map_name = soup.select("div.match-info h2.map-name")[0].text
                except IndexError:
                    continue
            map_name = map_name \
                .replace("Galicia", "加利西亚").replace("Giant's Shadow", "庞然暗影") \
                .replace("Brusilov Keep", "勃鲁希洛夫关口").replace("Rupture", "决裂") \
                .replace("Soissons", "苏瓦松").replace("Amiens", "亚眠") \
                .replace("St. Quentin Scar", "圣康坦的伤痕").replace("Argonne Forest", "阿尔贡森林") \
                .replace("Ballroom Blitz", "流血宴厅").replace("MP_Harbor", "泽布吕赫") \
                .replace("River Somme", "索姆河").replace("Prise de Tahure", "攻占托尔") \
                .replace("Fao Fortress", "法欧堡").replace("Achi Baba", "阿奇巴巴") \
                .replace("Cape Helles", "海丽丝岬").replace("Tsaritsyn", "察里津").replace("Volga River", "窝瓦河") \
                .replace("Empire's Edge", "帝国边境").replace("ŁUPKÓW PASS", "武普库夫山口") \
                .replace("Verdun Heights", "凡尔登高地").replace("Fort De Vaux", "法乌克斯要塞") \
                .replace("Sinai Desert", "西奈沙漠").replace("Monte Grappa", "格拉巴山").replace("Suez", "苏伊士") \
                .replace("Albion", "阿尔比恩").replace("Caporetto", "卡波雷托").replace("Passchendaele", "帕斯尚尔") \
                .replace("Nivelle Nights", "尼维尔之夜").replace("MP_Naval", "黑尔戈兰湾").strip()
            # 游戏模式,并将模式名字翻译成中文
            mode_name = soup.select('div.match-info')[0].select('span.type')[0].text \
                .replace("BreakthroughLarge0", "行动模式").replace("Frontlines", "前线") \
                .replace("Domination", "抢攻").replace("Team Deathmatch", "团队死斗") \
                .replace("War Pigeons", "战争信鸽").replace("Conquest", "征服") \
                .replace("AirAssault0", "空中突袭").replace("Rush", "突袭") \
                .replace("Breakthrough", "闪击行动").strip()
            # 游戏发生时间,转换成时间戳
            game_time = soup.select('div.match-info')[0].select('span.date')[0].text
            game_time = int(time.mktime(time.strptime(game_time, "%m/%d/%Y %I:%M:%S %p")))
            game_time = datetime.datetime.fromtimestamp(game_time)
            # 服务器名
            server_name = soup.select('div.match-info')[0].select('small.hidden-sm.hidden-xs')[0].text
            result_temp["game_info"] = {
                "server_name": server_name,
                "map_name": map_name,
                "mode_name": mode_name,
                "game_time": game_time,
            }
            result_temp["players"] = []
            # <div class="match-teams">下有三个<div class="team">,分别为TEAM 1、TEAM 2、NO TEAM
            # team下包含 card-heading和 card，
            # <div class="card-heading">
            #             <h3 class="card-title">Team 1</h3>
            #             <div class="additional-info">Lost</div>
            #         </div>
            # 循环获取team1和team2的胜负情况
            for team_item in soup.select('div.match-teams')[0].select('div.team'):
                # 获取team1和team2的胜负情况，如果赢了转换为True，否则为False
                team_name = team_item.select('div.card-heading')[0].select('h3.card-title')[0].text.strip().replace(" ",
                                                                                                                    "")
                # team1命名为1，team2命名为2，NO TEAM命名为0
                if team_name == 'Team1':
                    team_name = 1
                elif team_name == 'Team2':
                    team_name = 2
                else:
                    team_name = 0
                team_win = team_item.select('div.card-heading')[0].select('div.additional-info')[0].text
                if team_win == 'Won':
                    team_win = True
                else:
                    team_win = False
                # 在每个team的card下包含card-player-container,team-players
                # team-player下包含整个队伍的player
                # 获取玩家列表
                players = team_item.select('div.card')[0].select('div.card-player-container')[0].select(
                    'div.player')
                # 循环获取每个玩家的详细信息
                for player in players:
                    # 玩家名字在div player-header->div player-info->div->a player-name
                    player_name_item = player.select('div.player-header')[0].select('div.player-info')[0].select(
                        'div')[0].select('a.player-name')[0].text.replace('"', "").strip()
                    # 得分在div player-header->div quick-stats->div stat name=Score
                    player_score = 0
                    for value in player.select('div.player-header')[0].select('div.quick-stats')[0].select('div.stat'):
                        value_name = value.select('.name')[0].text.strip()
                        if value_name == "Score":
                            player_score = value.select('.value')[0].text.strip().replace(",", "")
                            if player_score.isdigit():
                                player_score = int(player_score)
                            else:
                                player_score = 0
                            break
                    if player_score == 0:
                        continue
                    # 获取玩家的详细信息,路径在player->player-details-container->player-details->row->col-md-7->stats
                    player_stats = player.select('div.player-details-container')[0].select(
                        'div.player-details')[0].select('div.row')[0].select('div.col-md-7')[0].select('div.stats')
                    # 获取击杀、死亡、爆头数、命中率、时间
                    player_kills = player_stats[0].select('div.stat')[0].select('div.value')[0].text
                    if player_kills.isdigit():
                        player_kills = int(player_kills)
                    else:
                        player_kills = 0
                    player_deaths = player_stats[0].select('div.stat')[1].select('div.value')[0].text
                    if player_deaths.isdigit():
                        player_deaths = int(player_deaths)
                    else:
                        player_deaths = 0
                    if player_kills == 0 and player_deaths == 0:
                        continue
                    kd = round(player_kills / player_deaths, 2) if player_deaths != 0 else 0
                    # 爆头率序号不定
                    # 通过value来确定
                    player_headshots = "0"
                    for value in player_stats[0].select('div.stat'):
                        value_name = value.select('.name')[0].text.strip()
                        if value_name == "Headshots":
                            player_headshots = value.select('.value')[0].text.strip()
                            break
                    if player_headshots.isdigit():
                        player_headshots = int(player_headshots) * 100
                    else:
                        player_headshots = 0
                    player_headshots = f"{round(player_headshots / player_kills, 2) if player_kills != 0 else 0}%"
                    # 命中率序号不定
                    # 通过value来确定
                    player_accuracy = "0%"
                    for value in player_stats[0].select('div.stat'):
                        if value.select('.name')[0].text.strip() == "Accuracy":
                            player_accuracy = value.select('.value')[0].text.strip()
                            break
                    # 时间序号不定
                    # 通过value来确定
                    player_time = "0s"
                    for value in player_stats[0].select('div.stat'):
                        if value.select('.name')[0].text.strip() == "Time Played":
                            player_time = value.select('.value')[0].text.strip()
                            break
                    # 时间都是  xh xm xs 的形式
                    # 转换成秒
                    time_second = 0
                    if "h" in player_time:
                        hours, remaining_time = player_time.split("h")
                        time_second += int(hours) * 3600
                    else:
                        remaining_time = player_time
                    if "m" in remaining_time:
                        minutes, remaining_time = remaining_time.split("m")
                        time_second += int(minutes) * 60
                    if "s" in remaining_time:
                        seconds = remaining_time.split("s")[0]
                        time_second += int(seconds)

                    # kpm、spm
                    if time_second != 0:
                        kpm = round(player_kills / time_second * 60, 2)
                        spm = round(player_score / time_second * 60, 2)
                    else:
                        kpm = 0
                        spm = 0

                    player_info = {
                        "player_name": player_name_item,
                        "team_name": team_name,
                        "team_win": team_win,
                        "kills": player_kills,
                        "deaths": player_deaths,
                        "kd": kd,
                        "kpm": kpm,
                        "score": player_score,
                        "spm": spm,
                        "headshots": player_headshots,
                        "accuracy": player_accuracy,
                        "time_played": player_time,
                    }
                    result_temp["players"].append(player_info)
                    # 将result_temp添加到result中
            result.append(result_temp)
        return result


class ServerData:
    """处理搜索到的服务器数据"""

    def __init__(self, data: dict):
        self.data: dict = data

    def sort(self, sort_type: str = "player") -> list[dict]:
        """对服务器进行排序,默认按照玩家数量排序"""
        server_list = []
        # 处理数据
        for server in self.data.get("gameservers"):
            game_id = server.get("gameId")
            guid = server.get("guid")
            name = server.get("name")
            description = server.get("description")
            SoldierCurrent = server.get("slots").get("Soldier").get("current")
            SoldierMax = server.get("slots").get("Soldier").get("max")
            QueueCurrent = server.get("slots").get("Queue").get("current")
            QueueMax = server.get("slots").get("Queue").get("max")
            SpectatorCurrent = server.get("slots").get("Spectator").get("current")
            SpectatorMax = server.get("slots").get("Spectator").get("max")
            map_name = server.get("mapNamePretty")
            mode_name = server.get("mapModePretty")
            mapImageUrl = server.get("mapImageUrl").replace(
                "[BB_PREFIX]", "https://eaassets-a.akamaihd.net/battlelog/battlebinary")
            server_list.append({
                "game_id": game_id,
                "guid": guid,
                "name": name,
                "description": description,
                "SoldierCurrent": SoldierCurrent,
                "SoldierMax": SoldierMax,
                "QueueCurrent": QueueCurrent,
                "QueueMax": QueueMax,
                "SpectatorCurrent": SpectatorCurrent,
                "SpectatorMax": SpectatorMax,
                "map_name": map_name,
                "mode_name": mode_name,
                "mapImageUrl": mapImageUrl,
            })

        # 排序
        if sort_type == "player":
            server_list.sort(key=lambda x: x.get("SoldierCurrent"), reverse=True)
        else:
            server_list.sort(key=lambda x: x.get("name"), reverse=True)

        return server_list


class BlazeData:
    language_dict = {
        "zh": "中",
        "ru": "俄",
        "en": "英",
        "th": "泰",
        "de": "德",
        "fr": "法",
        "it": "意",
        "pl": "波",
        "dk": "力",
        "cs": "捷",
        "hu": "匈",
        "ko": "韩",
        "es": "西",
        "ja": "日",
        "pt": "葡",
        "nl": "荷",
        "tr": "土",
        "sv": "瑞",
        "no": "挪",
        "fi": "芬",
        "ro": "罗",
        "ar": "阿",
    }

    @staticmethod
    def player_list_handle(data: dict) -> Union[dict, str]:
        """
        处理玩家列表数据
        origin:
        {
        "method": "GameManager.getGameDataFromId",
        "type": "Result",
        "id": 7,
        "length": 55126,
        "data": {
            "GDAT 43": []
        }
        :param data:
        :return:
        eg:
        {
            "8622724970463": {
            "server_name": "[JIAOYUAN#3]Noob welcome/NO SMG0818/qun642283064",
            "game_id": 8622724970463,
            "players": [
                {
                    "display_name": "Saber-master520",
                    "pid": 1004755893484,
                    "uid": 1009760693484,
                    "role": "spectator",
                    "rank": "28",
                    "latency": "27",
                    "team": 65535
                }
            ],
            "queues": 0,
            "spectator": 1,
            "max_player": 64
        }
        """
        result = {}
        if not data["data"]:
            return result
        if data["type"] == "Error":
            error_code = data.get("data", {}).get("ERRC", "Known")
            return f"Blaze查询出错!错误代码:{error_code}"
        for server_data in data["data"]["GDAT"]:
            game_id = server_data["GID"]
            server_name = server_data["GNAM"]
            # queue = server_data["QCNT 0"]
            # spectator = server_data["PCNT 40"][2]
            server_attribute = server_data["ATTR"]
            operation_info = {}
            if server_attribute.get("operationindex"):
                operation_info["operationstate"] = server_attribute["operationstate"]
                operation_info["operationindex"] = server_attribute["operationindex"]
                operation_info["progress"] = server_attribute["progress"]

            max_player = server_data["CAP"][0]
            players = []
            queues = []
            spectators = []
            if "ROST" in server_data:
                for player in server_data["ROST"]:
                    role = player["ROLE"]
                    if role == "":
                        role = "spectator"
                    try:
                        rank = int(player["PATT"].get("rank", 0))
                    except KeyError:
                        logger.debug(player)
                        rank = 0
                    try:
                        latency = int(player["PATT"].get("latency", 0))
                    except KeyError:
                        logger.debug(player)
                        latency = 0
                    join_time = player["JGTS"] / 1000000
                    display_name = player["NAME"]
                    pid = player["PID"]
                    uid = player["EXID"]
                    team = player["TIDX"]
                    language = player["LOC"].to_bytes(4, byteorder="big").decode("ascii")
                    language = BlazeData.language_dict.get(language[:2], language[:2])
                    if team == 65535 and rank == 0:
                        role = "queue"
                    player_data = {
                        "display_name": display_name,
                        "pid": pid,
                        "uid": uid,
                        "role": role,
                        "rank": rank,
                        "latency": latency,
                        "team": team,
                        "join_time": join_time,
                        "platoon": {},
                        "language": language,
                    }
                    if role == "queue":
                        queues.append(player_data)
                    elif role == "spectator":
                        spectators.append(player_data)
                    else:
                        players.append(player_data)
            result[game_id] = {
                "server_name": server_name,
                "game_id": game_id,
                "players": players,
                "queues": queues,
                "spectators": spectators,
                "max_player": max_player,
                "time": time.time(),
                "operation_info": operation_info
            }
        return result
