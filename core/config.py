import yaml

from abc import ABC
from pathlib import Path
from typing import List, Type
from creart import add_creator, AbstractCreator, CreateTargetInfo, exists_module
from pydantic import BaseModel


class GlobalConfig(BaseModel):
    Master: int
    bot_accounts: List[int]
    default_account: int
    mirai_host: str = "http://localhost:8080"
    verify_key: str = "1234567890"
    test_group: int
    proxy: str
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
        "ChatGPT": {
            "session_token": str
        }
    }
    GroupMsg_log: bool


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
        config = load_config()
        if not config.default_account:
            config.default_account = config.bot_accounts[0]
        return config


add_creator(ConfigClassCreator)
