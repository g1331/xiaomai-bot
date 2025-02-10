from typing import List, Dict, Any, AsyncGenerator, Union

from loguru import logger
from openai import AsyncOpenAI, AsyncStream
from openai.types import CompletionUsage
from openai.types.chat import ChatCompletionMessage, ChatCompletion
from openai.types.chat.chat_completion_chunk import ChoiceDelta, ChatCompletionChunk

from ..core.provider import BaseAIProvider, ProviderConfig


class OpenAICompatibleConfig(ProviderConfig):
    """OpenAI 接口兼容的配置基类"""
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.model = kwargs.get("model", "")  # 子类需要设置默认值


class OpenAICompatibleProvider(BaseAIProvider):
    """OpenAI 接口兼容的提供者基类"""
    def __init__(self, config: OpenAICompatibleConfig):
        self.config = config
        self.client = AsyncOpenAI(api_key=config.api_key, base_url=config.base_url)
        self.usage: CompletionUsage = CompletionUsage(**{
            "completion_tokens": 0,
            "prompt_tokens": 0,
            "total_tokens": 0
        })

    async def ask(
            self,
            messages: List[Dict[str, Any]],
            tools: List[Dict[str, Any]] = None,
            stream: bool = False,
            **kwargs
    ) -> AsyncGenerator[Union[ChoiceDelta, ChatCompletionMessage], None]:
        try:
            response: ChatCompletion | AsyncStream[ChatCompletionChunk] = await self.client.chat.completions.create(
                model=self.config.model,
                messages=messages,
                tools=tools or None,
                max_tokens=self.config.max_tokens,
                temperature=0.7,
                stream=False if tools else stream
            )

            if tools:
                self.update_usage(response.usage)
                yield response.choices[0].message
            else:
                if stream:
                    async for chunk in response:
                        if chunk.choices[0].delta.content:
                            yield chunk.choices[0].delta
                else:
                    self.update_usage(response.usage)
                    yield response.choices[0].message

        except Exception as e:
            logger.error(f"{self.__class__.__name__} API error: {e}")
            raise

    def get_usage(self) -> dict[str, int]:
        return self.usage.dict()

    def update_usage(self, usage: CompletionUsage):
        if not self.usage:
            self.usage = usage
            return
        if not usage:
            return
        self.usage.total_tokens += usage.total_tokens
        self.usage.completion_tokens += usage.completion_tokens
        self.usage.prompt_tokens += usage.prompt_tokens
        self.usage.completion_tokens_details = usage.completion_tokens_details
        self.usage.prompt_tokens_details = usage.prompt_tokens_details
