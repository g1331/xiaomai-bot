# src/ai_chat/providers/openai.py
"""
OpenAI 实现（兼容ChatGPT和API）
"""
import tiktoken
from revChatGPT.V3 import Chatbot

from ..core.provider import BaseAIProvider, ProviderConfig


class OpenAIConfig(ProviderConfig):
    """OpenAI特有配置"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.model = kwargs.get("model", "gpt-3.5-turbo")
        self.session_token = kwargs.get("session_token", "")


class OpenAIProvider(BaseAIProvider):
    def __init__(self, config: OpenAIConfig):
        self.config = config
        self.encoder = tiktoken.encoding_for_model(config.model)
        self._init_client()

    def _init_client(self):
        # 实现初始化逻辑（兼容官方库和第三方库）
        if self.config.session_token:
            from revChatGPT.V1 import AsyncChatbot
            self.client = AsyncChatbot(config={
                "access_token": self.config.session_token,
                "proxy": self.config.proxy
            })
        else:
            self.client = Chatbot(
                api_key=self.config.api_key,
                proxy=self.config.proxy,
                max_tokens=self.config.max_tokens
            )

    async def ask(self, prompt: str, history=None, **kwargs):
        if isinstance(self.client, Chatbot):  # API模式
            full_response = ""
            for resp in self.client.ask_stream(prompt):
                full_response += resp
                yield resp
            self._update_usage(prompt, full_response)
        else:  # 非官方API模式
            async for resp in self.client.ask(prompt):
                yield resp["message"]

    def _update_usage(self, prompt, response):
        prompt_tokens = len(self.encoder.encode(prompt))
        resp_tokens = len(self.encoder.encode(response))
        self.usage = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": resp_tokens,
            "total_tokens": prompt_tokens + resp_tokens
        }

    def get_usage(self):
        return getattr(self, "usage", {})

    def reset(self, system_prompt=""):
        if hasattr(self.client, "reset"):
            self.client.reset(system_prompt)
        else:
            self.client.reset_chat()
