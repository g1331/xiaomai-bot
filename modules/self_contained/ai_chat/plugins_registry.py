from .plugins.duckduckgo_search import DuckDuckGoPlugin, DuckDuckGoConfig
from .plugins.bochaai_websearch import BochaaiWebSearchPlugin, BochaaiWebSearchConfig
from .plugins.weather import WeatherPlugin, WeatherConfig
from .plugins.code_runner import CodeRunner, CodeRunnerConfig
from .plugins.tavily_search import TavilySearchPlugin, TavilySearchConfig

ALL_PLUGINS = {
    "duckduckgo": {
        "class": DuckDuckGoPlugin,
        "default_config": lambda cfg=None: DuckDuckGoConfig(**(cfg or {})),
    },
    "SeniverseWeather": {
        "class": WeatherPlugin,
        "default_config": lambda cfg=None: WeatherConfig(**(cfg or {})),
    },
    "code_runner": {
        "class": CodeRunner,
        "default_config": lambda cfg=None: CodeRunnerConfig(**(cfg or {})),
    },
    "bochaai_websearch": {
        "class": BochaaiWebSearchPlugin,
        "default_config": lambda cfg=None: BochaaiWebSearchConfig(**(cfg or {})),
    },
    "tavily_search": {
        "class": TavilySearchPlugin,
        "default_config": lambda cfg=None: TavilySearchConfig(**(cfg or {})),
    },
}
