# src/ai_chat/config.py
"""
配置处理
"""
import json
from pathlib import Path
from typing import Dict, Any

from loguru import logger

CONFIG_PATH = Path("data/ai_chat")


class ConfigLoader:
    def __init__(self, config_path: Path = CONFIG_PATH / "ai_chat.json"):
        self.config_path = config_path
        self.default_config = {
            "providers": {
                "openai": {
                    "api_key": "",
                    "session_token": "",
                    "model": "gpt-3.5-turbo",
                    "max_tokens": 4096
                },
                "deepseek": {
                    "api_key": "",
                    "model": "deepseek-chat",
                    "base_url": "https://api.deepseek.ai/v1/",
                    "max_tokens": 4096
                }
            },
            "plugins": {
                "web_search": {
                    "enabled": True,
                    "max_results": 3
                }
            },
            # 新增用户 provider 配置部分
            "user_providers": {
                "default": "deepseek",
                "users": {}
            }
        }
        self._config = self.load_config()

    def load_config(self) -> Dict[str, Any]:
        if not self.config_path.exists():
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_path, "w") as f:
                json.dump(self.default_config, f, indent=4, ensure_ascii=False)
            logger.info(f"[AIChat]Config file not found, created at: {self.config_path}")
            return self.default_config

        with open(self.config_path) as f:
            config = json.load(f)
            # 确保配置中包含所有必要的字段
            if "user_providers" not in config:
                config["user_providers"] = self.default_config["user_providers"]
            logger.info(f"[AIChat]Config loaded from: {self.config_path}")
            return config

    def save_config(self):
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(self._config, f, indent=4, ensure_ascii=False)

    # 新增用户 provider 管理方法
    def get_user_provider(self, user_id: str) -> str:
        return self._config["user_providers"]["users"].get(
            user_id,
            self._config["user_providers"]["default"]
        )

    def set_user_provider(self, user_id: str, provider: str):
        if provider not in self._config["providers"]:
            raise ValueError(f"Unknown provider: {provider}")
        self._config["user_providers"]["users"][user_id] = provider
        self.save_config()

    def get_default_provider(self) -> str:
        return self._config["user_providers"]["default"]

    def set_default_provider(self, provider: str):
        if provider not in self._config["providers"]:
            raise ValueError(f"Unknown provider: {provider}")
        self._config["user_providers"]["default"] = provider
        self.save_config()

    def get_provider_config(self, provider_name: str) -> Dict[str, Any]:
        if provider_name not in self._config["providers"]:
            raise ValueError(f"Unknown provider: {provider_name}")
        return self._config["providers"][provider_name]

    @property
    def config(self):
        return self._config
