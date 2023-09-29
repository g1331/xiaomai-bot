import time
from abc import ABC
from collections import deque
from typing import Type

from creart import create, AbstractCreator, CreateTargetInfo, exists_module, add_creator

frequency_controller_instance = None


class FrequencyController(object):
    """频率控制器
    frequency_dict = {
        module_name: {
            group_id: {
                sender_id: deque([(时间戳1, 权重1), (时间戳2, 权重2)])
                ...
            },
        },
    }

    blacklist = {
        group_id: {
            sender_id: {
                time: xxx,
                noticed: True/False
            }
        }
    }
    """

    def __init__(self):
        # 格式：{模块名: {群组ID: {发送者ID: deque([时间戳])}}}
        # 使用双端队列（deque）来存储每个用户在过去15秒内的触发时间。
        self.frequency_dict = {}

        # 格式：{群组ID: {发送者ID: {时间: xxx, 通知: True/False}}}
        # 黑名单数据结构，用于存储被限制的用户及其限制信息。
        self.blacklist = {}

    def init_blacklist(self, group_id, sender_id):
        if group_id not in self.blacklist:
            self.blacklist[group_id] = {}
        if sender_id not in self.blacklist[group_id]:
            self.blacklist[group_id][sender_id] = {}

    def add_weight(self, module_name, group_id, sender_id, weight):
        current_time = time.time()
        if module_name not in self.frequency_dict:
            self.frequency_dict[module_name] = {}
        if group_id not in self.frequency_dict[module_name]:
            self.frequency_dict[module_name][group_id] = {}
        if sender_id not in self.frequency_dict[module_name][group_id]:
            self.frequency_dict[module_name][group_id][sender_id] = deque()

        # 移除早于（当前时间 - 15秒）的元组
        while (len(self.frequency_dict[module_name][group_id][sender_id]) > 0) and \
                (self.frequency_dict[module_name][group_id][sender_id][0][0] < current_time - 15):
            self.frequency_dict[module_name][group_id][sender_id].popleft()

        # 添加新的权重和时间戳
        self.frequency_dict[module_name][group_id][sender_id].append((current_time, weight))

        # 计算总权重
        total_weight = sum(w for _, w in self.frequency_dict[module_name][group_id][sender_id])

        if total_weight >= 12:
            self.add_blacklist(group_id, sender_id)

    def get_weight(self, module_name, group_id, sender_id) -> int:
        current_time = time.time()
        if module_name not in self.frequency_dict:
            return 0
        if group_id not in self.frequency_dict[module_name]:
            return 0
        if sender_id not in self.frequency_dict[module_name][group_id]:
            return 0

        # 移除早于（当前时间 - 15秒）的元组
        while (len(self.frequency_dict[module_name][group_id][sender_id]) > 0) and \
                (self.frequency_dict[module_name][group_id][sender_id][0][0] < current_time - 15):
            self.frequency_dict[module_name][group_id][sender_id].popleft()

        # 计算并返回总权重
        return sum(w for _, w in self.frequency_dict[module_name][group_id][sender_id])

    def blacklist_judge(self, group_id, sender_id):
        """判断是否在黑名单中, 如果在黑名单中则返回True, 否则返回False"""
        self.init_blacklist(group_id, sender_id)
        if self.blacklist[group_id][sender_id].get("time", time.time()) > time.time():
            return True
        else:
            self.blacklist[group_id][sender_id] = {}
            return False

    def blacklist_notice(self, group_id, sender_id):
        self.blacklist[group_id][sender_id]["noticed"] = True

    def blacklist_noticed_judge(self, group_id, sender_id):
        if sender_id in self.blacklist[group_id]:
            return self.blacklist[group_id][sender_id].get("noticed", False)

    def add_blacklist(self, group_id, sender_id):
        self.init_blacklist(group_id, sender_id)
        self.blacklist[group_id][sender_id] = {
            "time": time.time() + 300,  # 5分钟
            "noticed": False
        }


def get_frequency_controller() -> FrequencyController:
    global frequency_controller_instance
    if not frequency_controller_instance:
        frequency_controller_instance = create(FrequencyController)
    return frequency_controller_instance


class FrequencyControllerClassCreator(AbstractCreator, ABC):
    targets = (CreateTargetInfo("core.models.frequency_model", "FrequencyController"),)

    @staticmethod
    def available() -> bool:
        return exists_module("core.models.frequency_model")

    @staticmethod
    def create(create_type: Type[FrequencyController]) -> FrequencyController:
        return FrequencyController()


add_creator(FrequencyControllerClassCreator)
