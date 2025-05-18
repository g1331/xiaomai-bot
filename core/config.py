import yaml

from abc import ABC
from pathlib import Path
from creart import add_creator, AbstractCreator, CreateTargetInfo, exists_module
from pydantic import BaseModel
from utils.Singleton import singleton


class BotAccount(BaseModel):
    """单个Bot账号的配置"""

    account: int | str
    mirai_host: str | None = None
    verify_key: str | None = None


class GlobalConfig(BaseModel):
    """全局配置"""

    Master: int
    bot_accounts: list[int | str | dict]
    default_account: int | str
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
        "bf1": {"default_account": int, "apikey": str},
        "image_search": {"saucenao_key": str},
        "steamdb_cookie": str,
    }
    GroupMsg_log: bool
    debug_mode: bool


@singleton
class ConfigLoader:
    def __init__(self):
        with open(Path().cwd() / "config" / "config.yaml", encoding="utf-8") as f:
            self.config_data = yaml.safe_load(f.read())

    def get_bot_config(self, account_entry: int | str | dict) -> BotAccount:
        """处理单个bot账号配置"""
        if isinstance(account_entry, dict):
            return BotAccount(
                account=account_entry["account"],
                mirai_host=account_entry.get("mirai_host"),
                verify_key=account_entry.get("verify_key"),
            )
        return BotAccount(account=account_entry)

    def load_config(self) -> GlobalConfig:
        """加载全局配置"""
        return GlobalConfig(**self.config_data)

    def get_bot_connection_info(
        self, account_entry: int | str | dict
    ) -> tuple[str, str]:
        """获取bot连接信息"""
        bot_config = self.get_bot_config(account_entry)
        return (
            bot_config.mirai_host or self.config_data["mirai_host"],
            bot_config.verify_key or self.config_data["verify_key"],
        )


class ConfigClassCreator(AbstractCreator, ABC):
    targets = (CreateTargetInfo("core.config", "GlobalConfig"),)

    @staticmethod
    def available() -> bool:
        return exists_module("core.config")

    @staticmethod
    def create(create_type: type[GlobalConfig]) -> GlobalConfig:
        """创建全局配置实例"""
        config_loader = ConfigLoader()
        config = config_loader.load_config()
        if not config.default_account and config.bot_accounts:
            first_account = config.bot_accounts[0]
            config.default_account = (
                first_account["account"]
                if isinstance(first_account, dict)
                else first_account
            )
        return config


add_creator(ConfigClassCreator)
