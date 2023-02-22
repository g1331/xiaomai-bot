import contextlib
import json
from abc import ABC
from enum import Enum
from json.decoder import JSONDecodeError
from pathlib import Path
from typing import Type, List

from creart import create, AbstractCreator, CreateTargetInfo, exists_module, add_creator
from graia.ariadne.model import Group
from graia.saya import Saya
from pydantic import BaseModel

from core.bot import Umaru

saya = create(Saya)
core = create(Umaru)
module_controller_instance = None


class Metadata(BaseModel):
    level: int = 1
    name: str = ""
    display_name: str = ""
    version: str = "0.1"
    authors: List[str] = []
    description: str = ""
    usage: List[str] = []
    example: List[str] = []
    default_switch: bool = True
    default_notice: bool = False


class ModuleOperationType(Enum):
    INSTALL = "install"
    UNINSTALL = "uninstall"
    RELOAD = "reload"


class ModulesController:
    """插件控制器
    插件数据
    self.modules={
        "module_name": {
                "groups": {
                    "group_id": {
                        "switch": "bool",
                        "notice": "bool"
                    }
                },
                "available": "bool"
            },
        "module2": {}
    }

    
    插件元数据
    module.metadata=
    {
        "level": "插件等级1/2/3",
        "name": "名字",
        "display_name": "显示名字",
        "version": "0.0.1",
        "author": ["作者"],
        "description": "描述",
        "usage": ["用法"],
        "example": ["例子"],
        "default_switch": "默认为开启状态 True",
        "default_notice": "默认不通知状态 False"
    }
    """

    def __init__(self):
        self.modules = {}
        """
        {
            "module_name": {
                    "groups": {
                        "group_id": {
                            "switch": "bool",
                            "notice": "bool"
                        }
                    },
                    "available": "bool"
                },
            "module2": {}
        }
        """
        self.groups = {}

    @staticmethod
    def get_metadata_from_path(module_path: Path) -> Metadata:
        """
        传入插件路径
        """
        # 如果是文件夹就找文件夹内的metadata.json
        if module_path.is_dir():
            metadata_path = module_path / 'metadata.json'
            if metadata_path.is_file():
                with open(metadata_path, "r", encoding="utf-8") as r:
                    data = json.load(r)
                return Metadata(**data)
        else:
            # 如果是metadata.json就直接读取
            if module_path.name == 'metadata.json':
                with open(module_path, "r", encoding="utf-8") as r:
                    data = json.load(r)
                return Metadata(**data)
            # 不是的话就找同级文件夹内的metadata.json
            else:
                metadata_path = module_path.parent / 'metadata.json'
                if metadata_path.is_file():
                    with open(metadata_path, "r", encoding="utf-8") as r:
                        data = json.load(r)
                    return Metadata(**data)
        with open(Path(__file__).parent / "Metadata_templates.json", "r", encoding="utf-8") as r:
            data = json.load(r)
        return Metadata(**data)

    @staticmethod
    def get_metadata_from_module_name(module_name: str) -> Metadata:
        """
        传入插件名
        """
        paths = module_name.split('.')
        base_path = Path().cwd()
        for path in paths:
            base_path = base_path / path
        module_path = Path(base_path)
        return ModulesController.get_metadata_from_path(module_path)

    def add_group(self, group: Group or int or str):
        """如果module默认为开，且群不在module数据内则添加"""
        if isinstance(group, Group):
            group = str(group.id)
        group_id = str(group)
        if group_id not in self.groups:
            self.groups[group_id] = {}
        for key in self.modules:
            module = self.get_metadata_from_module_name(key)
            if group_id not in self.modules[key]:
                self.modules[key][group_id] = {
                    "switch": module.default_switch,
                    "notice": module.default_notice
                }
        self.save()

    def remove_group(self, group: Group or int or str):
        """移除某个群"""
        if isinstance(group, Group):
            group = group.id
        group_id = str(group)
        if group_id in self.groups:
            del self.groups[group_id]
        for key in self.modules:
            if group_id in self.modules[key]:
                del self.modules[key][group_id]
        self.save()

    def add_module(self, module_name: str):
        """如果插件不在modules字典内就添加,读取modules元数据,尝试进行初始化"""
        module = self.get_metadata_from_module_name(module_name)
        if module_name not in self.modules:
            self.modules[module_name] = {
                group: {
                    "switch": module.default_switch,
                    "notice": module.default_notice
                } for group in self.groups
            }
            self.modules[module_name]["available"] = True
        self.save()

    def remove_module(self, module_name):
        """如果插件在modules字典内就删除"""
        if module_name in self.modules:
            del self.modules[module_name]
        self.save()

    def change_group_module(self, module_name: str, group: Group or int or str, key: str, value: bool):
        """群插件状态变更"""
        if isinstance(group, Group):
            group = group.id
        group_id = str(group)
        if self.modules.get(module_name):
            if group_id not in self.modules[module_name]:
                self.add_group(group_id)
        else:
            self.add_module(module_name)
            if not self.modules[module_name].get(group_id):
                self.add_group(group_id)
        self.modules[module_name][group_id][key] = value
        self.save()

    def turn_on_module(self, module_name: str, group: Group or int or str):
        """打开某群的插件开关"""
        self.change_group_module(module_name, group, "switch", True)

    def turn_off_module(self, module_name: str, group: Group or int or str):
        """关闭某群的插件开关"""
        self.change_group_module(module_name, group, "switch", False)

    def turn_on_notice(self, module_name: str, group: Group or int or str):
        """打开某群插件通知"""
        self.change_group_module(module_name, group, "notice", True)

    def turn_off_notice(self, module_name: str, group: Group or int or str):
        """关闭某群插件通知"""
        self.change_group_module(module_name, group, "notice", False)

    def if_module_switch_on(self, module_name: str, group: Group or int or str) -> bool:
        """检查某个群的开关是否开启"""
        if not self.if_module_available(module_name):
            return False
        if isinstance(group, Group):
            group = group.id
        group_id = str(group)
        if self.modules.get(module_name):
            if group_id in self.modules[module_name]:
                return self.modules[module_name][group_id]["switch"]
            self.add_group(group_id)
        else:
            self.add_module(module_name)
            if not self.modules[module_name].get(group_id):
                self.add_group(group_id)
            if group_id in self.modules[module_name]:
                return self.modules[module_name][group_id]["switch"]
        module = self.get_metadata_from_module_name(module_name)
        return module.default_switch

    def if_module_notice_on(self, module_name: str, group: Group or int or str) -> bool:
        """检查某个群的开关状态通知是否开启"""
        if not self.if_module_available(module_name):
            return False
        if isinstance(group, Group):
            group = group.id
        group_id = str(group)
        if self.modules.get(module_name):
            if group_id in self.modules[module_name]:
                return self.modules[module_name][group_id]["notice"]
            self.add_group(group_id)
        else:
            self.add_module(module_name)
            if not self.modules[module_name].get(group_id):
                self.add_group(group_id)
            if group_id in self.modules[module_name]:
                return self.modules[module_name][group_id]["notice"]
        module = self.get_metadata_from_module_name(module_name)
        return module.default_notice

    def module_available_change(self, module_name: str, status: bool):
        """插件是否可用变更"""
        if not self.modules.get(module_name):
            self.add_module(module_name)
        self.modules[module_name]["available"] = status
        self.save()

    def enable_module(self, module_name: str):
        """使插件可用"""
        self.module_available_change(module_name, True)

    def disable_module(self, module_name: str):
        """使插件不可用(进入维护状态)"""
        self.module_available_change(module_name, False)

    def if_module_available(self, module_name: str) -> bool:
        """插件是否处于维护状态"""
        if module_name not in saya.channels:
            return False
        if self.modules.get(module_name):
            return self.modules.get(module_name).get("available")
        else:
            self.add_module(module_name)
            if self.modules.get(module_name):
                return self.modules.get(module_name).get("available")
            else:
                return False

    def save(self, path: str = str(Path(__file__).parent.joinpath("modules_data.json"))):
        with open(path, "w") as w:
            w.write(
                json.dumps(
                    {"modules": self.modules, "groups": self.groups}, indent=4
                )
            )

    def load(self, path: str = str(Path(__file__).parent.joinpath("modules_data.json"))) -> "ModulesController":
        with contextlib.suppress(FileNotFoundError, JSONDecodeError):
            with open(path, "r") as r:
                data = json.load(r)
                self.modules = data.get("modules", {})
                self.groups = data.get("groups", {})
        return self

    @staticmethod
    def module_operation(modules: str or list[str], operation_type: ModuleOperationType) -> dict[str, Exception]:
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

    @staticmethod
    def get_all_channels() -> list[str]:
        ignore = ["__init__.py", "__pycache__"]
        dirs = [
            "modules/required",
            "modules/self_contained",
        ]
        modules = []
        for path in dirs:
            for module in Path(path).glob("*"):
                module = module.as_posix()
                if str(module).split("/")[-1] in ignore:
                    continue
                if (core.base_path / module).is_dir():
                    modules.append(str(module).replace("/", "."))
                else:
                    modules.append(str(module).split(".")[0].replace("/", "."))
        return sorted(modules)

    @staticmethod
    def get_installed_channels() -> list[str]:
        return sorted(list(saya.channels.keys()))

    @staticmethod
    def get_not_installed_channels() -> list[str]:
        return sorted([c for c in ModulesController.get_all_channels() if c not in saya.channels])

    @staticmethod
    def get_required_modules() -> list[str]:
        return sorted([c for c in saya.channels.keys() if c.startswith("modules.required")])

    def get_available_modules(self) -> list[str]:
        return sorted([module for module in self.modules if self.if_module_available(module) and module not in self.get_required_modules()])

    def get_unavailable_modules(self) -> list[str]:
        return sorted([module for module in self.get_all_channels() if not self.if_module_available(module) and module not in self.get_not_installed_channels()])

    def get_all_modules(self) -> list[str]:
        required_module_list = self.get_required_modules()
        normal_module_list = self.get_available_modules()
        unavailable_modules = self.get_unavailable_modules()
        module_list = required_module_list + normal_module_list + unavailable_modules
        return module_list


def get_module_controller() -> ModulesController:
    global module_controller_instance
    if not module_controller_instance:
        module_controller_instance = create(ModulesController)
    return module_controller_instance


class ModulesControllerClassCreator(AbstractCreator, ABC):
    targets = (CreateTargetInfo("core.models.saya_model", "ModulesController"),)

    @staticmethod
    def available() -> bool:
        return exists_module("core.models.saya_model")

    @staticmethod
    def create(create_type: Type[ModulesController]) -> ModulesController:
        return ModulesController().load()


add_creator(ModulesControllerClassCreator)
