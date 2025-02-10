"""插件系统的核心类和接口定义。

本模块定义了插件系统所需的基础类和接口，包括:
- PluginDescription: 插件描述信息模型
- PluginConfig: 插件配置基类
- BasePlugin: 插件抽象基类
"""
from abc import ABC, abstractmethod
from typing import Dict, Any

from pydantic import BaseModel


class PluginDescription(BaseModel):
    """插件功能描述数据模型。

    Attributes:
        name: 插件名称
        description: 插件功能描述
        parameters: 插件参数说明字典，key为参数名，value为参数说明
        example: 插件使用示例
    """
    name: str
    description: str
    parameters: Dict[str, str]
    example: str


class PluginConfig(BaseModel):
    """插件配置基类。

    Attributes:
        api_key: API密钥
        base_url: API基础URL
        max_results: 最大返回结果数
        timeout: 超时时间(秒)
    """
    api_key: str = ""
    base_url: str = ""
    max_results: int = 3
    timeout: int = 30


class BasePlugin(ABC):
    """插件抽象基类。

    所有具体插件类都必须继承此类并实现其抽象方法。
    """

    @property
    @abstractmethod
    def description(self) -> PluginDescription:
        """获取插件的功能描述。

        Returns:
            PluginDescription: 插件的功能描述对象
        """
        pass

    @abstractmethod
    async def execute(
            self,
            parameters: Dict[str, Any]
    ) -> str:
        """执行插件功能。

        Args:
            parameters: 执行插件所需的参数字典

        Returns:
            str: 插件执行的结果
            
        Raises:
            Exception: 插件执行过程中的任何异常
        """
        pass
