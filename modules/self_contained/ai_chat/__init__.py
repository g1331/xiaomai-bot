import mimetypes
import re
from pathlib import Path

import aiohttp
from graia.ariadne import Ariadne
from graia.ariadne.event.lifecycle import ApplicationLaunched
from graia.ariadne.event.message import GroupMessage
from graia.ariadne.message import Source
from graia.ariadne.message.chain import MessageChain
from graia.ariadne.message.element import Image as GraiaImage, At, Image, File
from graia.ariadne.message.parser.twilight import Twilight, ArgumentMatch, WildcardMatch, ArgResult, \
    RegexResult, ElementMatch, ElementResult, SpacePolicy
from graia.ariadne.model import Group, Member
from graia.saya import Channel
from graia.saya.builtins.broadcast.schema import ListenerSchema
from graiax.playwright import PlaywrightBrowser
from loguru import logger
from pydantic import ValidationError

from core.control import Distribute, Function, FrequencyLimitation, Permission, AtBotReply
from core.models import saya_model, response_model
from utils.text2img import html2img
from utils.text2img.md2img import MarkdownToImageConverter, Theme, OutputMode, HighlightTheme
from .config import ConfigLoader
from .core.manager import ConversationManager
from .core.preset import preset_dict
from .core.provider import BaseAIProvider, FileContent, FileType
from .plugins_registry import ALL_PLUGINS
from .providers.deepseek import DeepSeekProvider, DeepSeekConfig

module_controller = saya_model.get_module_controller()
account_controller = response_model.get_acc_controller()
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
        _config = DeepSeekConfig(
            **provider_config,
        )
        return DeepSeekProvider(_config)
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
    """为ConversationManager提供的插件工厂函数"""
    enabled_plugins = []
    plugins_cfg = g_config_loader.config.get("plugins", {})

    for plugin_name, plugin_info in ALL_PLUGINS.items():
        cfg = plugins_cfg.get(plugin_name, {})
        if cfg.get("enabled", False):
            try:
                plugin_instance = plugin_info["class"](plugin_info["default_config"](cfg))
                enabled_plugins.append(plugin_instance)
                logger.info(f"AiChat plugin {plugin_name} enabled")
            except ValidationError as ve:
                # 更详细的错误日志
                error_msgs = []
                try:
                    for error in ve.errors():
                        loc = " -> ".join(str(x) for x in error.get('loc', []))
                        msg = error.get('msg', 'Unknown error')
                        error_msgs.append(f"{loc}: {msg}")
                    logger.warning(f"Plugin {plugin_name} 配置验证错误:\n" + "\n".join(error_msgs))
                except Exception as e:
                    logger.error(f"Plugin {plugin_name} 处理验证错误时出错: {str(e)}")
                continue
            except Exception as e:
                logger.warning(f"Plugin {plugin_name} 初始化错误: {str(e)}")
                continue

    return enabled_plugins


async def process_image(image: Image) -> FileContent | None:
    """处理图像元素，转换为FileContent对象"""
    try:
        # 有URL，下载图片
        if hasattr(image, "url") and image.url:
            async with aiohttp.ClientSession() as session:
                async with session.get(image.url) as response:
                    if response.status == 200:
                        image_data = await response.read()
                        return FileContent(
                            file_type=FileType.IMAGE,
                            file_bytes=image_data,
                            mime_type=response.headers.get("Content-Type", "image/jpeg"),
                            file_name="image.jpg"
                        )
                
        # 如果所有方法都失败，尝试使用临时直链获取图片
        if hasattr(image, "get_bytes") and callable(image.get_bytes):
            image_data = await image.get_bytes()
            return FileContent(
                file_type=FileType.IMAGE,
                file_bytes=image_data,
                mime_type="image/jpeg",  # 假设为JPEG
                file_name="image.jpg"
            )
            
        raise ValueError("无法获取图片数据")
    except Exception as e:
        logger.error(f"处理图像时出错: {e}")
        return None


