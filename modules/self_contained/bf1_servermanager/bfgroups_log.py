import time
import yaml
from typing import Union


class rsp_log(object):

    @staticmethod
    def init_log(bfgroups_name: str):
        with open(f'./data/battlefield/binds/bfgroups/{bfgroups_name}/log.yaml', 'r', encoding="utf-8") as file1:
            data = yaml.load(file1, yaml.Loader)
            if data is None:
                data = {
                    "total": [],
                    "operators": {}
                }
                with open(f'./data/battlefield/binds/bfgroups/{bfgroups_name}/log.yaml', 'w',
                          encoding="utf-8") as file_temp2:
                    yaml.dump(data, file_temp2, allow_unicode=True)

    @staticmethod
    def kick_logger(qq_id: Union[int, str], group_id, action_object: str, server_id, reason: str):
        """
        记录踢人的日志
        :param reason: 踢出理由
        :param qq_id: qq号
        :param group_id: qq群号
        :param action_object: 踢出对象-name
        :param server_id:服务器serverid
        :return: 无
        """
        # 先检查绑定群组没
        group_path = f'./data/battlefield/binds/groups/{group_id}'
        file_path = group_path + "/bfgroups.yaml"
        # 打开绑定的文件
        with open(file_path, 'r', encoding="utf-8") as file1:
            data = yaml.load(file1, yaml.Loader)
            bfgroups_name = data["bfgroups"]
        # 记录数据 这里进行一个初始化检测
        rsp_log.init_log(bfgroups_name)
        with open(f'./data/battlefield/binds/bfgroups/{bfgroups_name}/log.yaml', 'r', encoding="utf-8") as file1:
            data = yaml.load(file1, yaml.Loader)
            if qq_id not in data["operators"]:
                data["operators"][qq_id] = []
            time_now = time.strftime('%Y/%m/%d/%H:%M:%S', time.localtime(time.time()))
            data["operators"][qq_id].append(f"{time_now}-踢出-踢出原因:{reason}-{action_object}-{server_id}")
            data["total"].append(f"{time_now}-{qq_id}-踢出-踢出原因:{reason}-{action_object}-{server_id}")
            with open(f'./data/battlefield/binds/bfgroups/{bfgroups_name}/log.yaml', 'w',
                      encoding="utf-8") as file_temp2:
                yaml.dump(data, file_temp2, allow_unicode=True)

    @staticmethod
    def ban_logger(qq_id: Union[int, str], action_object: str, server_id, reason: str,
                   bfgroups_name: str = None, group_id: int = None):
        """
        记录封禁的日志
        :param bfgroups_name: 如果没有群号就传入这个
        :param reason: 封禁理由
        :param qq_id: qq号
        :param group_id: qq群号
        :param action_object: 封禁对象-name
        :param server_id:服务器serverid
        :return: 无
        """
        # 先检查绑定群组没
        if group_id:
            group_path = f'./data/battlefield/binds/groups/{group_id}'
            file_path = group_path + "/bfgroups.yaml"
            # 打开绑定的文件
            with open(file_path, 'r', encoding="utf-8") as file1:
                data = yaml.load(file1, yaml.Loader)
                bfgroups_name = data["bfgroups"]
        # 记录数据 这里进行一个初始化检测
        rsp_log.init_log(bfgroups_name)
        with open(f'./data/battlefield/binds/bfgroups/{bfgroups_name}/log.yaml', 'r', encoding="utf-8") as file1:
            data = yaml.load(file1, yaml.Loader)
            if qq_id not in data["operators"]:
                data["operators"][qq_id] = []
            time_now = time.strftime('%Y/%m/%d/%H:%M:%S', time.localtime(time.time()))
            data["operators"][qq_id].append(f"{time_now}-封禁-封禁原因:{reason}-{action_object}-{server_id}")
            data["total"].append(f"{time_now}-{qq_id}-封禁-封禁原因:{reason}-{action_object}-{server_id}")
            with open(f'./data/battlefield/binds/bfgroups/{bfgroups_name}/log.yaml', 'w',
                      encoding="utf-8") as file_temp2:
                yaml.dump(data, file_temp2, allow_unicode=True)

    @staticmethod
    def unban_logger(qq_id: Union[int, str], action_object: str, server_id, group_id=None, bfgroups_name=None):
        """
        记录解封的日志
        :param bfgroups_name: 如果没有群号就传入这个
        :param qq_id: qq号
        :param group_id: qq群号
        :param action_object: 解封对象-name
        :param server_id:服务器serverid
        :return: 无
        """
        # 先检查绑定群组没
        if group_id:
            group_path = f'./data/battlefield/binds/groups/{group_id}'
            file_path = group_path + "/bfgroups.yaml"
            # 打开绑定的文件
            with open(file_path, 'r', encoding="utf-8") as file1:
                data = yaml.load(file1, yaml.Loader)
                bfgroups_name = data["bfgroups"]
        # 记录数据 这里进行一个初始化检测
        rsp_log.init_log(bfgroups_name)
        with open(f'./data/battlefield/binds/bfgroups/{bfgroups_name}/log.yaml', 'r', encoding="utf-8") as file1:
            data = yaml.load(file1, yaml.Loader)
            if qq_id not in data["operators"]:
                data["operators"][qq_id] = []
            time_now = time.strftime('%Y/%m/%d/%H:%M:%S', time.localtime(time.time()))
            data["operators"][qq_id].append(f"{time_now}-解封-{action_object}-{server_id}")
            data["total"].append(f"{time_now}-{qq_id}-解封-{action_object}-{server_id}")
            with open(f'./data/battlefield/binds/bfgroups/{bfgroups_name}/log.yaml', 'w',
                      encoding="utf-8") as file_temp2:
                yaml.dump(data, file_temp2, allow_unicode=True)

    @staticmethod
    def clearBan_logger(qq_id: Union[int, str], group_id, action_object: str, server_id):
        """
        记录解封的日志
        :param qq_id: qq号
        :param group_id: qq群号
        :param action_object: 解封个数
        :param server_id:服务器serverid
        :return: 无
        """
        # 先检查绑定群组没
        group_path = f'./data/battlefield/binds/groups/{group_id}'
        file_path = group_path + "/bfgroups.yaml"
        # 打开绑定的文件
        with open(file_path, 'r', encoding="utf-8") as file1:
            data = yaml.load(file1, yaml.Loader)
            bfgroups_name = data["bfgroups"]
        # 记录数据 这里进行一个初始化检测
        rsp_log.init_log(bfgroups_name)
        with open(f'./data/battlefield/binds/bfgroups/{bfgroups_name}/log.yaml', 'r', encoding="utf-8") as file1:
            data = yaml.load(file1, yaml.Loader)
            if qq_id not in data["operators"]:
                data["operators"][qq_id] = []
            time_now = time.strftime('%Y/%m/%d/%H:%M:%S', time.localtime(time.time()))
            data["operators"][qq_id].append(f"{time_now}-清理ban位:{action_object}个-{server_id}")
            data["total"].append(f"{time_now}-{qq_id}-清理ban位:{action_object}个-{server_id}")
            with open(f'./data/battlefield/binds/bfgroups/{bfgroups_name}/log.yaml', 'w',
                      encoding="utf-8") as file_temp2:
                yaml.dump(data, file_temp2, allow_unicode=True)

    @staticmethod
    def move_logger(qq_id: Union[int, str], group_id, action_object: str, server_id):
        """
        记录挪人的日志
        :param qq_id: qq号
        :param group_id: qq群号
        :param action_object: 解封对象-name
        :param server_id:服务器serverid
        :return: 无
        """
        # 先检查绑定群组没
        group_path = f'./data/battlefield/binds/groups/{group_id}'
        file_path = group_path + "/bfgroups.yaml"
        # 打开绑定的文件
        with open(file_path, 'r', encoding="utf-8") as file1:
            data = yaml.load(file1, yaml.Loader)
            bfgroups_name = data["bfgroups"]
        # 记录数据 这里进行一个初始化检测
        rsp_log.init_log(bfgroups_name)
        with open(f'./data/battlefield/binds/bfgroups/{bfgroups_name}/log.yaml', 'r', encoding="utf-8") as file1:
            data = yaml.load(file1, yaml.Loader)
            if qq_id not in data["operators"]:
                data["operators"][qq_id] = []
            time_now = time.strftime('%Y/%m/%d/%H:%M:%S', time.localtime(time.time()))
            data["operators"][qq_id].append(f"{time_now}-换边-{action_object}-{server_id}")
            data["total"].append(f"{time_now}-{qq_id}-换边-{action_object}-{server_id}")
            with open(f'./data/battlefield/binds/bfgroups/{bfgroups_name}/log.yaml', 'w',
                      encoding="utf-8") as file_temp2:
                yaml.dump(data, file_temp2, allow_unicode=True)

    @staticmethod
    def map_logger(qq_id: Union[int, str], group_id, map_name: str, server_id):
        """
        记录挪人的日志
        :param map_name:
        :param qq_id: qq号
        :param group_id: qq群号
        :param server_id:服务器serverid
        :return: 无
        """
        # 先检查绑定群组没
        group_path = f'./data/battlefield/binds/groups/{group_id}'
        file_path = group_path + "/bfgroups.yaml"
        # 打开绑定的文件
        with open(file_path, 'r', encoding="utf-8") as file1:
            data = yaml.load(file1, yaml.Loader)
            bfgroups_name = data["bfgroups"]
        # 记录数据 这里进行一个初始化检测
        rsp_log.init_log(bfgroups_name)
        with open(f'./data/battlefield/binds/bfgroups/{bfgroups_name}/log.yaml', 'r', encoding="utf-8") as file1:
            data = yaml.load(file1, yaml.Loader)
            if qq_id not in data["operators"]:
                data["operators"][qq_id] = []
            time_now = time.strftime('%Y/%m/%d/%H:%M:%S', time.localtime(time.time()))
            data["operators"][qq_id].append(f"{time_now}-换图:{map_name}-{server_id}")
            data["total"].append(f"{time_now}-{qq_id}-换图:{map_name}-{server_id}")
            with open(f'./data/battlefield/binds/bfgroups/{bfgroups_name}/log.yaml', 'w',
                      encoding="utf-8") as file_temp2:
                yaml.dump(data, file_temp2, allow_unicode=True)

    @staticmethod
    def addVip_logger(qq_id: Union[int, str], group_id, action_object: str, days: str, server_id):
        """
        记录挪人的日志
        :param days: 天数
        :param action_object:操作对象
        :param qq_id: qq号
        :param group_id: qq群号
        :param server_id:服务器serverid
        :return: 无
        """
        # 先检查绑定群组没
        group_path = f'./data/battlefield/binds/groups/{group_id}'
        file_path = group_path + "/bfgroups.yaml"
        # 打开绑定的文件
        with open(file_path, 'r', encoding="utf-8") as file1:
            data = yaml.load(file1, yaml.Loader)
            bfgroups_name = data["bfgroups"]
        # 记录数据 这里进行一个初始化检测
        rsp_log.init_log(bfgroups_name)
        with open(f'./data/battlefield/binds/bfgroups/{bfgroups_name}/log.yaml', 'r', encoding="utf-8") as file1:
            data = yaml.load(file1, yaml.Loader)
            if qq_id not in data["operators"]:
                data["operators"][qq_id] = []
            time_now = time.strftime('%Y/%m/%d/%H:%M:%S', time.localtime(time.time()))
            data["operators"][qq_id].append(f"{time_now}-上v:{days}-{action_object}-{server_id}")
            data["total"].append(f"{time_now}-{qq_id}-上v:{days}-{action_object}-{server_id}")
            with open(f'./data/battlefield/binds/bfgroups/{bfgroups_name}/log.yaml', 'w',
                      encoding="utf-8") as file_temp2:
                yaml.dump(data, file_temp2, allow_unicode=True)

    @staticmethod
    def delVip_logger(qq_id: Union[int, str], group_id, action_object: str, server_id):
        """
        记录挪人的日志
        :param action_object:操作对象
        :param qq_id: qq号
        :param group_id: qq群号
        :param server_id:服务器serverid
        :return: 无
        """
        # 先检查绑定群组没
        group_path = f'./data/battlefield/binds/groups/{group_id}'
        file_path = group_path + "/bfgroups.yaml"
        # 打开绑定的文件
        with open(file_path, 'r', encoding="utf-8") as file1:
            data = yaml.load(file1, yaml.Loader)
            bfgroups_name = data["bfgroups"]
        # 记录数据 这里进行一个初始化检测
        rsp_log.init_log(bfgroups_name)
        with open(f'./data/battlefield/binds/bfgroups/{bfgroups_name}/log.yaml', 'r', encoding="utf-8") as file1:
            data = yaml.load(file1, yaml.Loader)
            if qq_id not in data["operators"]:
                data["operators"][qq_id] = []
            time_now = time.strftime('%Y/%m/%d/%H:%M:%S', time.localtime(time.time()))
            data["operators"][qq_id].append(f"{time_now}-下v-{action_object}-{server_id}")
            data["total"].append(f"{time_now}-{qq_id}-下v-{action_object}-{server_id}")
            with open(f'./data/battlefield/binds/bfgroups/{bfgroups_name}/log.yaml', 'w',
                      encoding="utf-8") as file_temp2:
                yaml.dump(data, file_temp2, allow_unicode=True)

    @staticmethod
    def checkVip_logger(qq_id: Union[int, str], group_id, action_object: str, server_id):
        """
        记录挪人的日志
        :param action_object:清理个数
        :param qq_id: qq号
        :param group_id: qq群号
        :param server_id:服务器serverid
        :return: 无
        """
        # 先检查绑定群组没
        group_path = f'./data/battlefield/binds/groups/{group_id}'
        file_path = group_path + "/bfgroups.yaml"
        # 打开绑定的文件
        with open(file_path, 'r', encoding="utf-8") as file1:
            data = yaml.load(file1, yaml.Loader)
            bfgroups_name = data["bfgroups"]
        # 记录数据 这里进行一个初始化检测
        rsp_log.init_log(bfgroups_name)
        with open(f'./data/battlefield/binds/bfgroups/{bfgroups_name}/log.yaml', 'r', encoding="utf-8") as file1:
            data = yaml.load(file1, yaml.Loader)
            if qq_id not in data["operators"]:
                data["operators"][qq_id] = []
            time_now = time.strftime('%Y/%m/%d/%H:%M:%S', time.localtime(time.time()))
            data["operators"][qq_id].append(f"{time_now}-清理v:{action_object}个-{server_id}")
            data["total"].append(f"{time_now}-{qq_id}-清理v:{action_object}个-{server_id}")
            with open(f'./data/battlefield/binds/bfgroups/{bfgroups_name}/log.yaml', 'w',
                      encoding="utf-8") as file_temp2:
                yaml.dump(data, file_temp2, allow_unicode=True)
