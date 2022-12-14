import json
import os
import time

import aiofiles
from creart import create

from core.config import GlobalConfig

global_config = create(GlobalConfig)
default_account = global_config.bf1.get("default_account")


class record(object):
    # 创建配置文件
    @staticmethod
    async def config_bind(qq_id: int):
        """
        检查创建qq号文件夹-record和bind的json文件
        :param qq_id: qq号
        :return: bool
        """
        file_path = f'./data/battlefield/binds/players/{qq_id}'
        # 创建文件夹
        if not os.path.exists(file_path):
            os.makedirs(file_path)
        # 创建查询记录文件
        if not os.path.isfile(file_path + f'/record.json'):
            init_data = {
                "bind": {
                    "history": [

                    ]
                },
                "weapon": {
                    "history": [

                    ]
                },
                "vehicle": {
                    "history": [

                    ]
                },
                "stat": {
                    "history": [

                    ]
                },
                "recent": {
                    "history": [

                    ]
                },
                "matches": {
                    "history": [

                    ]
                },
                "server_playing": {
                    "history": [

                    ]
                },
                "lookup_other": {
                    "history": [
                    ]
                }
            }
            async with aiofiles.open(f"{file_path}/record.json", 'w', encoding="utf-8") as file_temp:
                await file_temp.write(json.dumps(init_data, indent=4, ensure_ascii=False))
        # 创建绑定文件
        if not os.path.exists(file_path + f'/bind.json'):
            open(f"{file_path}/bind.json", 'w', encoding="utf-8")
        # 如果不可读则初始化
        try:
            async with aiofiles.open(f"{file_path}/record.json", 'r', encoding="utf-8") as file_temp:
                json.loads(await file_temp.read())
        except:
            init_data = {
                "bind": {
                    "history": [

                    ]
                },
                "weapon": {
                    "history": [

                    ]
                },
                "vehicle": {
                    "history": [

                    ]
                },
                "stat": {
                    "history": [

                    ]
                },
                "recent": {
                    "history": [

                    ]
                },
                "matches": {
                    "history": [

                    ]
                },
                "server_playing": {
                    "history": [

                    ]
                },
                "lookup_other": {
                    "history": [
                    ]
                }
            }
            async with aiofiles.open(f"{file_path}/record.json", 'w', encoding="utf-8") as file_temp:
                await file_temp.write(json.dumps(init_data, indent=4, ensure_ascii=False))
        return True

    # 检查绑定没有
    @staticmethod
    def check_bind(qq_id: int) -> bool:
        """
        检查绑定没有
        :param qq_id: qq号
        :return: bool
        """
        file_path = f'./data/battlefield/binds/players/{qq_id}'
        # 创建文件夹
        if os.path.exists(file_path):
            return True
        else:
            return False

    # 从绑定的缓存获取pid
    @staticmethod
    async def get_bind_pid(qq_id: int) -> int:
        """
        从绑定的缓存获取pid
        :param qq_id: qq号
        :return: pid
        """
        file_path = f'./data/battlefield/binds/players/{qq_id}'
        async with aiofiles.open(f"{file_path}/bind.json", 'r', encoding="utf-8") as file_temp:
            data = json.loads(await file_temp.read())
            pid = data['personas']['persona'][0]['personaId']
            return pid

    # 从缓存获取displayname
    @staticmethod
    async def get_bind_name(qq_id: int) -> str:
        """
        从绑定的缓存获取pid
        :param qq_id: qq号
        :return: pid
        """
        file_path = f'./data/battlefield/binds/players/{qq_id}'
        async with aiofiles.open(f"{file_path}/bind.json", 'r', encoding="utf-8") as file_temp:
            data = json.loads(await file_temp.read())
            name = data['personas']['persona'][0]['displayName']
            return name

    # 从缓存获取uid
    @staticmethod
    async def get_bind_uid(qq_id: int) -> str:
        """
        从绑定的缓存获取pid
        :param qq_id: qq号
        :return: pid
        """
        file_path = f'./data/battlefield/binds/players/{qq_id}'
        async with aiofiles.open(f"{file_path}/bind.json", 'r', encoding="utf-8") as file_temp:
            data = json.loads(await file_temp.read())
            name = data['personas']['persona'][0]['pidId']
            return name

    # 获取主session
    @staticmethod
    async def get_session() -> str:
        """
        获取主session
        :return: session
        """
        file_path = f'./data/battlefield/managerAccount/{default_account}/session.json'
        async with aiofiles.open(file_path, 'r', encoding="utf-8") as file_temp:
            session = json.loads(await file_temp.read())["session"]
            return session

    # 绑定计数
    @staticmethod
    async def bind_counter(qq_id: int, bind_info: str):
        """
        绑定计数器
        :param qq_id: qq号
        :param bind_info: 绑定的name和pid
        :return: None
        """
        time_now = time.strftime('%Y/%m/%d/%H:%M:%S', time.localtime(time.time()))
        await record.config_bind(qq_id)
        file_path = f'./data/battlefield/binds/players/{qq_id}'
        async with aiofiles.open(f"{file_path}/record.json", 'r', encoding="utf-8") as file_temp:
            data_temp = json.loads(await file_temp.read())
            data_temp["bind"]["history"].append(f"{time_now}-{bind_info}")
            async with aiofiles.open(f"{file_path}/record.json", 'w', encoding="utf-8") as file_temp2:
                await file_temp2.write(json.dumps(data_temp, indent=4, ensure_ascii=False))

    # 获取绑定次数
    @staticmethod
    async def get_bind_counter(qq_id: int) -> list:
        file_path = f'./data/battlefield/binds/players/{qq_id}'
        try:
            async with aiofiles.open(f"{file_path}/record.json", 'r', encoding="utf-8") as file_temp:
                data_temp = json.loads(await file_temp.read())
                return data_temp["bind"]["history"]
        except Exception as e:
            return []

    # 武器计数
    @staticmethod
    async def weapon_counter(qq_id: int, player_id: str, player_name: str, weapon_type: str):
        """
        武器计数器
        :param weapon_type: 武器类型
        :param qq_id: qq号
        :param player_id: pid
        :param player_name: 名字
        :return: None
        """
        time_now = time.strftime('%Y/%m/%d/%H:%M:%S', time.localtime(time.time()))
        await record.config_bind(qq_id)
        file_path = f'./data/battlefield/binds/players/{qq_id}'
        async with aiofiles.open(f"{file_path}/record.json", 'r', encoding="utf-8") as file_temp:
            data_temp = json.loads(await file_temp.read())
            data_temp["weapon"]["history"].append(f"{time_now}-{player_id}-{player_name}-{weapon_type}")
            async with aiofiles.open(f"{file_path}/record.json", 'w', encoding="utf-8") as file_temp2:
                await file_temp2.write(json.dumps(data_temp, indent=4, ensure_ascii=False))

    # 获取武器查询次数
    @staticmethod
    async def get_weapon_counter(qq_id: int) -> list:
        file_path = f'./data/battlefield/binds/players/{qq_id}'
        try:
            async with aiofiles.open(f"{file_path}/record.json", 'r', encoding="utf-8") as file_temp:
                data_temp = json.loads(await file_temp.read())
                return data_temp["weapon"]["history"]
        except Exception as e:
            return []

    # 载具计数
    @staticmethod
    async def vehicle_counter(qq_id: int, player_id: str, player_name: str, vehicle_type: str):
        """
        载具
        :param vehicle_type: 载具类型
        :param qq_id: qq号
        :param player_id: pid
        :param player_name: 名字
        :return: None
        """
        time_now = time.strftime('%Y/%m/%d/%H:%M:%S', time.localtime(time.time()))
        await record.config_bind(qq_id)
        file_path = f'./data/battlefield/binds/players/{qq_id}'
        async with aiofiles.open(f"{file_path}/record.json", 'r', encoding="utf-8") as file_temp:
            data_temp = json.loads(await file_temp.read())
            data_temp["vehicle"]["history"].append(f"{time_now}-{player_id}-{player_name}-{vehicle_type}")
            async with aiofiles.open(f"{file_path}/record.json", 'w', encoding="utf-8") as file_temp2:
                await file_temp2.write(json.dumps(data_temp, indent=4, ensure_ascii=False))

    # 获取载具查询次数
    @staticmethod
    async def get_vehicle_counter(qq_id: int) -> list:
        file_path = f'./data/battlefield/binds/players/{qq_id}'
        try:
            async with aiofiles.open(f"{file_path}/record.json", 'r', encoding="utf-8") as file_temp:
                data_temp = json.loads(await file_temp.read())
                return data_temp["vehicle"]["history"]
        except Exception as e:
            return []

    # 生涯计数
    @staticmethod
    async def player_stat_counter(qq_id: int, player_id: str, player_name: str):
        """
        生涯
        :param qq_id: qq号
        :param player_id: pid
        :param player_name: 名字
        :return: None
        """
        time_now = time.strftime('%Y/%m/%d/%H:%M:%S', time.localtime(time.time()))
        await record.config_bind(qq_id)
        file_path = f'./data/battlefield/binds/players/{qq_id}'
        async with aiofiles.open(f"{file_path}/record.json", 'r', encoding="utf-8") as file_temp:
            data_temp = json.loads(await file_temp.read())
            data_temp["stat"]["history"].append(f"{time_now}-{player_id}-{player_name}")
            async with aiofiles.open(f"{file_path}/record.json", 'w', encoding="utf-8") as file_temp2:
                await file_temp2.write(json.dumps(data_temp, indent=4, ensure_ascii=False))

    # 获取生涯查询次数
    @staticmethod
    async def get_stat_counter(qq_id: int) -> list:
        file_path = f'./data/battlefield/binds/players/{qq_id}'
        try:
            async with aiofiles.open(f"{file_path}/record.json", 'r', encoding="utf-8") as file_temp:
                data_temp = json.loads(await file_temp.read())
                return data_temp["stat"]["history"]
        except Exception as e:
            return []

    # 最近计数
    @staticmethod
    async def recent_counter(qq_id: int, player_id: str, player_name: str):
        """
        最近
        :param qq_id: qq号
        :param player_id: pid
        :param player_name: 名字
        :return: None
        """
        time_now = time.strftime('%Y/%m/%d/%H:%M:%S', time.localtime(time.time()))
        await record.config_bind(qq_id)
        file_path = f'./data/battlefield/binds/players/{qq_id}'
        async with aiofiles.open(f"{file_path}/record.json", 'r', encoding="utf-8") as file_temp:
            data_temp = json.loads(await file_temp.read())
            data_temp["recent"]["history"].append(f"{time_now}-{player_id}-{player_name}")
            async with aiofiles.open(f"{file_path}/record.json", 'w', encoding="utf-8") as file_temp2:
                await file_temp2.write(json.dumps(data_temp, indent=4, ensure_ascii=False))

    # 获取最近查询次数
    @staticmethod
    async def get_recent_counter(qq_id: int) -> list:
        file_path = f'./data/battlefield/binds/players/{qq_id}'
        try:
            async with aiofiles.open(f"{file_path}/record.json", 'r', encoding="utf-8") as file_temp:
                data_temp = json.loads(await file_temp.read())
                return data_temp["recent"]["history"]
        except Exception as e:
            return []

    # 对局计数
    @staticmethod
    async def matches_counter(qq_id: int, player_id: str, player_name: str):
        """
        对局
        :param qq_id: qq号
        :param player_id: pid
        :param player_name: 名字
        :return: None
        """
        time_now = time.strftime('%Y/%m/%d/%H:%M:%S', time.localtime(time.time()))
        await record.config_bind(qq_id)
        file_path = f'./data/battlefield/binds/players/{qq_id}'
        async with aiofiles.open(f"{file_path}/record.json", 'r', encoding="utf-8") as file_temp:
            data_temp = json.loads(await file_temp.read())
            data_temp["matches"]["history"].append(f"{time_now}-{player_id}-{player_name}")
            async with aiofiles.open(f"{file_path}/record.json", 'w', encoding="utf-8") as file_temp2:
                await file_temp2.write(json.dumps(data_temp, indent=4, ensure_ascii=False))

    # 获取对局查询次数
    @staticmethod
    async def get_matches_counter(qq_id: int) -> list:
        file_path = f'./data/battlefield/binds/players/{qq_id}'
        try:
            async with aiofiles.open(f"{file_path}/record.json", 'r', encoding="utf-8") as file_temp:
                data_temp = json.loads(await file_temp.read())
                return data_temp["matches"]["history"]
        except Exception as e:
            return []

    # 天眼查计数
    @staticmethod
    async def tyc_counter(qq_id: int, player_id: str, player_name: str):
        """
        天眼查
        :param qq_id: qq号
        :param player_id: pid
        :param player_name: 名字
        :return: None
        """
        time_now = time.strftime('%Y/%m/%d/%H:%M:%S', time.localtime(time.time()))
        await record.config_bind(qq_id)
        file_path = f'./data/battlefield/binds/players/{qq_id}'
        async with aiofiles.open(f"{file_path}/record.json", 'r', encoding="utf-8") as file_temp:
            data_temp = json.loads(await file_temp.read())
            if "tyc" not in data_temp:
                data_temp["tyc"] = {"history": [
                ]}
            data_temp["tyc"]["history"].append(f"{time_now}-{player_id}-{player_name}")
            async with aiofiles.open(f"{file_path}/record.json", 'w', encoding="utf-8") as file_temp2:
                await file_temp2.write(json.dumps(data_temp, indent=4, ensure_ascii=False))

    # 获取天眼查查询次数
    @staticmethod
    async def get_tyc_counter(qq_id: int) -> list:
        file_path = f'./data/battlefield/binds/players/{qq_id}'
        try:
            async with aiofiles.open(f"{file_path}/record.json", 'r', encoding="utf-8") as file_temp:
                data_temp = json.loads(await file_temp.read())
                return data_temp["tyc"]["history"]
        except Exception as e:
            return []

    # 举报计数
    @staticmethod
    async def report_counter(qq_id: int, player_id: str, player_name: str):
        """
        天眼查
        :param qq_id: qq号
        :param player_id: pid
        :param player_name: 名字
        :return: None
        """
        time_now = time.strftime('%Y/%m/%d/%H:%M:%S', time.localtime(time.time()))
        await record.config_bind(qq_id)
        file_path = f'./data/battlefield/binds/players/{qq_id}'
        async with aiofiles.open(f"{file_path}/record.json", 'r', encoding="utf-8") as file_temp:
            data_temp = json.loads(await file_temp.read())
            if "report" not in data_temp:
                data_temp["report"] = {"history": [
                ]}
            data_temp["report"]["history"].append(f"{time_now}-举报-{player_id}-{player_name}")
            async with aiofiles.open(f"{file_path}/record.json", 'w', encoding="utf-8") as file_temp2:
                await file_temp2.write(json.dumps(data_temp, indent=4, ensure_ascii=False))

    # 获取举报查询次数
    @staticmethod
    async def get_report_counter(qq_id: int) -> list:
        file_path = f'./data/battlefield/binds/players/{qq_id}'
        try:
            async with aiofiles.open(f"{file_path}/record.json", 'r', encoding="utf-8") as file_temp:
                data_temp = json.loads(await file_temp.read())
                return data_temp["report"]["history"]
        except Exception as e:
            return []
