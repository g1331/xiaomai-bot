from .openai_compatible import OpenAICompatibleConfig, OpenAICompatibleProvider


class OpenAIConfig(OpenAICompatibleConfig):
    """OpenAI 特有配置"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.model = kwargs.get("model", "gpt-3.5-turbo")
        # 保留 session_token 字段兼容配置，但不再使用
        self.session_token = kwargs.get("session_token", "")
        if not self.base_url:
            self.base_url = "https://api.openai.com"


class OpenAIProvider(OpenAICompatibleProvider):
    """原生 OpenAI 提供者"""

    def __init__(self, config: OpenAIConfig):
        super().__init__(config)
