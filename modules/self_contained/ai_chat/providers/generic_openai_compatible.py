from typing import Any

from ..core.provider import ModelConfig
from .openai_compatible import OpenAICompatibleConfig, OpenAICompatibleProvider


class GenericOpenAICompatibleConfig(OpenAICompatibleConfig):
    """通用OpenAI兼容配置"""

    def __init__(self, **kwargs):
        # 先处理模型配置
        if "models" in kwargs and isinstance(kwargs["models"], dict):
            kwargs["models"] = {
                name: (
                    config
                    if isinstance(config, ModelConfig)
                    else ModelConfig(
                        name=name,
                        max_tokens=config.get("max_tokens", 4096),
                        max_total_tokens=config.get("max_total_tokens", 32768),
                        supports_vision=config.get("supports_vision", False),
                        supports_audio=config.get("supports_audio", False),
                        supports_document=config.get("supports_document", False),
                        supports_tool_calls=config.get("supports_tool_calls", False),
                    )
                )
                for name, config in kwargs["models"].items()
            }

        # 调用父类初始化
        super().__init__(**kwargs)

        # 允许配置文件完全覆盖所有配置项
        for key, value in kwargs.items():
            if hasattr(self, key) and key != "models":  # 排除models，因为已经处理过了
                setattr(self, key, value)


class GenericOpenAICompatibleProvider(OpenAICompatibleProvider):
    """通用OpenAI兼容提供者"""

    def __init__(
        self, config: GenericOpenAICompatibleConfig, model_name: str | None = None
    ):
        super().__init__(config, model_name)
        self.config = config  # 使用具体的配置类型

    def calculate_tokens(self, messages: list[dict[str, Any]]) -> int:
        # 直接使用父类的实现
        return super().calculate_tokens(messages)

    def get_available_models(self) -> list[str]:
        """获取可用的模型列表"""
        return list(self.config.models.keys()) if self.config.models else []
