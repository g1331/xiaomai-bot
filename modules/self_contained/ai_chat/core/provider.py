"""
AI提供商抽象层
定义统一的接口规范，方便扩展不同AI平台
"""

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, AsyncGenerator, Dict, List, Optional


class FileType(Enum):
    """文件类型枚举"""

    IMAGE = "image"
    DOCUMENT = "document"
    AUDIO = "audio"
    VIDEO = "video"
    OTHER = "other"


class FileContent:
    """文件内容结构"""

    def __init__(
        self,
        file_type: FileType,
        file_bytes: bytes = None,
        file_path: str = None,
        file_url: str = None,
        file_name: str = None,
        mime_type: str = None,
    ):
        self.file_type = file_type
        self.file_bytes = file_bytes
        self.file_path = file_path
        self.file_url = file_url
        self.file_name = file_name or "file"
        self.mime_type = mime_type


class ModelConfig:
    """模型配置类，描述特定模型的能力和限制"""

    def __init__(self, **kwargs):
        self.name: str = kwargs.get("name", "")  # 模型名称
        self.max_tokens: int = kwargs.get("max_tokens", 8192)  # 最大输出长度,默认8k
        self.max_total_tokens: int = kwargs.get(
            "max_total_tokens", 32 * 1024
        )  # 最大输入长度,默认32k
        # 是否支持多模态
        self.supports_vision: bool = kwargs.get("supports_vision", False)
        self.supports_audio: bool = kwargs.get("supports_audio", False)
        self.supports_document: bool = kwargs.get("supports_document", False)
        # 是否支持工具调用
        self.supports_tool_calls: bool = kwargs.get("supports_tool_calls", False)


class ProviderConfig:
    """提供商配置基类"""

    def __init__(self, **kwargs):
        self.api_key: str = kwargs.get("api_key", "")
        self.base_url: str = kwargs.get("base_url", "")
        self.proxy: str = kwargs.get("proxy", "")
        self.timeout: int = kwargs.get("timeout", 360)
        # 默认使用的模型名称
        self.default_model: str = kwargs.get("default_model", "")
        # 该提供商支持的所有模型配置字典
        self.models: Dict[str, ModelConfig] = kwargs.get("models", {})

    def get_model_config(self, model_name: Optional[str] = None) -> ModelConfig:
        """获取指定模型的配置，如果未指定则返回默认模型配置"""
        name = model_name or self.default_model
        if not name:
            raise ValueError("未指定模型名称且未设置默认模型")

        if name not in self.models:
            raise ValueError(f"未找到模型配置: {name}")

        return self.models[name]


class BaseAIProvider(ABC):

    def __init__(self, config: ProviderConfig, model_name: Optional[str] = None):
        self.config = config
        self.model_name = model_name or config.default_model

        # 获取当前使用的模型配置
        self.model_config = config.get_model_config(self.model_name)

        self.usage = {"completion_tokens": 0, "prompt_tokens": 0, "total_tokens": 0}

    @abstractmethod
    async def ask(
        self,
        messages: List[Dict[str, Any]],
        files: List[FileContent] = None,
        tools: List[Dict[str, Any]] = None,
        **kwargs,
    ) -> AsyncGenerator[Any, None]:
        """
        纯粹的消息接口封装,接收完整的消息列表和工具配置
        Args:
            messages: 完整的消息列表
            files: 文件内容列表(多模态支持)
            tools: 工具配置列表
        """
        yield

    @abstractmethod
    def get_usage(self) -> dict:
        """获取当前资源使用情况"""
        pass

    @abstractmethod
    def reset_usage(self):
        """重置资源使用情况"""
        pass

    @abstractmethod
    def set_total_tokens(self, total_tokens: int):
        pass

    @abstractmethod
    def calculate_tokens(self, messages: List[Dict[str, Any]]) -> int:
        """计算消息的token数"""
        pass

    def switch_model(self, model_name: str):
        """切换使用的模型"""
        if model_name not in self.config.models:
            raise ValueError(f"未找到模型配置: {model_name}")
        self.model_name = model_name
        self.model_config = self.config.get_model_config(model_name)

    @property
    def supports_multimodal(self) -> bool:
        """检查当前使用的模型是否支持多模态"""
        return any(
            [
                self.model_config.supports_vision,
                self.model_config.supports_audio,
                self.model_config.supports_document,
            ]
        )

    @property
    def supports_tools(self) -> bool:
        """检查当前使用的模型是否支持工具调用"""
        return self.model_config.supports_tool_calls

    def supports_file_type(self, file_type: FileType) -> bool:
        """检查当前使用的模型是否支持特定文件类型"""
        if file_type == FileType.IMAGE:
            return self.model_config.supports_vision
        elif file_type == FileType.AUDIO:
            return self.model_config.supports_audio
        elif file_type == FileType.DOCUMENT:
            return self.model_config.supports_document
        return False

    def process_files(self, files: List[FileContent]) -> List[FileContent]:
        """处理并过滤文件列表，只保留支持的类型"""
        if not files:
            return []

        if not self.supports_multimodal:
            return []

        return [f for f in files if self.supports_file_type(f.file_type)]

    def get_available_models(self) -> list[str]:
        """获取当前提供商可用的模型列表"""
        # 默认实现返回当前模型
        if hasattr(self, "model_name") and self.model_name:
            return [self.model_name]
        return []
