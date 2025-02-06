import openai

from ..core.provider import BaseAIProvider, ProviderConfig


class DeepSeekConfig(ProviderConfig):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.model = kwargs.get("model", "deepseek-chat")
        self.api_key = kwargs.get("api_key", "")
        self.base_url = kwargs.get("base_url", "https://api.deepseek.ai/v1/chat")


class DeepSeekProvider(BaseAIProvider):
    def __init__(self, config: DeepSeekConfig):
        self.config = config
        openai.api_key = config.api_key
        openai.api_base = config.base_url

    async def ask(self, prompt: str, history=None, **kwargs):
        if history:
            messages = history + [{"role": "user", "content": prompt}]
        else:
            messages = [{"role": "user", "content": prompt}]

        response = openai.ChatCompletion.create(
            model=self.config.model,
            messages=messages,
            stream=False
        )
        yield response.choices[0].message["content"]

    def reset(self, system_prompt: str = ""):
        # 仅用于清理内部状态，管理历史对话由 manager 负责
        pass

    def get_usage(self) -> dict:
        return {}
