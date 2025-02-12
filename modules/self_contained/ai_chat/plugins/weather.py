"""心知天气API插件实现。

本模块实现了基于心知天气API的天气查询功能。
支持实时天气和天气预报。
"""
from typing import Dict, Any, Set
import aiohttp
from ..core.plugin import BasePlugin, PluginConfig, PluginDescription


class WeatherConfig(PluginConfig):
    """心知天气API配置。

    Attributes:
        api_key: API密钥
        base_url: API基础URL
        language: 返回结果的语言，默认zh-Hans
        unit: 温度单位，默认摄氏度c
    """

    api_key: str = ""
    base_url: str = "https://api.seniverse.com/v3/weather/now.json"
    language: str = "zh-Hans"
    unit: str = "c"
    daily_url: str = "https://api.seniverse.com/v3/weather/daily.json"

    @property
    def required_fields(self) -> Set[str]:
        return {"api_key"}


class WeatherPlugin(BasePlugin):
    """天气查询插件实现类。"""

    def __init__(self, config: WeatherConfig) -> None:
        """初始化天气插件。

        Args:
            config: 插件配置对象
        """
        super().__init__(config)

    @property
    def description(self) -> PluginDescription:
        return PluginDescription(
            name="SeniverseWeather",
            description="心知天气：查询指定城市的天气信息，包括实时天气和天气预报",
            parameters={
                "location": "查询的城市名称",
                "query_type": "查询类型：now(实时天气)、forecast(天气预报)",
                "days": "可选，预报天数(1-15)，默认3天",
                "start": "可选，起始时间偏移，-1代表昨天",
                "language": "可选，返回结果的语言，默认zh-Hans",
                "unit": "可选，温度单位(c:摄氏度，f:华氏度)，默认c"
            },
            example="查询北京未来3天天气预报: {'location': 'beijing', 'query_type': 'forecast', 'days': 3}"
        )

    async def execute(self, parameters: Dict[str, Any]) -> str:
        """执行天气查询。

        Args:
            parameters: 包含查询参数的字典，必须包含"location"键

        Returns:
            str: 格式化的天气信息

        Raises:
            KeyError: 当parameters中缺少必要的"location"参数时
        """
        query_type = parameters.get("query_type", "now")
        if query_type == "now":
            return await self.get_current_weather(parameters)
        elif query_type == "forecast":
            return await self.get_weather_forecast(parameters)
        return "错误：无效的查询类型，支持的类型包括：now、forecast"

    async def get_weather_forecast(self, parameters: Dict[str, Any]) -> str:
        """获取天气预报。"""
        location = parameters.get("location")
        if not location:
            return "错误：请提供要查询的城市名称"

        params = {
            "key": self.config.api_key,
            "location": location,
            "language": parameters.get("language", self.config.language),
            "unit": parameters.get("unit", self.config.unit),
            "start": parameters.get("start", 0),
            "days": min(int(parameters.get("days", 3)), 15)
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(self.config.daily_url, params=params) as response:
                if response.status != 200:
                    return f"错误：查询失败 (HTTP {response.status})"

                data = await response.json()
                if "results" not in data:
                    return "错误：未获取到天气数据"

                result = data["results"][0]
                location_info = result["location"]
                daily = result["daily"]

                forecast = f"城市：{location_info['name']}\n天气预报：\n"
                for day in daily:
                    forecast += (
                        f"\n日期：{day['date']}\n"
                        f"白天天气：{day['text_day']}\n"
                        f"夜间天气：{day['text_night']}\n"
                        f"最高温度：{day['high']}°{params['unit'].upper()}\n"
                        f"最低温度：{day['low']}°{params['unit'].upper()}\n"
                        f"降水概率：{day.get('precip', 'N/A')}%\n"
                        f"风向：{day['wind_direction']}\n"
                        f"风速：{day['wind_speed']}km/h\n"
                    )
                return forecast

    async def get_current_weather(self, parameters: Dict[str, Any]) -> str:
        """获取实时天气。"""
        location = parameters.get("location")
        if not location:
            return "错误：请提供要查询的城市名称"

        params = {
            "key": self.config.api_key,
            "location": location,
            "language": parameters.get("language", self.config.language),
            "unit": parameters.get("unit", self.config.unit)
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(self.config.base_url, params=params) as response:
                if response.status != 200:
                    return f"错误：查询失败 (HTTP {response.status})"

                data = await response.json()
                if "results" not in data:
                    return "错误：未获取到天气数据"

                result = data["results"][0]
                location_info = result["location"]
                weather = result["now"]

                return (
                    f"城市：{location_info['name']}\n"
                    f"天气：{weather['text']}\n"
                    f"温度：{weather['temperature']}°{params['unit'].upper()}\n"
                    f"体感温度：{weather.get('feels_like', 'N/A')}°{params['unit'].upper()}\n"
                    f"相对湿度：{weather.get('humidity', 'N/A')}%\n"
                    f"风向：{weather.get('wind_direction', 'N/A')}\n"
                    f"风速：{weather.get('wind_speed', 'N/A')}km/h\n"
                    f"更新时间：{result['last_update']}"
                )
