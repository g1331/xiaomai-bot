from typing import List, Dict, Any, AsyncGenerator

import tiktoken
from loguru import logger
from openai import AsyncOpenAI

from ..core.provider import BaseAIProvider, ProviderConfig


class OpenAIConfig(ProviderConfig):
    """OpenAI特有配置"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.model = kwargs.get("model", "gpt-3.5-turbo")
        # 保留 session_token 字段兼容配置，但不再使用
        self.session_token = kwargs.get("session_token", "")
        if not self.base_url:
            self.base_url = "https://api.openai.com"


class OpenAIProvider(BaseAIProvider):
    def __init__(self, config: OpenAIConfig):
        self.config = config
        self.encoder = tiktoken.encoding_for_model(config.model)
        # 修改：使用 AsyncOpenAI 实例化客户端
        self.client = AsyncOpenAI(api_key=config.api_key, base_url=config.base_url)

    async def ask(
            self,
            messages: List[Dict[str, Any]],
            tools: List[Dict[str, Any]] = None,
            **kwargs
    ) -> AsyncGenerator[Any, None]:
        """纯粹的 API 调用封装，直接返回原始响应"""
        try:
            response = await self.client.chat.completions.create(
                model=self.config.model,
                messages=messages,
                tools=tools if tools else None,
                max_tokens=self.config.max_tokens,
                temperature=0.7,
                stream=True if tools else False
            )

            if tools:
                async for chunk in response:
                    if chunk.choices[0].delta.content:
                        yield chunk.choices[0].delta
            else:
                yield response.choices[0].message

        except Exception as e:
            logger.error(f"OpenAI API error: {e}")
            raise

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
