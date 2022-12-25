import yaml

from abc import ABC
from pathlib import Path
from typing import List, Type
from creart import add_creator, AbstractCreator, CreateTargetInfo, exists_module
from pydantic import BaseModel


class GlobalConfig(BaseModel):
    Master: int
    Admins: List[int]
    bot_accounts: List[int]
    default_account: int or None
    off_bots: List[int]
    bot_blocked: List[int]
    mirai_host: str = "http://localhost:8080"
    verify_key: str = "1234567890"
    test_group: int
    vip_group: List[int]
    black_group: List[int]
    proxy: str
    db_link: str = "sqlite+aiosqlite:///data.db"
    log_related: dict = {"error_retention": 14, "common_retention": 7}
    bf1: dict = {
        "default_account": 0
    }


def load_config():
    with open(Path().cwd() / "config.yaml", "r", encoding="utf-8") as f:
        config_data = yaml.safe_load(f.read())
        return GlobalConfig(**config_data)


class ConfigClassCreator(AbstractCreator, ABC):
    targets = (CreateTargetInfo("core.config", "GlobalConfig"),)

    @staticmethod
    def available() -> bool:
        return exists_module("core.config")

    @staticmethod
    def create(create_type: Type[GlobalConfig]) -> GlobalConfig:
        with open(Path().cwd() / "config.yaml", "r", encoding="utf-8") as f:
            configs = yaml.safe_load(f.read())
            config = GlobalConfig(**configs)
            if not config.default_account:
                config.default_account = config.bot_accounts[0]
            return config


add_creator(ConfigClassCreator)
