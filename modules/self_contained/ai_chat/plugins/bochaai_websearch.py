"""博查AI高级搜索插件实现。

本模块调用博查AI开放平台的网页搜索 API 接口，实现高级网页搜索功能。
接口域名：https://api.bochaai.com
EndPoint：https://api.bochaai.com/v1/web-search

调用方式：
- 请求方式：POST
- 请求头：
    - Authorization: Bearer {API KEY}
      （鉴权参数，示例：Bearer xxxxxx，API KEY 请先前往博查AI开放平台（https://open.bochaai.com）> API KEY 管理中获取）
    - Content-Type: application/json

请求体参数说明：
    - query (String, 必填)：用户的搜索关键词。
    - freshness (String, 可选)：搜索指定时间范围内的网页。
          可填值：oneDay（一日内）、oneWeek（一周内）、oneMonth（一月内）、oneYear（一年内）、noLimit（不限，默认）。
    - summary (Boolean, 可选)：是否返回文本摘要。取值 true 表示显示，false 表示不显示（默认）。
    - count (Int, 可选)：返回结果的条数（取值范围：1-10），默认为 10。
    - page (Int, 可选)：页码，默认为 1。

响应内容说明：
    响应数据中包含 WebSearchWebPages 部分，其内部字段包括：
        - name：网页标题
        - url：网页 URL
        - displayUrl：展示的 URL
        - snippet：网页简短描述
        - summary：当请求参数 summary 为 true 时返回的文本摘要
        等其他字段。

本插件将返回格式化后的搜索结果文本，主要展示网页标题、描述和链接。
"""

from typing import Dict, Any

import aiohttp

from modules.self_contained.ai_chat.core.plugin import BasePlugin, PluginConfig, PluginDescription


class BochaaiWebSearchConfig(PluginConfig):
    """
    博查AI高级搜索插件配置

    Attributes:
        api_key: API 密钥，请从博查AI开放平台（https://open.bochaai.com）获取。
        freshness: 搜索时间范围，默认 "noLimit"（不限）。
        summary: 是否显示文本摘要，默认 False。
        count: 返回结果的条数，默认 10（取值范围 1-10）。
        page: 页码，默认 1。
        endpoint: API 接口地址，固定为 "https://api.bochaai.com/v1/web-search"。
    """
    freshness: str = "noLimit"
    summary: bool = False
    count: int = 10
    page: int = 1
    endpoint: str = "https://api.bochaai.com/v1/web-search"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)


class BochaaiWebSearchPlugin(BasePlugin):
    """
    博查AI高级搜索插件实现类

    该插件调用博查AI开放平台的网页搜索 API 接口，
    支持设置搜索关键词、时间范围、是否返回摘要、指定返回结果条数及页码等高级功能，
    返回的结果包括网页标题、描述、链接等信息。
    """

    def __init__(self, config: BochaaiWebSearchConfig) -> None:
        self.config = config

    @property
    def description(self) -> PluginDescription:
        return PluginDescription(
            name="BochaaiWebSearch",
            description="博查AI高级搜索插件，通过博查AI开放平台 API 实现网页搜索，支持时间范围、摘要显示、结果条数及页码设置。",
            parameters={
                "query": "搜索关键词",
                "freshness": "搜索时间范围，可选值：oneDay, oneWeek, oneMonth, oneYear, noLimit（默认）",
                "summary": "是否返回文本摘要，取值 true 或 false，默认 false",
                "count": "返回结果条数（范围 1-10），默认 10",
                "page": "页码，默认 1"
            },
            example="搜索 'Python教程'，freshness 设为 oneWeek，summary 设为 true，count 为 5"
        )

    async def execute(self, parameters: Dict[str, Any]) -> str:
        """执行搜索功能。"""
        return await self.handle(parameters)

    async def handle(self, params: Dict[str, Any]) -> str:
        """
        处理搜索请求，调用博查AI网页搜索 API 接口，并格式化返回结果。

        Args:
            params: 搜索参数字典，必须包含 'query' 键

        Returns:
            str: 格式化后的搜索结果文本，包含网页标题、描述和链接
        """
        query = params.get("query")
        if not query:
            return "错误：缺少搜索关键词，请提供参数 'query'。"
        freshness = params.get("freshness", self.config.freshness)
        summary = params.get("summary", self.config.summary)
        count = int(params.get("count", self.config.count))
        page = int(params.get("page", self.config.page))

        payload = {
            "query": query,
            "freshness": freshness,
            "summary": summary,
            "count": count,
            "page": page
        }
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json"
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(self.config.endpoint, json=payload, headers=headers) as response:
                if response.status != 200:
                    return f"请求失败，状态码：{response.status}"
                data = await response.json()

        # 解析返回数据中的网页搜索结果（WebSearchWebPages）
        web_pages = data.get("data", {}).get("webPages", {})
        values = web_pages.get("value", [])
        if not values:
            return "没有找到搜索结果。"

        total_matches = web_pages.get("totalEstimatedMatches", "未知")
        formatted = f"搜索结果（总匹配数: {total_matches}）：\n"
        for idx, item in enumerate(values, start=1):
            title = item.get("name", "无标题")
            if summary:
                snippet = item.get("summary", "")
            else:
                snippet = item.get("snippet", "")
            url = item.get("url", "")
            formatted += f"{idx}. {title}\n描述：{snippet}\n链接：{url}\n\n"
        return formatted
