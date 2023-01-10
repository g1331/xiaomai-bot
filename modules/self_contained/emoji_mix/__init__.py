from pathlib import Path

from aiohttp import ClientSession
from creart import create
from graia.ariadne import Ariadne
from graia.ariadne.event.message import GroupMessage
from graia.ariadne.message.chain import MessageChain
from graia.ariadne.message.element import Image, Plain
from graia.ariadne.message.parser.twilight import (
    Twilight,
    UnionMatch,
    RegexResult,
)
from graia.ariadne.util.saya import listen, decorate, dispatch
from graia.saya import Channel

from core.config import GlobalConfig
from core.control import (
    Permission,
    Function,
    FrequencyLimitation,
    Distribute
)
from core.models import saya_model
from .util import ALL_EMOJI, get_mix_emoji_url

module_controller = saya_model.get_module_controller()
global_config = create(GlobalConfig)

channel = Channel.current()
channel.name("EmojiMix")
channel.author("nullqwertyuiop")
channel.author("SAGIRI-kawaii")
channel.author("from: MeetWq")
channel.description("一个生成emoji融合图的插件，发送 '{emoji1}{emoji2}' 即可")
channel.metadata = module_controller.get_metadata_from_path(Path(__file__))

config = create(GlobalConfig)
proxy = config.proxy if config.proxy != "proxy" else ""


@listen(GroupMessage)
@dispatch(
    Twilight([
        UnionMatch(*ALL_EMOJI) @ "emoji1",
        UnionMatch(*ALL_EMOJI) @ "emoji2",
    ])
)
@decorate(
    Distribute.require(),
    FrequencyLimitation.require(channel.module),
    Function.require(channel.module),
    Permission.user_require(Permission.User, if_noticed=True),
    Permission.group_require(channel.metadata.level, if_noticed=True),
)
async def emoji_mix(
        app: Ariadne, event: GroupMessage, emoji1: RegexResult, emoji2: RegexResult
):
    emoji1 = emoji1.result.display
    emoji2 = emoji2.result.display
    try:
        async with ClientSession() as session:
            assert (link := get_mix_emoji_url(emoji1, emoji2)), "无法获取合成链接"
            async with session.get(link, proxy=proxy) as resp:
                assert resp.status == 200, "图片获取失败"
                image = await resp.read()
                return await app.send_group_message(
                    event.sender.group, MessageChain([Image(data_bytes=image)])
                )
    except AssertionError as err:
        err_text = err.args[0]
    except Exception as err:
        err_text = str(err)
    return await app.send_group_message(
        event.sender.group, MessageChain([Plain(err_text)])
    )
