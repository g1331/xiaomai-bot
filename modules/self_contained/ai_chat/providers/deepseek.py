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
