from .plugins.duckduckgo_search import DuckDuckGoPlugin, DuckDuckGoConfig
from .plugins.weather import WeatherPlugin, WeatherConfig

ALL_PLUGINS = {
    "web_search": {
        "class": DuckDuckGoPlugin,
        "default_config": lambda cfg: DuckDuckGoConfig(**cfg)
    },
    "SeniverseWeather": {
        "class": WeatherPlugin,
        "default_config": lambda cfg: WeatherConfig(**cfg)
    }
}
