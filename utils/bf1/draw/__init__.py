import asyncio
import base64
import datetime
import io
import json
import os
import random
import time
from io import BytesIO
from pathlib import Path
from typing import Union

import aiohttp
from PIL import Image, ImageFont, ImageDraw, ImageFilter, ImageEnhance
from loguru import logger
from zhconv import zhconv
import pandas as pd
import seaborn as sns
import matplotlib.pyplot as plt

from utils.bf1.bf_utils import download_skin, gt_get_player_id
from utils.bf1.default_account import BF1DA
from utils.bf1.draw.choose_bg_pic import bg_pic
from utils.bf1.map_team_info import MapData
from utils.text2img import template2img


class PlayerStatPic:
    def __init__(self, stat_data: dict = None, weapon_data: list = None, vehicle_data: list = None):
        """初始化处理数据,使用模板html转图片
        :param stat_data: 生涯数据
        :param weapon_data: 武器数据
        :param vehicle_data: 载具数据
        """
        self.stat_data: dict = stat_data
        self.weapon_data: list = weapon_data
        self.vehicle_data: list = vehicle_data

    async def draw(self) -> Union[bytes, None]:
        """绘制生涯数据图片"""
        if not self.stat_data:
            return None


class PlayerWeaponPic:
    weapon_data: list

    def __init__(self, weapon_data: list = None):
        """初始化处理数据,使用模板html转图片
        :param weapon_data: 武器数据
        """
        data = []
        for weapon in weapon_data:
            if not weapon.get("stats").get('values'):
                continue
            name = zhconv.convert(weapon.get('name'), 'zh-hans')
            kills = int(weapon["stats"]["values"]["kills"])
            seconds = weapon["stats"]["values"]["seconds"]
            kpm = "{:.2f}".format(kills / seconds * 60) if seconds != 0 else kills
            acc = (
                round(
                    weapon["stats"]["values"]["hits"]
                    / weapon["stats"]["values"]["shots"]
                    * 100,
                    2,
                )
                if weapon["stats"]["values"]["shots"] != 0
                else 0
            )
            hs = round(weapon["stats"]["values"]["headshots"] / weapon["stats"]["values"]["kills"] * 100, 2) \
                if weapon["stats"]["values"]["kills"] != 0 else 0
            eff = round(weapon["stats"]["values"]["hits"] / weapon["stats"]["values"]["kills"], 2) \
                if weapon["stats"]["values"]["kills"] != 0 else 0
            time_played = "{:.1f}H".format(seconds / 3600)
            item = {
                "name": name,
                "kills": kills,
                "kpm": kpm,
                "acc": acc,
                "hs": hs,
                "eff": eff,
                "time_played": time_played,
                "url": weapon["imageUrl"].replace("[BB_PREFIX]",
                                                  "https://eaassets-a.akamaihd.net/battlelog/battlebinary")
            }
            data.append(item)
        self.weapon_data: list = data

    async def draw(self, player_name: str, player_pid: str, row: int = 4, col: int = 2) -> Union[bytes, None]:
        """绘制武器数据图片
        :param player_pid: 玩家pid
        :param player_name: 玩家名
        :param row: 行数
        :param col: 列数
        """
        if not self.weapon_data:
            return None
        # 从bg_path文件夹内中随机选择一张图片
        bg_path: Path
        bg_path = bg_pic.choose_bg(player_pid)
        if not bg_path:
            bg_path = Path(__file__).parent / "template" / "background"
            bg_list = [x for x in bg_path.iterdir() if x.is_file()]
            bg_path = random.choice(bg_list)
        background = f"data:image/png;base64,{base64.b64encode(bg_path.read_bytes()).decode()}"
        TEMPLATE_PATH = Path(__file__).parent / "template" / "weapon_template.html"
        weapon_data = [self.weapon_data[i * col:(i + 1) * col] for i in range(row)]
        gt_id = await gt_get_player_id(player_name)
        avatar = gt_id.get("avatar") if isinstance(gt_id, dict) else None
        pid = gt_id.get("id") if isinstance(gt_id, dict) else None
        return await template2img(
            TEMPLATE_PATH.read_text(encoding="utf-8"),
            {
                "background": background,
                "weapons": weapon_data,
                "player_name": player_name,
                "pid": pid,
                "avatar": avatar,
                "update_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            },
            page_option={
                "device_scale_factor": 2,
            }
        )


class PlayerVehiclePic:
    vehicle_data: list

    def __init__(self, vehicle_data: list = None):
        """初始化处理数据,使用模板html转图片
        :param vehicle_data: 载具数据
        """
        self.vehicle_data: list = vehicle_data
        data = []
        for vehicle in self.vehicle_data:
            if not vehicle.get("stats").get('values'):
                continue
            name = zhconv.convert(vehicle.get('name'), 'zh-hans')
            kills = int(vehicle["stats"]["values"]["kills"])
            seconds = vehicle["stats"]["values"]["seconds"]
            kpm = "{:.2f}".format(kills / seconds * 60) if seconds != 0 else kills
            destroyed = int(vehicle["stats"]["values"]["destroyed"])
            time_played = "{:.1f}H".format(seconds / 3600)
            item = {
                "name": name,
                "kills": kills,
                "kpm": kpm,
                "destroyed": destroyed,
                "time_played": time_played,
                "url": vehicle["imageUrl"].replace("[BB_PREFIX]",
                                                   "https://eaassets-a.akamaihd.net/battlelog/battlebinary")
            }
            data.append(item)
        self.vehicle_data: list = data

    async def draw(self, player_name: str, player_pid: str, row: int = 4, col: int = 2) -> Union[bytes, None]:
        """绘制载具数据图片"""
        if not self.vehicle_data:
            return None
        # 从bg_path文件夹内中随机选择一张图片
        bg_path: Path
        bg_path = bg_pic.choose_bg(player_pid)
        if not bg_path:
            bg_path = Path(__file__).parent / "template" / "background"
            bg_list = [x for x in bg_path.iterdir() if x.is_file()]
            bg_path = random.choice(bg_list)
        background = f"data:image/png;base64,{base64.b64encode(bg_path.read_bytes()).decode()}"
        TEMPLATE_PATH = Path(__file__).parent / "template" / "vehicle_template.html"
        vehicle_data = [self.vehicle_data[i * col:(i + 1) * col] for i in range(row)]
        gt_id = await gt_get_player_id(player_name)
        avatar = gt_id.get("avatar") if isinstance(gt_id, dict) else None
        pid = gt_id.get("id") if isinstance(gt_id, dict) else None
        return await template2img(
            TEMPLATE_PATH.read_text(encoding="utf-8"),
            {
                "background": background,
                "vehicles": vehicle_data,
                "player_name": player_name,
                "pid": pid,
                "avatar": avatar,
                "update_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            },
            page_option={
                "device_scale_factor": 2,
            }
        )


class Exchange:
    def __init__(self, data: dict = None):
        """初始化处理数据,使用模板html转图片
        :param data: 兑换数据
        """
        self.data: dict = data
        self.img: bytes = bytes()

    async def draw(self) -> Union[bytes, None]:
        """绘制兑换图片"""
        if not self.data:
            return None
        now_date = datetime.datetime.now()
        # 文件名为xxxx年xx月xx日
        # 先查询是否有当天的文件，否则获取gw api的数据制图
        file_name = f"{now_date.year}年{now_date.month}月{now_date.day}日"
        SE_data_list = self.data["result"]["items"]
        # 创建一个交换物件的列表列表，元素列表的元素有价格，皮肤名字，武器名字，品质，武器图片
        SE_list = []
        for item in SE_data_list:
            temp_list = [item["price"], zhconv.convert(item["item"]["name"], 'zh-cn')]
            # 处理成简体
            parentName = item["item"]["parentName"] if item["item"]["parentName"] is not None else ""
            temp_list.append(zhconv.convert(f"{parentName}外观", 'zh-cn'))
            temp_list.append(
                item["item"]["rarenessLevel"]["name"].replace(
                    "Superior", "传奇").replace(
                    "Enhanced", "精英").replace(
                    "Standard", "特殊"))
            temp_list.append(
                item["item"]["images"]["Png1024xANY"].replace(
                    "[BB_PREFIX]", "https://eaassets-a.akamaihd.net/battlelog/battlebinary"
                )
            )
            SE_list.append(temp_list)
        # 保存/获取皮肤图片路径
        i = 0
        while i < len(SE_list):
            SE_list[i][4] = await download_skin(SE_list[i][4])
            i += 1
        # 制作图片,总大小:2351*1322,黑框间隔为8,黑框尺寸220*292，第一张黑框距左边界39，上边界225，武器尺寸为180*45,第一个钱币图片的位置是72*483
        # 交换的背景图
        bg_img = Image.open('./data/battlefield/pic/bg/SE_bg.png')
        draw = ImageDraw.Draw(bg_img)

        # 字体路径
        font_path = './data/battlefield/font/BFText-Regular-SC-19cf572c.ttf'
        price_font = ImageFont.truetype(font_path, 18)
        seName_font = ImageFont.truetype(font_path, 13)
        seSkinName_font = ImageFont.truetype(font_path, 18)
        # 保存路径
        SavePic = f"./data/battlefield/exchange/{file_name}.png"
        x = 59
        y = 340
        for i in range(len(SE_list)):
            while y < 1097:
                while x < 2131 and i < len(SE_list):
                    if SE_list[i][3] == "特殊":
                        i += 1
                        continue
                    # 从上到下分别是武器图片、武器名字、皮肤名字、品质、价格
                    # [
                    #   300,
                    #   '魯特斯克戰役',
                    #   'SMG 08/18',
                    #   '特殊',
                    #   'https://eaassets-a.akamaihd.net/battlelog/battlebinary
                    #   /gamedata/Tunguska/123/1/U_MAXIMSMG_BATTLEPACKS_FABERGE_T1S3_LARGE-7b01c879.png'
                    #   ]
                    # 打开交换图像
                    SE_png = Image.open(SE_list[i][4]).convert('RGBA')
                    # 武器名字
                    draw.text((x, y + 52), SE_list[i][2], (169, 169, 169), font=seName_font)
                    # 皮肤名字
                    draw.text((x, y + 79), SE_list[i][1], (255, 255, 255), font=seSkinName_font)
                    # 如果品质为传奇则品质颜色为(255, 132, 0)，精英则为(74, 151, 255)，特殊则为白色
                    XD_skin_list = ["菲姆", "菲姆特", "索得格雷",
                                    "巴赫馬奇", "菲力克斯穆勒", "狼人", "黑貓",
                                    "苟白克", "比利‧米契尔", "在那边", "飞蛾扑火", "佛伦",
                                    "默勒谢什蒂", "奥伊图兹", "埃丹", "滨海努瓦耶勒", "唐登空袭",
                                    "青春誓言", "德塞夫勒", "克拉奥讷之歌", "芙萝山德斯", "死去的君王",
                                    "波佐洛", "奧提加拉山", "奧托‧迪克斯", "保罗‧克利", "阿莫斯‧怀德",
                                    "集合点", "法兰兹‧马克", "风暴", "我的机枪", "加利格拉姆", "多贝尔多",
                                    "茨纳河", "莫纳斯提尔", "科巴丁", "德•奇里诃", "若宫丸", "波珀灵厄",
                                    "K连", "玛德蓉", "巨马", "罗曼诺卡夫", "薩利卡米什", "贝利库尔隧道",
                                    "史特拉姆", "阿道戴", "克里夫兰", "家乡套件", "夏日套件", "监禁者",
                                    "罗曼诺夫卡", "阿涅森", "波珀灵厄", "威玛猎犬", "齐格飞防线",
                                    "华盛顿", "泰罗林猎犬", "怪奇之物", "法兰兹‧马克", "风暴"]
                    if SE_list[i][3] == "传奇":
                        if SE_list[i][0] in [270, 300]:
                            draw.text((x, y + 110), f"{SE_list[i][3]}(限定)", (255, 132, 0), font=price_font)
                        elif SE_list[i][1] in XD_skin_list:
                            draw.text((x, y + 110), f"{SE_list[i][3]}(限定)", (255, 132, 0), font=price_font)
                        else:
                            draw.text((x, y + 110), SE_list[i][3], (255, 132, 0), font=price_font)
                        # 打开特效图像
                        tx_png = Image.open('./data/battlefield/pic/tx/1.png').convert('RGBA')
                    elif SE_list[i][1] in XD_skin_list:
                        draw.text((x, y + 110), f"{SE_list[i][3]}(限定)", (255, 132, 0), font=price_font)
                        # 打开特效图像
                        tx_png = Image.open('./data/battlefield/pic/tx/2.png').convert('RGBA')
                    else:
                        draw.text((x, y + 110), SE_list[i][3], (74, 151, 255), font=price_font)
                        # 打开特效图像
                        tx_png = Image.open('./data/battlefield/pic/tx/2.png').convert('RGBA')
                    # 特效图片拉伸
                    tx_png = tx_png.resize((100, 153), Image.ANTIALIAS)
                    # 特效图片拼接
                    bg_img.paste(tx_png, (x + 36, y - 105), tx_png)
                    # 武器图片拉伸
                    SE_png = SE_png.resize((180, 45), Image.ANTIALIAS)
                    # 武器图片拼接
                    bg_img.paste(SE_png, (x, y - 45), SE_png)
                    # 价格
                    draw.text((x + 24, y + 134), str(SE_list[i][0]), (255, 255, 255), font=price_font)
                    x += 228
                    i += 1
                    # bg_img.show()
                y += 298
                x = 59
        bg_img.save(SavePic, 'png', quality=100)
        # 返回bytes
        output_buffer = BytesIO()
        bg_img.save(output_buffer, format='PNG')
        self.img = output_buffer.getvalue()
        return self.img


class PlayerListPic:

    @staticmethod
    async def download_serverMap_pic(url: str) -> Union[str, None]:
        file_name = './data/battlefield/pic/map/' + url[url.rfind('/') + 1:]
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
                            with open(file_name, 'wb') as fp:
                                fp.write(pic)
                            return file_name
                    except Exception as e:
                        logger.error(e)
                        i += 1
            return None

    @staticmethod
    async def get_server_map_pic(map_name: str) -> Union[str, None]:
        file_path = "./data/battlefield/游戏模式/data.json"
        with open(file_path, 'r', encoding="utf-8") as file1:
            data = json.load(file1)["result"]["maps"]
        for item in data:
            if item["assetName"] == map_name:
                try:
                    return await PlayerListPic.download_serverMap_pic(
                        item["images"]["JpgAny"].replace(
                            "[BB_PREFIX]",
                            "https://eaassets-a.akamaihd.net/battlelog/battlebinary",
                        )
                    )
                except Exception:
                    return None

    @staticmethod
    def get_team_pic(team_name: str) -> str:
        team_pic_list = os.listdir("./data/battlefield/pic/team/")
        for item in team_pic_list:
            if team_name in item:
                return f"./data/battlefield/pic/team/{item}"

    @staticmethod
    def get_width(o):
        """Return the screen column width for unicode ordinal o."""
        if o in [0xE, 0xF]:
            return 0
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
        return next((wid for num, wid in widths if o <= num), 1)

    @staticmethod
    async def draw(playerlist_data, server_info, bind_pid_list) -> Union[bytes, None, str]:
        admin_pid_list = [str(item['personaId']) for item in server_info["rspInfo"]["adminList"]]
        admin_counter = 0
        admin_color = (0, 255, 127)
        vip_pid_list = [str(item['personaId']) for item in server_info["rspInfo"]["vipList"]]
        vip_counter = 0
        vip_color = (255, 99, 71)
        bind_color = (179, 244, 255)
        bind_counter = 0
        max_level_counter = 0

        playerlist_data["teams"] = {
            0: [item for item in playerlist_data["players"] if item["team"] == 0],
            1: [item for item in playerlist_data["players"] if item["team"] == 1]
        }
        playerlist_data["teams"][0].sort(key=lambda x: x["rank"], reverse=True)
        playerlist_data["teams"][1].sort(key=lambda x: x["rank"], reverse=True)
        update_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(playerlist_data["time"]))

        # 获取玩家生涯战绩
        # 队伍1
        scrape_index_tasks_t1 = [
            asyncio.ensure_future((await BF1DA.get_api_instance()).detailedStatsByPersonaId(player_item['pid'])) for
            player_item in playerlist_data["teams"][0]]
        tasks = asyncio.gather(*scrape_index_tasks_t1)
        try:
            await tasks
        except asyncio.TimeoutError:
            pass

        # 队伍2
        scrape_index_tasks_t2 = [
            asyncio.ensure_future((await BF1DA.get_api_instance()).detailedStatsByPersonaId(player_item['pid'])) for
            player_item in playerlist_data["teams"][1]]
        tasks = asyncio.gather(*scrape_index_tasks_t2)
        try:
            await tasks
        except asyncio.TimeoutError:
            pass

        # 服务器名
        server_name = server_info["serverInfo"]["name"]
        # MP_xxx
        server_mapName = server_info["serverInfo"]["mapName"]

        team1_name = MapData.MapTeamDict[server_info["serverInfo"]["mapName"]]["Team1"]
        team1_pic = PlayerListPic.get_team_pic(team1_name)
        team1_pic = Image.open(team1_pic).convert('RGBA')
        team1_pic = team1_pic.resize((40, 40), Image.ANTIALIAS)
        team2_name = MapData.MapTeamDict[server_info["serverInfo"]["mapName"]]["Team2"]
        team2_pic = PlayerListPic.get_team_pic(team2_name)
        team2_pic = Image.open(team2_pic).convert('RGBA')
        team2_pic = team2_pic.resize((40, 40), Image.ANTIALIAS)

        # 地图路径
        server_map_pic = await PlayerListPic.get_server_map_pic(server_mapName)
        # 地图作为画布底图并且高斯模糊化
        if server_map_pic is None:
            logger.warning(f"获取地图{server_mapName}图片出错")
            return "网络出错，请稍后再试!"
        IMG = Image.open(server_map_pic)
        # 高斯模糊
        IMG = IMG.filter(ImageFilter.GaussianBlur(radius=12))
        # 调低亮度
        IMG = ImageEnhance.Brightness(IMG).enhance(0.7)
        # 裁剪至1920x1080
        box = (0, 70, 1920, 1150)  # 将要裁剪的图片块距原图左边界距左边距离，上边界距上边距离，右边界距左边距离，下边界距上边的距离。
        IMG = IMG.crop(box)

        # 延迟 5:小于50 4:50< <100 3: 150< < 100 2: 150<  <200 1: 250< <300 0:300+
        Ping1 = Image.open(f"./data/battlefield/pic/ping/4.png").convert('RGBA')
        Ping1 = Ping1.resize((int(Ping1.size[0] * 0.04), int(Ping1.size[1] * 0.04)), Image.ANTIALIAS)
        Ping2 = Image.open(f"./data/battlefield/pic/ping/3.png").convert('RGBA')
        Ping2 = Ping2.resize((int(Ping2.size[0] * 0.04), int(Ping2.size[1] * 0.04)), Image.ANTIALIAS)
        Ping3 = Image.open(f"./data/battlefield/pic/ping/2.png").convert('RGBA')
        Ping3 = Ping3.resize((int(Ping3.size[0] * 0.04), int(Ping3.size[1] * 0.04)), Image.ANTIALIAS)
        Ping4 = Image.open(f"./data/battlefield/pic/ping/1.png").convert('RGBA')
        Ping4 = Ping4.resize((int(Ping4.size[0] * 0.04), int(Ping4.size[1] * 0.04)), Image.ANTIALIAS)
        Ping5 = Image.open(f"./data/battlefield/pic/ping/0.png").convert('RGBA')
        Ping5 = Ping5.resize((int(Ping5.size[0] * 0.04), int(Ping5.size[1] * 0.04)), Image.ANTIALIAS)

        draw = ImageDraw.Draw(IMG)
        # 字体路径
        font_path = './data/battlefield/font/BFText-Regular-SC-19cf572c.ttf'
        title_font = ImageFont.truetype(font_path, 40)
        team_font = ImageFont.truetype(font_path, 25)
        title_font_small = ImageFont.truetype(font_path, 22)
        player_font = ImageFont.truetype(font_path, 20)
        rank_font = ImageFont.truetype(font_path, 15)
        info_font = ImageFont.truetype(font_path, 22)
        # 服务器名字
        draw.text((97, 30), f"服务器名:{server_name}", fill='white', font=title_font)
        # 更新时间
        draw.text((100, 80), update_time, fill="white", font=rank_font)
        max_level_color = (255, 132, 0)

        KD_counter1 = 0
        KPM_counter1 = 0
        RANK_counter1 = 0
        TIME_counter1 = 0
        WIN_counter1 = 0
        # 队伍1
        # 队伍1图片
        IMG.paste(team1_pic, (100, 101))
        # 队伍1名
        draw.text((152, 105), team1_name, fill='white', font=team_font)
        draw.text((520, 113), f"胜率", fill='white', font=title_font_small)
        draw.text((600, 113), f"K/D", fill='white', font=title_font_small)
        draw.text((670, 113), f"KPM", fill='white', font=title_font_small)
        draw.text((750, 113), f"时长(h)", fill='white', font=title_font_small)
        draw.text((840, 113), f"延迟", fill='white', font=title_font_small)
        draw.text((900, 113), f"语言", fill='white', font=title_font_small)
        # 队伍1横线
        draw.line([100, 141, 950, 141], fill=(114, 114, 114), width=2, joint=None)
        # 队伍1竖线
        draw.line([100, 155, 100, 915], fill=(114, 114, 114), width=2, joint=None)
        leve_position_1 = None
        for i, player_item in enumerate(playerlist_data["teams"][0]):
            # 序号
            draw.text((135, 156 + i * 23), f"{i + 1}", anchor="ra", fill='white', font=player_font)

            # 等级框 30*15  等级 居中显示
            draw.rectangle([155, 159 + i * 23, 185, 173.5 + i * 23],
                           fill=max_level_color if player_item['rank'] == 150 else None, outline=None, width=1)
            RANK_counter1 += player_item['rank']
            if player_item['rank'] == 150:
                max_level_counter += 1
            rank_font_temp = ImageFont.truetype(font_path, 15)
            ascent, descent = rank_font_temp.getsize(f"{player_item['rank']}")
            leve_position_1 = 170 - ascent / 2, 165.5 + i * 23 - descent / 2
            draw.text(leve_position_1, f"{player_item['rank']}",
                      fill="white",
                      font=rank_font)
            # 战队 名字
            color_temp = 'white'
            if str(player_item["display_name"]).upper() in bind_pid_list:
                color_temp = bind_color
                bind_counter += 1
            if str(player_item["pid"]) in vip_pid_list:
                color_temp = vip_color
                vip_counter += 1
            if str(player_item["pid"]) in admin_pid_list:
                color_temp = admin_color
                admin_counter += 1
            if player_item["platoon"]:
                draw.text(
                    (195, 155 + i * 23), f"[{player_item['platoon']['tag']}]{player_item['display_name']}",
                    fill=color_temp,
                    font=player_font
                )
            else:
                draw.text((195, 155 + i * 23), player_item["display_name"], fill=color_temp, font=player_font)

            # 延迟 靠右显示
            ping_pic = Ping5
            if player_item['latency'] <= 50:
                ping_pic = Ping1
            elif 50 < player_item['latency'] <= 100:
                ping_pic = Ping2
            elif 100 < player_item['latency'] <= 150:
                ping_pic = Ping3
            elif 150 < player_item['latency']:
                ping_pic = Ping4
            IMG.paste(ping_pic, (830, 158 + i * 23), ping_pic)
            draw.text((880, 155 + i * 23), f"{player_item['latency']}", anchor="ra", fill='white', font=player_font)

            # 语言
            draw.text((940, 155 + i * 23), f"{player_item['language']}", anchor="ra", fill='white', font=player_font)

            # KD KPM 时长
            try:
                player_stat_data = scrape_index_tasks_t1[i].result()["result"]
                # 胜率
                win_p = int(player_stat_data['basicStats']['wins'] / (
                        player_stat_data['basicStats']['losses'] + player_stat_data['basicStats']['wins']) * 100)
                WIN_counter1 += win_p
                draw.text((565, 155 + i * 23), f'{win_p}%', anchor="ra",
                          fill=max_level_color if win_p >= 70 else 'white',
                          font=player_font)
                # kd
                kd = player_stat_data['kdr']
                KD_counter1 += kd
                draw.text((635, 155 + i * 23), f'{kd}', anchor="ra", fill=max_level_color if kd >= 3 else 'white',
                          font=player_font)
                # kpm
                kpm = player_stat_data['basicStats']["kpm"]
                KPM_counter1 += kpm
                draw.text((710, 155 + i * 23), f'{kpm}', fill=max_level_color if kpm >= 2 else 'white', anchor="ra",
                          font=player_font)
                # 时长
                time_played = "{:.1f}".format(player_stat_data['basicStats']["timePlayed"] / 3600)
                TIME_counter1 += float(time_played)
                draw.text((810, 155 + i * 23), f"{time_played}", anchor="ra",
                          fill=max_level_color if float(time_played) >= 1000 else 'white',
                          font=player_font)
            except:
                pass

        # x相差860

        KD_counter2 = 0
        KPM_counter2 = 0
        RANK_counter2 = 0
        TIME_counter2 = 0
        WIN_counter2 = 0
        # 队伍2
        # 队伍2图片
        IMG.paste(team2_pic, (960, 101))
        # 队伍2名
        draw.text((1012, 105), team2_name, fill='white', font=team_font)
        draw.text((1380, 113), f"胜率", fill='white', font=title_font_small)
        draw.text((1460, 113), f"K/D", fill='white', font=title_font_small)
        draw.text((1530, 113), f"KPM", fill='white', font=title_font_small)
        draw.text((1610, 113), f"时长(h)", fill='white', font=title_font_small)
        draw.text((1700, 113), f"延迟", fill='white', font=title_font_small)
        draw.text((1760, 113), f"语言", fill='white', font=title_font_small)
        # 队伍2横线
        draw.line([960, 141, 1810, 141], fill=(114, 114, 114), width=2, joint=None)
        # 队伍2竖线
        draw.line([960, 155, 960, 915], fill=(114, 114, 114), width=2, joint=None)
        leve_position_2 = None
        for i, player_item in enumerate(playerlist_data["teams"][1]):
            # 序号
            draw.text((995, 156 + i * 23), f"{int(i + 1 + server_info['serverInfo']['slots']['Soldier']['max'] / 2)}",
                      anchor="ra", fill='white', font=player_font)
            # 等级框 30*15 等级居中显示
            draw.rectangle([1015, 159 + i * 23, 1045, 173.5 + i * 23],
                           fill=max_level_color if player_item['rank'] == 150 else None, outline=None, width=1)
            RANK_counter2 += player_item['rank']
            if player_item['rank'] == 150:
                max_level_counter += 1
            rank_font_temp = ImageFont.truetype(font_path, 15)
            ascent, descent = rank_font_temp.getsize(f"{player_item['rank']}")
            leve_position_2 = 1030 - ascent / 2, 165.5 + i * 23 - descent / 2
            draw.text(
                leve_position_2, f"{player_item['rank']}",
                fill="white",
                font=rank_font
            )
            # 战队 名字
            color_temp = 'white'
            if str(player_item["display_name"]).upper() in bind_pid_list:
                color_temp = bind_color
                bind_counter += 1
            if str(player_item["pid"]) in vip_pid_list:
                color_temp = vip_color
                vip_counter += 1
            if str(player_item["pid"]) in admin_pid_list:
                color_temp = admin_color
                admin_counter += 1
            if player_item["platoon"]:
                draw.text(
                    (1055, 155 + i * 23), f"[{player_item['platoon']['tag']}]{player_item['display_name']}",
                    fill=color_temp,
                    font=player_font
                )
            else:
                draw.text((1055, 155 + i * 23), player_item["display_name"], fill=color_temp, font=player_font)
            # 延迟 靠右显示
            ping_pic = Ping5
            if player_item['latency'] <= 50:
                ping_pic = Ping1
            elif 50 < player_item['latency'] <= 100:
                ping_pic = Ping2
            elif 100 < player_item['latency'] <= 150:
                ping_pic = Ping3
            elif 150 < player_item['latency']:
                ping_pic = Ping4
            IMG.paste(ping_pic, (1690, 158 + i * 23), ping_pic)
            draw.text((1740, 155 + i * 23), f"{player_item['latency']}", anchor="ra", fill='white', font=player_font)

            # 语言
            draw.text((1800, 155 + i * 23), f"{player_item['language']}", anchor="ra", fill='white', font=player_font)
            # 生涯数据
            try:
                player_stat_data = scrape_index_tasks_t2[i].result()["result"]
                # 胜率
                win_p = int(player_stat_data['basicStats']['wins'] / (
                        player_stat_data['basicStats']['losses'] + player_stat_data['basicStats']['wins']) * 100)
                WIN_counter2 += win_p
                draw.text((1425, 155 + i * 23), f'{win_p}%', anchor="ra",
                          fill=max_level_color if win_p >= 70 else 'white',
                          font=player_font)
                # kd
                kd = player_stat_data['kdr']
                KD_counter2 += kd
                draw.text((1495, 155 + i * 23), f'{kd}', anchor="ra", fill=max_level_color if kd >= 3 else 'white',
                          font=player_font)
                # kpm
                kpm = player_stat_data['basicStats']["kpm"]
                KPM_counter2 += kpm
                draw.text((1570, 155 + i * 23), f'{kpm}', fill=max_level_color if kpm >= 2 else 'white', anchor="ra",
                          font=player_font)
                # 时长
                time_played = "{:.1f}".format(player_stat_data['basicStats']["timePlayed"] / 3600)
                TIME_counter2 += float(time_played)
                draw.text((1670, 155 + i * 23), f"{time_played}", anchor="ra",
                          fill=max_level_color if float(time_played) >= 1000 else 'white',
                          font=player_font)
            except:
                pass

        i_temp = len(playerlist_data['teams'][0]) if len(playerlist_data['teams'][0]) >= len(
            playerlist_data['teams'][1]) else len(playerlist_data['teams'][1])
        avg_color = (250, 183, 39)
        avg_1_1 = 0
        avg_1_2 = 0
        avg_1_3 = 0
        avg_1_4 = 0
        avg_1_5 = 0
        if len(playerlist_data['teams'][0]) != 0:
            avg_1_1 = int(RANK_counter1 / len(playerlist_data['teams'][0]))
            avg_1_2 = KD_counter1 / len(playerlist_data['teams'][0])
            avg_1_3 = KPM_counter1 / len(playerlist_data['teams'][0])
            avg_1_4 = TIME_counter1 / len(playerlist_data['teams'][0])
            avg_1_5 = int(WIN_counter1 / len(playerlist_data['teams'][0]))
        avg_2_1 = 0
        avg_2_2 = 0
        avg_2_3 = 0
        avg_2_4 = 0
        avg_2_5 = 0
        if len(playerlist_data['teams'][1]) != 0:
            avg_2_1 = int(RANK_counter2 / len(playerlist_data['teams'][1]))
            avg_2_2 = KD_counter2 / len(playerlist_data['teams'][1])
            avg_2_3 = KPM_counter2 / len(playerlist_data['teams'][1])
            avg_2_4 = TIME_counter2 / len(playerlist_data['teams'][1])
            avg_2_5 = int(WIN_counter2 / len(playerlist_data['teams'][1]))

        if leve_position_1:
            rank_font_temp = ImageFont.truetype(font_path, 15)
            ascent, descent = rank_font_temp.getsize(f"{int(RANK_counter1 / len(playerlist_data['teams'][0]))}")
            leve_position_1 = 168 - ascent / 2, 156 + i_temp * 23
            draw.text((115, 156 + i_temp * 23), f"平均:",
                      fill="white",
                      font=player_font)
            if RANK_counter1 != 0:
                draw.text(leve_position_1, f"{int(RANK_counter1 / len(playerlist_data['teams'][0]))}",
                          fill=avg_color if avg_1_1 > avg_2_1 else "white",
                          font=player_font)
            if WIN_counter1 != 0:
                draw.text((565, 156 + i_temp * 23), f"{int(WIN_counter1 / len(playerlist_data['teams'][0]))}%",
                          anchor="ra",
                          fill=avg_color if avg_1_5 > avg_2_5 else "white",
                          font=player_font)
            if KD_counter1 != 0:
                draw.text((635, 156 + i_temp * 23),
                          "{:.2f}".format(KD_counter1 / len(playerlist_data['teams'][0])),
                          anchor="ra",
                          fill=avg_color if avg_1_2 > avg_2_2 else "white",
                          font=player_font)
            if KPM_counter1 != 0:
                draw.text((710, 156 + i_temp * 23),
                          "{:.2f}".format(KPM_counter1 / len(playerlist_data['teams'][0])),
                          anchor="ra",
                          fill=avg_color if avg_1_3 > avg_2_3 else "white",
                          font=player_font)
            if TIME_counter1 != 0:
                draw.text((810, 156 + i_temp * 23),
                          "{:.1f}".format(TIME_counter1 / len(playerlist_data['teams'][0])),
                          anchor="ra",
                          fill=avg_color if avg_1_4 > avg_2_4 else "white",
                          font=player_font)

        if leve_position_2:
            rank_font_temp = ImageFont.truetype(font_path, 15)
            ascent, descent = rank_font_temp.getsize(f"{int(RANK_counter1 / len(playerlist_data['teams'][1]))}")
            leve_position_2 = 1028 - ascent / 2, 156 + i_temp * 23
            draw.text((975, 156 + i_temp * 23), f"平均:",
                      fill="white",
                      font=player_font)
            if RANK_counter2 != 0:
                draw.text(leve_position_2, f"{int(RANK_counter2 / len(playerlist_data['teams'][1]))}",
                          fill=avg_color if avg_1_1 < avg_2_1 else "white",
                          font=player_font)
            if WIN_counter2 != 0:
                draw.text((1425, 156 + i_temp * 23), f"{int(WIN_counter2 / len(playerlist_data['teams'][1]))}%",
                          anchor="ra",
                          fill=avg_color if avg_1_5 < avg_2_5 else "white",
                          font=player_font)
            if KD_counter2 != 0:
                draw.text((1495, 156 + i_temp * 23),
                          "{:.2f}".format(KD_counter2 / len(playerlist_data['teams'][1])),
                          anchor="ra",
                          fill=avg_color if avg_1_2 < avg_2_2 else "white",
                          font=player_font)
            if KPM_counter2 != 0:
                draw.text((1570, 156 + i_temp * 23),
                          "{:.2f}".format(KPM_counter2 / len(playerlist_data['teams'][1])),
                          anchor="ra",
                          fill=avg_color if avg_1_3 < avg_2_3 else "white",
                          font=player_font)
            if TIME_counter2 != 0:
                draw.text((1670, 156 + i_temp * 23),
                          "{:.1f}".format(TIME_counter2 / len(playerlist_data['teams'][1])),
                          anchor="ra",
                          fill=avg_color if avg_1_4 < avg_2_4 else "white",
                          font=player_font)

        # 服务器信息
        server_info_text = f'服务器状态:{server_info["serverInfo"]["mapModePretty"]}-{server_info["serverInfo"]["mapNamePretty"]}  ' \
                           f'在线人数:{server_info["serverInfo"]["slots"]["Soldier"]["current"]}/{server_info["serverInfo"]["slots"]["Soldier"]["max"]}' \
                           f'[{server_info["serverInfo"]["slots"]["Queue"]["current"]}]({server_info["serverInfo"]["slots"]["Spectator"]["current"]})  ' \
                           f"收藏:{server_info['serverInfo']['serverBookmarkCount']}"

        draw.text((240, 925), server_info_text, fill="white", font=info_font)

        # 服务器简介
        server_dscr = f'        {server_info["serverInfo"]["description"]}'
        test_temp = ""
        i = 0
        for letter in server_dscr:
            if i * 11 % 125 == 0 or (i + 1) * 11 % 125 == 0:
                test_temp += '\n'
                i = 0
            i += PlayerListPic.get_width(ord(letter))
            test_temp += letter
        draw.text((240, 955), f"服务器简介:{test_temp}", fill="white", font=info_font)

        # 颜色标识
        # 管理
        draw.rectangle([1100, 925, 1120, 945], fill=admin_color, outline=None, width=1)
        draw.text((1130, 925), f"在线管理:{admin_counter}", fill="white", font=player_font)
        # vip
        draw.rectangle([1250, 925, 1270, 945], fill=vip_color, outline=None, width=1)
        draw.text((1280, 925), f"在线VIP:{vip_counter}", fill="white", font=player_font)
        # 群友
        draw.rectangle([1400, 925, 1420, 945], fill=bind_color, outline=None, width=1)
        draw.text((1430, 925), f"在线群友:{bind_counter}", fill="white", font=player_font)
        # 150数量
        draw.rectangle([1550, 925, 1570, 945], fill=max_level_color, outline=None, width=1)
        draw.text((1580, 925), f"150数量:{max_level_counter}", fill="white", font=player_font)

        # 水印
        draw.text((1860, 1060), f"by.13", fill=(114, 114, 114), font=player_font)

        # IMG.show()
        # SavePic = f"./data/battlefield/Temp/{round(time.time())}.jpg"
        # IMG.save(SavePic, quality=100)
        # 直接IO流发送
        img_bytes = io.BytesIO()
        IMG.save(img_bytes, format='PNG')
        return img_bytes.getvalue()


class Bf1Status:

    def __init__(self, private_server_data, official_server_data):
        self.private_server_data = private_server_data
        self.official_server_data = official_server_data

    def generate_comparison_charts(self) -> bytes:
        private_server_data = self.private_server_data
        official_server_data = self.official_server_data
        sns.set_style("whitegrid")
        from pylab import mpl
        mpl.rcParams["font.sans-serif"] = ["SimHei"]

        def plot_comparison_bar_chart_sns(data, title, rotation=0):
            official_color = "#9ebc62"
            private_color = "#e68d63"
            df = pd.DataFrame(data)
            ax = df.plot(kind='bar', figsize=(12, 6), color=[official_color, private_color])
            plt.title(title)
            plt.ylabel('数量')
            plt.xticks(rotation=rotation)
            for p in ax.patches:
                ax.annotate(str(int(p.get_height())), (p.get_x() + p.get_width() / 2., p.get_height()),
                            ha='center', va='center', xytext=(0, 10), textcoords='offset points')
            plt.tight_layout()

            buffer_temp = io.BytesIO()
            plt.savefig(buffer_temp, format='png', bbox_inches='tight')
            plt.close()

            return Image.open(buffer_temp)

        region_country_comparison_data = {
            "官服": {
                "服务器数量": len(official_server_data["regions"]),
            },
            "私服": {
                "服务器数量": len(private_server_data["regions"]),
            }
        }

        for region in set(
                list(official_server_data["regions"].keys()) + list(private_server_data["regions"].keys())):
            region_country_comparison_data["官服"][region] = official_server_data["regions"].get(region, 0)
            region_country_comparison_data["私服"][region] = private_server_data["regions"].get(region, 0)

        plot1 = plot_comparison_bar_chart_sns(
            region_country_comparison_data,
            f"开启服务器数：{sum(region_country_comparison_data['官服'].values()) + sum(region_country_comparison_data['私服'].values())}\n"
            f"私服：{sum(region_country_comparison_data['私服'].values())} / 官服：{sum(region_country_comparison_data['官服'].values())}"
        )

        plot2 = plot_comparison_bar_chart_sns(
            {"官服": official_server_data["countries"], "私服": private_server_data["countries"]}, "")

        plot3 = plot_comparison_bar_chart_sns(
            {"官服": official_server_data["maps"], "私服": private_server_data["maps"]},
            "游玩地图", rotation=45)

        plot4 = plot_comparison_bar_chart_sns(
            {"官服": official_server_data["modes"], "私服": private_server_data["modes"]},
            "游玩模式")

        # Pie chart for total players comparison
        total_players_data = {
            '官服': official_server_data["players"],
            '私服': private_server_data["players"]
        }
        plt.figure(figsize=(8, 8))
        plt.pie(total_players_data.values(), labels=total_players_data.keys(), autopct='%1.0f%%', startangle=90,
                colors=sns.color_palette("coolwarm"))
        plt.title(
            f"BF1当前游玩总人数：{sum(total_players_data.values())}\n{datetime.datetime.now().strftime('%Y年%m月%d日 %H:%M:%S')}")
        plt.axis('equal')
        buf_pie = io.BytesIO()
        plt.savefig(buf_pie, format='png', bbox_inches='tight', transparent=True)
        plt.close()
        plot5 = Image.open(buf_pie)

        # 合成为一张图片
        merged_image = Image.new('RGB', (plot1.width, plot1.height * 4 + plot5.height), (255, 255, 255))
        merged_image.paste(plot5, (int((plot1.width - plot5.width) / 2), 0), plot5)
        merged_image.paste(plot1, (0, plot5.height))
        merged_image.paste(plot2, (0, plot5.height + plot1.height))
        merged_image.paste(plot3, (0, plot5.height + plot1.height * 2))
        merged_image.paste(plot4, (0, plot5.height + plot1.height * 3))

        buf = io.BytesIO()
        merged_image.save(buf, format='PNG')
        data_bytes = buf.getvalue()

        return data_bytes