async def process_file(file: File) -> FileContent:
    """处理文件元素，转换为FileContent对象"""
    try:
        # 确定文件类型
        file_type = FileType.DOCUMENT  # 默认文档类型
        mime_type = None
        
        if hasattr(file, "name") and file.name:
            mime_type = mimetypes.guess_type(file.name)[0]
            if mime_type:
                if mime_type.startswith("image/"):
                    file_type = FileType.IMAGE
                elif mime_type.startswith("audio/"):
                    file_type = FileType.AUDIO
                elif mime_type.startswith("video/"):
                    file_type = FileType.VIDEO
        
        # 获取文件内容
        file_bytes = None
        if hasattr(file, "data") and file.data:
            file_bytes = file.data
        elif hasattr(file, "url") and file.url:
            async with aiohttp.ClientSession() as session:
                async with session.get(file.url) as response:
                    if response.status == 200:
                        file_bytes = await response.read()
        elif hasattr(file, "path") and file.path:
            with open(file.path, "rb") as f:
                file_bytes = f.read()
        elif hasattr(file, "get_bytes") and callable(file.get_bytes):
            file_bytes = await file.get_bytes()
            
        if not file_bytes:
            raise ValueError("无法获取文件数据")
            
        return FileContent(
            file_type=file_type,
            file_bytes=file_bytes,
            mime_type=mime_type,
            file_name=getattr(file, "name", "file") or "file"
        )
    except Exception as e:
        logger.error(f"处理文件时出错: {e}")
        return None


async def extract_files_from_message(message_chain) -> list[FileContent]:
    """从消息链中提取所有文件"""
    files = []
    
    # 处理图片
    for image in message_chain.get(Image):
        file_content = await process_image(image)
        if file_content:
            files.append(file_content)
            
    # 处理文件
    for file in message_chain.get(File):
        file_content = await process_file(file)
        if file_content:
            files.append(file_content)
            
    return files


@channel.use(ListenerSchema(listening_events=[ApplicationLaunched]))
async def init():
    global g_manager, g_config_loader
    logger.info("AI Chat模块初始化中...")
    # 初始化配置加载器
    g_config_loader = ConfigLoader()
    # 初始化对话管理器
    g_manager = ConversationManager(provider_factory, plugins_factory)
    logger.success("AI Chat模块初始化完成")


