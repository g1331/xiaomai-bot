import mimetypes
import re
import ssl
from pathlib import Path

import aiohttp
from graia.ariadne import Ariadne
from graia.ariadne.event.lifecycle import ApplicationLaunched
from graia.ariadne.event.message import GroupMessage
from graia.ariadne.message import Source
from graia.ariadne.message.chain import MessageChain
from graia.ariadne.message.element import At, File, Image
from graia.ariadne.message.element import Image as GraiaImage
from graia.ariadne.message.parser.twilight import (
    ArgResult,
    ArgumentMatch,
    ElementMatch,
    ElementResult,
    RegexResult,
    SpacePolicy,
    Twilight,
    WildcardMatch,
)
from graia.ariadne.model import Group, Member
from graia.saya import Channel
from graia.saya.builtins.broadcast.schema import ListenerSchema
from graiax.playwright import PlaywrightBrowser
from loguru import logger
from pydantic import ValidationError

from core.control import (
    AtBotReply,
    Distribute,
    FrequencyLimitation,
    Function,
    Permission,
)
from core.models import response_model, saya_model
from utils.text2img import html2img
from utils.text2img.md2img import (
    HighlightTheme,
    MarkdownToImageConverter,
    OutputMode,
    Theme,
)

from .config import ConfigLoader
from .core.manager import ConversationManager
from .core.preset import preset_dict
from .core.provider import BaseAIProvider, FileContent, FileType
from .plugins_registry import ALL_PLUGINS
from .providers.deepseek import DeepSeekConfig, DeepSeekProvider
from .providers.openai import OpenAIConfig, OpenAIProvider

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


def create_provider(provider_name: str, user_id: str | None = None) -> BaseAIProvider:
    """根据提供商名称创建对应的Provider实例，配置可由master动态修改"""
    global g_config_loader
    if not g_config_loader:
        raise ValueError("ConfigLoader not initialized")

    provider_config = g_config_loader.get_provider_config(provider_name)

    # 获取用户偏好的模型，如果有的话
    user_model = (
        g_config_loader.get_user_model(user_id, provider_name) if user_id else None
    )

    # 检查是否是通用OpenAI兼容提供者
    if provider_config.get("type") == "generic_openai_compatible":
        from .providers.generic_openai_compatible import (
            GenericOpenAICompatibleConfig,
            GenericOpenAICompatibleProvider,
        )

        _config = GenericOpenAICompatibleConfig(**provider_config)
        return GenericOpenAICompatibleProvider(_config, model_name=user_model)
    elif provider_name == "deepseek":
        _config = DeepSeekConfig(**provider_config)
        return DeepSeekProvider(_config, model_name=user_model)
    elif provider_name == "openai":
        _config = OpenAIConfig(**provider_config)
        return OpenAIProvider(_config, model_name=user_model)
    raise ValueError(f"Unknown provider: {provider_name}")


def get_available_providers() -> list[str]:
    """获取所有可用的AI提供商列表"""
    global g_config_loader
    if not g_config_loader:
        raise ValueError("ConfigLoader not initialized")

    return list(g_config_loader.config.get("providers", {}).keys())


def provider_factory(key: str):
    """为ConversationManager提供的工厂函数"""
    global g_config_loader
    if not g_config_loader:
        raise ValueError("ConfigLoader not initialized")

    # 从key中提取用户ID
    user_id = None
    if "-" in key:
        user_id = key.split("-")[-1]

    # 获取用户偏好的提供商
    provider_name = g_config_loader.get_user_provider(user_id)

    # 创建提供商实例
    return create_provider(provider_name, user_id)


