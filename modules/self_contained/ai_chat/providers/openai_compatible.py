import base64
from abc import abstractmethod
from typing import Any
from collections.abc import AsyncGenerator

from loguru import logger
from openai import AsyncOpenAI, AsyncStream
from openai.types import CompletionUsage
from openai.types.chat import ChatCompletion, ChatCompletionMessage
from openai.types.chat.chat_completion_chunk import ChatCompletionChunk, ChoiceDelta

from ..core.provider import (
    BaseAIProvider,
    FileContent,
    FileType,
    ProviderConfig,
)


class OpenAICompatibleConfig(ProviderConfig):
    """OpenAI 接口兼容的配置基类"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # OpenAI兼容的提供者可能有其他特殊配置项


class OpenAICompatibleProvider(BaseAIProvider):
    """OpenAI 接口兼容的提供者基类"""

    def __init__(self, config: OpenAICompatibleConfig, model_name: str | None = None):
        super().__init__(config, model_name)
        self.client = AsyncOpenAI(api_key=config.api_key, base_url=config.base_url)
        self.usage: CompletionUsage = CompletionUsage(
            **{"completion_tokens": 0, "prompt_tokens": 0, "total_tokens": 0}
        )

    @abstractmethod
    def calculate_tokens(self, messages: list[dict[str, Any]]) -> int:
        pass

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

            # 处理工具调用支持
            use_tools = tools and self.supports_tools
            if tools and not self.supports_tools:
                logger.warning(f"模型 {self.model_name} 不支持工具调用，已忽略工具配置")
                tools = None

            # 在API请求前记录日志，帮助调试
            if logger.level == "DEBUG":
                # 只输出重要字段，避免日志过大
                log_messages = []
                for msg in processed_messages:
                    log_msg = {"role": msg.get("role")}
                    content = msg.get("content")
                    if isinstance(content, str):
                        log_msg["content"] = (
                            content[:100] + "..." if len(content) > 100 else content
                        )
                    elif isinstance(content, list):
                        log_msg["content"] = f"[多模态内容，包含 {len(content)} 项]"
                    log_messages.append(log_msg)
                logger.debug(f"发送给API的消息: {log_messages}")

            try:
                # temperature 设置
                # 代码生成/数学解题 0.0
                # 数据抽取/分析	1.0
                # 通用对话	1.3
                # 翻译	1.3
                # 创意类写作/诗歌创作	1.5
                response: (
                    ChatCompletion | AsyncStream[ChatCompletionChunk]
                ) = await self.client.chat.completions.create(
                    model=self.model_name,
                    messages=processed_messages,
                    tools=tools or None,
                    max_tokens=self.model_config.max_tokens,
                    temperature=1.3,
                    stream=False if use_tools else stream,
                )

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
                # 提供更详细的错误信息
                error_message = f"{self.__class__.__name__} API error: {str(e)}"
                logger.error(error_message)
                # 创建一个包含错误信息的消息对象返回给调用者
                error_response = ChatCompletionMessage(
                    role="assistant",
                    content=f"与AI服务通信时发生错误: {str(e)}",
                )
                yield error_response

        except Exception as e:
            logger.error(f"{self.__class__.__name__} ASK方法错误: {e}")
            raise
