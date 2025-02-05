import yaml

from abc import ABC
from pathlib import Path
from typing import List, Type
from creart import add_creator, AbstractCreator, CreateTargetInfo, exists_module
from pydantic import BaseModel
from utils.Singleton import singleton


class GlobalConfig(BaseModel):
    Master: int
    bot_accounts: List[int]
    default_account: int
    mirai_host: str = "http://localhost:8080"
    verify_key: str = "1234567890"
    test_group: int
    proxy: str
    api_port: int = 8080
    api_expose: bool = False
    web_manager_api: bool = True
    web_manager_auto_boot: bool = False
    db_link: str = "sqlite+aiosqlite:///data.db"
    log_related: dict = {"error_retention": 14, "common_retention": 7}
    auto_upgrade: bool = False
    functions: dict = {
        "bf1": {
            "default_account": int,
            "apikey": str
        },
        "image_search": {
            "saucenao_key": str
        },
        "steamdb_cookie": str,
    }
    GroupMsg_log: bool


@singleton
class ConfigLoader:
    def __init__(self):
        with open(Path().cwd() / "config" / "config.yaml", "r", encoding="utf-8") as f:
            self.config_data = yaml.safe_load(f.read())

    def load_config(self) -> GlobalConfig:
        return GlobalConfig(**self.config_data)


class ConfigClassCreator(AbstractCreator, ABC):
    targets = (CreateTargetInfo("core.config", "GlobalConfig"),)

    @staticmethod
    def available() -> bool:
        return exists_module("core.config")

    @staticmethod
    def create(create_type: Type[GlobalConfig]) -> GlobalConfig:
        config_loader = ConfigLoader()
        config = config_loader.load_config()
        if not config.default_account:
            config.default_account = config.bot_accounts[0]
        return config


add_creator(ConfigClassCreator)