@channel.use(
    ListenerSchema(
        listening_events=[GroupMessage],
        inline_dispatchers=[
            Twilight([
                ElementMatch(At, optional=False).space(SpacePolicy.PRESERVE) @ "AtResult",
                ArgumentMatch("-p", "-preset", optional=True) @ "preset",
                ArgumentMatch("-n", "-new", action="store_true", optional=True) @ "new_thread",
                ArgumentMatch("-P", "--pic", action="store_true", optional=True) @ "pic",
                ArgumentMatch("-t", "--tool", action="store_true", optional=True) @ "tool",
                ArgumentMatch("--show-preset", action="store_true", optional=True) @ "show_preset",
                ArgumentMatch(
                    "--show-tokens",
                    action="store_true",
                    optional=True, type=bool, default=False
                ) @ "show_tokens",
                ArgumentMatch("--reload-cfg", action="store_true", optional=True) @ "reload_cfg",
                # -c --clear，清除对话历史
                ArgumentMatch("-c", "--clear", action="store_true", optional=True) @ "clear_history",
                # 禁用多模态
                ArgumentMatch("--no-vision", action="store_true", optional=True) @ "no_vision",
                # 显示模型信息
                ArgumentMatch("--model-info", "--info", action="store_true", optional=True) @ "show_model_info",
                WildcardMatch().flags(re.DOTALL) @ "content",
            ])
        ],
        decorators=[
            Distribute.require(),
            AtBotReply.require(),
            Function.require(channel.module, False),  # 因为@触发条件比较广泛，这里关闭功能未开启时的通知，防止刷屏
            FrequencyLimitation.require(channel.module, 5),
            Permission.group_require(channel.metadata.level, if_noticed=True),
            Permission.user_require(Permission.User),
        ],
    )
)
async def ai_chat(
        app: Ariadne,
        group: Group,
        member: Member,
        message: MessageChain,
        source: Source,
        AtResult: ElementResult,
        new_thread: ArgResult,
        pic: ArgResult,
        tool: ArgResult,
        preset: ArgResult,
        content: RegexResult,
        show_preset: ArgResult,
        show_tokens: ArgResult,
        reload_cfg: ArgResult,
        clear_history: ArgResult,
        no_vision: ArgResult,
        show_model_info: ArgResult,
):
    """
    修改默认为文字响应，主要考量：
    
    1.性能考虑
      - 文字响应更快，不需要额外的图片渲染时间
      - 减少服务器资源消耗（CPU、内存）
      - 节省网络带宽
    2.实用性
      - 大多数对话场景下，纯文本足以满足需求
      - 文字更容易复制、转发和二次使用
      - 文字消息在移动端加载更快，更省流量
    3.特殊场景使用图片 当确实需要图片格式时，用户可以通过 -P 或 --pic 参数主动选择，比如：
      - 需要展示代码且保持格式的场景
      - 内容包含复杂格式或表格
      - 需要更好的视觉效果时
    4.用户体验
      - 让用户自主选择输出格式更灵活
      - 避免在简单对话时产生不必要的图片负担
      - 图片加载失败的风险更低
      
    新增多模态支持:
    - 自动检测消息中的图片和文件
    - 支持通过--no-vision选项禁用多模态
    """
    global g_config_loader, g_manager

    if not AtResult.matched:
        return

    at_result: At = AtResult.result  # type: ignore
    at_qq_num = at_result.target
    # 防止At任意对象都能触发，这里At对象只能为已经初始化的bot
    if at_qq_num not in account_controller.initialized_bot_list:
        return

    group_id_str = str(group.id)
    member_id_str = str(member.id)
    content_text = content.result.display.strip() if content.matched else ""

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
        return await app.send_group_message(
            group,
            MessageChain(GraiaImage(data_bytes=await html2img(
                MarkdownToImageConverter.generate_html(
                    "# 预设列表\n\n" +
                    "> 请使用标题括号前的文本进行设置\n"
                    "## 当前预设\n\n" +
                    f"{g_manager.get_preset(group_id_str, member_id_str)}\n\n" +
                    "## 内置预设：\n\n" +
                    "\n\n".join(
                        [f"### {i} ({v['name']})\n>{v['description']}" for i, v
                         in preset_dict.items()])
                )
            ))),
            quote=source
        )

    if show_tokens.result:
        usage_total_tokens = g_manager.get_total_usage(group_id_str, member_id_str)
        cur_round = g_manager.get_round(group_id_str, member_id_str)
        return await app.send_group_message(
            group,
            MessageChain(f"当前是第 {cur_round} 轮对话，已消耗 {usage_total_tokens} tokens。"),
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
        await app.send_group_message(
            group,
            MessageChain("已清除上下文并开始新对话"),
            quote=source
        )

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
    
    if clear_history.matched:
        # 先获取群聊模式，如果是shared就鉴权，只能是群管理员以上才能清除上下文
        cur_group_mode = g_manager.get_group_mode(group_id_str)
        if cur_group_mode == ConversationManager.GroupMode.SHARED:
            group_perm = await Permission.get_user_perm_byID(group.id, member.id)
            if group_perm < Permission.GroupAdmin:
                return await app.send_group_message(
                    group,
                    MessageChain("当前对话为群共享模式，只有群管理员才能执行这个操作"),
                    quote=source
                )
        g_manager.clear_memory(group_id_str, member_id_str)
        await app.send_group_message(
            group,
            MessageChain("已清除对话历史"),
            quote=source
        )

    if show_model_info.matched:
        # 获取当前会话对象
        conversation = g_manager.get_conversation(group_id_str, member_id_str)
        provider = conversation.provider
        
        # 收集模型信息
        provider_name = provider.__class__.__name__
        model_name = provider.config.model
        max_tokens = provider.config.max_tokens
        max_total_tokens = provider.config.max_total_tokens
        
        # 多模态支持情况
        supports_vision = "✅ 支持" if provider.config.supports_vision else "❌ 不支持"
        supports_audio = "✅ 支持" if provider.config.supports_audio else "❌ 不支持"
        supports_document = "✅ 支持" if provider.config.supports_document else "❌ 不支持"
        
        # 会话状态
        current_round = conversation.get_round()
        has_conversation = current_round > 0
        conversation_status = f"已有 {current_round} 轮对话" if has_conversation else "暂无对话"
        usage_tokens = provider.get_usage().get("total_tokens", 0)
        
        # 插件信息
        loaded_plugins = conversation.plugins
        plugin_count = len(loaded_plugins)
        
        # 格式化插件信息，包含名称和描述
        plugin_info = ""
        if plugin_count > 0:
            plugin_info = "\n\n### 已加载插件详情\n"
            for plugin in loaded_plugins:
                plugin_name = plugin.description.name
                # 使用HTML <br>标签替换换行符，确保不会破坏Markdown列表结构
                plugin_desc = plugin.description.description.replace("\n", "<br>")
                plugin_info += f"- **{plugin_name}**: {plugin_desc}\n"
        else:
            plugin_info = "\n\n目前没有加载任何插件"
        
        # 群聊模式
        group_mode = g_manager.get_group_mode(group_id_str).name
        user_mode = g_manager.get_user_mode(group_id_str, member_id_str).name
        
        # 预设信息
        preset_info = "未设置"
        if conversation.preset:
            # 限制显示的预设长度，过长时截断
            preset_text = conversation.preset
            preset_info = f"{preset_text}"
        
        # 构建信息字符串
        info_md = f"""
# AI模型信息

## 基本信息
- **提供商**: {provider_name}
- **模型名称**: {model_name}
- **单次输出上限**: {max_tokens} tokens
- **上下文窗口**: {max_total_tokens} tokens

## 多模态支持
- **图片**: {supports_vision}
- **音频**: {supports_audio}
- **文档**: {supports_document}

## 会话状态
- **当前状态**: {conversation_status}
- **已消耗**: {usage_tokens} tokens
- **对话模式**: 群聊({group_mode}) / 用户({user_mode})

## 插件信息
- **已加载插件数量**: {plugin_count} 个{plugin_info}

## 预设信息
- **当前预设**: {preset_info}
"""
        
        # 渲染为图片
        converter = MarkdownToImageConverter(
            browser=app.current().launch_manager.get_interface(PlaywrightBrowser).browser)
        img_bytes = await converter.convert_markdown(
            info_md,
            theme=Theme.DARK,
            output_mode=OutputMode.BINARY,
            highlight_theme=HighlightTheme.ATOM_ONE_DARK
        )
        return await app.send_group_message(
            group,
            MessageChain(GraiaImage(data_bytes=img_bytes)),
            quote=source
        )

    if not content_text and not any(isinstance(elem, (Image, File)) for elem in message):
        return
    
    # 提取消息内容
    user_content = f"群{group.name}({group.id})用户{member.name}(QQ{member.id})说：{content_text}"
    
    # 处理文件和图片
    files = []
    if not no_vision.matched:
        files = await extract_files_from_message(message)
        if files:
            logger.info(f"从消息中提取到 {len(files)} 个文件")
    
    # 向AI发送消息
    response = await g_manager.send_message(
        group_id_str, 
        member_id_str, 
        member.name, 
        user_content, 
        files=files, 
        use_tool=tool.matched
    )
    
    # 当用户主动选择图片输出或者对话内容过长时，使用图片输出，目前QQ限制消息字符长度为9000，这里取6000字符作为限制，汉字约3000字
    if not pic.matched and len(response) < 6000:
        return await app.send_group_message(
            group,
            MessageChain(response),
            quote=source
        )
    else:
        converter = MarkdownToImageConverter(
            browser=app.current().launch_manager.get_interface(PlaywrightBrowser).browser)
        img_bytes = await converter.convert_markdown(
            response,
            theme=Theme.DARK,
            output_mode=OutputMode.BINARY,
            highlight_theme=HighlightTheme.ATOM_ONE_DARK
        )
        return await app.send_group_message(
            group,
            MessageChain(GraiaImage(data_bytes=img_bytes)),
            quote=source
        )
