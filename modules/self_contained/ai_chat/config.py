# src/ai_chat/config.py
"""
配置处理
"""

import json
from pathlib import Path
from typing import Any

from loguru import logger

CONFIG_PATH = Path("data/ai_chat")


class ConfigLoader:
    def __init__(
        self,
        config_path: Path = CONFIG_PATH / "ai_chat.json",
        user_prefs_path: Path = CONFIG_PATH / "user_preferences.json",
    ):
        self.config_path = config_path
        self.user_prefs_path = user_prefs_path
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
                        "deepseek-reasoner": {
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
            },
        }
        self.default_user_prefs = {
            "default": {"provider": "deepseek", "model": "deepseek-chat"},
            "users": {},
        }
        self._config = self.load_config()
        self._user_prefs = self.load_user_preferences()
        self._update_plugins_config()
        self._migrate_old_config_if_needed()

    def load_config(self) -> dict[str, Any]:
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

    def load_user_preferences(self) -> dict[str, Any]:
        """加载用户偏好设置文件"""
        if not self.user_prefs_path.exists():
            self.user_prefs_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.user_prefs_path, "w") as f:
                json.dump(self.default_user_prefs, f, indent=4, ensure_ascii=False)
            logger.info(
                f"[AIChat]User preferences not found, created at: {self.user_prefs_path}"
            )
            return self.default_user_prefs

        with open(self.user_prefs_path) as f:
            prefs = json.load(f)
            logger.info(f"[AIChat]User preferences loaded from: {self.user_prefs_path}")
            return prefs

    def save_config(self):
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(self._config, f, indent=4, ensure_ascii=False)

    def save_user_preferences(self):
        """保存用户偏好设置"""
        with open(self.user_prefs_path, "w", encoding="utf-8") as f:
            json.dump(self._user_prefs, f, indent=4, ensure_ascii=False)

    def _migrate_old_config_if_needed(self):
        """迁移旧版配置到新版配置结构"""
        # 检测旧版配置结构
        if "user_providers" in self._config:
            logger.info("[AIChat]检测到旧版配置结构，正在迁移...")

            old_providers = self._config.pop("user_providers", {})
            default_provider = old_providers.get("default", "deepseek")
            user_providers = old_providers.get("users", {})

            # 设置默认提供商和模型
            self._user_prefs["default"] = {
                "provider": default_provider,
                "model": self._config["providers"]
                .get(default_provider, {})
                .get("default_model", ""),
            }

            # 迁移用户提供商配置
            for user_id, provider in user_providers.items():
                default_model = (
                    self._config["providers"].get(provider, {}).get("default_model", "")
                )
                self._user_prefs["users"][user_id] = {
                    "provider": provider,
                    "model": default_model,
                }

            self.save_user_preferences()

        # 从主配置中迁移用户偏好到单独文件
        if "user_preferences" in self._config:
            logger.info("[AIChat]将用户偏好从主配置迁移到单独文件...")

            # 将主配置中的用户偏好合并到用户偏好文件
            old_prefs = self._config.pop("user_preferences", {})

            # 迁移默认设置
            if "default" in old_prefs:
                self._user_prefs["default"] = old_prefs["default"]

            # 迁移用户设置
            if "users" in old_prefs:
                for user_id, prefs in old_prefs["users"].items():
                    self._user_prefs["users"][user_id] = prefs

            # 迁移可能保存在user_models中的用户模型偏好
            if "user_models" in self._config:
                for user_id, provider_models in self._config.pop(
                    "user_models", {}
                ).items():
                    if user_id not in self._user_prefs["users"]:
                        # 获取用户默认提供商
                        default_provider = self._user_prefs["default"]["provider"]
                        self._user_prefs["users"][user_id] = {
                            "provider": default_provider,
                            "model": "",
                        }

                    # 设置用户的模型偏好
                    for provider, model in provider_models.items():
                        if self._user_prefs["users"][user_id]["provider"] == provider:
                            self._user_prefs["users"][user_id]["model"] = model

            self.save_config()
            self.save_user_preferences()
            logger.success("[AIChat]用户偏好迁移完成")

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

    def get_user_preference(self, user_id: str) -> dict[str, str]:
        """获取用户偏好设置，包括提供商和模型"""
        if not user_id:
            return self._user_prefs["default"]

        user_prefs = self._user_prefs.get("users", {}).get(user_id)
        if not user_prefs:
            return self._user_prefs["default"]

        return user_prefs

    def get_user_provider(self, user_id: str) -> str:
        """获取用户使用的提供商"""
        return self.get_user_preference(user_id)["provider"]

    def get_user_model(
        self, user_id: str, provider_name: str | None = None
    ) -> str | None:
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
        self, user_id: str, provider: str, model: str | None = None
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

        # 更新用户偏好
        self._user_prefs.setdefault("users", {})[user_id] = {
            "provider": provider,
            "model": model,
        }
        self.save_user_preferences()

    def set_user_model(self, user_id: str, provider_name: str, model_name: str) -> None:
        """设置用户偏好的模型"""
        if not user_id:
            return

        # 验证模型是否有效
        provider_config = self.get_provider_config(provider_name)
        if model_name not in provider_config["models"]:
            raise ValueError(f"无效的模型名称: {model_name}")

        # 获取当前用户偏好
        current_pref = self.get_user_preference(user_id)

        # 如果用户当前的提供商与要设置的不同，则更新用户配置中的提供商
        if current_pref.get("provider") != provider_name:
            self._user_prefs.setdefault("users", {})[user_id] = {
                "provider": provider_name,
                "model": model_name,
            }
        else:
            # 如果提供商相同，只更新模型
            self._user_prefs.setdefault("users", {})[user_id]["model"] = model_name

        # 保存用户偏好
        self.save_user_preferences()
        logger.info(f"已设置用户 {user_id} 的模型为 {provider_name}:{model_name}")

    def get_default_preference(self) -> dict[str, str]:
        """获取默认的提供商和模型偏好"""
        return self._user_prefs["default"]

    def set_default_preference(self, provider: str, model: str | None = None):
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

        self._user_prefs["default"] = {
            "provider": provider,
            "model": model,
        }
        self.save_user_preferences()

    def get_provider_config(self, provider_name: str) -> dict[str, Any]:
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
        self, provider_name: str, model_name: str | None = None
    ) -> dict[str, Any]:
        """获取模型配置，如果未指定模型名则使用提供商默认模型"""
        provider_config = self.get_provider_config(provider_name)

        if not model_name:
            model_name = provider_config.get("default_model")

        if not model_name or model_name not in provider_config.get("models", {}):
            raise ValueError(
                f"Invalid model for provider {provider_name}: {model_name}"
            )

        return provider_config["models"][model_name]

    def is_provider_configured(self, provider_name: str) -> tuple[bool, str]:
        """
        检查提供商配置是否完整有效

        Args:
            provider_name: 提供商名称

        Returns:
            tuple[bool, str]: (是否配置完整, 错误信息)
        """
        if not self.config:
            return False, "配置未加载"

        providers = self.config.get("providers", {})
        if provider_name not in providers:
            return False, f"未找到提供商 {provider_name} 的配置"

        provider_config = providers[provider_name]

        # 检查通用配置项
        if "api_key" not in provider_config or not provider_config["api_key"]:
            return False, f"{provider_name} 缺少 API key 配置"

        # 针对特定提供商的配置检查
        if provider_name == "openai":
            if "api_base" not in provider_config or not provider_config["api_base"]:
                return False, f"{provider_name} 缺少 API Base URL 配置"
        # 可以在这里添加其他供应商的特定配置检查

        return True, "配置完整"

    @property
    def config(self):
        return self._config

    @property
    def user_preferences(self):
        return self._user_prefs
