"""
新增插件元数据和方法
"""
from typing import Optional, Dict, Any
from abc import ABC, abstractmethod
from pydantic import BaseModel


class PluginDecision(BaseModel):
    """插件决策结果"""
    should_trigger: bool
    parameters: Dict[str, Any] = {}
    confidence: float = 0.0


class PluginDescription(BaseModel):
    """插件功能描述"""
    name: str
    description: str
    parameters: Dict[str, str]
    example: str


class PluginConfig(BaseModel):
    """插件配置基类"""
    api_key: str = ""
    base_url: str = ""
    max_results: int = 3
    timeout: int = 30


class BasePlugin(ABC):
    @property
    @abstractmethod
    def description(self) -> PluginDescription:
        """返回插件的功能描述"""
        pass

    @abstractmethod
    async def decide(
            self,
            user_input: str,
            history: list[dict],
            provider: Any
    ) -> PluginDecision:
        """由AI决定是否触发插件"""
        pass

    @abstractmethod
    async def execute(
            self,
            parameters: Dict[str, Any]
    ) -> str:
        """执行插件功能"""
        pass
