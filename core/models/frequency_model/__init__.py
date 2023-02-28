import asyncio
import time
from abc import ABC
from typing import Type

from creart import create, AbstractCreator, CreateTargetInfo, exists_module, add_creator

frequency_controller_instance = None


class FrequencyController(object):
    """频率控制器
    frequency_dict = {
        module_name:{
            group_id:{
                sender_id: weights
            },
        },

    }

    blacklist = {
        group_id:{
            sender_id: {
                time: xxx,
                noticed: True
            }
        }
    }
    """

    def __init__(self):
        self.frequency_dict = {}
        self.blacklist = {}
        self.limit_running = False

    def init_module(self, module_name: str):
        """添加插件"""
        if module_name not in self.frequency_dict:
            self.frequency_dict[module_name] = {}

    def init_group(self, group_id: int):
        """初始化群"""
        for module in self.frequency_dict:
            if group_id not in self.frequency_dict[module]:
                self.frequency_dict[module][group_id] = {}
            if group_id not in self.blacklist:
                self.blacklist[group_id] = {}

    def init_blacklist(self, group_id: int, sender_id: int):
        if group_id not in self.blacklist:
            self.blacklist[group_id] = {}
        if sender_id not in self.blacklist[group_id]:
            self.blacklist[group_id][sender_id] = {}

    def add_weight(self, module_name: str, group_id: int, sender_id: int, weight: int):
        self.init_module(module_name)
        self.init_group(group_id)
        self.init_blacklist(group_id, sender_id)
        if sender_id not in self.frequency_dict[module_name][group_id]:
            self.frequency_dict[module_name][group_id][sender_id] = weight
        else:
            self.frequency_dict[module_name][group_id][sender_id] += weight
        if self.frequency_dict[module_name][group_id][sender_id] > 12:
            self.add_blacklist(group_id, sender_id)

    def get_weight(self, module_name: str, group_id: int, sender_id: int):
        self.init_module(module_name)
        self.init_group(group_id)
        if sender_id not in self.frequency_dict[module_name][group_id]:
            self.frequency_dict[module_name][group_id][sender_id] = 0
            return 0
        else:
            return self.frequency_dict[module_name][group_id][sender_id]

    def blacklist_judge(self, group_id: int, sender_id: int) -> bool:
        self.init_blacklist(group_id, sender_id)
        if self.blacklist[group_id][sender_id].get("time", time.time()) > time.time():
            return True
        elif self.blacklist[group_id][sender_id].get("time", time.time()) <= time.time():
            self.blacklist[group_id][sender_id] = {}
        return False

    def blacklist_notice(self, group_id: int, sender_id: int):
        self.blacklist[group_id][sender_id]["noticed"] = True

    def blacklist_noticed_judge(self, group_id: int, sender_id: int) -> bool:
        if sender_id in self.blacklist[group_id]:
            return self.blacklist[group_id][sender_id].get("noticed")
        return False

    def add_blacklist(self, group_id: int, sender_id: int):
        if not self.blacklist[group_id][sender_id].get("time"):
            self.blacklist[group_id][sender_id] = {
                "time": time.time() + 300,
                "noticed": False
            }
        elif self.blacklist[group_id][sender_id].get("time") < time.time():
            self.blacklist[group_id][sender_id] = {
                "time": time.time() + 300,
                "noticed": False
            }

    async def limited(self):
        if self.limit_running:
            return
        self.limit_running = True
        while True:
            await self.set_zero()
            await asyncio.sleep(15)

    async def set_zero(self):
        for module in self.frequency_dict:
            for group in self.frequency_dict[module]:
                self.frequency_dict[module][group] = {}


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
