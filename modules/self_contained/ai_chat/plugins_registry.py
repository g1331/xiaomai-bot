from .plugins.duckduckgo_search import DuckDuckGoPlugin, DuckDuckGoConfig
from .plugins.bochaai_websearch import BochaaiWebSearchPlugin, BochaaiWebSearchConfig
from .plugins.weather import WeatherPlugin, WeatherConfig
from .plugins.code_runner import CodeRunner, CodeRunnerConfig

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
}
