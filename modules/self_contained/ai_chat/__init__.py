import re
from pathlib import Path

from graia.ariadne import Ariadne
from graia.ariadne.event.lifecycle import ApplicationLaunched
from graia.ariadne.event.message import GroupMessage
from graia.ariadne.message import Source
from graia.ariadne.message.chain import MessageChain
from graia.ariadne.message.element import Image as GraiaImage
from graia.ariadne.message.parser.twilight import Twilight, FullMatch, ArgumentMatch, WildcardMatch, ArgResult, \
    RegexResult
from graia.ariadne.model import Group, Member
from graia.saya import Channel
from graia.saya.builtins.broadcast.schema import ListenerSchema
from graiax.playwright import PlaywrightBrowser
from loguru import logger

from core.control import Distribute, Function, FrequencyLimitation, Permission
from core.models import saya_model
from utils.text2img import html2img
from utils.text2img.md2img import MarkdownToImageConverter, Theme, OutputMode, HighlightTheme
from .config import ConfigLoader
from .core.manager import ConversationManager
from .core.preset import preset_dict
from .core.provider import BaseAIProvider
from .plugins_registry import ALL_PLUGINS
from .providers.deepseek import DeepSeekProvider, DeepSeekConfig

module_controller = saya_model.get_module_controller()
# 初始化通道
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


@channel.use(
    ListenerSchema(
        listening_events=[GroupMessage],
        inline_dispatchers=[
            Twilight([
                FullMatch("-chat"),
                ArgumentMatch("-n", "-new", action="store_true", optional=True) @ "new_thread",
                ArgumentMatch("-t", "-text", action="store_true", optional=True) @ "text",
                ArgumentMatch("-p", "-preset", optional=True) @ "preset",
                ArgumentMatch("--tool", action="store_true", optional=True) @ "tool",
                ArgumentMatch("--show-preset", action="store_true", optional=True) @ "show_preset",
                ArgumentMatch("--reload-cfg", action="store_true", optional=True) @ "reload_cfg",
                WildcardMatch().flags(re.DOTALL) @ "content",
            ])
        ],
        decorators=[
            Distribute.require(),
            Function.require(channel.module),
            FrequencyLimitation.require(channel.module, 5),
            Permission.group_require(channel.metadata.level, if_noticed=True),
            Permission.user_require(Permission.User),
        ],
    )
)
async def chat_gpt(
        app: Ariadne,
        group: Group,
        member: Member,
        source: Source,
        new_thread: ArgResult,
        text: ArgResult,
        tool: ArgResult,
        preset: ArgResult,
        content: RegexResult,
        show_preset: ArgResult,
        reload_cfg: ArgResult
):
    global g_config_loader, g_manager
    group_id_str = str(group.id)
    member_id_str = str(member.id)
    content = content.result.display.strip() if content.matched else ""

    if reload_cfg.matched:
        # 鉴权
        group_perm = await Permission.get_user_perm_byID(group.id, member.id)
        if group_perm < Permission.BotAdmin:
            return await app.send_group_message(
                group,
                MessageChain("你没有权限执行此操作"),
                quote=source
            )
        g_config_loader = ConfigLoader()
        g_manager = ConversationManager(provider_factory, plugins_factory)
        return await app.send_group_message(
            group,
            MessageChain("已重新加载AI对话模块配置"),
            quote=source
        )

    if show_preset.matched:
        await app.send_group_message(
            group,
            MessageChain(GraiaImage(data_bytes=await html2img(
                MarkdownToImageConverter.generate_html(
                    "# 预设列表\n\n" +
                    "## 当前预设\n\n" +
                    f"{g_manager.get_preset(group_id_str, member_id_str)}\n\n" +
                    "## 内置预设：\n\n" +
                    "\n\n".join(
                        [f"### {i} **{v['name']}**\n>{v['description']}" for i, v
                         in preset_dict.items()])
                )
            ))),
            quote=source
        )
        return

    if preset.matched:
        # 群聊预设暂不鉴权
        preset_str = preset.result.display.strip()
        g_manager.set_preset(
            group_id_str,
            member_id_str,
            preset_dict[preset_str]["content"] if preset_str in preset_dict \
                else (preset_str or preset_dict["umaru"]["content"])
        )
        await app.send_group_message(
            group,
            MessageChain(f"已设置预设：{preset_str}{'(内置预设)' if preset_str in preset_dict else '(自定义预设)'}"),
            quote=source
        )

    if new_thread.matched:
        # 先获取群聊模式，如果是shared就鉴权，只能是群管理员以上才能清除上下文并开始新对话
        cur_group_mode = g_manager.get_group_mode(group_id_str)
        if cur_group_mode == ConversationManager.GroupMode.SHARED:
            group_perm = await Permission.get_user_perm_byID(group.id, member.id)
            if group_perm < Permission.GroupAdmin:
                return await app.send_group_message(
                    group,
                    MessageChain("当前对话为群共享模式，只有群管理员才能执行这个操作"),
                    quote=source
                )
        g_manager.new(group_id=group_id_str, member_id=member_id_str)
        return await app.send_group_message(
            group,
            MessageChain("已清除上下文并开始新对话"),
            quote=source
        )

    if not content:
        return await app.send_group_message(
            group,
            MessageChain("你好像什么也没说哦(｡･∀･)ﾉﾞ"),
            quote=source
        )
    await app.send_group_message(
        group,
        MessageChain("(｡･∀･)ﾉﾞ响应ing"),
        quote=source
    )
    response = await g_manager.send_message(group_id_str, member_id_str, member.name, content, tool.matched)
    usage_total_tokens = g_manager.get_total_usage(group_id_str, member_id_str)
    cur_round = g_manager.get_round(group_id_str, member_id_str)
    if text.matched:
        response += f"\n\n（消耗 {usage_total_tokens} tokens，第 {cur_round} 轮）"
        return await app.send_group_message(
            group,
            MessageChain(response),
            quote=source
        )
    else:
        response += f"\n\n> 消耗：{usage_total_tokens} tokens，第 {cur_round} 轮"
        converter = MarkdownToImageConverter(browser=app.current().launch_manager.get_interface(PlaywrightBrowser).browser)
        img_bytes = await converter.convert_markdown(
            response, 
            theme=Theme.DARK, 
            output_mode=OutputMode.BINARY, 
            highlight_theme=HighlightTheme.ATOM_ONE_DARK
        )
        return await app.send_group_message(
            group,
            # MessageChain(GraiaImage(data_bytes=await html2img(
            #     MarkdownToImageConverter.generate_html(response, theme=Theme.DARK)
            # ))),
            MessageChain(GraiaImage(data_bytes=img_bytes)),
            quote=source
        )
