from typing import Union


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
