from datetime import datetime
from pathlib import Path

import aiofiles
from aiohttp import ClientSession
from creart import create
from graia.ariadne import Ariadne
from graia.ariadne.event.lifecycle import ApplicationLaunch
from graia.ariadne.event.message import GroupMessage
from graia.ariadne.message import Source
from graia.ariadne.message.chain import MessageChain
from graia.ariadne.message.element import Forward, ForwardNode, Image
from graia.ariadne.message.parser.twilight import (
    FullMatch,
    RegexMatch,
    RegexResult,
    Twilight,
    UnionMatch,
)
from graia.ariadne.util.saya import decorate, dispatch, listen
from graia.saya import Channel
from graia.saya.builtins.broadcast import ListenerSchema

from core.config import GlobalConfig
from core.control import Distribute, FrequencyLimitation, Function, Permission
from core.models import saya_model

from .util import (
    ALL_EMOJIS,
    CACHE_DIR,
    METADATA_DIR,
    PROXY,
    download_metadata_update,
    ensure_directory_exists,
    get_available_pairs,
    get_emoji_cache_path,
    get_mix_emoji_url,
    is_emoji_cached,
)

# 模块初始化
module_controller = saya_model.get_module_controller()
config = create(GlobalConfig)

# 频道设置
channel = Channel.current()
channel.meta["name"] = "EmojiMix"
channel.meta["author"] = "nullqwertyuiop, SAGIRI-kawaii, from: MeetWq"
channel.meta["description"] = "一个生成emoji融合图的插件，发送 '{emoji1}{emoji2}' 即可"
channel.metadata = module_controller.get_metadata_from_path(Path(__file__))


@listen(GroupMessage)
@dispatch(
    Twilight(
        [
            UnionMatch(*ALL_EMOJIS) @ "left_emoji",
            UnionMatch(*ALL_EMOJIS) @ "right_emoji",
        ]
    )
)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module, 3),
    Permission.group_require(channel.metadata.level, if_noticed=True),
    Permission.user_require(Permission.User, if_noticed=True),
)
async def handle_emoji_mix(
    app: Ariadne,
    event: GroupMessage,
    left_emoji: RegexResult,
    right_emoji: RegexResult,
    source: Source,
):
    """处理emoji融合请求"""
    left = left_emoji.result.display
    right = right_emoji.result.display

    try:
        # 检查本地缓存
        if is_emoji_cached(left, right):
            cache_path = get_emoji_cache_path(left, right)
            return await app.send_group_message(
                event.sender.group, MessageChain(Image(path=cache_path)), quote=source
            )

        # 从网络获取并缓存
        async with ClientSession() as session:
            # 获取混合URL
            emoji_url = get_mix_emoji_url(left, right)
            if not emoji_url:
                error_msg = (
                    f'不存在该Emoji组合，可以发送"查看emoji组合：{left}"查找可用组合'
                )
                return await app.send_group_message(
                    event.sender.group, MessageChain(error_msg), quote=source
                )

            # 下载图片
            async with session.get(emoji_url, proxy=PROXY) as response:
                if response.status != 200:
                    return await app.send_group_message(
                        event.sender.group, MessageChain("图片下载失败"), quote=source
                    )

                image_data = await response.read()

                # 保存到缓存
                cache_path = get_emoji_cache_path(left, right)
                ensure_directory_exists(cache_path.parent)
                async with aiofiles.open(cache_path, "wb") as file:
                    await file.write(image_data)

                # 发送图片
                return await app.send_group_message(
                    event.sender.group,
                    MessageChain(Image(data_bytes=image_data)),
                    quote=source,
                )
    except Exception as error:
        error_message = str(error)
        return await app.send_group_message(
            event.sender.group,
            MessageChain(f"生成Emoji组合失败: {error_message}"),
            quote=source,
        )


@listen(GroupMessage)
@dispatch(
    Twilight(
        FullMatch("查看"),
        RegexMatch(r"[eE][mM][oO][jJ][iI]"),
        FullMatch("组合"),
        RegexMatch(r"[:：] ?\S+") @ "keyword",
    )
)
@decorate(
    Distribute.require(),
    FrequencyLimitation.require(channel.module, 3),
    Function.require(channel.module),
    Permission.group_require(channel.metadata.level, if_noticed=True),
    Permission.user_require(Permission.User, if_noticed=True),
)
async def show_emoji_combinations(
    app: Ariadne, event: GroupMessage, keyword: RegexResult, source: Source
):
    """显示与特定emoji可组合的其他emoji"""
    # 提取关键字
    query_emoji = keyword.result.display[1:].trip()

    # 获取可用组合
    available_pairs = get_available_pairs(query_emoji)
    if not available_pairs:
        return await app.send_message(
            event.sender.group, MessageChain("没有可用的Emoji组合")
        )

    # 使用转发消息展示结果
    combinations_text = f"可用Emoji组合：\n{', '.join(available_pairs)}"
    forward_node = ForwardNode(
        target=event.sender,
        time=datetime.now(),
        message=MessageChain(combinations_text),
    )

    return await app.send_message(
        event.sender.group,
        MessageChain(Forward(forward_node)),
        quote=source,
    )


@channel.use(ListenerSchema(listening_events=[ApplicationLaunch]))
async def update_emoji_data():
    """应用启动时更新emoji数据"""

    ensure_directory_exists(CACHE_DIR)
    ensure_directory_exists(METADATA_DIR)

    # 更新元数据
    await download_metadata_update()
