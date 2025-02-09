from pathlib import Path

from graia.ariadne.event.lifecycle import ApplicationLaunched
from graia.saya import Channel
from graia.saya.builtins.broadcast.schema import ListenerSchema

from core.models import saya_model
from .config import ConfigLoader
from .core.manager import ConversationManager
from .core.provider import BaseAIProvider
from .providers.deepseek import DeepSeekProvider, DeepSeekConfig
from .plugins_registry import ALL_PLUGINS

module_controller = saya_model.get_module_controller()
channel = Channel.current()
channel.meta["name"] = "AI对话"
channel.meta["description"] = "AI对话模块"
channel.meta["author"] = "十三"
channel.metadata = module_controller.get_metadata_from_path(Path(__file__))

# 全局变量
g_manager: ConversationManager
g_config_loader: ConfigLoader


def create_provider(provider_name: str, user_id: str = None) -> BaseAIProvider:
    """根据提供商名称创建对应的Provider实例，配置可由master动态修改"""
    global g_config_loader
    if not g_config_loader:
        raise ValueError("ConfigLoader not initialized")
    provider_config = g_config_loader.get_provider_config(provider_name)

    if provider_name == "deepseek":
        config = DeepSeekConfig(
            api_key=provider_config["api_key"],  # 直接从配置文件中获取
            model=provider_config["model"],
            base_url=provider_config["base_url"],
            max_tokens=provider_config["max_tokens"]
        )
        return DeepSeekProvider(config)
    raise ValueError(f"Unknown provider: {provider_name}")


def provider_factory(key: str):
    """为ConversationManager提供的工厂函数"""
    global g_config_loader
    if not g_config_loader:
        raise ValueError("ConfigLoader not initialized")
    user_id = key.split('-')[-1]  # 从key中提取用户ID
    provider_name = g_config_loader.get_user_provider(user_id)
    return create_provider(provider_name, user_id)


def plugins_factory(key: str):
    """为ConversationManager提供的插件工厂函数，
    从插件注册表中获取所有插件，根据配置判断是否启用"""
    enabled_plugins = []
    plugins_cfg = g_config_loader.config.get("plugins", {})
    for plugin_name, plugin_info in ALL_PLUGINS.items():
        cfg = plugins_cfg.get(plugin_name, {})
        if cfg.get("enabled", False):
            plugin_instance = plugin_info["class"](plugin_info["default_config"](cfg))
            enabled_plugins.append(plugin_instance)
    return enabled_plugins


@channel.use(ListenerSchema(listening_events=[ApplicationLaunched]))
async def init():
    global g_manager, g_config_loader
    # 初始化配置加载器
    g_config_loader = ConfigLoader()
    # 初始化对话管理器
    g_manager = ConversationManager(provider_factory, plugins_factory)
