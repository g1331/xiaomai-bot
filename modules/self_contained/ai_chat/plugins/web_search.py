# src/ai_chat/plugins/web_search.py
"""
网络搜索插件实现
"""
from typing import Optional, Dict, Any

import aiohttp
from ..core.plugin import BasePlugin, PluginConfig, PluginDescription, PluginDecision


class WebSearchConfig(PluginConfig):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.api_url: str = kwargs.get("api_url", "https://ddg-webapp-aagd.vercel.app/search")
        self.max_results: int = kwargs.get("max_results", 3)


class WebSearchPlugin(BasePlugin):

    async def decide(self, user_input: str, history: list[dict], provider: Any) -> PluginDecision:
        # 这里可以替换为更智能的判断逻辑
        if "[SEARCH]" in user_input:
            return PluginDecision(should_trigger=True, parameters={"query": user_input.replace("[SEARCH]", "").strip()})
        return PluginDecision(should_trigger=False)

    async def execute(self, parameters: Dict[str, Any]) -> str:
        return await self.handle("", parameters)

    @property
    def description(self) -> PluginDescription:
        return PluginDescription(
            name="WebSearch",
            description="使用DuckDuckGo搜索引擎进行搜索",
            parameters={"query": "搜索关键词"},
            example="搜索[SEARCH]的相关信息"
        )

    def __init__(self, config: WebSearchConfig):
        self.config = config
        self.session = aiohttp.ClientSession()

    @property
    def name(self):
        return "WebSearch"

    async def can_handle(self, prompt: str) -> Optional[dict]:
        # 这里可以替换为更智能的判断逻辑
        if "[SEARCH]" in prompt:
            return {"query": prompt.replace("[SEARCH]", "").strip()}
        return None

    async def handle(self, input_text: str, params: dict) -> str:
        query = params["query"]
        async with self.session.get(
                url=self.config.api_url,
                params={
                    "q": query,
                    "max_results": self.config.max_results,
                    "region": "cn-zh"
                },
                timeout=10
        ) as resp:
            results = await resp.json()

        formatted = "网络搜索结果：\n"
        for i, item in enumerate(results, 1):
            formatted += f"{i}. {item['body']}\nURL: {item['href']}\n\n"
        return formatted

    async def close(self):
        await self.session.close()
