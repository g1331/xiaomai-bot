from typing import List, Dict, Any, AsyncGenerator

from loguru import logger
from openai import AsyncOpenAI

from ..core.provider import BaseAIProvider, ProviderConfig


class DeepSeekConfig(ProviderConfig):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.model = kwargs.get("model", "deepseek-chat")
        self.api_key = kwargs.get("api_key", "")
        self.base_url = kwargs.get("base_url", "https://api.deepseek.com/v1")


class DeepSeekProvider(BaseAIProvider):
    def __init__(self, config: DeepSeekConfig):
        self.config = config
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
            logger.error(f"DeepSeek API error: {e}")
            raise

    def get_usage(self) -> dict:
        return {}
