import asyncio
import datetime
import io
import json
import os
import random
import time
from io import BytesIO
from pathlib import Path
from typing import Union, Tuple

import aiohttp
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns
from PIL import Image, ImageFont, ImageDraw, ImageFilter, ImageEnhance
from loguru import logger
from zhconv import zhconv

from utils.bf1.bf_utils import download_skin
from utils.bf1.data_handle import VehicleData, WeaponData
from utils.bf1.default_account import BF1DA
from utils.bf1.draw.choose_bg_pic import bg_pic
from utils.bf1.map_team_info import MapData

BB_PREFIX = "https://eaassets-a.akamaihd.net/battlelog/battlebinary"
# 整图大小
StatImageWidth = 2000
StatImageHeight = 1550
# 图片临时存放根目录
FileTempSaveRoot = Path("./data/battlefield/Temp/")
# 背景图片根目录
BackgroundPathRoot = Path("./data/battlefield/pic/background/")
DefaultBackgroundPath = Path(__file__).parent / "template" / "background"
# 头像根目录
AvatarPathRoot = Path("./data/battlefield/pic/avatar/")
# 默认头像
DefaultAvatarImg = (AvatarPathRoot / "default_bot_avatar.jpg").open("rb").read()
# 皮肤文件映射目录
SkinAllPathRoot = Path("./utils/bf1/src/skin_all.json")
# 兵种
AssaultImg = Path("./data/battlefield/pic/src/soldiers/assault.png").open("rb").read()
CavalryImg = Path("./data/battlefield/pic/src/soldiers/cavalry.png").open("rb").read()
MedicImg = Path("./data/battlefield/pic/src/soldiers/medic.png").open("rb").read()
PilotImg = Path("./data/battlefield/pic/src/soldiers/pilot.png").open("rb").read()
ScoutImg = Path("./data/battlefield/pic/src/soldiers/scout.png").open("rb").read()
SupportImg = Path("./data/battlefield/pic/src/soldiers/support.png").open("rb").read()
TankerImg = Path("./data/battlefield/pic/src/soldiers/tanker.png").open("rb").read()
# 头像框模板
AvatarOnlineImg = Path("./data/battlefield/pic/src/template/avatar2.png").open("rb").read()
AvatarOfflineImg = Path("./data/battlefield/pic/src/template/avatar1.png").open("rb").read()
# 封禁框模板
BanImg = Path("./data/battlefield/pic/src/template/ban.png").open("rb").read()
# 战队框模板
PlatoonImg = Path("./data/battlefield/pic/src/template/platoon.png").open("rb").read()
PlatoonImgNone = Path("./data/battlefield/pic/src/template/platoon_none.png").open("rb").read()
# 战绩信息框模板
StatImg = Path("./data/battlefield/pic/src/template/stat.png").open("rb").read()
# 武器/载具框模板
SkinRootPath = Path("./data/battlefield/pic/skins/")
WeaponGoldImg = Path("./data/battlefield/pic/src/template/weapon_gold.png").open("rb").read()
WeaponBlueImg = Path("./data/battlefield/pic/src/template/weapon_blue.png").open("rb").read()
WeaponWhiteImg = Path("./data/battlefield/pic/src/template/weapon_white.png").open("rb").read()
BlackTrapezoidImg = Path("./data/battlefield/pic/src/template/black_trapezoid.png").open("rb").read()
# 字体
FontRootPath = Path("./data/battlefield/font/")
GlobalFontPath = FontRootPath / "BFText-Regular-SC-19cf572c.ttf"
# 普通字体大小
NormalFontSize = 30
StatFontSize = 25
SkinFontSize = 20
# 颜色
ColorGold = (202, 132, 58)
ColorBlue = (30, 144, 255)
ColorWhite = (255, 255, 255)
ColorRed = (255, 0, 0)
ColorGoldAndGray = (236, 217, 150)
ColorBlueAndGray = (191, 207, 222)
ColorWhiteAndGray = (255, 255, 255, 150)


class PilImageUtils:
    @staticmethod
    def draw_centered_text(
            draw: ImageDraw.Draw, text: str,
            center: Tuple[int, int],
            font: ImageFont.FreeTypeFont,
            fill: Tuple[int, int, int]
    ) -> None:
        """
        在图像上居中绘制文本。对于给定的坐标x, y，文本将以x, y为轴心水平居中绘制。

        :param draw: PIL.ImageDraw 实例，用于在图像上绘制。
        :param text: 要绘制的文本字符串。
        :param center: 文本的中心点坐标，格式为 (x, y)。
        :param font: PIL.ImageFont 实例，定义了绘制文本的字体。
        :param fill: 文本颜色，格式为 (R, G, B)。
        """
        # 计算文本边界框的大小
        text_bbox = draw.textbbox((0, 0), text, font=font)
        text_width = text_bbox[2] - text_bbox[0]
        text_height = text_bbox[3] - text_bbox[1]
        # 计算文本绘制的起始坐标，使文本以 center 为中心
        text_x = center[0] - text_width / 2
        text_y = center[1] - text_height / 2
        # 在图像上绘制文本
        draw.text((text_x, text_y), text, font=font, fill=fill)

    @staticmethod
    def draw_multiline_text(
            draw: ImageDraw.Draw,
            text: str, position: Tuple[int, int],
            font: ImageFont.FreeTypeFont,
            fill: Tuple[int, int, int],
            max_width: int
    ):
        """
        在图像上绘制多行文本，支持中英文混排，在文本宽度超过max_width时自动换行。

        :param draw: PIL.ImageDraw 实例，用于在图像上绘制。
        :param text: 要绘制的文本字符串。
        :param position: 文本绘制的起始坐标 (x, y)。
        :param font: PIL.ImageFont 实例，定义了绘制文本的字体。
        :param fill: 文本颜色，格式为 (R, G, B)。
        :param max_width: 文本换行的最大宽度。
        """
        x, y = position
        line = ''
        for word in text:
            # 单字加入当前行后检测宽度
            test_line = line + word
            width = draw.textbbox((0, 0), test_line, font=font)[2]
            if width <= max_width:
                line += word
            else:
                # 绘制当前行并准备新的一行
                draw.text((x, y), line, font=font, fill=fill)
                y += draw.textbbox((x, y), line, font=font)[3] - draw.textbbox((x, y), line, font=font)[1]
                line = word
        # 绘制最后一行
        if line:
            draw.text((x, y), line, font=font, fill=fill)

    @staticmethod
    def crop_circle(image_input: Union[Image.Image, bytes], radius: int) -> Image:
        """
        将传入的图片，根据指定的半径裁剪为圆形。
        :param image_input: PIL.Image 对象
        :param radius: 圆的半径
        :return: PIL.Image 对象
        """

        # 检查输入类型并加载图片
        if isinstance(image_input, bytes):
            image_input = Image.open(BytesIO(image_input))
        elif isinstance(image_input, Image.Image):
            image_input = image_input
        else:
            raise TypeError("image_input must be a PIL.Image.Image object or bytes")

        # 将图片调整为2*radius大小
        image_input = image_input.resize((2 * radius, 2 * radius), Image.LANCZOS)

        # 创建一个遮罩用于裁剪
        mask = Image.new('L', (2 * radius, 2 * radius), 0)
        draw = ImageDraw.Draw(mask)
        draw.ellipse((0, 0, 2 * radius, 2 * radius), fill=255)

        # 应用遮罩裁剪图片
        result = Image.new('RGBA', (2 * radius, 2 * radius))
        result.paste(image_input, (0, 0), mask)
        return result

    @staticmethod
    def resize_and_crop_to_center(
            image_input: Union[Image.Image, bytes],
            target_width: int,
            target_height: int
    ) -> Image:
        """
        将图片调整为指定宽高，并且居中裁剪。

        此函数接受图片对象或图片的二进制数据，先对图片进行缩放，确保图片缩放后的宽度和高度包含目标尺寸，
        然后从缩放后的图片中心裁剪出目标尺寸的图片。

        参数:
        image_input (Image.Image | bytes): 原始图片对象或图片的二进制数据。
        target_width (int): 目标宽度。
        target_height (int): 目标高度。

        返回值:
        Image: 调整和裁剪后的图片对象。

        用法示例:
        # 如果是从文件中读取图片，使用以下方式：
        with open('图片路径', 'rb') as image_file:
            image_data = image_file.read()
            new_image = resize_and_crop_to_center(image_data, 2000, 1550)
            new_image.show()  # 展示图片

        # 如果已经有一个Image对象，直接传入：
        image_obj = Image.open('图片路径').convert("RGBA")
        new_image = resize_and_crop_to_center(image_obj, 2000, 1550)
        new_image.show()  # 展示图片
        """

        # 检查输入类型并加载图片
        if isinstance(image_input, bytes):
            image = Image.open(BytesIO(image_input)).convert("RGBA")
        elif isinstance(image_input, Image.Image):
            image = image_input
        else:
            raise TypeError("image_input must be a PIL.Image.Image object or bytes")

        # 计算缩放比例
        original_width, original_height = image.size
        resize_ratio = max(target_width / original_width, target_height / original_height)

        # 根据缩放比例调整图片尺寸
        new_dimensions = (
            int(original_width * resize_ratio),
            int(original_height * resize_ratio)
        )
        resized_image = image.resize(new_dimensions, Image.LANCZOS)

        # 计算裁剪区域
        crop_left = (resized_image.width - target_width) / 2
        crop_top = (resized_image.height - target_height) / 2
        crop_right = (resized_image.width + target_width) / 2
        crop_bottom = (resized_image.height + target_height) / 2

        # 裁剪图片至指定尺寸
        cropped_image = resized_image.crop((crop_left, crop_top, crop_right, crop_bottom))

        return cropped_image

    # 适应最长边
    @staticmethod
    def scale_image_to_dimension(
            image_input: Union[Image.Image, bytes],
            target_width: int,
            target_height: int
    ) -> Image:
        """
        根据提供的目标尺寸缩放图像。会将图形最长边缩放至目标尺寸，另一边按比例缩放，保证图像内容全部被包含。

        :param image_input: PIL.Image.Image 对象或图片的二进制数据。
        :param target_width: 目标宽度。
        :param target_height: 目标高度。
        :return: 调整后的图片对象。
        """

        # 检查输入类型并加载图片
        if isinstance(image_input, bytes):
            image = Image.open(BytesIO(image_input))
        elif isinstance(image_input, Image.Image):
            image = image_input
        else:
            raise TypeError("image_input must be a PIL.Image.Image object or bytes")

        original_width, original_height = image.size

        # 宽度和高度的缩放比例
        width_ratio = target_width / original_width
        height_ratio = target_height / original_height

        # 选择较小的缩放比例以保持图像全部内容
        scale_ratio = min(width_ratio, height_ratio)

        # 计算新尺寸
        new_width = int(original_width * scale_ratio)
        new_height = int(original_height * scale_ratio)

        # 缩放图像
        scaled_image = image.resize((new_width, new_height), Image.LANCZOS)

        return scaled_image

    @staticmethod
    def paste_center(
            background_img: Union[Image.Image, bytes],
            overlay_img: Union[Image.Image, bytes]
    ) -> Image.Image:
        """
        将一个图像居中粘贴到另一个图像上。

        :param background_img: 背景图像，将作为基底。
        :param overlay_img: 覆盖图像，将被居中粘贴到背景上。
        :return: 合成后的图像。
        """
        # 检查输入类型并加载图片
        if isinstance(background_img, bytes):
            background_img = Image.open(BytesIO(background_img))
        elif isinstance(background_img, Image.Image):
            background_img = background_img
        else:
            raise TypeError("background_img must be a PIL.Image.Image object or bytes")

        if isinstance(overlay_img, bytes):
            overlay_img = Image.open(BytesIO(overlay_img))
        elif isinstance(overlay_img, Image.Image):
            overlay_img = overlay_img
        else:
            raise TypeError("overlay_img must be a PIL.Image.Image object or bytes")

        # 背景图像的尺寸
        bg_width, bg_height = background_img.size

        # 覆盖图像的尺寸
        overlay_width, overlay_height = overlay_img.size

        # 计算粘贴的起始位置
        x = (bg_width - overlay_width) // 2
        y = (bg_height - overlay_height) // 2

        # 创建一个复制的背景图像以避免修改原图
        new_img = background_img.copy()
        overlay_img = overlay_img.convert("RGBA")

        # 将覆盖图像居中粘贴到背景图像上
        new_img.paste(overlay_img, (x, y), overlay_img)

        return new_img

    @staticmethod
    async def read_img_by_url(url: str) -> Union[bytes, None]:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        img = await resp.read()
                        return img
                    else:
                        logger.warning(f"读取图片失败，url: {url}")
                        return None
        except TimeoutError:
            logger.warning(f"读取图片失败，url: {url}")
            return None


