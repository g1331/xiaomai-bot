# src/ai_chat/config.py
"""
配置处理
"""
import json
from pathlib import Path
from typing import Any, Dict, Optional

from loguru import logger

CONFIG_PATH = Path("data/ai_chat")


class ConfigLoader:
    def __init__(self, config_path: Path = CONFIG_PATH / "ai_chat.json"):
        self.config_path = config_path
        self.default_config = {
            "providers": {
                "openai": {
                    "api_key": "",
                    "base_url": "https://api.openai.com/v1",
                    "default_model": "gpt-3.5-turbo",
                    "models": {
                        "gpt-3.5-turbo": {
                            "max_tokens": 4096,
                            "max_total_tokens": 16384,
                            "supports_tool_calls": True,
                        },
                        "gpt-4": {
                            "max_tokens": 8192,
                            "max_total_tokens": 32768,
                            "supports_tool_calls": True,
                        },
                        "gpt-4o": {
                            "max_tokens": 8192,
                            "max_total_tokens": 128000,
                            "supports_vision": True,
                            "supports_tool_calls": True,
                        },
                        "gpt-4-vision-preview": {
                            "max_tokens": 4096,
                            "max_total_tokens": 128000,
                            "supports_vision": True,
                        },
                    },
                },
                "deepseek": {
                    "api_key": "",
                    "base_url": "https://api.deepseek.com/v1",
                    "default_model": "deepseek-chat",
                    "models": {
                        "deepseek-chat": {
                            "max_tokens": 8192,
                            "max_total_tokens": 64000,
                            "supports_tool_calls": True,
                        },
                        "deepseek-r1": {
                            "max_tokens": 8192,
                            "max_total_tokens": 64000,
                            "supports_tool_calls": False,
                        },
                    },
                },
            },
            "plugins": {},  # 将由自动生成填充
            "user_preferences": {
                "default": {"provider": "deepseek", "model": "deepseek-chat"},
                "users": {},
            },
        }
        self._config = self.load_config()
        self._update_plugins_config()
        self._migrate_old_config_if_needed()

    def load_config(self) -> Dict[str, Any]:
        if not self.config_path.exists():
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_path, "w") as f:
                json.dump(self.default_config, f, indent=4, ensure_ascii=False)
            logger.info(
                f"[AIChat]Config file not found, created at: {self.config_path}"
            )
            return self.default_config

        with open(self.config_path) as f:
            config = json.load(f)
            logger.info(f"[AIChat]Config loaded from: {self.config_path}")
            return config

    def save_config(self):
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(self._config, f, indent=4, ensure_ascii=False)

    def _migrate_old_config_if_needed(self):
        """迁移旧版配置到新版配置结构"""
        # 检测旧版配置结构
        if "user_providers" in self._config and "user_preferences" not in self._config:
            logger.info("[AIChat]检测到旧版配置结构，正在迁移...")

            old_providers = self._config.pop("user_providers", {})
            default_provider = old_providers.get("default", "deepseek")
            user_providers = old_providers.get("users", {})

            # 创建新的用户偏好配置
            user_preferences = {
                "default": {
                    "provider": default_provider,
                    "model": self._config["providers"]
                    .get(default_provider, {})
                    .get("default_model", ""),
                },
                "users": {},
            }

            # 迁移用户提供商配置
            for user_id, provider in user_providers.items():
                default_model = (
                    self._config["providers"].get(provider, {}).get("default_model", "")
                )
                user_preferences["users"][user_id] = {
                    "provider": provider,
                    "model": default_model,
                }

            self._config["user_preferences"] = user_preferences

            # 迁移旧版提供商配置到新版模型结构
            for provider, config in list(self._config["providers"].items()):
                if "model" in config and "models" not in config:
                    model_name = config.pop("model", "")
                    max_tokens = config.pop("max_tokens", 8192)

                    # 创建默认模型配置
                    config["default_model"] = model_name
                    config["models"] = {
                        model_name: {
                            "max_tokens": max_tokens,
                            "max_total_tokens": max_tokens * 4,  # 默认为输出限制的4倍
                            "supports_tool_calls": False,  # 默认不支持工具调用
                        }
                    }

            self.save_config()
            logger.success("[AIChat]配置迁移完成")

    def _update_plugins_config(self):
        """根据已注册的插件更新配置"""
        from .plugins_registry import ALL_PLUGINS

        plugins_cfg = self._config.setdefault("plugins", {})
        config_modified = False

        # 遍历所有已注册的插件
        for plugin_name, plugin_info in ALL_PLUGINS.items():
            if plugin_name not in plugins_cfg:
                # 为新插件创建默认配置，无需传入参数
                default_config = plugin_info["default_config"]()
                plugins_cfg[plugin_name] = {
                    "enabled": False,  # 默认禁用
                    **default_config.dict(exclude_none=True),  # 将配置模型转换为字典
                }
                config_modified = True
                logger.info(f"[AIChat]Added default config for plugin: {plugin_name}")

        if config_modified:
            self.save_config()

    def get_user_preference(self, user_id: str) -> Dict[str, str]:
        """获取用户偏好设置，包括提供商和模型"""
        if not user_id:
            return self._config["user_preferences"]["default"]

        user_prefs = (
            self._config.get("user_preferences", {}).get("users", {}).get(user_id)
        )
        if not user_prefs:
            return self._config["user_preferences"]["default"]

        return user_prefs

    def get_user_provider(self, user_id: str) -> str:
        """获取用户使用的提供商"""
        return self.get_user_preference(user_id)["provider"]

    def get_user_model(
        self, user_id: str, provider_name: Optional[str] = None
    ) -> Optional[str]:
        """获取用户偏好的模型名称，并验证与提供商的兼容性"""
        preference = self.get_user_preference(user_id)
        provider = provider_name or preference["provider"]
        model = preference.get("model")

        # 如果提供商发生变化，或者模型在当前提供商中不存在，使用提供商的默认模型
        provider_config = self.get_provider_config(provider)
        available_models = provider_config.get("models", {})

        if not model or model not in available_models:
            return provider_config.get("default_model")

        return model

    def set_user_preference(
        self, user_id: str, provider: str, model: Optional[str] = None
    ):
        """设置用户的提供商和模型偏好"""
        if provider not in self._config["providers"]:
            raise ValueError(f"Unknown provider: {provider}")

        provider_config = self._config["providers"][provider]

        # 如果没有指定模型，使用提供商的默认模型
        if not model:
            model = provider_config.get("default_model", "")
        # 验证模型是否存在于提供商的可用模型中
        elif model not in provider_config.get("models", {}):
            model = provider_config.get("default_model", "")
            logger.warning(
                f"Model {model} not available for provider {provider}, using default model"
            )

        # 确保user_preferences结构存在
        if "user_preferences" not in self._config:
            self._config["user_preferences"] = {
                "default": {"provider": "deepseek", "model": "deepseek-chat"},
                "users": {},
            }

        self._config["user_preferences"].setdefault("users", {})[user_id] = {
            "provider": provider,
            "model": model,
        }
        self.save_config()

    def get_default_preference(self) -> Dict[str, str]:
        """获取默认的提供商和模型偏好"""
        return self._config["user_preferences"]["default"]

    def set_default_preference(self, provider: str, model: Optional[str] = None):
        """设置默认的提供商和模型偏好"""
        if provider not in self._config["providers"]:
            raise ValueError(f"Unknown provider: {provider}")

        provider_config = self._config["providers"][provider]

        # 如果没有指定模型，使用提供商的默认模型
        if not model:
            model = provider_config.get("default_model", "")
        # 验证模型是否存在于提供商的可用模型中
        elif model not in provider_config.get("models", {}):
            model = provider_config.get("default_model", "")
            logger.warning(
                f"Model {model} not available for provider {provider}, using default model"
            )

        self._config["user_preferences"]["default"] = {
            "provider": provider,
            "model": model,
        }
        self.save_config()

    def get_provider_config(self, provider_name: str) -> Dict[str, Any]:
        """获取提供商配置"""
        if provider_name not in self._config["providers"]:
            raise ValueError(f"Unknown provider: {provider_name}")

        # 创建配置的深拷贝，这样我们可以修改它而不影响原始配置
        import copy

        config = copy.deepcopy(self._config["providers"][provider_name])

        # 确保基本字段存在
        if "default_model" not in config:
            config["default_model"] = (
                list(config.get("models", {}))[0] if config.get("models") else ""
            )

        # 处理旧版本配置
        if "model" in config and "models" not in config:
            model_name = config.pop("model")
            max_tokens = config.pop("max_tokens", 8192)

            config["default_model"] = model_name
            config["models"] = {
                model_name: {
                    "max_tokens": max_tokens,
                    "max_total_tokens": max_tokens * 4,  # 默认为最大输出的4倍
                }
            }

        # 如果没有models字段，创建一个空字典
        if "models" not in config:
            config["models"] = {}

        return config

    def get_model_config(
        self, provider_name: str, model_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """获取模型配置，如果未指定模型名则使用提供商默认模型"""
        provider_config = self.get_provider_config(provider_name)

        if not model_name:
            model_name = provider_config.get("default_model")

        if not model_name or model_name not in provider_config.get("models", {}):
            raise ValueError(
                f"Invalid model for provider {provider_name}: {model_name}"
            )

        return provider_config["models"][model_name]

    @property
    def config(self):
        return self._config
