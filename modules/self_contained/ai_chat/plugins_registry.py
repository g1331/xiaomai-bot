from .plugins.web_search import WebSearchPlugin, WebSearchConfig
from .plugins.weather import WeatherPlugin, WeatherConfig

ALL_PLUGINS = {
    "web_search": {
        "class": WebSearchPlugin,
        "default_config": lambda cfg: WebSearchConfig(max_results=cfg.get("max_results", 10))
    },
    "SeniverseWeather": {
        "class": WeatherPlugin,
        "default_config": lambda cfg: WeatherConfig(
            api_key=cfg.get("api_key", ""),
            language=cfg.get("language", "zh-Hans"),
            unit=cfg.get("unit", "c")
        )
    }
}
