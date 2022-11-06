import json
import os
import time

from loguru import logger


class InfoCache(object):

    def __init__(self, player_pid: str, player_cache_type: str):
        """
        初始化
        :param player_pid: 玩家pid
        :param player_cache_type: stat, weapon, vehicle
        """
        self.pid = player_pid
        self.player_cache_type = player_cache_type
        self.player_cache_path = f"./data/battlefield/players/{player_pid}"
        self.file_cache_path = f"{self.player_cache_path}/{player_cache_type}.json"

        # 创建玩家文件
        if not os.path.exists(self.player_cache_path):
            os.makedirs(self.player_cache_path)
            logger.success(f"成功创建{self.pid}档案")
        if not os.path.exists(self.file_cache_path):
            open(self.file_cache_path, 'w', encoding='utf-8')

    def get_cache_changedTime(self) -> float:
        return os.path.getmtime(self.file_cache_path)

    def check_if_need_api(self) -> bool:
        try:
            with open(self.file_cache_path, "r", encoding="utf-8") as file:
                data = json.load(file)
                if "error" in data:
                    return True
        except:
            return True
        if time.time() - self.get_cache_changedTime() >= 900:
            return True
        elif time.time() - self.get_cache_changedTime() <= 2:
            return True
        else:
            return False

    async def read_cache(self) -> dict:
        try:
            with open(self.file_cache_path, "r", encoding="utf-8") as file:
                data = json.load(file)
                return data
        except Exception as e:
            logger.error(e)
            await self.update_cache()
            with open(self.file_cache_path, "r", encoding="utf-8") as file:
                data = json.load(file)
                return data

    async def update_cache(self) -> bool:
        from modules.bf1战绩 import get_weapon_data, get_vehicle_data, get_player_stat_data
        try:
            if self.player_cache_type == "weapon":
                data = await get_weapon_data(self.pid)
            elif self.player_cache_type == "vehicle":
                data = await get_vehicle_data(self.pid)
            else:
                data = await get_player_stat_data(self.pid)
            with open(self.file_cache_path, 'w', encoding="utf-8") as file:
                json.dump(data, file, indent=4, ensure_ascii=False)
            return True
        except Exception as e:
            logger.warning(f"更新{self.pid}-{self.player_cache_type}缓存失败:{e}")
            return False

    async def get_data(self) -> dict:
        if self.check_if_need_api():
            await self.update_cache()
            return await self.read_cache()
        else:
            return await self.read_cache()


class InfoCache_stat(InfoCache):
    def __init__(self, player_pid: str):
        """
        初始化
        """
        self.player_cache_type = "stat"
        super().__init__(player_pid, self.player_cache_type)


class InfoCache_weapon(InfoCache):
    def __init__(self, player_pid: str):
        """
        初始化
        """
        self.player_cache_type = "weapon"
        super().__init__(player_pid, self.player_cache_type)


class InfoCache_vehicle(InfoCache):
    def __init__(self, player_pid: str):
        """
        初始化
        """
        self.player_cache_type = "vehicle"
        super().__init__(player_pid, self.player_cache_type)


class InfoCache_account(InfoCache):
    def __init__(self, player_pid: str):
        """
        初始化
        """
        self.player_cache_type = "account"
        super().__init__(player_pid, self.player_cache_type)
