from typing import List, Dict, Any

import tiktoken

from .openai_compatible import OpenAICompatibleConfig, OpenAICompatibleProvider


class OpenAIConfig(OpenAICompatibleConfig):
    """OpenAI 特有配置"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.model = kwargs.get("model", "gpt-3.5-turbo")
        if not self.base_url:
            self.base_url = "https://api.openai.com"
        
        # 根据模型名称设置多模态支持
        vision_models = ["gpt-4-vision", "gpt-4-vision-preview", "gpt-4o", "gpt-4-turbo"]
        if any(vm in self.model for vm in vision_models):
            self.supports_vision = True


class OpenAIProvider(OpenAICompatibleProvider):
    """原生 OpenAI 提供者"""

    def __init__(self, config: OpenAIConfig):
        super().__init__(config)
        self.encoder = tiktoken.encoding_for_model(config.model)

    def calculate_tokens(self, messages: List[Dict[str, Any]]) -> int:
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
