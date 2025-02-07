# src/ai_chat/config.py
"""
配置处理
"""
import json
from pathlib import Path
from typing import Dict, Any


class ConfigLoader:
    def __init__(self, config_path: Path = Path("config/ai_chat.json")):
        self.config_path = config_path
        self.default_config = {
            "providers": {
                "openai": {
                    "api_key": "",
                    "session_token": "",
                    "model": "gpt-3.5-turbo",
                    "max_tokens": 2000
                },
                "deepseek": {
                    "api_key": "",
                    "model": "deepseek-chat",
                    "base_url": "https://api.deepseek.ai/v1/",
                    "max_tokens": 2000
                }
            },
            "plugins": {
                "web_search": {
                    "enabled": True,
                    "max_results": 3
                }
            }
        }

    def load_config(self) -> Dict[str, Any]:
        if not self.config_path.exists():
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_path, "w") as f:
                json.dump(self.default_config, f, indent=2)
            return self.default_config

        with open(self.config_path) as f:
            return json.load(f)
