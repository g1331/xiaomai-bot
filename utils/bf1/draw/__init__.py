import datetime
from io import BytesIO
from typing import Union
from loguru import logger
from zhconv import zhconv
from PIL import Image, ImageDraw, ImageFont

from utils.bf1.bf_utils import download_skin


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
    def __init__(self, weapon_data: list = None):
        """初始化处理数据,使用模板html转图片
        :param weapon_data: 武器数据
        """
        self.weapon_data: list = weapon_data

    async def draw(self, play_name: str, row: int, col: int) -> Union[bytes, None]:
        """绘制武器数据图片"""
        if not self.weapon_data:
            return None

    async def draw_search(self, play_name: str, row: int, col: int) -> Union[bytes, None]:
        """绘制武器数据图片"""
        if not self.weapon_data:
            return None


class PlayerVehiclePic:
    def __init__(self, vehicle_data: list = None):
        """初始化处理数据,使用模板html转图片
        :param vehicle_data: 载具数据
        """
        self.vehicle_data: list = vehicle_data

    async def draw(self, play_name: str, row: int, col: int) -> Union[bytes, None]:
        """绘制载具数据图片"""
        if not self.vehicle_data:
            return None

    async def draw_search(self, play_name: str, row: int, col: int) -> Union[bytes, None]:
        """绘制载具数据图片"""
        if not self.vehicle_data:
            return None


class Exchange:
    def __init__(self, data: dict = None):
        """初始化处理数据,使用模板html转图片
        :param data: 兑换数据
        """
        self.data: dict = data
        self.img: bytes = None

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
            temp_list.append(zhconv.convert(parentName + "外观", 'zh-cn'))
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
            while y + 225 < 1322:
                while x + 220 < 2351 and i < len(SE_list):
                    if SE_list[i][3] == "特殊":
                        i += 1
                        continue
                    # 从上到下分别是武器图片、武器名字、皮肤名字、品质、价格
                    # [300, '魯特斯克戰役', 'SMG 08/18', '特殊', 'https://eaassets-a.akamaihd.net/battlelog/battlebinary/gamedata/Tunguska/123/1/U_MAXIMSMG_BATTLEPACKS_FABERGE_T1S3_LARGE-7b01c879.png']
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
        logger.info("更新交换缓存成功!")
        # 返回bytes
        output_buffer = BytesIO()
        bg_img.save(output_buffer, format='PNG')
        self.img = output_buffer.getvalue()
        return self.img
