"""DuckDuckGo搜索插件实现。

本模块实现了基于DuckDuckGo搜索引擎的网络搜索功能，
支持文本搜索与新闻搜索，均可实时获取信息并返回参考链接。
使用duckduckgo_search库的text()和news()方法执行搜索。
"""
from typing import Dict, Any, Set
import asyncio
from duckduckgo_search import DDGS
from ..core.plugin import BasePlugin, PluginConfig, PluginDescription


class DuckDuckGoConfig(PluginConfig):
    """DuckDuckGo搜索插件配置。

    Attributes:
        region: 搜索区域代码，默认"cn-zh"
        max_results: 最大返回结果数，默认10条
    """
    region: str = "cn-zh"
    max_results: int = 10

    @property
    def required_fields(self) -> Set[str]:
        return set()


class DuckDuckGoPlugin(BasePlugin):
    """DuckDuckGo搜索插件实现类。"""

    def __init__(self, config: DuckDuckGoConfig) -> None:
        """初始化搜索插件。

        Args:
            config: 插件配置对象
        """
        super().__init__(config)

    @property
    def description(self) -> PluginDescription:
        """获取插件描述。

        Returns:
            PluginDescription: 包含插件功能描述的对象
        """
        return PluginDescription(
            name="DuckDuckGoSearch",
            description="提供简易的搜索功能。",
            parameters={
                "query": "搜索关键词",
                "region": "搜索区域代码，如`cn-zh`表示中国",
                "max_results": f"最大返回结果数，不能超过{self.config.max_results}条",
                "type": "搜索类型，默认为'web'，可选'news'表示新闻搜索",
            },
            example="搜索`Python`相关信息，或搜索新闻时指定 type 为 news",
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
            str: 格式化的搜索结果文本，包含标题、描述和链接
        """
        query = params.get("query")
        if not query:
            return "错误：缺少搜索关键词，请提供参数 'query'。"
        max_results = int(params.get("max_results", self.config.max_results))
        if max_results > self.config.max_results:
            return f"错误：最大返回结果数不能超过{self.config.max_results}条。"
        region = params.get("region", self.config.region)
        search_type = params.get("type", "web").lower()  # 默认为 web 搜索
        loop = asyncio.get_event_loop()

        # 根据搜索类型调用不同的方法
        if search_type == "news":
            search_func = lambda: list(DDGS().news(
                keywords=query,
                region=region,
                safesearch="moderate",
                timelimit=None,
                max_results=max_results,
            )) or []
        else:
            search_func = lambda: list(DDGS().text(
                keywords=query,
                region=region,
                safesearch="moderate",
                timelimit=None,
                backend="auto",
                max_results=max_results,
            )) or []

        results = await loop.run_in_executor(None, search_func)
        formatted = "网络搜索结果：\n"
        for i, item in enumerate(results, 1):
            if search_type == "news":
                formatted += (
                    f"{i}. {item.get('title', '')}\n"
                    f"描述: {item.get('body', '')}\n"
                    f"链接: {item.get('url', '')}\n\n"
                )
            else:
                formatted += (
                    f"{i}. {item.get('body', item.get('title', ''))}\n"
                    f"URL: {item.get('href', '')}\n\n"
                )
        return formatted
