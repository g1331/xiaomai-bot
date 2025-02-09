from .plugins.web_search import WebSearchPlugin, WebSearchConfig

# ALL_PLUGINS 字典中，每个插件提供 class 与一个默认配置生成器
ALL_PLUGINS = {
    "web_search": {
        "class": WebSearchPlugin,
        "default_config": lambda cfg: WebSearchConfig(max_results=cfg.get("max_results", 3))
    },
    # 在此添加其他插件
}
