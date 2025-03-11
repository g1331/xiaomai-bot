from typing import Any

import tiktoken

from ..core.provider import ModelConfig
from .openai_compatible import OpenAICompatibleConfig, OpenAICompatibleProvider


class OpenAIConfig(OpenAICompatibleConfig):
    """OpenAI 特有配置"""

    def __init__(self, **kwargs):
        # 首先调用父类初始化
        super().__init__(**kwargs)

        # 如果没有提供基础URL，设置默认值
        if not self.base_url:
            self.base_url = "https://api.openai.com/v1"

        # 确保models是字典而不是None
        if not self.models:
            self.models = {}

        # 如果models为空，创建默认模型配置
        if not self.models:
            self.models["gpt-3.5-turbo"] = ModelConfig(
                name="gpt-3.5-turbo",
                max_tokens=4096,
                max_total_tokens=16384,
                supports_tool_calls=True,
            )
            self.models["gpt-4"] = ModelConfig(
                name="gpt-4",
                max_tokens=8192,
                max_total_tokens=32768,
                supports_tool_calls=True,
            )
            self.models["gpt-4o"] = ModelConfig(
                name="gpt-4o",
                max_tokens=8192,
                max_total_tokens=128000,
                supports_vision=True,
                supports_tool_calls=True,
            )
            self.models["gpt-4-vision-preview"] = ModelConfig(
                name="gpt-4-vision-preview",
                max_tokens=4096,
                max_total_tokens=128000,
                supports_vision=True,
            )
        # 如果配置中提供了models但是是字典格式，将它们转换为ModelConfig对象
        else:
            for model_name, model_data in list(self.models.items()):
                if not isinstance(model_data, ModelConfig):
                    self.models[model_name] = ModelConfig(
                        name=model_name,
                        max_tokens=model_data.get("max_tokens", 4096),
                        max_total_tokens=model_data.get("max_total_tokens", 16384),
                        supports_vision=model_data.get("supports_vision", False),
                        supports_audio=model_data.get("supports_audio", False),
                        supports_document=model_data.get("supports_document", False),
                        supports_tool_calls=model_data.get(
                            "supports_tool_calls", False
                        ),
                    )

        # 确保有默认模型
        if not self.default_model or self.default_model not in self.models:
            # 尝试使用第一个可用模型作为默认值
            if self.models:
                self.default_model = next(iter(self.models.keys()))
            else:
                self.default_model = "gpt-3.5-turbo"


class OpenAIProvider(OpenAICompatibleProvider):
    """原生 OpenAI 提供者"""

    def __init__(self, config: OpenAIConfig, model_name: str | None = None):
        # 确保传入的model_name在config.models中存在，否则使用默认模型
        if model_name and model_name not in config.models:
            model_name = config.default_model
        super().__init__(config, model_name)
        # 根据当前使用的模型选择合适的token编码器
        self._setup_encoder()

    def _setup_encoder(self):
        """设置token编码器"""
        try:
            self.encoder = tiktoken.encoding_for_model(self.model_name)
        except KeyError:
            # 如果找不到当前模型的编码器，使用通用编码器
            self.encoder = tiktoken.get_encoding("cl100k_base")

    def switch_model(self, model_name: str):
        """切换使用的模型并更新token编码器"""
        super().switch_model(model_name)
        self._setup_encoder()

    def calculate_tokens(self, messages: list[dict[str, Any]]) -> int:
        token_count = 0
        for message in messages:
            content = message.get("content", "")
            if isinstance(content, str):
                token_count += len(self.encoder.encode(content))
            elif isinstance(content, list):
                # 处理多模态内容
                for item in content:
                    if item.get("type") == "text":
                        token_count += len(self.encoder.encode(item.get("text", "")))
                    # 图片大致估算，每张图片约1000 tokens
                    elif item.get("type") == "image_url":
                        token_count += 1000
        return token_count

    def get_available_models(self) -> list[str]:
        """获取OpenAI可用的模型列表"""
        # 返回配置中支持的模型
        return list(self.config.models.keys())
