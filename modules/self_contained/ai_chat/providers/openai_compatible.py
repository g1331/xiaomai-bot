import base64
from abc import abstractmethod
from typing import Any
from collections.abc import AsyncGenerator

from loguru import logger
from openai import AsyncOpenAI
from openai.types import CompletionUsage
from openai.types.chat import ChatCompletionMessage
from openai.types.chat.chat_completion_chunk import ChoiceDelta

from ..core.provider import (
    BaseAIProvider,
    FileContent,
    FileType,
    ModelConfig,
    ProviderConfig,
)


class OpenAICompatibleConfig(ProviderConfig):
    """OpenAI 接口兼容的配置基类"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        # API配置
        self.api_version = kwargs.get("api_version", "v1")
        self.organization = kwargs.get("organization", None)
        self.headers = kwargs.get("headers", {})

        # 请求配置
        self.request_timeout = kwargs.get("request_timeout", 60)
        self.max_retries = kwargs.get("max_retries", 2)

        # 响应格式配置
        self.response_format = kwargs.get("response_format", {"type": "text"})

        # 模型行为配置
        self.supports_functions = kwargs.get("supports_functions", True)
        self.supports_tools = kwargs.get("supports_tools", True)
        self.supports_json_mode = kwargs.get("supports_json_mode", False)
        self.supports_vision = kwargs.get("supports_vision", False)

        # 令牌计数配置
        self.token_encoding = kwargs.get(
            "token_encoding", "cl100k_base"
        )  # 使用的分词器
        self.token_multiplier = kwargs.get(
            "token_multiplier", 1.0
        )  # 令牌估算的乘数因子

        # 请求参数映射，允许自定义参数名称
        self.param_mapping = kwargs.get(
            "param_mapping",
            {
                "model": "model",
                "messages": "messages",
                "temperature": "temperature",
                "max_tokens": "max_tokens",
                "stream": "stream",
                "tools": "tools",
                "tool_choice": "tool_choice",
            },
        )

        # 响应格式映射，允许适配不同的返回格式
        self.response_mapping = kwargs.get(
            "response_mapping",
            {
                "choices": "choices",
                "message": "message",
                "content": "content",
                "role": "role",
                "delta": "delta",
                "tool_calls": "tool_calls",
            },
        )

        # 确保models字典的每个值都是ModelConfig对象
        if self.models:
            self.models = {
                name: (
                    config
                    if isinstance(config, ModelConfig)
                    else ModelConfig(
                        name=name,
                        max_tokens=config.get("max_tokens", 4096),
                        max_total_tokens=config.get("max_total_tokens", 32768),
                        supports_vision=config.get("supports_vision", False),
                        supports_audio=config.get("supports_audio", False),
                        supports_document=config.get("supports_document", False),
                        supports_tool_calls=config.get("supports_tool_calls", False),
                    )
                )
                for name, config in self.models.items()
            }


class OpenAICompatibleProvider(BaseAIProvider):
    """OpenAI 接口兼容的提供者基类"""

    def __init__(self, config: OpenAICompatibleConfig, model_name: str | None = None):
        super().__init__(config, model_name)
        self.config = config
        # 创建带有自定义配置的客户端
        self.client = AsyncOpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
            organization=config.organization,
            default_headers=config.headers,
            timeout=config.request_timeout,
            max_retries=config.max_retries,
        )
        self.usage: CompletionUsage = CompletionUsage(
            **{"completion_tokens": 0, "prompt_tokens": 0, "total_tokens": 0}
        )

    def _map_request_params(self, **params) -> dict:
        """根据配置映射请求参数"""
        mapped_params = {}
        for key, value in params.items():
            if key in self.config.param_mapping:
                mapped_key = self.config.param_mapping[key]
                mapped_params[mapped_key] = value
        return mapped_params

    def _map_response_data(self, response_data: dict) -> dict:
        """根据配置映射响应数据"""
        mapped_data = {}
        for key, value in self.config.response_mapping.items():
            if value in response_data:
                mapped_data[key] = response_data[value]
        return mapped_data

    @abstractmethod
    def calculate_tokens(self, messages: list[dict[str, Any]]) -> int:
        """使用配置的编码器和乘数因子估算token数量"""
        try:
            import tiktoken

            encoding = tiktoken.get_encoding(self.config.token_encoding)
            total_tokens = 0

            for message in messages:
                content = message.get("content", "")
                if isinstance(content, str):
                    tokens = len(encoding.encode(content))
                elif isinstance(content, list):  # 多模态内容
                    for item in content:
                        if item.get("type") == "text":
                            tokens = len(encoding.encode(item.get("text", "")))
                            total_tokens += tokens
                        elif item.get("type") == "image_url":
                            # 图片token估算（根据不同模型可能需要调整）
                            total_tokens += 1000  # 默认估算值
                else:
                    continue

                total_tokens += tokens

            # 应用配置的乘数因子
            return int(total_tokens * self.config.token_multiplier)
        except Exception as e:
            logger.warning(f"Token计算失败，使用字符长度估算: {str(e)}")
            # 降级方案：使用字符长度粗略估算
            return sum(len(str(msg.get("content", ""))) for msg in messages)

    def set_total_tokens(self, total_tokens: int):
        self.usage.total_tokens = total_tokens

    def get_usage(self) -> dict[str, int]:
        return self.usage.dict()

    def reset_usage(self):
        self.usage.completion_tokens = 0
        self.usage.prompt_tokens = 0
        self.usage.total_tokens = 0

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

    def _process_file_content(self, file: FileContent) -> dict[str, Any]:
        """处理文件内容，转换为OpenAI API可接受的格式"""
        if file.file_type == FileType.IMAGE:
            # 处理图片文件
            content = None
            if file.file_bytes:
                # 直接使用字节数据
                b64_data = base64.b64encode(file.file_bytes).decode("utf-8")
                mime = file.mime_type or "image/jpeg"  # 默认为JPEG
                content = {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{b64_data}"},
                }
            elif file.file_url:
                # 使用URL
                content = {"type": "image_url", "image_url": {"url": file.file_url}}
            return content

        # 其他文件类型暂不处理，未来可以扩展
        return None

    def _prepare_messages_with_files(
        self, messages: list[dict[str, Any]], files: list[FileContent] = None
    ) -> list[dict[str, Any]]:
        """准备包含文件的消息"""
        if not files or not self.supports_multimodal:
            return messages

        # 找到最后一条用户消息
        last_user_msg_idx = None
        for i in range(len(messages) - 1, -1, -1):
            if messages[i].get("role") == "user":
                last_user_msg_idx = i
                break

        if last_user_msg_idx is None:
            # 如果没有用户消息，将文件附加到最后一条消息
            return messages

        # 处理文件
        supported_files = self.process_files(files)
        if not supported_files:
            return messages

        # 创建新的消息副本
        new_messages = messages.copy()
        last_msg = new_messages[last_user_msg_idx].copy()

        # 转换为多模态格式
        content = last_msg.get("content", "")
        new_content = []

        # 添加文本内容
        if isinstance(content, str) and content:
            new_content.append({"type": "text", "text": content})

        # 添加文件内容，限制图片大小和数量
        image_count = 0
        max_images = 5  # 限制每次请求最多添加5张图片

        for file in supported_files:
            # 限制图片数量
            if file.file_type == FileType.IMAGE:
                if image_count >= max_images:
                    logger.warning(f"图片数量超过限制({max_images})，忽略额外图片")
                    continue
                image_count += 1

            file_content = self._process_file_content(file)
            if file_content:
                new_content.append(file_content)

        # 更新消息
        if new_content:
            last_msg["content"] = new_content
            new_messages[last_user_msg_idx] = last_msg

        return new_messages

    async def ask(
        self,
        messages: list[dict[str, Any]],
        files: list[FileContent] = None,
        tools: list[dict[str, Any]] = None,
        stream: bool = False,
        **kwargs,
    ) -> AsyncGenerator[ChoiceDelta | ChatCompletionMessage, None]:
        try:
            # 处理多模态消息
            processed_messages = self._prepare_messages_with_files(messages, files)

            # 检查并应用工具支持
            use_tools = tools and self.config.supports_tools
            if tools and not self.config.supports_tools:
                logger.warning(f"模型 {self.model_name} 不支持工具调用，已忽略工具配置")
                tools = None

            # 准备请求参数
            request_params = self._map_request_params(
                model=self.model_name,
                messages=processed_messages,
                tools=tools,
                max_tokens=self.model_config.max_tokens,
                temperature=kwargs.get("temperature", 1.3),
                stream=False if use_tools else stream,
                response_format=self.config.response_format
                if self.config.supports_json_mode
                else None,
            )

            try:
                # 发送请求
                response = await self.client.chat.completions.create(**request_params)

                if use_tools:
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
                error_message = f"{self.__class__.__name__} API error: {str(e)}"
                logger.error(error_message)
                yield ChatCompletionMessage(
                    role="assistant",
                    content=f"与AI服务通信时发生错误: {str(e)}",
                )

        except Exception as e:
            logger.error(f"{self.__class__.__name__} ASK方法错误: {e}")
            raise