def get_provider_models(provider_name: str) -> list[str]:
    """获取指定提供商的可用模型列表"""
    global g_config_loader
    if not g_config_loader:
        raise ValueError("ConfigLoader not initialized")

    provider_config = g_config_loader.get_provider_config(provider_name)

    # 检查是否是通用OpenAI兼容提供者
    if provider_config.get("type") == "generic_openai_compatible":
        from .providers.generic_openai_compatible import (
            GenericOpenAICompatibleConfig,
            GenericOpenAICompatibleProvider,
        )

        _config = GenericOpenAICompatibleConfig(**provider_config)
        provider = GenericOpenAICompatibleProvider(_config)
        return provider.get_available_models()
    elif provider_name == "deepseek":
        _config = DeepSeekConfig(**provider_config)
        provider = DeepSeekProvider(_config)
        return provider.get_available_models()
    elif provider_name == "openai":
        _config = OpenAIConfig(**provider_config)
        provider = OpenAIProvider(_config)
        return provider.get_available_models()
    raise ValueError(f"Unknown provider: {provider_name}")


def plugins_factory(key: str):
    """为ConversationManager提供的插件工厂函数"""
    enabled_plugins = []
    plugins_cfg = g_config_loader.config.get("plugins", {})

    for plugin_name, plugin_info in ALL_PLUGINS.items():
        cfg = plugins_cfg.get(plugin_name, {})
        if cfg.get("enabled", False):
            try:
                plugin_instance = plugin_info["class"](
                    plugin_info["default_config"](cfg)
                )
                enabled_plugins.append(plugin_instance)
                logger.info(f"AiChat plugin {plugin_name} enabled")
            except ValidationError as ve:
                # 更详细的错误日志
                error_msgs = []
                try:
                    for error in ve.errors():
                        loc = " -> ".join(str(x) for x in error.get("loc", []))
                        msg = error.get("msg", "Unknown error")
                        error_msgs.append(f"{loc}: {msg}")
                    logger.warning(
                        f"Plugin {plugin_name} 配置验证错误:\n" + "\n".join(error_msgs)
                    )
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
        image_data = None
        mime_type = "image/jpeg"  # 默认MIME类型

        # 优先尝试使用临时直链获取图片，因为这通常是本地获取，更稳定
        if hasattr(image, "get_bytes") and callable(image.get_bytes):
            try:
                image_data = await image.get_bytes()
                logger.debug("通过 get_bytes 成功获取图片数据")
            except Exception as e:
                logger.warning(f"通过 get_bytes 获取图片失败: {e}")

        # 如果 get_bytes 失败或没有，尝试通过URL下载图片
        if image_data is None and hasattr(image, "url") and image.url:
            # 创建一个不验证SSL证书的上下文，以解决SSL握手问题
            # 注意：这会降低安全性，仅在确定目标安全且无法通过正常方式连接时使用
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE

            # 模拟浏览器请求头，避免被服务器拒绝
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.88 Safari/537.36",
                "Accept": "image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
                "Accept-Encoding": "gzip, deflate, br",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Connection": "keep-alive",
            }

            try:
                async with aiohttp.ClientSession(headers=headers) as session:
                    # 设置超时，避免长时间等待
                    async with session.get(
                        image.url, ssl=ssl_context, timeout=30
                    ) as response:
                        if response.status == 200:
                            image_data = await response.read()
                            mime_type = response.headers.get(
                                "Content-Type", "image/jpeg"
                            )
                            logger.debug(
                                f"通过 URL 成功获取图片数据，MIME: {mime_type}"
                            )
                        else:
                            logger.warning(
                                f"从 URL 获取图片失败，状态码: {response.status}, URL: {image.url}"
                            )
            except aiohttp.ClientError as ce:
                logger.error(f"从 URL 获取图片时发生客户端错误: {ce}, URL: {image.url}")
            except Exception as ex:
                logger.error(f"从 URL 获取图片时发生未知错误: {ex}, URL: {image.url}")

        if image_data:
            return FileContent(
                file_type=FileType.IMAGE,
                file_bytes=image_data,
                mime_type=mime_type,
                file_name="image.jpg",
            )
        else:
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
            file_name=getattr(file, "name", "file") or "file",
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
            Twilight(
                [
                    ElementMatch(At, optional=False).space(SpacePolicy.PRESERVE)
                    @ "AtResult",
                    ArgumentMatch("-p", "-preset", optional=True) @ "preset",
                    ArgumentMatch("-n", "-new", action="store_true", optional=True)
                    @ "new_thread",
                    ArgumentMatch("-P", "--pic", action="store_true", optional=True)
                    @ "pic",
                    # 新增参数 --no-tool 用于禁用工具
                    ArgumentMatch("--no-tool", action="store_true", optional=True)
                    @ "no_tool",
                    ArgumentMatch("--show-preset", action="store_true", optional=True)
                    @ "show_preset",
                    ArgumentMatch("--reload-cfg", action="store_true", optional=True)
                    @ "reload_cfg",
                    # -c --clear，清除对话历史
                    ArgumentMatch("-c", "--clear", action="store_true", optional=True)
                    @ "clear_history",
                    # 禁用多模态
                    ArgumentMatch("--no-vision", action="store_true", optional=True)
                    @ "no_vision",
                    # 显示模型信息
                    ArgumentMatch(
                        "--info", "--model-info", action="store_true", optional=True
                    )
                    @ "show_model_info",
                    # 切换模型
                    ArgumentMatch("-m", "--model", optional=True) @ "switch_model",
                    # 添加切换提供商参数
                    ArgumentMatch("-v", "--provider", optional=True)
                    @ "switch_provider",
                    # 重试指令
                    ArgumentMatch("-r", "--retry", action="store_true", optional=True)
                    @ "retry",
                    WildcardMatch().flags(re.DOTALL) @ "content",
                ]
            )
        ],
        decorators=[
            Distribute.require(),
            AtBotReply.require(),
            Function.require(
                channel.module, False
            ),  # 因为@触发条件比较广泛，这里关闭功能未开启时的通知，防止刷屏
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
    no_tool: ArgResult,
    preset: ArgResult,
    content: RegexResult,
    show_preset: ArgResult,
    reload_cfg: ArgResult,
    clear_history: ArgResult,
    no_vision: ArgResult,
    show_model_info: ArgResult,
    switch_model: ArgResult,
    retry: ArgResult,
    switch_provider: ArgResult,
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
                group, MessageChain("你没有权限执行此操作"), quote=source
            )
        g_config_loader = ConfigLoader()
        g_manager = ConversationManager(provider_factory, plugins_factory)
        return await app.send_group_message(
            group, MessageChain("已重新加载AI对话模块配置"), quote=source
        )

    if switch_provider.matched:
        provider_name = switch_provider.result.display.strip()
        if not provider_name:
            available_providers = get_available_providers()
            providers_list = "\n".join(
                [f"- {provider}" for provider in available_providers]
            )
            return await app.send_group_message(
                group,
                MessageChain(
                    f"请指定要切换的提供商名称。\n\n可用的提供商列表：\n{providers_list}"
                ),
                quote=source,
            )

        try:
            # 检查提供商是否存在
            if provider_name not in get_available_providers():
                available_providers = get_available_providers()
                providers_list = "\n".join(
                    [f"- {provider}" for provider in available_providers]
                )
                return await app.send_group_message(
                    group,
                    MessageChain(
                        f"提供商 '{provider_name}' 不存在。\n\n可用的提供商列表：\n{providers_list}"
                    ),
                    quote=source,
                )

            # 尝试切换提供商
            success, message = switch_provider_for_conversation(
                group_id_str, member_id_str, provider_name
            )

            if success:
                return await app.send_group_message(
                    group,
                    MessageChain(message),
                    quote=source,
                )
            else:
                return await app.send_group_message(
                    group,
                    MessageChain(f"切换提供商失败: {message}"),
                    quote=source,
                )
        except Exception as e:
            logger.error(f"切换提供商时出错: {str(e)}")
            return await app.send_group_message(
                group, MessageChain(f"切换提供商时出错: {str(e)}"), quote=source
            )

    if switch_model.matched:
        model_name = switch_model.result.display.strip()
        if not model_name:
            return await app.send_group_message(
                group,
                MessageChain("请指定要切换的模型名称，使用 --info 查看可用模型"),
                quote=source,
            )

        # 获取当前用户的提供商
        provider_name = g_config_loader.get_user_provider(member_id_str)

        try:
            # 检查模型是否在可用列表中
            models = get_provider_models(provider_name)

            # 获取当前会话的实际模型
            current_conversation = g_manager.get_conversation(
                group_id_str, member_id_str
            )
            actual_model = current_conversation.provider.model_name

            if model_name not in models:
                # 使用实心圆(●)标记当前模型，其他模型使用空心圆(○)
                models_text = "\n".join(
                    [
                        f"- {'●' if model == actual_model else '○'} {model}"
                        for model in models
                    ]
                )
                return await app.send_group_message(
                    group,
                    MessageChain(
                        f"模型 '{model_name}' 不存在。\n\n当前提供商{provider_name}可用模型：\n{models_text}"
                    ),
                    quote=source,
                )

            # 如果已经在使用这个模型，不需要切换
            if actual_model == model_name:
                return await app.send_group_message(
                    group,
                    MessageChain(f"已经在使用模型：{model_name}"),
                    quote=source,
                )

            # 切换模型并验证结果
            success, message = g_manager.switch_conversation_model(
                group_id_str, member_id_str, model_name
            )

            if success:
                # 切换成功后再更新用户模型偏好配置
                g_config_loader.set_user_model(member_id_str, provider_name, model_name)

                return await app.send_group_message(
                    group,
                    MessageChain(f"已切换到模型：{model_name}\n对话历史和预设已保留"),
                    quote=source,
                )
            else:
                # 切换失败，保持原模型不变，并显示失败原因
                return await app.send_group_message(
                    group,
                    MessageChain(
                        f"模型切换失败：{message}\n\n如需强制切换，请先使用 -n 开始新对话，再使用 --model 切换模型"
                    ),
                    quote=source,
                )
        except Exception as e:
            logger.error(f"切换模型时出错: {str(e)}")
            return await app.send_group_message(
                group, MessageChain(f"切换模型时出错: {str(e)}"), quote=source
            )

    if show_model_info.matched:
        # 获取当前会话对象
        conversation = g_manager.get_conversation(group_id_str, member_id_str)
        provider = conversation.provider

        # 收集模型信息
        provider_name = provider.__class__.__name__
        model_name = provider.model_name
        model_config = provider.model_config
        max_tokens = model_config.max_tokens
        max_total_tokens = model_config.max_total_tokens

        # 多模态支持情况
        supports_vision = "✅ 支持" if model_config.supports_vision else "❌ 不支持"
        supports_audio = "✅ 支持" if model_config.supports_audio else "❌ 不支持"
        supports_document = "✅ 支持" if model_config.supports_document else "❌ 不支持"

        # 工具调用支持
        supports_tools = "✅ 支持" if model_config.supports_tool_calls else "❌ 不支持"

        # 会话状态
        current_round = conversation.get_round()
        has_conversation = current_round > 0
        conversation_status = (
            f"已有 {current_round} 轮对话" if has_conversation else "暂无对话"
        )
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

        # 获取当前提供商的可用模型列表
        try:
            available_models = get_provider_models(
                g_config_loader.get_user_provider(member_id_str)
            )
            available_models_text = "\n".join(
                [
                    f"- `{model}`{' (当前)' if model == model_name else ''}"
                    for model in available_models
                ]
            )
            models_info = f"\n\n## 可用模型\n可以使用 `--model <模型名>` 切换模型\n\n{available_models_text}"
        except Exception as e:
            models_info = f"\n\n## 可用模型\n获取模型列表失败: {str(e)}"

        # 获取所有提供商及其配置状态
        all_providers = get_available_providers()
        provider_status = []
        for p in all_providers:
            is_configured, error_msg = g_config_loader.is_provider_configured(p)
            status = "✅ 已配置" if is_configured else f"❌ 未配置 ({error_msg})"
            current = (
                "（当前）"
                if p == g_config_loader.get_user_provider(member_id_str)
                else ""
            )
            provider_status.append(f"- **{p}** {current}: {status}")

        providers_info = (
            "\n\n## 可用提供商\n可以使用 `-v / --provider <提供商名称>` 切换提供商\n\n"
            + "\n".join(provider_status)
        )

        # 构建信息字符串
        info_md = f"""
# AI模型信息

## 当前信息
- **提供商**: {provider_name}
- **模型名称**: {model_name}
- **单次输出上限**: {max_tokens} tokens
- **上下文窗口**: {max_total_tokens} tokens

## 多模态支持
- **图片**: {supports_vision}
- **音频**: {supports_audio}
- **文档**: {supports_document}
- **工具调用**: {supports_tools}
{models_info}{providers_info}

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
            browser=app.current()
            .launch_manager.get_interface(PlaywrightBrowser)
            .browser
        )
        img_bytes = await converter.convert_markdown(
            info_md,
            theme=Theme.DARK,
            output_mode=OutputMode.BINARY,
            highlight_theme=HighlightTheme.ATOM_ONE_DARK,
        )
        return await app.send_group_message(
            group, MessageChain(GraiaImage(data_bytes=img_bytes)), quote=source
        )

    if show_preset.matched:
        return await app.send_group_message(
            group,
            MessageChain(
                GraiaImage(
                    data_bytes=await html2img(
                        MarkdownToImageConverter.generate_html(
                            "# 预设列表\n\n" + "> 请使用标题括号前的文本进行设置\n"
                            "## 当前预设\n\n"
                            + f"{g_manager.get_preset(group_id_str, member_id_str)}\n\n"
                            + "## 内置预设：\n\n"
                            + "\n\n".join(
                                [
                                    f"### {i} ({v['name']})\n>{v['description']}"
                                    for i, v in preset_dict.items()
                                ]
                            )
                        )
                    )
                )
            ),
            quote=source,
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
                    quote=source,
                )
        g_manager.new(group_id=group_id_str, member_id=member_id_str)
        await app.send_group_message(
            group, MessageChain("已清除上下文并开始新对话"), quote=source
        )

    if preset.matched:
        # 群聊预设暂不鉴权
        preset_str = preset.result.display.strip()
        g_manager.set_preset(
            group_id_str,
            member_id_str,
            (
                preset_dict[preset_str]["content"]
                if preset_str in preset_dict
                else (preset_str or preset_dict["umaru"]["content"])
            ),
        )
        await app.send_group_message(
            group, MessageChain(f"已设置预设：{preset_str}{'(内置预设)'}"), quote=source
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
                    quote=source,
                )
        g_manager.clear_memory(group_id_str, member_id_str)
        await app.send_group_message(
            group, MessageChain("已清除对话历史"), quote=source
        )

    # 处理重试请求
    if retry.matched:
        # 检查群聊模式，如果是共享模式需要鉴权
        cur_group_mode = g_manager.get_group_mode(group_id_str)
        if cur_group_mode == ConversationManager.GroupMode.SHARED:
            group_perm = await Permission.get_user_perm_byID(group.id, member.id)
            if group_perm < Permission.GroupAdmin:
                return await app.send_group_message(
                    group,
                    MessageChain("当前对话为群共享模式，只有群管理员才能执行重试操作"),
                    quote=source,
                )

        # 尝试重试
        success, retry_result_or_error = g_manager.can_retry(
            group_id_str, member_id_str
        )
        if not success:
            return await app.send_group_message(
                group,
                MessageChain(f"无法重试: {retry_result_or_error}"),
                quote=source,
            )

        # 处理文件和图片
        files = []
        if not no_vision.matched:
            files = await extract_files_from_message(message)
            if files:
                logger.info(f"从消息中提取到 {len(files)} 个文件")

        # 反转工具使用逻辑: 默认启用，除非使用 --no-tool 禁用
        use_tool = not no_tool.matched

        # 执行重试
        response = await g_manager.retry(
            group_id_str, member_id_str, files=files, use_tool=use_tool
        )
    else:
        # 如果没有内容，且消息中没有图片或文件，则不处理
        if not content_text and not any(
            isinstance(elem, Image | File) for elem in message
        ):
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
        # 反转工具使用逻辑: 默认启用，除非使用 --no-tool 禁用
        use_tool = not no_tool.matched

        response = await g_manager.send_message(
            group_id_str,
            member_id_str,
            member.name,
            user_content,
            files=files,
            use_tool=use_tool,
        )

    # 当用户主动选择图片输出或者对话内容过长时，使用图片输出，目前QQ限制消息字符长度为9000，这里取6000字符作为限制，汉字约3000字
    if not pic.matched and len(response) < 6000:
        return await app.send_group_message(group, MessageChain(response), quote=source)
    else:
        converter = MarkdownToImageConverter(
            browser=app.current()
            .launch_manager.get_interface(PlaywrightBrowser)
            .browser
        )
        img_bytes = await converter.convert_markdown(
            response,
            theme=Theme.DARK,
            output_mode=OutputMode.BINARY,
            highlight_theme=HighlightTheme.ATOM_ONE_DARK,
        )
        return await app.send_group_message(
            group, MessageChain(GraiaImage(data_bytes=img_bytes)), quote=source
        )


def switch_provider_for_conversation(
    group_id: str, member_id: str, provider_name: str, model_name: str | None = None
) -> tuple[bool, str]:
    """
    为指定会话切换提供商

    Args:
        group_id: 群组ID
        member_id: 用户ID
        provider_name: 要切换的提供商名称
        model_name: 可选的模型名称，如果不提供，将使用提供商的默认模型

    Returns:
        tuple: (是否成功, 成功/失败消息)
    """
    global g_config_loader, g_manager

    # 验证提供商是否存在
    if provider_name not in get_available_providers():
        return False, f"提供商 '{provider_name}' 不存在"

    # 验证提供商配置是否完整
    is_configured, error_msg = g_config_loader.is_provider_configured(provider_name)
    if not is_configured:
        return False, error_msg

    try:
        # 尝试获取当前会话
        current_conversation = g_manager.get_conversation(group_id, member_id)

        # 如果当前提供商与目标提供商相同，只需返回信息
        if provider_name == g_config_loader.get_user_provider(member_id):
            return True, f"已经在使用提供商：{provider_name}"

        # 如果目标模型未指定，使用提供商默认模型
        if not model_name:
            provider_config = g_config_loader.get_provider_config(provider_name)
            model_name = provider_config.get("default_model")

        # 创建新的提供商实例
        new_provider = create_provider(provider_name, member_id)

        # 如果指定了模型，切换到该模型
        if model_name:
            try:
                new_provider.switch_model(model_name)
            except ValueError:
                # 模型切换失败，使用提供商默认模型
                provider_config = g_config_loader.get_provider_config(provider_name)
                model_name = provider_config.get("default_model")
                new_provider.switch_model(model_name)

        # 更新用户偏好配置
        g_config_loader.set_user_preference(member_id, provider_name, model_name)

        # 创建新会话并保留预设
        preset = current_conversation.preset
        new_conversation = g_manager.new(group_id, member_id)
        if preset:
            new_conversation.set_preset(preset)

        return True, f"已切换到提供商：{provider_name}，使用模型：{model_name}"

    except Exception as e:
        logger.error(f"切换提供商时出错: {str(e)}")
        return False, f"切换提供商时出错: {str(e)}"
