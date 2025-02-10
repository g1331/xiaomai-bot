"""DuckDuckGo搜索插件实现。

本模块实现了基于DuckDuckGo搜索引擎的网络搜索功能。
使用duckduckgo_search库的text()方法执行搜索。
"""
from typing import Dict, Any
import asyncio
from duckduckgo_search import DDGS
from ..core.plugin import BasePlugin, PluginConfig, PluginDescription


class WebSearchConfig(PluginConfig):
    """DuckDuckGo搜索插件配置。

    Attributes:
        region: 搜索区域代码，默认"cn-zh"
        max_results: 最大返回结果数，默认3条
    """
    region: str = "cn-zh"
    max_results: int = 3


class WebSearchPlugin(BasePlugin):
    """DuckDuckGo搜索插件实现类。"""

    def __init__(self, config: WebSearchConfig) -> None:
        """初始化搜索插件。

        Args:
            config: 插件配置对象
        """
        self.config = config

    @property
    def description(self) -> PluginDescription:
        """获取插件描述。

        Returns:
            PluginDescription: 包含插件功能描述的对象
        """
        return PluginDescription(
            name="WebSearch",
            description="使用DDG进行文本搜索",
            parameters={"query": "搜索关键词", "region": "搜索区域代码如`cn-zh for China`",
                        "max_results": "最大返回结果数"},
            example="搜索`Python`相关信息",
        )

    async def execute(self, parameters: Dict[str, Any]) -> str:
        """执行搜索功能。

        Args:
            parameters: 包含搜索参数的字典，必须包含"query"键

        Returns:
            str: 格式化的搜索结果文本

        Raises:
            KeyError: 当parameters中缺少必要的"query"参数时
        """
        return await self.handle(parameters)

    async def handle(self, params: dict) -> str:
        """处理搜索请求。

        Args:
            params: 搜索参数字典，必须包含"query"键
            
        Returns:
            str: 格式化的搜索结果文本，包含标题、描述和URL
        """
        query = params.get("query")
        if not query:
            return "错误：缺少搜索关键词，请提供参数 'query'。"
        max_results = int(params.get("max_results", self.config.max_results))
        if max_results > 10:
            return "错误：最大返回结果数不能超过10条。"
        region = params.get("region", self.config.region)
        loop = asyncio.get_event_loop()
        results = await loop.run_in_executor(
            None,
            lambda: DDGS().text(
                keywords=query,
                region=region,
                safesearch="moderate",
                timelimit=None,
                backend="auto",
                max_results=max_results,
            ) or []
        )
        formatted = "网络搜索结果：\n"
        for i, item in enumerate(results, 1):
            formatted += f"{i}. {item.get('body', item.get('title', ''))}\nURL: {item.get('href', '')}\n\n"
        return formatted
