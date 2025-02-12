from typing import List, Dict, Any

from .openai_compatible import OpenAICompatibleConfig, OpenAICompatibleProvider


class DeepSeekConfig(OpenAICompatibleConfig):
    """DeepSeek 特有配置"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.model = kwargs.get("model", "deepseek-chat")
        if not self.base_url:
            self.base_url = "https://api.deepseek.com/v1"


class DeepSeekProvider(OpenAICompatibleProvider):
    """DeepSeek 提供者"""

    def __init__(self, config: DeepSeekConfig):
        super().__init__(config)

    def calculate_tokens(self, messages: List[Dict[str, Any]]) -> int:
        """计算消息的token数
        这里只是根据官方文档的提示，简单估算了一下。
        1 个英文字符 ≈ 0.3 个 token。
        1 个中文字符 ≈ 0.6 个 token。
        """
        total_tokens = 0
        for message in messages:
            content = message["content"]
            english_chars = sum(bool(char.isascii()) for char in content)
            chinese_chars = len(content) - english_chars
            total_tokens += english_chars * 0.3 + chinese_chars * 0.6
        return int(total_tokens)
