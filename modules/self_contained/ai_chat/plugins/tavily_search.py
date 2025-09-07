"""Tavily 搜索插件实现。

本模块实现了基于 Tavily 的网络搜索功能，适用于 AI 代理检索实时信息。
使用 tavily-python 客户端进行调用，支持基础/深度搜索、控制返回条数、是否返回简要回答与原始内容等。

依赖：
- 包名：tavily-python
- 安装（推荐，需管理员执行）：uv add tavily-python

注意：
- 为了避免未安装依赖导致全局导入失败，本插件在执行阶段进行懒加载导入。
"""

from __future__ import annotations

import asyncio
from typing import Any

from ..core.plugin import BasePlugin, PluginConfig, PluginDescription


class TavilySearchConfig(PluginConfig):
    """Tavily 搜索插件配置。

    Attributes:
        api_key: Tavily API Key（必填）
        search_depth: 搜索深度，"basic" 或 "advanced"
        max_results: 最大返回结果数上限（用于运行时入参校验）
        include_answer: 是否返回简要回答（由服务端汇总）
        include_raw_content: 是否返回网页原始内容（可能较大）
    """

    api_key: str = ""
    search_depth: str = "basic"
    max_results: int = 5
    include_answer: bool = True
    include_raw_content: bool = False

    @property
    def required_fields(self) -> set[str]:
        return {"api_key"}


class TavilySearchPlugin(BasePlugin):
    """Tavily 搜索插件实现类。"""

    def __init__(self, config: TavilySearchConfig) -> None:
        """初始化 Tavily 搜索插件。

        Args:
            config: 插件配置对象
        """
        super().__init__(config)

    @property
    def description(self) -> PluginDescription:
        """获取插件描述。

        Returns:
            PluginDescription: 插件功能描述
        """
        return PluginDescription(
            name="tavily_search",
            description=(
                "使用 Tavily 搜索引擎检索网页信息，可选基础/深度模式，支持返回简要回答与原始内容。"
            ),
            parameters={
                "query": "搜索关键词（必填）",
                "search_depth": '搜索深度："basic" 或 "advanced"，默认 basic',
                "max_results": f"最大返回结果数（1-{self.config.max_results}）",
                "include_answer": "是否返回简要回答（true/false）",
                "include_raw_content": "是否返回原始内容（true/false）",
            },
            example=(
                "{'query': 'Python 新特性 3.12', 'search_depth': 'basic', 'max_results': 5, "
                "'include_answer': True}"
            ),
        )

    async def execute(self, parameters: dict[str, Any]) -> str:
        """执行搜索功能。

        Args:
            parameters: 执行参数

        Returns:
            str: 格式化的搜索结果
        """
        return await self.handle(parameters)

    async def handle(self, params: dict[str, Any]) -> str:
        """处理搜索请求。

        Args:
            params: 参数字典

        Returns:
            str: 格式化结果
        """
        query = params.get("query")
        if not query:
            return "错误：缺少搜索关键词，请提供参数 'query'。"

        # 读取与校验参数
        search_depth = str(params.get("search_depth", self.config.search_depth)).lower()
        if search_depth not in {"basic", "advanced"}:
            return "错误：search_depth 仅支持 'basic' 或 'advanced'。"

        try:
            max_results = int(params.get("max_results", self.config.max_results))
        except Exception:
            return "错误：max_results 需要为整数。"
        if max_results <= 0 or max_results > self.config.max_results:
            return f"错误：max_results 需在 1-{self.config.max_results} 之间。"

        include_answer = bool(params.get("include_answer", self.config.include_answer))
        include_raw_content = bool(
            params.get("include_raw_content", self.config.include_raw_content)
        )

        # 懒加载 tavily 依赖
        try:
            from tavily import TavilyClient  # type: ignore
        except Exception:
            return (
                "错误：未安装 tavily-python 依赖，请管理员执行 `uv add tavily-python` 后重试。"
            )

        client = TavilyClient(api_key=self.config.api_key)

        def _search() -> dict[str, Any]:
            # TavilyClient.search 返回 dict，包含 answer 与 results 等字段
            return client.search(
                query,
                search_depth=search_depth,
                max_results=max_results,
                include_answer=include_answer,
                include_raw_content=include_raw_content,
            )

        try:
            resp: dict[str, Any] = await asyncio.to_thread(_search)
        except Exception as e:  # 网络或鉴权错误
            return f"错误：Tavily 搜索失败：{e}"

        # 格式化输出
        parts: list[str] = [f"Tavily 搜索结果（{search_depth}）：\n"]
        if include_answer and isinstance(resp, dict) and resp.get("answer"):
            parts.append(f"简要回答：{resp.get('answer')}\n\n")

        results = (resp or {}).get("results") or []
        if not results:
            parts.append("未找到相关结果。")
            return "".join(parts)

        for i, item in enumerate(results, 1):
            title = str(item.get("title") or "").strip()
            url = str(item.get("url") or item.get("source", "")).strip()
            content = str(item.get("content") or item.get("snippet", "")).strip()
            snippet = content.replace("\n", " ")[:400]
            parts.append(
                f"{i}. {title}\n"
                f"摘要: {snippet}\n"
                f"链接: {url}\n\n"
            )

        return "".join(parts)

