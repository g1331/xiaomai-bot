"""
AI提供商抽象层
定义统一的接口规范，方便扩展不同AI平台
"""
from abc import ABC, abstractmethod
from typing import Any, AsyncGenerator


class BaseAIProvider(ABC):
    @abstractmethod
    async def ask(
            self,
            prompt: str,
            history: list[dict] = None,
            json_mode: bool = False,
            **kwargs
    ) -> AsyncGenerator[str, None]:
        """异步生成器，流式返回响应"""
        pass

    @abstractmethod
    def reset(self, system_prompt: str = ""):
        """重置提供商内部状态，对话历史由 manager 管理"""
        pass

    @abstractmethod
    def get_usage(self) -> dict:
        """获取当前资源使用情况"""
        pass


class ProviderConfig:
    """提供商配置基类"""

    def __init__(self, **kwargs):
        self.api_key: str = kwargs.get("api_key", "")
        self.base_url: str = kwargs.get("base_url", "")
        self.max_tokens: int = kwargs.get("max_tokens", 2000)
        self.proxy: str = kwargs.get("proxy", "")
        self.timeout: int = kwargs.get("timeout", 30)
