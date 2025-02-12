from .plugins.duckduckgo_search import DuckDuckGoPlugin, DuckDuckGoConfig
from .plugins.weather import WeatherPlugin, WeatherConfig
from .plugins.code_runner import CodeRunner, CodeRunnerConfig

ALL_PLUGINS = {
    "web_search": {
        "class": DuckDuckGoPlugin,
        "default_config": lambda cfg: DuckDuckGoConfig(**cfg)
    },
    "SeniverseWeather": {
        "class": WeatherPlugin,
        "default_config": lambda cfg: WeatherConfig(**cfg)
    },
    "code_runner": {
        "class": CodeRunner,
        "default_config": lambda cfg: CodeRunnerConfig(
            timeout=cfg.get("timeout", 5),
            max_code_length=cfg.get("max_code_length", 1000),
            allowed_modules=set(cfg.get("allowed_modules", [
                "math", "random", "statistics", "decimal"
            ]))
        )
    }
}
