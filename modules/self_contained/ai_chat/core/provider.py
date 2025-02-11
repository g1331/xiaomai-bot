"""
AI提供商抽象层
定义统一的接口规范，方便扩展不同AI平台
"""
from abc import ABC, abstractmethod
from typing import AsyncGenerator, List, Dict, Any


class ProviderConfig:
    """提供商配置基类"""

    def __init__(self, **kwargs):
        self.api_key: str = kwargs.get("api_key", "")
        self.base_url: str = kwargs.get("base_url", "")
        self.max_tokens: int = kwargs.get("max_tokens", 8192)  # 最大输出长度,默认8k
        self.max_total_tokens: int = kwargs.get("max_total_tokens", 32 * 1024)  # 最大输入长度,默认32k
        self.proxy: str = kwargs.get("proxy", "")
        self.timeout: int = kwargs.get("timeout", 360)
        self.model: str = kwargs.get("model", "")


class BaseAIProvider(ABC):

    def __init__(self, config: ProviderConfig):
        self.config = config

    @abstractmethod
    async def ask(
            self,
            messages: List[Dict[str, Any]],
            tools: List[Dict[str, Any]] = None,
            **kwargs
    ) -> AsyncGenerator[Any, None]:
        """
        纯粹的消息接口封装,接收完整的消息列表和工具配置
        Args:
            messages: 完整的消息列表
            tools: 工具配置列表
        """
        yield

    @abstractmethod
    def get_usage(self) -> dict:
        """获取当前资源使用情况"""
        pass
