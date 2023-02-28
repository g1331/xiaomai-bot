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

    async def get_data(self) -> dict:
        from modules.self_contained.bf1_info import get_weapon_data, get_vehicle_data, get_player_stat_data
        try:
            if self.player_cache_type == "weapon":
                data = await get_weapon_data(self.pid)
            elif self.player_cache_type == "vehicle":
                data = await get_vehicle_data(self.pid)
            else:
                data = await get_player_stat_data(self.pid)
            return data
        except Exception as e:
            logger.warning(f"获取{self.pid}-{self.player_cache_type}数据失败:{e}")
            return None


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
