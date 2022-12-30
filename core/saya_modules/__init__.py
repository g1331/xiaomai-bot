"""
插件元数据
module_metadata:
{
    "module_name": {
        "level": "插件等级1/2/3",
        "name": "文件名",
        "display_name": "显示名字",
        "version": "0.0.1",
        "author": ["作者"],
        "description": "描述",
        "usage": ["用法"],
        "eg": ["例子"],
        "default_switch": "默认是否为开启状态 TRUE/FALSE"
    },
    "module2": {

    }
}

插件开关列表
modules_data.json:

{
    "module_name" :{
        "groups": {
            "group_id" :{
                "switch": "bool",
                "notice": "bool"
            }
        },
        "available": "bool"
    }
}
"""
import contextlib
import json
from abc import ABC
from enum import Enum
from json.decoder import JSONDecodeError
from pathlib import Path
from typing import Type

from creart import create, AbstractCreator, CreateTargetInfo, exists_module, add_creator
from graia.ariadne.model import Group
from graia.saya import Saya

module_data_instance = None


class ModuleOperationType(Enum):
    INSTALL = "install"
    UNINSTALL = "uninstall"
    RELOAD = "reload"


class ModulesController:
    def __init__(self, modules=None):
        self.modules = modules or {}

    def add_group(self, module_name):
        """如果module默认为开，且群组不在module数据内则添加"""
        self.save()

    def remove_group(self, module_name: str, group: Group or int):
        """移除某个组"""
        self.save()

    def switch_change(self, module_name: str, switch: bool):
        """开关状态变更"""

    def turn_on_module(self, module_name: str, group: Group or int):
        """打开某群的插件开关"""
        self.save()

    def turn_off_module(self, module_name: str, group: Group or int):
        """关闭某群的插件开关"""
        self.save()

    def module_status_change(self, module_name: str, status: bool):
        """插件是否可用变更"""

    def enable_module(self, module_name: str):
        """使插件可用"""
        self.save()

    def disable_module(self, module_name: str):
        """使插件不可用(进入维护状态)"""
        self.save()

    def if_module_switch_on(self, module_name: str, group: Group or int) -> bool:
        """检查某个群的开关是否开启"""

    def if_module_notice_on(self, module_name: str, group: Group or int) -> bool:
        """检查某个群的开关状态通知是否开启"""

    def save(self, path: str = str(Path(__file__).parent.joinpath("modules_data.json"))):
        with open(path, "w") as w:
            w.write(
                json.dumps(
                    {"modules": self.modules}, indent=4
                )
            )

    def load(self, path: str = str(Path(__file__).parent.joinpath("modules_data.json"))) -> "ModulesController":
        with contextlib.suppress(FileNotFoundError, JSONDecodeError):
            with open(path, "r") as r:
                data = json.load(r)
                self.modules = data.get("modules", {})
        return self

    @staticmethod
    def module_operation(modules: str or list[str], operation_type: ModuleOperationType) -> dict[str, Exception]:
        saya = create(Saya)
        exceptions = {}
        if isinstance(modules, str):
            modules = [modules]
        if operation_type == ModuleOperationType.INSTALL:
            op_modules = {
                module: module
                for module in modules
            }
        else:
            loaded_channels = saya.channels
            op_modules = {
                module: loaded_channels[module]
                for module in modules
                if module in loaded_channels
            }
        with saya.module_context():
            for c, value in op_modules.items():
                try:
                    if operation_type == ModuleOperationType.INSTALL:
                        saya.require(c)
                    elif operation_type == ModuleOperationType.UNINSTALL:
                        saya.uninstall_channel(value)
                    else:
                        saya.reload_channel(value)
                except Exception as e:
                    exceptions[c] = e
        return exceptions


def get_module_data():
    global module_data_instance
    if not module_data_instance:
        module_data_instance = create(ModulesController)
    return module_data_instance


class ModulesControllerClassCreator(AbstractCreator, ABC):
    targets = (CreateTargetInfo("core.saya_modules", "ModulesController"),)

    @staticmethod
    def available() -> bool:
        return exists_module("core.saya_modules")

    @staticmethod
    def create(create_type: Type[ModulesController]) -> ModulesController:
        return ModulesController().load()


add_creator(ModulesControllerClassCreator)
