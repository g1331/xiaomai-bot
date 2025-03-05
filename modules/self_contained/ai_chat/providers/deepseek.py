from typing import Any, Dict, List, Optional

from ..core.provider import ModelConfig
from .openai_compatible import OpenAICompatibleConfig, OpenAICompatibleProvider


class DeepSeekConfig(OpenAICompatibleConfig):
    """DeepSeek 特有配置"""

    def __init__(self, **kwargs):
        # 首先调用父类初始化
        super().__init__(**kwargs)

        # 如果没有提供基础URL，设置默认值
        if not self.base_url:
            self.base_url = "https://api.deepseek.com/v1"

        # 确保models是字典而不是None
        if not self.models:
            self.models = {}

        # 如果models为空，创建默认模型配置
        if not self.models:
            self.models["deepseek-chat"] = ModelConfig(
                name="deepseek-chat",
                max_tokens=8192,
                max_total_tokens=64000,
                supports_tool_calls=True,
            )
            self.models["deepseek-reasoner"] = ModelConfig(
                name="deepseek-reasoner",
                max_tokens=8192,
                max_total_tokens=64000,
                supports_tool_calls=True,
            )
        # 如果配置中提供了models但是是字典格式，将它们转换为ModelConfig对象
        else:
            for model_name, model_data in list(self.models.items()):
                if not isinstance(model_data, ModelConfig):
                    self.models[model_name] = ModelConfig(
                        name=model_name,
                        max_tokens=model_data.get("max_tokens", 8192),
                        max_total_tokens=model_data.get("max_total_tokens", 32000),
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
                self.default_model = "deepseek-chat"


class DeepSeekProvider(OpenAICompatibleProvider):
    """DeepSeek 提供者"""

    def __init__(self, config: DeepSeekConfig, model_name: Optional[str] = None):
        # 确保传入的model_name在config.models中存在，否则使用默认模型
        if model_name and model_name not in config.models:
            model_name = config.default_model
        super().__init__(config, model_name)

    def calculate_tokens(self, messages: List[Dict[str, Any]]) -> int:
        """计算消息的token数
        这里只是根据官方文档的提示，简单估算了一下。
        1 个英文字符 ≈ 0.3 个 token。
        1 个中文字符 ≈ 0.6 个 token。
        """
        total_tokens = 0
        for message in messages:
            content = message.get("content", "")
            if isinstance(content, str):
                english_chars = sum(bool(char.isascii()) for char in content)
                chinese_chars = len(content) - english_chars
                total_tokens += english_chars * 0.3 + chinese_chars * 0.6
            elif isinstance(content, list):
                # 处理多模态内容
                for item in content:
                    if item.get("type") == "text":
                        text_content = item.get("text", "")
                        english_chars = sum(
                            bool(char.isascii()) for char in text_content
                        )
                        chinese_chars = len(text_content) - english_chars
                        total_tokens += english_chars * 0.3 + chinese_chars * 0.6
                    # 图片大致估算，每张图片约1000 tokens
                    elif item.get("type") == "image_url":
                        total_tokens += 1000
        return int(total_tokens)

    def get_available_models(self) -> list[str]:
        """获取DeepSeek可用的模型列表"""
        # 返回配置中支持的模型
        return list(self.config.models.keys())