class PlayerStatPic:
    def __init__(
            self,
            player_name: str,
            player_pid: Union[str, int],
            personas: dict,
            stat: dict,
            weapons: dict,
            vehicles: dict,
            bfeac_info: dict,
            bfban_info: dict,
            server_playing_info: dict,
            platoon_info: dict,
            skin_info: dict,
            gt_id_info: Union[dict, None]
    ):
        self.player_name = player_name
        self.player_pid = str(player_pid)
        self.personas = personas
        self.stat = stat
        self.weapons = weapons
        self.vehicles = vehicles
        self.bfeac_info = bfeac_info
        self.bfban_info = bfban_info
        self.server_playing_info = server_playing_info
        self.platoon_info = platoon_info
        self.skin_info = skin_info
        self.gt_id_info = gt_id_info
        self.player_background_path = bg_pic.choose_bg(self.player_pid)

        # 玩家数据
        player_info = self.stat["result"]
        rank = player_info.get('basicStats').get('rank')
        rank_list = [
            0, 1000, 5000, 15000, 25000, 40000, 55000, 75000, 95000, 120000, 145000, 175000, 205000, 235000,
            265000, 295000, 325000, 355000, 395000, 435000, 475000, 515000, 555000, 595000, 635000, 675000, 715000,
            755000, 795000, 845000, 895000, 945000, 995000, 1045000, 1095000, 1145000, 1195000, 1245000, 1295000,
            1345000, 1405000, 1465000, 1525000, 1585000, 1645000, 1705000, 1765000, 1825000, 1885000, 1945000,
            2015000, 2085000, 2155000, 2225000, 2295000, 2365000, 2435000, 2505000, 2575000, 2645000, 2745000,
            2845000, 2945000, 3045000, 3145000, 3245000, 3345000, 3445000, 3545000, 3645000, 3750000, 3870000,
            4000000, 4140000, 4290000, 4450000, 4630000, 4830000, 5040000, 5260000, 5510000, 5780000, 6070000,
            6390000, 6730000, 7110000, 7510000, 7960000, 8430000, 8960000, 9520000, 10130000, 10800000, 11530000,
            12310000, 13170000, 14090000, 15100000, 16190000, 17380000, 20000000, 20500000, 21000000, 21500000,
            22000000, 22500000, 23000000, 23500000, 24000000, 24500000, 25000000, 25500000, 26000000, 26500000,
            27000000, 27500000, 28000000, 28500000, 29000000, 29500000, 30000000, 30500000, 31000000, 31500000,
            32000000, 32500000, 33000000, 33500000, 34000000, 34500000, 35000000, 35500000, 36000000, 36500000,
            37000000, 37500000, 38000000, 38500000, 39000000, 39500000, 40000000, 41000000, 42000000, 43000000,
            44000000, 45000000, 46000000, 47000000, 48000000, 49000000, 50000000
        ]
        # 转换成xx小时xx分钟
        time_seconds = player_info.get('basicStats').get('timePlayed')
        if time_seconds < 3600:
            self.time_played = f"{round(time_seconds // 60)}分钟"
        else:
            self.time_played = f"{round(time_seconds // 3600)}小时{round(time_seconds % 3600 // 60)}分钟"
        kills = player_info.get('basicStats').get('kills')
        self.kills = kills
        deaths = player_info.get('basicStats').get('deaths')
        self.deaths = deaths
        kd = round(kills / deaths, 2) if deaths else kills
        self.kd = kd
        wins = player_info.get('basicStats').get('wins')
        self.wins = wins
        losses = player_info.get('basicStats').get('losses')
        self.losses = losses
        # 百分制
        win_rate = round(wins / (wins + losses) * 100, 2) if wins + losses else 100
        self.win_rate = win_rate
        kpm = player_info.get('basicStats').get('kpm')
        self.kpm = kpm
        spm = player_info.get('basicStats').get('spm')
        self.spm = spm
        # 用spm / 60 * 游玩时间 得出经验值exp,看exp在哪个区间,可确定整数等级
        exp = spm * time_seconds / 60
        rank = 0
        for i in range(len(rank_list)):
            if exp <= rank_list[1]:
                rank = 0
                break
            if exp >= rank_list[-1]:
                rank = 150
                break
            if exp <= rank_list[i]:
                rank = i - 1
                break
        self.rank = rank
        vehicle_kill = sum(item["killsAs"] for item in player_info["vehicleStats"])
        vehicle_kill = int(vehicle_kill)
        self.vehicle_kill = vehicle_kill
        infantry_kill = int(player_info['basicStats']['kills'] - vehicle_kill)
        self.infantry_kill = infantry_kill
        skill = player_info.get('basicStats').get('skill')
        self.skill = skill
        longest_headshot = player_info.get('longestHeadShot')
        self.longest_headshot = longest_headshot
        killAssists = int(player_info.get('killAssists'))
        self.killAssists = killAssists
        highestKillStreak = int(player_info.get('highestKillStreak'))
        self.highestKillStreak = highestKillStreak
        revives = int(player_info.get('revives'))
        self.revives = revives
        heals = int(player_info.get('heals'))
        self.heals = heals
        repairs = int(player_info.get('repairs'))
        self.repairs = repairs
        dogtagsTaken = int(player_info.get('dogtagsTaken'))
        self.dogtagsTaken = dogtagsTaken

    # 根据传入的url下载头像，并打开返回img，如果下载失败则返回default_bot_avatar.jpg
    @staticmethod
    async def get_avatar(url: str, pid: Union[str, int]) -> bytes:
        # 如果 URL 为空，直接返回默认头像
        if not url:
            return DefaultAvatarImg
        avatar_path = AvatarPathRoot / f"{pid}.jpg"
        # 如果头像文件存在且最后修改时间距现在不足一天，则直接读取
        if avatar_path.is_file() and avatar_path.stat().st_mtime + 86400 > time.time():
            return avatar_path.read_bytes()
        # 读取头像
        avatar = await PilImageUtils.read_img_by_url(url)
        if avatar:
            avatar_path.write_bytes(avatar)
            return avatar
        elif avatar_path.is_file():
            return avatar_path.read_bytes()
        # 如果下载失败，返回默认头像
        return DefaultAvatarImg

    async def get_background(self, pid: Union[str, int]) -> Image:
        """根据pid查找路径是否存在，如果存在尝试随机选择一张图"""
        background_path = BackgroundPathRoot / f"{pid}"
        player_background_path = self.player_background_path
        if not player_background_path:
            if background_path.exists():
                background = random.choice(list(background_path.iterdir())).open("rb").read()
            else:
                background = random.choice(list(DefaultBackgroundPath.iterdir())).open("rb").read()
        else:
            background = player_background_path.open("rb").read()
        # if not player_background_path:  # 如果没有背景图，就用默认的，且放大
        #     # 将图片调整为2000*1550，如果图片任意一边小于2000则放大，否则缩小，然后将图片居中的部分裁剪出来
        #     background_img = ImageUtils.resize_and_crop_to_center(background, StatImageWidth, StatImageHeight)
        #     # 加一点高斯模糊
        #     background_img = background_img.filter(ImageFilter.GaussianBlur(radius=5))
        # else:  # 如果有背景图，就用原图，且不放大
        #     # 保留原图全部内容
        #     background_img = ImageUtils.scale_image_to_dimension(background, StatImageWidth, StatImageHeight)

        # 先放大填充全部+高斯模糊 然后再放大保留原图自适应全部内容
        background_img = PilImageUtils.resize_and_crop_to_center(background, StatImageWidth, StatImageHeight)
        background_img = background_img.filter(ImageFilter.GaussianBlur(radius=30))
        background_img_top = PilImageUtils.scale_image_to_dimension(background, StatImageWidth, StatImageHeight)
        # 将background_img_top粘贴到background_img上
        background_img = PilImageUtils.paste_center(background_img, background_img_top)
        return background_img

    async def avatar_template_handle(self) -> Image:
        avatar_img_data = None
        local_avatar_path = AvatarPathRoot / f"{self.player_pid}.jpg"

        # 检查本地路径是否存在，如果存在就判断时间是否超过一天，没超过就直接读取头像
        if local_avatar_path.is_file() and \
                (datetime.datetime.now() - datetime.datetime.fromtimestamp(
                    local_avatar_path.stat().st_mtime)) < datetime.timedelta(days=1):
            avatar_img_data = local_avatar_path.read_bytes()
        else:
            # 本地路径不存在，从 self.personas["result"] 或 self.gt_id_info 获取头像链接
            avatar_url = None
            if self.player_pid in self.personas["result"]:
                avatar_url = self.personas["result"][self.player_pid].get("avatar")
            elif isinstance(self.gt_id_info, dict):
                avatar_url = self.gt_id_info.get("avatar")

            if avatar_url:
                avatar_img_data = await self.get_avatar(avatar_url, self.player_pid)
            else:
                # 链接也获取失败，使用默认头像
                avatar_img_data = DefaultAvatarImg
        avatar_img = Image.open(BytesIO(avatar_img_data))
        # 裁剪为圆形
        avatar_img = PilImageUtils.crop_circle(avatar_img, 79)
        # 根据是否在线选择头像框
        if not self.server_playing_info["result"][self.player_pid]:
            avatar_template = Image.open(BytesIO(AvatarOfflineImg)).convert("RGBA")
        else:
            avatar_template = Image.open(BytesIO(AvatarOnlineImg)).convert("RGBA")
        # 将头像放入头像框,在320,90的位置
        avatar_template.paste(avatar_img, (420, 117), avatar_img)
        # 粘贴名字、PID、时长、等级
        avatar_template_draw = ImageDraw.Draw(avatar_template)
        # 名字
        avatar_template_draw.text(
            (80, 110),
            f"名字: {self.player_name}",
            fill=ColorWhite,
            font=ImageFont.truetype(str(GlobalFontPath), NormalFontSize)
        )
        # PID
        avatar_template_draw.text(
            (80, 160),
            f"PID : {self.player_pid}",
            fill=ColorWhite,
            font=ImageFont.truetype(str(GlobalFontPath), NormalFontSize)
        )
        # 时长
        avatar_template_draw.text(
            (80, 210),
            f"时长: {self.time_played}",
            fill=ColorWhite,
            font=ImageFont.truetype(str(GlobalFontPath), NormalFontSize)
        )
        # 等级
        text_position = (80, 260)
        # 获取"等级: "文本的边界框
        text_bbox = avatar_template_draw.textbbox(
            text_position,
            "等级: ",
            font=ImageFont.truetype(str(GlobalFontPath), NormalFontSize)
        )
        # text_bbox是一个四元组(left, top, right, bottom)，我们可以通过right - left来获取文本的宽度
        text_width = text_bbox[2] - text_bbox[0]
        # 计算数字部分的位置，这里我们仅需要水平位置
        rank_position_x = text_position[0] + text_width
        avatar_template_draw.text(
            text_position,
            "等级: ",
            fill=ColorWhite,  # 假设等级之前的文字是白色
            font=ImageFont.truetype(str(GlobalFontPath), NormalFontSize)
        )
        avatar_template_draw.text(
            (rank_position_x, text_position[1]),
            f"{self.rank}",
            fill=ColorGoldAndGray if self.rank == 150 else ColorBlueAndGray if self.rank >= 100 else ColorWhiteAndGray,
            font=ImageFont.truetype(str(GlobalFontPath), NormalFontSize)
        )
        return avatar_template

    async def ban_template_handle(self) -> Image:
        # 粘贴BFBAN和BFEAC的信息
        ban_template = Image.open(BytesIO(BanImg)).convert("RGBA")
        ban_template_draw = ImageDraw.Draw(ban_template)
        # BFBAN
        PilImageUtils.draw_centered_text(
            ban_template_draw,
            self.bfban_info["stat"] if self.bfban_info["stat"] else "无信息",
            (180, 57),
            fill=ColorRed if self.bfban_info["stat"] == "实锤" else ColorWhite,
            font=ImageFont.truetype(str(GlobalFontPath), NormalFontSize)
        )
        # BFEAC
        PilImageUtils.draw_centered_text(
            ban_template_draw,
            self.bfeac_info["stat"] if self.bfeac_info["stat"] else "无信息",
            (490, 57),
            fill=ColorRed if self.bfeac_info["stat"] == "已封禁" else ColorWhite,
            font=ImageFont.truetype(str(GlobalFontPath), NormalFontSize)
        )
        return ban_template

    async def stat_template_handle(self) -> Image:
        stat_template = Image.open(BytesIO(StatImg)).convert("RGBA")
        stat_template_draw = ImageDraw.Draw(stat_template)
        # 前三列: 击杀、死亡、kd，胜局、败局、胜率，kpm、spm、技巧值
        # 后两行：步战击杀、载具击杀、最远爆头距离
        row_diff_distance = 46
        start_row = 20
        col1_x = 65
        col2_x = 65 + 185
        col3_x = 65 + 185 * 2
        # 击杀、死亡、kd
        stat_template_draw.text(
            (col1_x, start_row + row_diff_distance * 0),
            f"击杀: {self.kills}",
            fill=ColorWhite,
            font=ImageFont.truetype(str(GlobalFontPath), StatFontSize)
        )
        stat_template_draw.text(
            (col1_x, start_row + row_diff_distance),
            f"死亡: {self.deaths}",
            fill=ColorWhite,
            font=ImageFont.truetype(str(GlobalFontPath), StatFontSize)
        )
        stat_template_draw.text(
            (col1_x, start_row + row_diff_distance * 2),
            f"KD: {self.kd}",
            fill=ColorWhite,
            font=ImageFont.truetype(str(GlobalFontPath), StatFontSize)
        )
        # 胜局、败局、胜率
        stat_template_draw.text(
            (col2_x, start_row + row_diff_distance * 0),
            f"胜局: {self.wins}",
            fill=ColorWhite,
            font=ImageFont.truetype(str(GlobalFontPath), StatFontSize)
        )
        stat_template_draw.text(
            (col2_x, start_row + row_diff_distance * 1),
            f"败局: {self.losses}",
            fill=ColorWhite,
            font=ImageFont.truetype(str(GlobalFontPath), StatFontSize)
        )
        stat_template_draw.text(
            (col2_x, start_row + row_diff_distance * 2),
            f"胜率: {self.win_rate}%",
            fill=ColorWhite,
            font=ImageFont.truetype(str(GlobalFontPath), StatFontSize)
        )
        # kpm、spm、技巧值
        stat_template_draw.text(
            (col3_x, start_row + row_diff_distance * 0),
            f"KPM: {self.kpm}",
            fill=ColorWhite,
            font=ImageFont.truetype(str(GlobalFontPath), StatFontSize)
        )
        stat_template_draw.text(
            (col3_x, start_row + row_diff_distance * 1),
            f"SPM: {self.spm}",
            fill=ColorWhite,
            font=ImageFont.truetype(str(GlobalFontPath), StatFontSize)
        )
        stat_template_draw.text(
            (col3_x, start_row + row_diff_distance * 2),
            f"技巧值: {self.skill}",
            fill=ColorWhite,
            font=ImageFont.truetype(str(GlobalFontPath), StatFontSize)
        )
        # 步战击杀、载具击杀、最远爆头距离
        stat_template_draw.text(
            (col1_x, start_row + row_diff_distance * 3),
            f"步战击杀: {self.infantry_kill}",
            fill=ColorWhite,
            font=ImageFont.truetype(str(GlobalFontPath), StatFontSize)
        )
        stat_template_draw.text(
            (col2_x + 100, start_row + row_diff_distance * 3),
            f"载具击杀: {self.vehicle_kill}",
            fill=ColorWhite,
            font=ImageFont.truetype(str(GlobalFontPath), StatFontSize)
        )
        stat_template_draw.text(
            (col1_x, start_row + row_diff_distance * 4),
            f"最远爆头距离: {self.longest_headshot}米",
            fill=ColorWhite,
            font=ImageFont.truetype(str(GlobalFontPath), StatFontSize)
        )
        return stat_template

    async def soldier_template_handle(self) -> Image:
        favoriteClass = self.stat["result"]["favoriteClass"]
        if favoriteClass == "Assault":
            soldier_img = Image.open(BytesIO(AssaultImg)).convert("RGBA")
            favoriteClass = "突击兵"
        elif favoriteClass == "Cavalry":
            soldier_img = Image.open(BytesIO(CavalryImg)).convert("RGBA")
            favoriteClass = "骑兵"
        elif favoriteClass == "Medic":
            soldier_img = Image.open(BytesIO(MedicImg)).convert("RGBA")
            favoriteClass = "医疗兵"
        elif favoriteClass == "Pilot":
            soldier_img = Image.open(BytesIO(PilotImg)).convert("RGBA")
            favoriteClass = "飞行员"
        elif favoriteClass == "Scout":
            soldier_img = Image.open(BytesIO(ScoutImg)).convert("RGBA")
            favoriteClass = "侦察兵"
        elif favoriteClass == "Support":
            soldier_img = Image.open(BytesIO(SupportImg)).convert("RGBA")
            favoriteClass = "支援兵"
        elif favoriteClass == "Tanker":
            soldier_img = Image.open(BytesIO(TankerImg)).convert("RGBA")
            favoriteClass = "坦克手"
        else:
            soldier_img = Image.open(BytesIO(AssaultImg)).convert("RGBA")
            favoriteClass = "突击兵"
        soldier_template_draw = ImageDraw.Draw(soldier_img)
        # 最佳兵种名字、协助击杀、最高连杀、复活数、修理数、狗牌数
        row_diff_distance = 60
        start_row = 220
        col1_x = 300
        col2_x = 300 + 185
        # 最佳兵种名字
        soldier_template_draw.text(
            (300, 120),
            f"最佳兵种: {favoriteClass}",
            fill=ColorWhite,
            font=ImageFont.truetype(str(GlobalFontPath), NormalFontSize)
        )
        soldier_template_draw.text(
            (col1_x, start_row + row_diff_distance * 0),
            f"协助击杀: {self.killAssists}",
            fill=ColorWhite,
            font=ImageFont.truetype(str(GlobalFontPath), StatFontSize)
        )
        soldier_template_draw.text(
            (col1_x, start_row + row_diff_distance * 1),
            f"复活数: {self.revives}",
            fill=ColorWhite,
            font=ImageFont.truetype(str(GlobalFontPath), StatFontSize)
        )
        soldier_template_draw.text(
            (col1_x, start_row + row_diff_distance * 2),
            f"修理数: {self.repairs}",
            fill=ColorWhite,
            font=ImageFont.truetype(str(GlobalFontPath), StatFontSize)
        )
        soldier_template_draw.text(
            (col2_x, start_row + row_diff_distance * 0),
            f"最高连杀: {self.highestKillStreak}",
            fill=ColorWhite,
            font=ImageFont.truetype(str(GlobalFontPath), StatFontSize)
        )
        soldier_template_draw.text(
            (col2_x, start_row + row_diff_distance * 1),
            f"治疗数: {self.heals}",
            fill=ColorWhite,
            font=ImageFont.truetype(str(GlobalFontPath), StatFontSize)
        )
        soldier_template_draw.text(
            (col2_x, start_row + row_diff_distance * 2),
            f"狗牌数: {self.dogtagsTaken}",
            fill=ColorWhite,
            font=ImageFont.truetype(str(GlobalFontPath), StatFontSize)
        )

        return soldier_img

    async def platoon_template_handle(self) -> Image:
        row_diff_distance = 30
        start_row = 20
        col1_x = 35
        if self.platoon_info["result"]:
            platoon_template = Image.open(BytesIO(PlatoonImg)).convert("RGBA")
            platoon_template_draw = ImageDraw.Draw(platoon_template)
            if self.platoon_info["result"]["emblem"]:
                emblem = self.platoon_info["result"]["emblem"].replace("[SIZE]", "256").replace("[FORMAT]", "png")
                emblem_img = await PilImageUtils.read_img_by_url(emblem)
                if emblem_img:
                    emblem_img = Image.open(BytesIO(emblem_img)).convert("RGBA")
                    # 重置为170*170
                    emblem_img = emblem_img.resize((170, 170), Image.LANCZOS)
                    # 单独将图章做一个放大填充的高斯模糊背景
                    emblem_img_background = PilImageUtils.resize_and_crop_to_center(
                        emblem_img, platoon_template.width, platoon_template.height
                    )
                    emblem_img_background = emblem_img_background.filter(ImageFilter.GaussianBlur(radius=10))
                    # 将emblem_img_background粘贴到platoon_template上
                    platoon_template = PilImageUtils.paste_center(emblem_img_background, platoon_template)
                    platoon_template.paste(emblem_img, (422, 22), emblem_img)
                    platoon_template_draw = ImageDraw.Draw(platoon_template)
                else:
                    logger.warning(f"下载战队徽章失败，url: {emblem}")
            # 战队名字、人数、描述
            platoon_template_draw.text(
                (col1_x, start_row + row_diff_distance * 0),
                f"[{self.platoon_info['result']['tag']}]{self.platoon_info['result']['name']}",
                fill=ColorWhite,
                font=ImageFont.truetype(str(GlobalFontPath), StatFontSize)
            )
            platoon_template_draw.text(
                (col1_x, start_row + row_diff_distance * 1),
                f"人数: {self.platoon_info['result']['size']}",
                fill=ColorWhite,
                font=ImageFont.truetype(str(GlobalFontPath), StatFontSize)
            )
            PilImageUtils.draw_multiline_text(
                platoon_template_draw,
                f"描述: {self.platoon_info['result']['description']}",
                (col1_x, start_row + row_diff_distance * 2),
                ImageFont.truetype(str(GlobalFontPath), StatFontSize),
                ColorWhite,
                StatFontSize * 15
            )
        else:
            platoon_template = Image.open(BytesIO(PlatoonImgNone)).convert("RGBA")
            platoon_template_draw = ImageDraw.Draw(platoon_template)
            file_path = f"./data/battlefield/小标语/data.json"
            with open(file_path, 'r', encoding="utf-8") as file1:
                data = json.load(file1)['result']
                data.append({'name': "你知道吗,小埋BOT最初的灵感来自于胡桃-by水神"})
                data.append({'name': "当武器击杀达到60⭐时为蓝光,当达到100⭐之后会发出耀眼的金光~"})
                tip = zhconv.convert(random.choice(data)['name'], 'zh-cn')
            PilImageUtils.draw_multiline_text(
                platoon_template_draw,
                tip,
                (col1_x, start_row + row_diff_distance * 0),
                ImageFont.truetype(str(GlobalFontPath), StatFontSize),
                ColorWhite,
                StatFontSize * 22
            )
        return platoon_template

    async def weapon_template_handle(self, weapon: dict) -> Image:
        weapon_name = zhconv.convert(weapon.get('name'), 'zh-hans')
        kills = int(weapon["stats"]["values"]["kills"])
        # 星数是kills/100向下取整
        stars = kills // 100
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
        if seconds < 3600:
            time_played = f"{round(seconds // 60)}分钟"
        else:
            time_played = f"{round(seconds // 3600)}小时{round(seconds % 3600 // 60)}分钟"

        if kills >= 10000:
            weapon_template = Image.open(BytesIO(WeaponGoldImg)).convert("RGBA")
        elif kills >= 6000:
            weapon_template = Image.open(BytesIO(WeaponBlueImg)).convert("RGBA")
        else:
            weapon_template = Image.open(BytesIO(WeaponWhiteImg)).convert("RGBA")
        weapon_template_draw = ImageDraw.Draw(weapon_template)
        # 粘贴武器图片/皮肤图片
        weapon_guid = weapon["guid"]
        skin_guids = self.skin_info["result"]["weapons"].get(weapon_guid)
        weapon_img = None
        skin_level = skin_name = None
        # 下载/获取对应武器的皮肤图片
        if skin_guids:
            for k in skin_guids.keys():
                skin_guid = skin_guids[k]
                skin_all_info = json.loads(open(SkinAllPathRoot, "r", encoding="utf-8").read())
                if skin_all_info.get(skin_guid):
                    skin_url = skin_all_info[skin_guid]["images"]["Png1024xANY"].replace("[BB_PREFIX]", BB_PREFIX)
                    skin_name = zhconv.convert(skin_all_info[skin_guid]["name"], 'zh-hans')
                    skin_level = skin_all_info[skin_guid]["rarenessLevel"]["name"]  # Superior/Enhanced/Standard
                    skin_file_name = skin_url.split("/")[-1]
                    skin_file_path = SkinRootPath / skin_file_name
                    if skin_file_path.exists():
                        weapon_img = Image.open(skin_file_path).convert("RGBA")
                        break
                    else:
                        weapon_img = await PilImageUtils.read_img_by_url(skin_url)
                        if weapon_img:
                            weapon_img = Image.open(BytesIO(weapon_img)).convert("RGBA")
                            weapon_img.save(skin_file_path)
                            break
                        else:
                            logger.warning(f"下载武器皮肤失败，url: {skin_url}")
        if not weapon_img:
            pic_url = weapon["imageUrl"].replace("[BB_PREFIX]", BB_PREFIX)
            weapon_img = await PilImageUtils.read_img_by_url(pic_url)
            weapon_img = Image.open(BytesIO(weapon_img)).convert("RGBA")
        # 武器的长宽比1024/256 = 4,等比缩放为384*96
        weapon_img = weapon_img.resize((384, 96), Image.LANCZOS)
        # 粘贴到144,20
        weapon_template.paste(weapon_img, (144, 20), weapon_img)
        # 武器星星数
        weapon_template_draw.text(
            (54, 97),
            f"{stars}",
            fill=ColorGold if stars >= 100 else ColorBlue if stars >= 60 else ColorWhite,
            font=ImageFont.truetype(str(GlobalFontPath), NormalFontSize)
        )
        # 武器名字 55 160  列1:击杀、命中率、效率 列2:爆头率、kpm、时长
        start_row = 150
        row_diff_distance = 40
        col1_x = 55
        col2_x = 55 + 220
        weapon_template_draw.text(
            (col1_x, start_row + row_diff_distance * 0),
            f"{weapon_name}",
            fill=ColorWhite,
            font=ImageFont.truetype(str(GlobalFontPath), StatFontSize)
        )
        if skin_name:
            weapon_template_draw.text(
                (20, 65),
                f"{skin_name}",
                fill=ColorGoldAndGray if skin_level == "Superior"
                else ColorBlueAndGray if skin_level == "Enhanced"
                else ColorWhiteAndGray,
                font=ImageFont.truetype(str(GlobalFontPath), SkinFontSize)
            )
        weapon_template_draw.text(
            (col1_x, start_row + row_diff_distance * 1),
            f"击杀: {kills}",
            fill=ColorWhite,
            font=ImageFont.truetype(str(GlobalFontPath), StatFontSize)
        )
        weapon_template_draw.text(
            (col1_x, start_row + row_diff_distance * 2),
            f"命中率: {acc}%",
            fill=ColorWhite,
            font=ImageFont.truetype(str(GlobalFontPath), StatFontSize)
        )
        weapon_template_draw.text(
            (col1_x, start_row + row_diff_distance * 3),
            f"效率: {eff}",
            fill=ColorWhite,
            font=ImageFont.truetype(str(GlobalFontPath), StatFontSize)
        )
        weapon_template_draw.text(
            (col2_x, start_row + row_diff_distance * 1),
            f"KPM: {kpm}",
            fill=ColorWhite,
            font=ImageFont.truetype(str(GlobalFontPath), StatFontSize)
        )
        weapon_template_draw.text(
            (col2_x, start_row + row_diff_distance * 2),
            f"爆头率: {hs}%",
            fill=ColorWhite,
            font=ImageFont.truetype(str(GlobalFontPath), StatFontSize)
        )
        weapon_template_draw.text(
            (col2_x, start_row + row_diff_distance * 3),
            f"时长: {time_played}",
            fill=ColorWhite,
            font=ImageFont.truetype(str(GlobalFontPath), StatFontSize)
        )
        return weapon_template

    async def vehicle_template_handle(self, vehicle: dict) -> Image:
        vehicle_name = zhconv.convert(vehicle.get('name'), 'zh-hans')
        kills = int(vehicle["stats"]["values"]["kills"])
        stars = kills // 100
        seconds = vehicle["stats"]["values"]["seconds"]
        kpm = "{:.2f}".format(kills / seconds * 60) if seconds != 0 else kills
        destroyed = int(vehicle["stats"]["values"]["destroyed"])
        if seconds < 3600:
            time_played = f"{round(seconds // 60)}分钟"
        else:
            time_played = f"{round(seconds // 3600)}小时{round(seconds % 3600 // 60)}分钟"
        if kills >= 10000:
            vehicle_template = Image.open(BytesIO(WeaponGoldImg)).convert("RGBA")
        elif kills >= 6000:
            vehicle_template = Image.open(BytesIO(WeaponBlueImg)).convert("RGBA")
        else:
            vehicle_template = Image.open(BytesIO(WeaponWhiteImg)).convert("RGBA")
        vehicle_template_draw = ImageDraw.Draw(vehicle_template)
        # 粘贴载具图片/皮肤图片
        vehicle_guid = vehicle["guid"]
        skin_guids = self.skin_info["result"]["kits"].get(f"{vehicle['sortOrder']}")
        if skin_guids:
            skin_guids = skin_guids[0]
        vehicle_img = None
        skin_level = skin_name = None
        # 下载/获取对应载具的皮肤图片
        if skin_guids:
            for k in skin_guids.keys():
                skin_guid = skin_guids[k]
                skin_all_info = json.loads(open(SkinAllPathRoot, "r", encoding="utf-8").read())
                if skin_all_info.get(skin_guid):
                    skin_url = skin_all_info[skin_guid]["images"]["Png1024xANY"].replace("[BB_PREFIX]", BB_PREFIX)
                    skin_name = zhconv.convert(skin_all_info[skin_guid]["name"], 'zh-hans')
                    skin_level = skin_all_info[skin_guid]["rarenessLevel"]["name"]
                    skin_file_name = skin_url.split("/")[-1]
                    skin_file_path = SkinRootPath / skin_file_name
                    if skin_file_path.exists():
                        vehicle_img = Image.open(skin_file_path).convert("RGBA")
                        break
                    else:
                        vehicle_img = await PilImageUtils.read_img_by_url(skin_url)
                        if vehicle_img:
                            vehicle_img = Image.open(BytesIO(vehicle_img)).convert("RGBA")
                            vehicle_img.save(skin_file_path)
                            break
                        else:
                            logger.warning(f"下载载具皮肤失败，url: {skin_url}")
        if not vehicle_img:
            pic_url = vehicle["imageUrl"].replace("[BB_PREFIX]", BB_PREFIX)
            vehicle_img = await PilImageUtils.read_img_by_url(pic_url)
            vehicle_img = Image.open(BytesIO(vehicle_img)).convert("RGBA")
        # 载具的长宽比1024/256 = 4,等比缩放为384*96
        vehicle_img = vehicle_img.resize((384, 96), Image.LANCZOS)
        # 粘贴到144,20
        vehicle_template.paste(vehicle_img, (144, 20), vehicle_img)
        # 载具星星数
        vehicle_template_draw.text(
            (54, 97),
            f"{stars}",
            fill=ColorGold if stars >= 100 else ColorBlue if stars >= 60 else ColorWhite,
            font=ImageFont.truetype(str(GlobalFontPath), NormalFontSize)
        )
        # 载具名字 55 160  列1:击杀、摧毁 列2:kpm、时长
        start_row = 150
        row_diff_distance = 40
        col1_x = 55
        col2_x = 55 + 220
        vehicle_template_draw.text(
            (col1_x, start_row + row_diff_distance * 0),
            f"{vehicle_name}",
            fill=ColorWhite,
            font=ImageFont.truetype(str(GlobalFontPath), StatFontSize)
        )
        if skin_name:
            vehicle_template_draw.text(
                (20, 65),
                f"{skin_name}",
                fill=ColorGoldAndGray if skin_level == "Superior"
                else ColorBlueAndGray if skin_level == "Enhanced"
                else ColorWhiteAndGray,
                font=ImageFont.truetype(str(GlobalFontPath), SkinFontSize)
            )
        vehicle_template_draw.text(
            (col1_x, start_row + row_diff_distance * 1),
            f"击杀: {kills}",
            fill=ColorWhite,
            font=ImageFont.truetype(str(GlobalFontPath), StatFontSize)
        )
        vehicle_template_draw.text(
            (col1_x, start_row + row_diff_distance * 2),
            f"摧毁: {destroyed}",
            fill=ColorWhite,
            font=ImageFont.truetype(str(GlobalFontPath), StatFontSize)
        )
        vehicle_template_draw.text(
            (col2_x, start_row + row_diff_distance * 1),
            f"KPM: {kpm}",
            fill=ColorWhite,
            font=ImageFont.truetype(str(GlobalFontPath), StatFontSize)
        )
        vehicle_template_draw.text(
            (col2_x, start_row + row_diff_distance * 2),
            f"时长: {time_played}",
            fill=ColorWhite,
            font=ImageFont.truetype(str(GlobalFontPath), StatFontSize)
        )
        return vehicle_template

    @staticmethod
    async def best_text_trapezoid(text) -> Image:
        # 打开BlackTrapezoidImg图片 228*44 ，并将其转换为RGBA模式，写入text
        best_text_trapezoid = Image.open(BytesIO(BlackTrapezoidImg)).convert("RGBA")
        best_text_trapezoid_draw = ImageDraw.Draw(best_text_trapezoid)
        # 写入text
        PilImageUtils.draw_centered_text(
            best_text_trapezoid_draw,
            text,
            (72, 22),
            fill=ColorWhite,
            font=ImageFont.truetype(str(GlobalFontPath), NormalFontSize)
        )
        return best_text_trapezoid

    async def draw(self) -> Union[bytes, Path]:
        # 图的大小: 2000*1550
        # 画布
        output_img = Image.new("RGB", (StatImageWidth, StatImageHeight), ColorWhite)

        # 粘贴背景
        background_img = await self.get_background(self.player_pid)
        output_img = PilImageUtils.paste_center(output_img, background_img)

        # 粘贴头像框
        avatar_template = await self.avatar_template_handle()
        output_img.paste(avatar_template, (58, 60), avatar_template)

        # 粘贴战绩信息
        stat_template = await self.stat_template_handle()
        output_img.paste(stat_template, (56, 579), stat_template)

        # 粘贴兵种信息
        soldier_template = await self.soldier_template_handle()
        output_img.paste(soldier_template, (8, 800), soldier_template)

        # 粘贴战排信息
        platoon_template = await self.platoon_template_handle()
        output_img.paste(platoon_template, (58, 1256), platoon_template)

        # 粘贴武器信息
        player_weapon: list = WeaponData(self.weapons).filter()
        weapon_templates = []
        for weapon in player_weapon[:4]:
            if not weapon.get("stats").get('values'):
                continue
            weapon_template = await self.weapon_template_handle(weapon)
            weapon_templates.append(weapon_template)
        # 粘贴武器信息,前4个
        weapon_col = 750
        weapon_start_row = 124
        weapon_row_diff_distance = 345
        for i, weapon_template in enumerate(weapon_templates[:4]):
            output_img.paste(
                weapon_template,
                (weapon_col, weapon_start_row + weapon_row_diff_distance * i),
                weapon_template
            )
        # 粘贴最佳武器信息 761, 88
        best_weapon_template = await self.best_text_trapezoid("最佳武器")
        output_img.paste(best_weapon_template, (761, 88), best_weapon_template)

        # 粘贴载具信息
        player_vehicle: list = VehicleData(self.vehicles).filter()
        vehicle_templates = []
        for vehicle in player_vehicle[:4]:
            if not vehicle.get("stats").get('values'):
                continue
            vehicle_template = await self.vehicle_template_handle(vehicle)
            vehicle_templates.append(vehicle_template)
        # 粘贴载具信息,前4个
        vehicle_col = 1363
        vehicle_start_row = 124
        vehicle_row_diff_distance = 345
        for i, vehicle_template in enumerate(vehicle_templates[:4]):
            output_img.paste(
                vehicle_template,
                (vehicle_col, vehicle_start_row + vehicle_row_diff_distance * i),
                vehicle_template
            )
        # 粘贴最佳载具信息 1374, 88
        best_vehicle_template = await self.best_text_trapezoid("最佳载具")
        output_img.paste(best_vehicle_template, (1374, 88), best_vehicle_template)

        # 水印和时间
        output_img_draw = ImageDraw.Draw(output_img)
        # 居中
        PilImageUtils.draw_centered_text(
            output_img_draw,
            "Powered by XiaoMaiBot | Made by 13&&XM | " + time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
            (StatImageWidth // 2, StatImageHeight - 30),
            fill=(253, 245, 242),
            font=ImageFont.truetype(str(GlobalFontPath), StatFontSize)
        )

        # 如果bfeac信息为已封禁，或者bfban信息为实锤，则将整张图片置黑白
        if self.bfeac_info["stat"] == "已封禁" or self.bfban_info["stat"] == "实锤":
            output_img = output_img.convert("L").convert("RGB")

        # 粘贴封禁框
        ban_template = await self.ban_template_handle()
        output_img.paste(ban_template, (91, 440), ban_template)

        # 存为bytes
        # img_bytes = BytesIO()
        # output_img.save(img_bytes, format="PNG")
        # return img_bytes.getvalue()

        # 存为 FileTempSaveRoot / 时间戳.png
        file_path = FileTempSaveRoot / f"{round(time.time() * 1000)}.png"
        # output_img.save(file_path, format="PNG")
        # 存为jpeg
        output_img.save(file_path, format="JPEG", quality=95)
        return file_path


class PlayerWeaponPic:
    weapon_data: list

    def __init__(
            self,
            player_name: str,
            player_pid: Union[str, int],
            personas: dict,
            stat: dict,
            weapons: list[dict],
            server_playing_info: dict,
            skin_info: dict,
            gt_id_info: Union[dict, None]
    ):
        """初始化处理数据,使用PIL绘制图片
        :param player_name: 玩家名字
        :param player_pid: 玩家pid
        :param personas: 玩家信息
        :param stat: 玩家战绩
        :param weapons: 玩家武器数据
        :param server_playing_info: 玩家服务器信息
        :param skin_info: 玩家皮肤信息
        :param gt_id_info: gt玩家信息
        """
        self.player_name: str = player_name
        self.player_pid: Union[str, int] = str(player_pid)
        self.personas: dict = personas
        self.stat: dict = stat
        self.weapons: list[dict] = weapons
        self.server_playing_info: dict = server_playing_info
        self.skin_info: dict = skin_info
        self.gt_id_info: Union[dict, None] = gt_id_info

        self.player_background_path = bg_pic.choose_bg(self.player_pid)

        # 玩家数据
        player_info = self.stat["result"]
        rank = player_info.get('basicStats').get('rank')
        rank_list = [
            0, 1000, 5000, 15000, 25000, 40000, 55000, 75000, 95000, 120000, 145000, 175000, 205000, 235000,
            265000, 295000, 325000, 355000, 395000, 435000, 475000, 515000, 555000, 595000, 635000, 675000, 715000,
            755000, 795000, 845000, 895000, 945000, 995000, 1045000, 1095000, 1145000, 1195000, 1245000, 1295000,
            1345000, 1405000, 1465000, 1525000, 1585000, 1645000, 1705000, 1765000, 1825000, 1885000, 1945000,
            2015000, 2085000, 2155000, 2225000, 2295000, 2365000, 2435000, 2505000, 2575000, 2645000, 2745000,
            2845000, 2945000, 3045000, 3145000, 3245000, 3345000, 3445000, 3545000, 3645000, 3750000, 3870000,
            4000000, 4140000, 4290000, 4450000, 4630000, 4830000, 5040000, 5260000, 5510000, 5780000, 6070000,
            6390000, 6730000, 7110000, 7510000, 7960000, 8430000, 8960000, 9520000, 10130000, 10800000, 11530000,
            12310000, 13170000, 14090000, 15100000, 16190000, 17380000, 20000000, 20500000, 21000000, 21500000,
            22000000, 22500000, 23000000, 23500000, 24000000, 24500000, 25000000, 25500000, 26000000, 26500000,
            27000000, 27500000, 28000000, 28500000, 29000000, 29500000, 30000000, 30500000, 31000000, 31500000,
            32000000, 32500000, 33000000, 33500000, 34000000, 34500000, 35000000, 35500000, 36000000, 36500000,
            37000000, 37500000, 38000000, 38500000, 39000000, 39500000, 40000000, 41000000, 42000000, 43000000,
            44000000, 45000000, 46000000, 47000000, 48000000, 49000000, 50000000
        ]
        # 转换成xx小时xx分钟
        time_seconds = player_info.get('basicStats').get('timePlayed')
        if time_seconds < 3600:
            self.time_played = f"{round(time_seconds // 60)}分钟"
        else:
            self.time_played = f"{round(time_seconds // 3600)}小时{round(time_seconds % 3600 // 60)}分钟"
        kills = player_info.get('basicStats').get('kills')
        self.kills = kills
        deaths = player_info.get('basicStats').get('deaths')
        self.deaths = deaths
        kd = round(kills / deaths, 2) if deaths else kills
        self.kd = kd
        wins = player_info.get('basicStats').get('wins')
        self.wins = wins
        losses = player_info.get('basicStats').get('losses')
        self.losses = losses
        # 百分制
        win_rate = round(wins / (wins + losses) * 100, 2) if wins + losses else 100
        self.win_rate = win_rate
        kpm = player_info.get('basicStats').get('kpm')
        self.kpm = kpm
        spm = player_info.get('basicStats').get('spm')
        self.spm = spm
        # 用spm / 60 * 游玩时间 得出经验值exp,看exp在哪个区间,可确定整数等级
        exp = spm * time_seconds / 60
        rank = 0
        for i in range(len(rank_list)):
            if exp <= rank_list[1]:
                rank = 0
                break
            if exp >= rank_list[-1]:
                rank = 150
                break
            if exp <= rank_list[i]:
                rank = i - 1
                break
        self.rank = rank
        vehicle_kill = sum(item["killsAs"] for item in player_info["vehicleStats"])
        vehicle_kill = int(vehicle_kill)
        self.vehicle_kill = vehicle_kill
        infantry_kill = int(player_info['basicStats']['kills'] - vehicle_kill)
        self.infantry_kill = infantry_kill
        skill = player_info.get('basicStats').get('skill')
        self.skill = skill
        longest_headshot = player_info.get('longestHeadShot')
        self.longest_headshot = longest_headshot
        killAssists = int(player_info.get('killAssists'))
        self.killAssists = killAssists
        highestKillStreak = int(player_info.get('highestKillStreak'))
        self.highestKillStreak = highestKillStreak
        revives = int(player_info.get('revives'))
        self.revives = revives
        heals = int(player_info.get('heals'))
        self.heals = heals
        repairs = int(player_info.get('repairs'))
        self.repairs = repairs
        dogtagsTaken = int(player_info.get('dogtagsTaken'))
        self.dogtagsTaken = dogtagsTaken

    @staticmethod
    async def get_avatar(url: str, pid: Union[str, int]) -> bytes:
        # 如果 URL 为空，直接返回默认头像
        if not url:
            return DefaultAvatarImg
        avatar_path = AvatarPathRoot / f"{pid}.jpg"
        # 如果头像文件存在且最后修改时间距现在不足一天，则直接读取
        if avatar_path.is_file() and avatar_path.stat().st_mtime + 86400 > time.time():
            return avatar_path.read_bytes()
        # 尝试下载头像
        avatar = await PilImageUtils.read_img_by_url(url)
        if avatar:
            avatar_path.write_bytes(avatar)
            return avatar
        elif avatar_path.is_file():
            return avatar_path.read_bytes()
        # 如果下载失败，返回默认头像
        return DefaultAvatarImg

    async def avatar_template_handle(self) -> Image:
        avatar_img_data = None
        local_avatar_path = AvatarPathRoot / f"{self.player_pid}.jpg"

        # 检查本地路径是否存在，如果存在就判断时间是否超过一天，没超过就直接读取头像
        if local_avatar_path.is_file() and \
                (datetime.datetime.now() - datetime.datetime.fromtimestamp(
                    local_avatar_path.stat().st_mtime)) < datetime.timedelta(days=1):
            avatar_img_data = local_avatar_path.read_bytes()
        else:
            # 本地路径不存在，从 self.personas["result"] 或 self.gt_id_info 获取头像链接
            avatar_url = None
            if self.player_pid in self.personas["result"]:
                avatar_url = self.personas["result"][self.player_pid].get("avatar")
            elif isinstance(self.gt_id_info, dict):
                avatar_url = self.gt_id_info.get("avatar")

            if avatar_url:
                avatar_img_data = await self.get_avatar(avatar_url, self.player_pid)
            elif local_avatar_path.is_file():
                avatar_img_data = local_avatar_path.read_bytes()
            else:
                # 链接也获取失败，使用默认头像
                avatar_img_data = DefaultAvatarImg
        avatar_img = Image.open(BytesIO(avatar_img_data))
        # 裁剪为圆形
        avatar_img = PilImageUtils.crop_circle(avatar_img, 79)
        # 根据是否在线选择头像框
        if not self.server_playing_info["result"][self.player_pid]:
            avatar_template = Image.open(BytesIO(AvatarOfflineImg)).convert("RGBA")
        else:
            avatar_template = Image.open(BytesIO(AvatarOnlineImg)).convert("RGBA")
        # 将头像放入头像框,在320,90的位置
        avatar_template.paste(avatar_img, (420, 117), avatar_img)
        # 粘贴名字、PID、时长、等级
        avatar_template_draw = ImageDraw.Draw(avatar_template)
        # 名字
        avatar_template_draw.text(
            (80, 110),
            f"名字: {self.player_name}",
            fill=ColorWhite,
            font=ImageFont.truetype(str(GlobalFontPath), NormalFontSize)
        )
        # PID
        avatar_template_draw.text(
            (80, 160),
            f"PID : {self.player_pid}",
            fill=ColorWhite,
            font=ImageFont.truetype(str(GlobalFontPath), NormalFontSize)
        )
        # 时长
        avatar_template_draw.text(
            (80, 210),
            f"时长: {self.time_played}",
            fill=ColorWhite,
            font=ImageFont.truetype(str(GlobalFontPath), NormalFontSize)
        )
        # 等级
        text_position = (80, 260)
        # 获取"等级: "文本的边界框
        text_bbox = avatar_template_draw.textbbox(
            text_position,
            "等级: ",
            font=ImageFont.truetype(str(GlobalFontPath), NormalFontSize)
        )
        # text_bbox是一个四元组(left, top, right, bottom)，我们可以通过right - left来获取文本的宽度
        text_width = text_bbox[2] - text_bbox[0]
        # 计算数字部分的位置，这里我们仅需要水平位置
        rank_position_x = text_position[0] + text_width
        avatar_template_draw.text(
            text_position,
            "等级: ",
            fill=ColorWhite,  # 假设等级之前的文字是白色
            font=ImageFont.truetype(str(GlobalFontPath), NormalFontSize)
        )
        avatar_template_draw.text(
            (rank_position_x, text_position[1]),
            f"{self.rank}",
            fill=ColorGoldAndGray if self.rank == 150 else ColorBlueAndGray if self.rank >= 100 else ColorWhiteAndGray,
            font=ImageFont.truetype(str(GlobalFontPath), NormalFontSize)
        )
        return avatar_template

    async def get_background(self, pid: Union[str, int], target_width, target_height) -> Image:
        """根据pid查找路径是否存在，如果存在尝试随机选择一张图"""
        background_path = BackgroundPathRoot / f"{pid}"
        player_background_path = self.player_background_path
        if not player_background_path:
            if background_path.exists():
                background = random.choice(list(background_path.iterdir())).open("rb").read()
            else:
                background = random.choice(list(DefaultBackgroundPath.iterdir())).open("rb").read()
        else:
            background = player_background_path.open("rb").read()
        # 默认背景，直接放大填充
        if not player_background_path:
            background_img = PilImageUtils.resize_and_crop_to_center(background, target_width, target_height)
            # 加一点高斯模糊
            # background_img = background_img.filter(ImageFilter.GaussianBlur(radius=5))
        # 自定义背景，先放大填充全部+高斯模糊 然后再放大保留原图自适应全部内容
        else:
            background_img = PilImageUtils.resize_and_crop_to_center(background, target_width, target_height)
            background_img = background_img.filter(ImageFilter.GaussianBlur(radius=30))
            background_img_top = PilImageUtils.scale_image_to_dimension(background, target_width, target_height)
            # 将background_img_top粘贴到background_img上
            background_img = PilImageUtils.paste_center(background_img, background_img_top)
        return background_img

    async def weapon_template_handle(self, weapon: dict) -> Image:
        weapon_name = zhconv.convert(weapon.get('name'), 'zh-hans')
        kills = int(weapon["stats"]["values"]["kills"])
        # 星数是kills/100向下取整
        stars = kills // 100
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
        if seconds < 3600:
            time_played = f"{round(seconds // 60)}分钟"
        else:
            time_played = f"{round(seconds // 3600)}小时{round(seconds % 3600 // 60)}分钟"

        if kills >= 10000:
            weapon_template = Image.open(BytesIO(WeaponGoldImg)).convert("RGBA")
        elif kills >= 6000:
            weapon_template = Image.open(BytesIO(WeaponBlueImg)).convert("RGBA")
        else:
            weapon_template = Image.open(BytesIO(WeaponWhiteImg)).convert("RGBA")
        weapon_template_draw = ImageDraw.Draw(weapon_template)
        # 粘贴武器图片/皮肤图片
        weapon_guid = weapon["guid"]
        skin_guids = self.skin_info["result"]["weapons"].get(weapon_guid)
        weapon_img = None
        skin_level = skin_name = None
        # 下载/获取对应武器的皮肤图片
        if skin_guids:
            for k in skin_guids.keys():
                skin_guid = skin_guids[k]
                skin_all_info = json.loads(open(SkinAllPathRoot, "r", encoding="utf-8").read())
                if skin_all_info.get(skin_guid):
                    skin_url = skin_all_info[skin_guid]["images"]["Png1024xANY"].replace("[BB_PREFIX]", BB_PREFIX)
                    skin_name = zhconv.convert(skin_all_info[skin_guid]["name"], 'zh-hans')
                    skin_level = skin_all_info[skin_guid]["rarenessLevel"]["name"]  # Superior/Enhanced/Standard
                    skin_file_name = skin_url.split("/")[-1]
                    skin_file_path = SkinRootPath / skin_file_name
                    if skin_file_path.exists():
                        weapon_img = Image.open(skin_file_path).convert("RGBA")
                        break
                    else:
                        weapon_img = await PilImageUtils.read_img_by_url(skin_url)
                        if weapon_img:
                            weapon_img = Image.open(BytesIO(weapon_img)).convert("RGBA")
                            weapon_img.save(skin_file_path)
                            break
                        else:
                            logger.warning(f"下载武器皮肤失败，url: {skin_url}")
        if not weapon_img:
            pic_url = weapon["imageUrl"].replace("[BB_PREFIX]", BB_PREFIX)
            weapon_img = await PilImageUtils.read_img_by_url(pic_url)
            weapon_img = Image.open(BytesIO(weapon_img)).convert("RGBA")
        # 武器的长宽比1024/256 = 4,等比缩放为384*96
        weapon_img = weapon_img.resize((384, 96), Image.LANCZOS)
        # 粘贴到144,20
        weapon_template.paste(weapon_img, (144, 20), weapon_img)
        # 武器星星数
        weapon_template_draw.text(
            (54, 97),
            f"{stars}",
            fill=ColorGold if stars >= 100 else ColorBlue if stars >= 60 else ColorWhite,
            font=ImageFont.truetype(str(GlobalFontPath), NormalFontSize)
        )
        # 武器名字 55 160  列1:击杀、命中率、效率 列2:爆头率、kpm、时长
        start_row = 150
        row_diff_distance = 40
        col1_x = 55
        col2_x = 55 + 220
        weapon_template_draw.text(
            (col1_x, start_row + row_diff_distance * 0),
            f"{weapon_name}",
            fill=ColorWhite,
            font=ImageFont.truetype(str(GlobalFontPath), StatFontSize)
        )
        if skin_name:
            weapon_template_draw.text(
                (20, 65),
                f"{skin_name}",
                fill=ColorGoldAndGray if skin_level == "Superior"
                else ColorBlueAndGray if skin_level == "Enhanced"
                else ColorWhiteAndGray,
                font=ImageFont.truetype(str(GlobalFontPath), SkinFontSize)
            )
        weapon_template_draw.text(
            (col1_x, start_row + row_diff_distance * 1),
            f"击杀: {kills}",
            fill=ColorWhite,
            font=ImageFont.truetype(str(GlobalFontPath), StatFontSize)
        )
        weapon_template_draw.text(
            (col1_x, start_row + row_diff_distance * 2),
            f"命中率: {acc}%",
            fill=ColorWhite,
            font=ImageFont.truetype(str(GlobalFontPath), StatFontSize)
        )
        weapon_template_draw.text(
            (col1_x, start_row + row_diff_distance * 3),
            f"效率: {eff}",
            fill=ColorWhite,
            font=ImageFont.truetype(str(GlobalFontPath), StatFontSize)
        )
        weapon_template_draw.text(
            (col2_x, start_row + row_diff_distance * 1),
            f"KPM: {kpm}",
            fill=ColorWhite,
            font=ImageFont.truetype(str(GlobalFontPath), StatFontSize)
        )
        weapon_template_draw.text(
            (col2_x, start_row + row_diff_distance * 2),
            f"爆头率: {hs}%",
            fill=ColorWhite,
            font=ImageFont.truetype(str(GlobalFontPath), StatFontSize)
        )
        weapon_template_draw.text(
            (col2_x, start_row + row_diff_distance * 3),
            f"时长: {time_played}",
            fill=ColorWhite,
            font=ImageFont.truetype(str(GlobalFontPath), StatFontSize)
        )
        return weapon_template

    async def draw(
            self,
            col: int = 2,
            row: int = 4,
    ) -> Union[bytes, Path, None]:
        """绘制武器数据图片
        与生涯不同，武器只绘制头像框+武器数据，默认为两列四行
        这里是动态计算,每个武器框距离左边边界间距:90,列间距:43,行间距:25,右边边界间距:90，
        获取weapons的长度，图片一行最多允许8列，每8个武器换一行，行数最多为10行，所以最多80个武器，
        图片总宽度为90 + 武器框宽度 * 列数 + 列间距 * (列数 - 1) + 90
        图片总高度为60 + 头像框高度 + 武器框高度 * 行数 + 行间距 * (行数 - 1) + 60
        武器框: 570x320
        头像框: 631x349
        """
        weapons = []
        if not self.weapons:
            return None
        else:
            for weapon in self.weapons:
                if not weapon.get("stats").get('values'):
                    continue
                weapons.append(weapon)
        # 整理成col列row行的列表
        if col > 8:
            col = 8
        if row > 10:
            row = 10
        weapon_data = [weapons[i * col:(i + 1) * col] for i in range(row)]
        col_origin = col
        row_origin = row
        col = len(weapon_data[0])
        row = len(weapon_data)
        weapon_template_num = col * row

        # 图片大小
        image_width = 90 + 570 * col + 43 * (col - 1) + 90
        image_height = 60 + 349 + 320 * row + 25 * (row - 1) + 60
        weapon_template_width = 570  # 每个武器模板的宽度为570像素
        weapon_template_height = 320  # 每个武器模板的高度为320像素
        # 画布
        output_img = Image.new("RGB", (image_width, image_height), ColorWhite)

        # 粘贴背景
        background_img = await self.get_background(self.player_pid, image_width, image_height)
        output_img = PilImageUtils.paste_center(output_img, background_img)

        # 粘贴头像框
        avatar_template = await self.avatar_template_handle()
        output_img.paste(avatar_template, (58, 60), avatar_template)

        # 粘贴武器信息
        weapon_templates = []
        for weapon in weapon_data[:weapon_template_num]:
            for item in weapon:
                weapon_template = await self.weapon_template_handle(item)
                weapon_templates.append(weapon_template)
        # 整理成col_origin列row_origin行的列表
        weapon_templates = [weapon_templates[i * col_origin:(i + 1) * col_origin] for i in range(row_origin)]
        # 粘贴武器信息
        row_diff_distance = weapon_template_height + 25  # 行与行之间的距离
        start_row = 60 + 349 + 25  # 首行起始位置
        col_diff_distance = weapon_template_width + 43  # 列与列之间的距离
        start_col = 90  # 首列起始位置

        for row_index, weapon_template_row in enumerate(weapon_templates):
            for col_index, weapon_template in enumerate(weapon_template_row):
                # 计算每个武器模板的粘贴位置
                paste_x = start_col + col_diff_distance * col_index
                paste_y = start_row + row_diff_distance * row_index
                output_img.paste(
                    weapon_template,
                    (paste_x, paste_y),
                    weapon_template
                )

        # 水印和时间
        output_img_draw = ImageDraw.Draw(output_img)
        # 居中
        PilImageUtils.draw_centered_text(
            output_img_draw,
            "Powered by XiaoMaiBot | Made by 13&&XM | " + time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
            (image_width // 2, image_height - 20),
            fill=(253, 245, 242),
            font=ImageFont.truetype(str(GlobalFontPath), StatFontSize)
        )

        # 存为 FileTempSaveRoot / 时间戳.png
        file_path = FileTempSaveRoot / f"{round(time.time() * 1000)}.png"
        # output_img.save(file_path, format="PNG")
        # 存为jpeg
        output_img.save(file_path, format="JPEG", quality=95)
        return file_path


class PlayerVehiclePic:
    vehicle_data: list

    def __init__(
            self,
            player_name: str,
            player_pid: Union[str, int],
            personas: dict,
            stat: dict,
            vehicles: list[dict],
            server_playing_info: dict,
            skin_info: dict,
            gt_id_info: Union[dict, None]
    ):
        """初始化处理数据,使用PIL绘制图片
        :param player_name: 玩家名字
        :param player_pid: 玩家pid
        :param personas: 玩家信息
        :param stat: 玩家战绩
        :param vehicles: 玩家载具数据
        :param server_playing_info: 玩家服务器信息
        :param skin_info: 玩家皮肤信息
        :param gt_id_info: gt玩家信息
        """
        self.player_name: str = player_name
        self.player_pid: Union[str, int] = str(player_pid)
        self.personas: dict = personas
        self.stat: dict = stat
        self.vehicles: list[dict] = vehicles
        self.server_playing_info: dict = server_playing_info
        self.skin_info: dict = skin_info
        self.gt_id_info: Union[dict, None] = gt_id_info

        self.player_background_path = bg_pic.choose_bg(self.player_pid)

        # 玩家数据
        player_info = self.stat["result"]
        rank = player_info.get('basicStats').get('rank')
        rank_list = [
            0, 1000, 5000, 15000, 25000, 40000, 55000, 75000, 95000, 120000, 145000, 175000, 205000, 235000,
            265000, 295000, 325000, 355000, 395000, 435000, 475000, 515000, 555000, 595000, 635000, 675000, 715000,
            755000, 795000, 845000, 895000, 945000, 995000, 1045000, 1095000, 1145000, 1195000, 1245000, 1295000,
            1345000, 1405000, 1465000, 1525000, 1585000, 1645000, 1705000, 1765000, 1825000, 1885000, 1945000,
            2015000, 2085000, 2155000, 2225000, 2295000, 2365000, 2435000, 2505000, 2575000, 2645000, 2745000,
            2845000, 2945000, 3045000, 3145000, 3245000, 3345000, 3445000, 3545000, 3645000, 3750000, 3870000,
            4000000, 4140000, 4290000, 4450000, 4630000, 4830000, 5040000, 5260000, 5510000, 5780000, 6070000,
            6390000, 6730000, 7110000, 7510000, 7960000, 8430000, 8960000, 9520000, 10130000, 10800000, 11530000,
            12310000, 13170000, 14090000, 15100000, 16190000, 17380000, 20000000, 20500000, 21000000, 21500000,
            22000000, 22500000, 23000000, 23500000, 24000000, 24500000, 25000000, 25500000, 26000000, 26500000,
            27000000, 27500000, 28000000, 28500000, 29000000, 29500000, 30000000, 30500000, 31000000, 31500000,
            32000000, 32500000, 33000000, 33500000, 34000000, 34500000, 35000000, 35500000, 36000000, 36500000,
            37000000, 37500000, 38000000, 38500000, 39000000, 39500000, 40000000, 41000000, 42000000, 43000000,
            44000000, 45000000, 46000000, 47000000, 48000000, 49000000, 50000000
        ]
        # 转换成xx小时xx分钟
        time_seconds = player_info.get('basicStats').get('timePlayed')
        if time_seconds < 3600:
            self.time_played = f"{round(time_seconds // 60)}分钟"
        else:
            self.time_played = f"{round(time_seconds // 3600)}小时{round(time_seconds % 3600 // 60)}分钟"
        kills = player_info.get('basicStats').get('kills')
        self.kills = kills
        deaths = player_info.get('basicStats').get('deaths')
        self.deaths = deaths
        kd = round(kills / deaths, 2) if deaths else kills
        self.kd = kd
        wins = player_info.get('basicStats').get('wins')
        self.wins = wins
        losses = player_info.get('basicStats').get('losses')
        self.losses = losses
        # 百分制
        win_rate = round(wins / (wins + losses) * 100, 2) if wins + losses else 100
        self.win_rate = win_rate
        kpm = player_info.get('basicStats').get('kpm')
        self.kpm = kpm
        spm = player_info.get('basicStats').get('spm')
        self.spm = spm
        # 用spm / 60 * 游玩时间 得出经验值exp,看exp在哪个区间,可确定整数等级
        exp = spm * time_seconds / 60
        rank = 0
        for i in range(len(rank_list)):
            if exp <= rank_list[1]:
                rank = 0
                break
            if exp >= rank_list[-1]:
                rank = 150
                break
            if exp <= rank_list[i]:
                rank = i - 1
                break
        self.rank = rank
        vehicle_kill = sum(item["killsAs"] for item in player_info["vehicleStats"])
        vehicle_kill = int(vehicle_kill)
        self.vehicle_kill = vehicle_kill
        infantry_kill = int(player_info['basicStats']['kills'] - vehicle_kill)
        self.infantry_kill = infantry_kill
        skill = player_info.get('basicStats').get('skill')
        self.skill = skill
        longest_headshot = player_info.get('longestHeadShot')
        self.longest_headshot = longest_headshot
        killAssists = int(player_info.get('killAssists'))
        self.killAssists = killAssists
        highestKillStreak = int(player_info.get('highestKillStreak'))
        self.highestKillStreak = highestKillStreak
        revives = int(player_info.get('revives'))
        self.revives = revives
        heals = int(player_info.get('heals'))
        self.heals = heals
        repairs = int(player_info.get('repairs'))
        self.repairs = repairs
        dogtagsTaken = int(player_info.get('dogtagsTaken'))
        self.dogtagsTaken = dogtagsTaken

    @staticmethod
    async def get_avatar(url: str, pid: Union[str, int]) -> bytes:
        # 如果 URL 为空，直接返回默认头像
        if not url:
            return DefaultAvatarImg
        avatar_path = AvatarPathRoot / f"{pid}.jpg"
        # 如果头像文件存在且最后修改时间距现在不足一天，则直接读取
        if avatar_path.is_file() and avatar_path.stat().st_mtime + 86400 > time.time():
            return avatar_path.read_bytes()
        # 尝试下载头像
        avatar = await PilImageUtils.read_img_by_url(url)
        if avatar:
            avatar_path.write_bytes(avatar)
            return avatar
        elif avatar_path.is_file():
            return avatar_path.read_bytes()
        # 如果下载失败，返回默认头像
        return DefaultAvatarImg

    async def avatar_template_handle(self) -> Image:
        avatar_img_data = None
        local_avatar_path = AvatarPathRoot / f"{self.player_pid}.jpg"

        # 检查本地路径是否存在，如果存在就判断时间是否超过一天，没超过就直接读取头像
        if local_avatar_path.is_file() and \
                (datetime.datetime.now() - datetime.datetime.fromtimestamp(
                    local_avatar_path.stat().st_mtime)) < datetime.timedelta(days=1):
            avatar_img_data = local_avatar_path.read_bytes()
        else:
            # 本地路径不存在，从 self.personas["result"] 或 self.gt_id_info 获取头像链接
            avatar_url = None
            if self.player_pid in self.personas["result"]:
                avatar_url = self.personas["result"][self.player_pid].get("avatar")
            elif isinstance(self.gt_id_info, dict):
                avatar_url = self.gt_id_info.get("avatar")

            if avatar_url:
                avatar_img_data = await self.get_avatar(avatar_url, self.player_pid)
            elif local_avatar_path.is_file():
                avatar_img_data = local_avatar_path.read_bytes()
            else:
                # 链接也获取失败，使用默认头像
                avatar_img_data = DefaultAvatarImg
        avatar_img = Image.open(BytesIO(avatar_img_data))
        # 裁剪为圆形
        avatar_img = PilImageUtils.crop_circle(avatar_img, 79)
        # 根据是否在线选择头像框
        if not self.server_playing_info["result"][self.player_pid]:
            avatar_template = Image.open(BytesIO(AvatarOfflineImg)).convert("RGBA")
        else:
            avatar_template = Image.open(BytesIO(AvatarOnlineImg)).convert("RGBA")
        # 将头像放入头像框,在320,90的位置
        avatar_template.paste(avatar_img, (420, 117), avatar_img)
        # 粘贴名字、PID、时长、等级
        avatar_template_draw = ImageDraw.Draw(avatar_template)
        # 名字
        avatar_template_draw.text(
            (80, 110),
            f"名字: {self.player_name}",
            fill=ColorWhite,
            font=ImageFont.truetype(str(GlobalFontPath), NormalFontSize)
        )
        # PID
        avatar_template_draw.text(
            (80, 160),
            f"PID : {self.player_pid}",
            fill=ColorWhite,
            font=ImageFont.truetype(str(GlobalFontPath), NormalFontSize)
        )
        # 时长
        avatar_template_draw.text(
            (80, 210),
            f"时长: {self.time_played}",
            fill=ColorWhite,
            font=ImageFont.truetype(str(GlobalFontPath), NormalFontSize)
        )
        # 等级
        text_position = (80, 260)
        # 获取"等级: "文本的边界框
        text_bbox = avatar_template_draw.textbbox(
            text_position,
            "等级: ",
            font=ImageFont.truetype(str(GlobalFontPath), NormalFontSize)
        )
        # text_bbox是一个四元组(left, top, right, bottom)，我们可以通过right - left来获取文本的宽度
        text_width = text_bbox[2] - text_bbox[0]
        # 计算数字部分的位置，这里我们仅需要水平位置
        rank_position_x = text_position[0] + text_width
        avatar_template_draw.text(
            text_position,
            "等级: ",
            fill=ColorWhite,  # 假设等级之前的文字是白色
            font=ImageFont.truetype(str(GlobalFontPath), NormalFontSize)
        )
        avatar_template_draw.text(
            (rank_position_x, text_position[1]),
            f"{self.rank}",
            fill=ColorGoldAndGray if self.rank == 150 else ColorBlueAndGray if self.rank >= 100 else ColorWhiteAndGray,
            font=ImageFont.truetype(str(GlobalFontPath), NormalFontSize)
        )
        return avatar_template

    async def get_background(self, pid: Union[str, int], target_width, target_height) -> Image:
        """根据pid查找路径是否存在，如果存在尝试随机选择一张图"""
        background_path = BackgroundPathRoot / f"{pid}"
        player_background_path = self.player_background_path
        if not player_background_path:
            if background_path.exists():
                background = random.choice(list(background_path.iterdir())).open("rb").read()
            else:
                background = random.choice(list(DefaultBackgroundPath.iterdir())).open("rb").read()
        else:
            background = player_background_path.open("rb").read()
        # 默认背景，直接放大填充
        if not player_background_path:
            background_img = PilImageUtils.resize_and_crop_to_center(background, target_width, target_height)
            # 加一点高斯模糊
            # background_img = background_img.filter(ImageFilter.GaussianBlur(radius=5))
        # 自定义背景，先放大填充全部+高斯模糊 然后再放大保留原图自适应全部内容
        else:
            background_img = PilImageUtils.resize_and_crop_to_center(background, target_width, target_height)
            background_img = background_img.filter(ImageFilter.GaussianBlur(radius=30))
            background_img_top = PilImageUtils.scale_image_to_dimension(background, target_width, target_height)
            # 将background_img_top粘贴到background_img上
            background_img = PilImageUtils.paste_center(background_img, background_img_top)
        return background_img

    async def vehicle_template_handle(self, vehicle: dict) -> Image:
        vehicle_name = zhconv.convert(vehicle.get('name'), 'zh-hans')
        kills = int(vehicle["stats"]["values"]["kills"])
        stars = kills // 100
        seconds = vehicle["stats"]["values"]["seconds"]
        kpm = "{:.2f}".format(kills / seconds * 60) if seconds != 0 else kills
        destroyed = int(vehicle["stats"]["values"]["destroyed"])
        if seconds < 3600:
            time_played = f"{round(seconds // 60)}分钟"
        else:
            time_played = f"{round(seconds // 3600)}小时{round(seconds % 3600 // 60)}分钟"
        if kills >= 10000:
            vehicle_template = Image.open(BytesIO(WeaponGoldImg)).convert("RGBA")
        elif kills >= 6000:
            vehicle_template = Image.open(BytesIO(WeaponBlueImg)).convert("RGBA")
        else:
            vehicle_template = Image.open(BytesIO(WeaponWhiteImg)).convert("RGBA")
        vehicle_template_draw = ImageDraw.Draw(vehicle_template)
        # 粘贴载具图片/皮肤图片
        vehicle_guid = vehicle["guid"]
        skin_guids = self.skin_info["result"]["kits"].get(f"{vehicle['sortOrder']}")
        if skin_guids:
            skin_guids = skin_guids[0]
        vehicle_img = None
        skin_level = skin_name = None
        # 下载/获取对应载具的皮肤图片
        if skin_guids:
            for k in skin_guids.keys():
                skin_guid = skin_guids[k]
                skin_all_info = json.loads(open(SkinAllPathRoot, "r", encoding="utf-8").read())
                if skin_all_info.get(skin_guid):
                    skin_url = skin_all_info[skin_guid]["images"]["Png1024xANY"].replace("[BB_PREFIX]", BB_PREFIX)
                    skin_name = zhconv.convert(skin_all_info[skin_guid]["name"], 'zh-hans')
                    skin_level = skin_all_info[skin_guid]["rarenessLevel"]["name"]
                    skin_file_name = skin_url.split("/")[-1]
                    skin_file_path = SkinRootPath / skin_file_name
                    if skin_file_path.exists():
                        vehicle_img = Image.open(skin_file_path).convert("RGBA")
                        break
                    else:
                        vehicle_img = await PilImageUtils.read_img_by_url(skin_url)
                        if vehicle_img:
                            vehicle_img = Image.open(BytesIO(vehicle_img)).convert("RGBA")
                            vehicle_img.save(skin_file_path)
                            break
                        else:
                            logger.warning(f"下载载具皮肤失败，url: {skin_url}")
        if not vehicle_img:
            pic_url = vehicle["imageUrl"].replace("[BB_PREFIX]", BB_PREFIX)
            vehicle_img = await PilImageUtils.read_img_by_url(pic_url)
            vehicle_img = Image.open(BytesIO(vehicle_img)).convert("RGBA")
        # 载具的长宽比1024/256 = 4,等比缩放为384*96
        vehicle_img = vehicle_img.resize((384, 96), Image.LANCZOS)
        # 粘贴到144,20
        vehicle_template.paste(vehicle_img, (144, 20), vehicle_img)
        # 载具星星数
        vehicle_template_draw.text(
            (54, 97),
            f"{stars}",
            fill=ColorGold if stars >= 100 else ColorBlue if stars >= 60 else ColorWhite,
            font=ImageFont.truetype(str(GlobalFontPath), NormalFontSize)
        )
        # 载具名字 55 160  列1:击杀、摧毁 列2:kpm、时长
        start_row = 150
        row_diff_distance = 40
        col1_x = 55
        col2_x = 55 + 220
        vehicle_template_draw.text(
            (col1_x, start_row + row_diff_distance * 0),
            f"{vehicle_name}",
            fill=ColorWhite,
            font=ImageFont.truetype(str(GlobalFontPath), StatFontSize)
        )
        if skin_name:
            vehicle_template_draw.text(
                (20, 65),
                f"{skin_name}",
                fill=ColorGoldAndGray if skin_level == "Superior"
                else ColorBlueAndGray if skin_level == "Enhanced"
                else ColorWhiteAndGray,
                font=ImageFont.truetype(str(GlobalFontPath), SkinFontSize)
            )
        vehicle_template_draw.text(
            (col1_x, start_row + row_diff_distance * 1),
            f"击杀: {kills}",
            fill=ColorWhite,
            font=ImageFont.truetype(str(GlobalFontPath), StatFontSize)
        )
        vehicle_template_draw.text(
            (col1_x, start_row + row_diff_distance * 2),
            f"摧毁: {destroyed}",
            fill=ColorWhite,
            font=ImageFont.truetype(str(GlobalFontPath), StatFontSize)
        )
        vehicle_template_draw.text(
            (col2_x, start_row + row_diff_distance * 1),
            f"KPM: {kpm}",
            fill=ColorWhite,
            font=ImageFont.truetype(str(GlobalFontPath), StatFontSize)
        )
        vehicle_template_draw.text(
            (col2_x, start_row + row_diff_distance * 2),
            f"时长: {time_played}",
            fill=ColorWhite,
            font=ImageFont.truetype(str(GlobalFontPath), StatFontSize)
        )
        return vehicle_template

    async def draw(
            self,
            col: int = 2,
            row: int = 4,
    ) -> Union[bytes, Path, None]:
        """绘制载具数据图片
        与生涯不同，载具只绘制头像框+载具数据，默认为两列四行
        这里是动态计算,每个载具框距离左边边界间距:90,列间距:43,行间距:25,右边边界间距:90，
        获取vehicles的长度，图片一行最多允许8列，每8个载具换一行，行数最多为10行，所以最多80个载具，
        图片总宽度为90 + 载具框宽度 * 列数 + 列间距 * (列数 - 1) + 90
        图片总高度为60 + 头像框高度 + 载具框高度 * 行数 + 行间距 * (行数 - 1) + 60
        载具框: 570x320
        头像框: 631x349
        """
        vehicles = []
        if not self.vehicles:
            return None
        else:
            for vehicle in self.vehicles:
                if not vehicle.get("stats").get('values'):
                    continue
                vehicles.append(vehicle)
        # 整理成col列row行的列表
        if col > 8:
            col = 8
        if row > 10:
            row = 10
        vehicle_data = [vehicles[i * col:(i + 1) * col] for i in range(row)]
        col_origin = col
        row_origin = row
        col = len(vehicle_data[0])
        row = len(vehicle_data)
        vehicle_template_num = col * row

        # 图片大小
        image_width = 90 + 570 * col + 43 * (col - 1) + 90
        image_height = 60 + 349 + 320 * row + 25 * (row - 1) + 60
        vehicle_template_width = 570  # 每个载具模板的宽度为570像素
        vehicle_template_height = 320  # 每个载具模板的高度为320像素
        # 画布
        output_img = Image.new("RGB", (image_width, image_height), ColorWhite)

        # 粘贴背景
        background_img = await self.get_background(self.player_pid, image_width, image_height)
        output_img = PilImageUtils.paste_center(output_img, background_img)

        # 粘贴头像框
        avatar_template = await self.avatar_template_handle()
        output_img.paste(avatar_template, (58, 60), avatar_template)

        # 粘贴载具信息
        vehicle_templates = []
        for vehicle in vehicle_data[:vehicle_template_num]:
            for item in vehicle:
                vehicle_template = await self.vehicle_template_handle(item)
                vehicle_templates.append(vehicle_template)
        # 整理成col_origin列row_origin行的列表
        vehicle_templates = [vehicle_templates[i * col_origin:(i + 1) * col_origin] for i in range(row_origin)]
        # 粘贴载具信息
        row_diff_distance = vehicle_template_height + 25
        start_row = 60 + 349 + 25
        col_diff_distance = vehicle_template_width + 43
        start_col = 90

        for row_index, vehicle_template_row in enumerate(vehicle_templates):
            for col_index, vehicle_template in enumerate(vehicle_template_row):
                # 计算每个载具模板的粘贴位置
                paste_x = start_col + col_diff_distance * col_index
                paste_y = start_row + row_diff_distance * row_index
                output_img.paste(
                    vehicle_template,
                    (paste_x, paste_y),
                    vehicle_template
                )

        # 水印和时间
        output_img_draw = ImageDraw.Draw(output_img)
        # 居中
        PilImageUtils.draw_centered_text(
            output_img_draw,
            "Powered by XiaoMaiBot | Made by 13&&XM | " + time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
            (image_width // 2, image_height - 20),
            fill=(253, 245, 242),
            font=ImageFont.truetype(str(GlobalFontPath), StatFontSize)
        )

        # 存为 FileTempSaveRoot / 时间戳.png
        file_path = FileTempSaveRoot / f"{round(time.time() * 1000)}.png"
        # output_img.save(file_path, format="PNG")
        # 存为jpeg
        output_img.save(file_path, format="JPEG", quality=95)
        return file_path


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

        rank_list = [
            0, 1000, 5000, 15000, 25000, 40000, 55000, 75000, 95000, 120000, 145000, 175000, 205000, 235000,
            265000, 295000, 325000, 355000, 395000, 435000, 475000, 515000, 555000, 595000, 635000, 675000, 715000,
            755000, 795000, 845000, 895000, 945000, 995000, 1045000, 1095000, 1145000, 1195000, 1245000, 1295000,
            1345000, 1405000, 1465000, 1525000, 1585000, 1645000, 1705000, 1765000, 1825000, 1885000, 1945000,
            2015000, 2085000, 2155000, 2225000, 2295000, 2365000, 2435000, 2505000, 2575000, 2645000, 2745000,
            2845000, 2945000, 3045000, 3145000, 3245000, 3345000, 3445000, 3545000, 3645000, 3750000, 3870000,
            4000000, 4140000, 4290000, 4450000, 4630000, 4830000, 5040000, 5260000, 5510000, 5780000, 6070000,
            6390000, 6730000, 7110000, 7510000, 7960000, 8430000, 8960000, 9520000, 10130000, 10800000, 11530000,
            12310000, 13170000, 14090000, 15100000, 16190000, 17380000, 20000000, 20500000, 21000000, 21500000,
            22000000, 22500000, 23000000, 23500000, 24000000, 24500000, 25000000, 25500000, 26000000, 26500000,
            27000000, 27500000, 28000000, 28500000, 29000000, 29500000, 30000000, 30500000, 31000000, 31500000,
            32000000, 32500000, 33000000, 33500000, 34000000, 34500000, 35000000, 35500000, 36000000, 36500000,
            37000000, 37500000, 38000000, 38500000, 39000000, 39500000, 40000000, 41000000, 42000000, 43000000,
            44000000, 45000000, 46000000, 47000000, 48000000, 49000000, 50000000
        ]

        playerlist_data["teams"] = {
            0: [item for item in playerlist_data["players"] if item["team"] == 0],
            1: [item for item in playerlist_data["players"] if item["team"] == 1]
        }

        # 获取玩家生涯战绩
        # 队伍1
        scrape_index_tasks_t1 = [
            asyncio.ensure_future((await BF1DA.get_api_instance()).detailedStatsByPersonaId(player_item['pid'])) for
            player_item in playerlist_data["teams"][0]]
        tasks = asyncio.gather(*scrape_index_tasks_t1)
        try:
            await tasks
            for i in range(len(playerlist_data["teams"][0])):
                if scrape_index_tasks_t1[i].result():
                    player_stat_data = scrape_index_tasks_t1[i].result()["result"]
                    # 重新计算等级
                    time_seconds = player_stat_data.get('basicStats').get('timePlayed')
                    spm = player_stat_data.get('basicStats').get('spm')
                    exp = spm * time_seconds / 60
                    rank = 0
                    for _ in range(len(rank_list)):
                        if exp <= rank_list[1]:
                            rank = 0
                            break
                        if exp >= rank_list[-1]:
                            rank = 150
                            break
                        if exp <= rank_list[_]:
                            rank = _ - 1
                            break
                    playerlist_data["teams"][0][i]["rank"] = rank
        except asyncio.TimeoutError:
            pass

        # 队伍2
        scrape_index_tasks_t2 = [
            asyncio.ensure_future((await BF1DA.get_api_instance()).detailedStatsByPersonaId(player_item['pid'])) for
            player_item in playerlist_data["teams"][1]]
        tasks = asyncio.gather(*scrape_index_tasks_t2)
        try:
            await tasks
            for i in range(len(playerlist_data["teams"][1])):
                if scrape_index_tasks_t2[i].result():
                    player_stat_data = scrape_index_tasks_t2[i].result()["result"]
                    # 重新计算等级
                    time_seconds = player_stat_data.get('basicStats').get('timePlayed')
                    spm = player_stat_data.get('basicStats').get('spm')
                    exp = spm * time_seconds / 60
                    rank = 0
                    for _ in range(len(rank_list)):
                        if exp <= rank_list[1]:
                            rank = 0
                            break
                        if exp >= rank_list[-1]:
                            rank = 150
                            break
                        if exp <= rank_list[_]:
                            rank = _ - 1
                            break
                    playerlist_data["teams"][1][i]["rank"] = rank
        except asyncio.TimeoutError:
            pass

        # 按等级排序
        playerlist_data["teams"][0].sort(key=lambda x: x["rank"], reverse=True)
        playerlist_data["teams"][1].sort(key=lambda x: x["rank"], reverse=True)
        update_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(playerlist_data["time"]))

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
        font_path = './statics/fonts/simhei.ttf'
        font_prop = fm.FontProperties(fname=font_path)

        def plot_comparison_bar_chart_sns(data, title, rotation=0):
            official_color = "#9ebc62"
            private_color = "#e68d63"
            df = pd.DataFrame(data)
            ax = df.plot(kind='bar', figsize=(12, 6), color=[official_color, private_color])
            plt.title(title, fontproperties=font_prop)
            plt.ylabel('数量', fontproperties=font_prop)
            plt.xticks(rotation=rotation, fontproperties=font_prop)
            legend = ax.legend(prop=font_prop)
            plt.setp(legend.get_texts(), fontproperties=font_prop)
            plt.setp(legend.get_title(), fontproperties=font_prop)
            for p in ax.patches:
                ax.annotate(
                    str(int(p.get_height())), (p.get_x() + p.get_width() / 2., p.get_height()),
                    ha='center', va='center', xytext=(0, 10), textcoords='offset points', fontproperties=font_prop
                )
            plt.tight_layout()

            buffer_temp = io.BytesIO()
            plt.savefig(buffer_temp, format='png', bbox_inches='tight')
            plt.close()

            return Image.open(buffer_temp)

        region_country_comparison_data = {
            "官服": {},
            "私服": {}
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
        plt.pie(
            total_players_data.values(), labels=total_players_data.keys(), autopct='%1.0f%%', startangle=90,
            colors=sns.color_palette("coolwarm"), textprops={'fontproperties': font_prop}
        )
        plt.title(
            f"BF1当前游玩总人数：{sum(total_players_data.values())}\n{datetime.datetime.now().strftime('%Y年%m月%d日 %H:%M:%S')}",
            fontproperties=font_prop
        )
        plt.axis('equal')
        buf_pie = io.BytesIO()
        plt.savefig(buf_pie, format='png', bbox_inches='tight', transparent=True)
        plt.close()
        plot5 = Image.open(buf_pie)

        # 合成为一张图片
        merged_image = Image.new('RGB', (plot1.width, plot1.height * 4 + plot5.height), (255, 255, 255))
        merged_image.paste(plot1, (0, 0))
        merged_image.paste(plot2, (0, plot1.height))
        merged_image.paste(plot5, (int((plot1.width - plot5.width) / 2), plot1.height * 2))
        merged_image.paste(plot3, (0, plot1.height * 2 + plot5.height))
        merged_image.paste(plot4, (0, plot1.height * 3 + plot5.height))

        buf = io.BytesIO()
        merged_image.save(buf, format='PNG')
        data_bytes = buf.getvalue()

        return data_bytes
