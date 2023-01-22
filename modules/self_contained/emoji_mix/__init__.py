from datetime import datetime
from pathlib import Path

from aiohttp import ClientSession
from creart import create
from graia.ariadne import Ariadne
from graia.ariadne.event.lifecycle import ApplicationLaunch
from graia.ariadne.event.message import GroupMessage
from graia.ariadne.message import Source
from graia.ariadne.message.chain import MessageChain
from graia.ariadne.message.element import Image, Forward, ForwardNode
from graia.ariadne.message.parser.twilight import (
    Twilight,
    UnionMatch,
    RegexResult, FullMatch, RegexMatch,
)
from graia.ariadne.util.saya import listen, decorate, dispatch
from graia.saya import Channel
from graia.saya.builtins.broadcast import ListenerSchema

from core.config import GlobalConfig
from core.control import (
    Permission,
    Function,
    FrequencyLimitation,
    Distribute
)
from core.models import saya_model
from .util import _ALL_EMOJI, get_mix_emoji_url, get_available_pairs, _download_update

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
    Twilight(
        [
            UnionMatch(*_ALL_EMOJI) @ "left",
            UnionMatch(*_ALL_EMOJI) @ "right",
        ]
    )
)
@decorate(
    Distribute.require(),
    FrequencyLimitation.require(channel.module, 3),
    Function.require(channel.module),
    Permission.user_require(Permission.User, if_noticed=True),
    Permission.group_require(channel.metadata.level, if_noticed=True),
)
async def emoji_mix(
        app: Ariadne, event: GroupMessage, left: RegexResult, right: RegexResult, source: Source
):
    left: str = left.result.display
    right: str = right.result.display
    try:
        async with ClientSession() as session:
            assert (
                url := get_mix_emoji_url(left, right)
            ), f'不存在该 Emoji 组合，可以发送 "查看 emoji 组合：{left}" 查找可用组合'
            async with session.get(url, proxy=proxy) as resp:
                assert resp.status == 200, "图片下载失败"
                image: bytes = await resp.read()
                return await app.send_group_message(
                    event.sender.group, MessageChain(Image(data_bytes=image)), quote=source
                )
    except AssertionError as err:
        err_text = err.args[0]
    except Exception as err:
        err_text = str(err)
    return await app.send_group_message(event.sender.group, MessageChain(err_text), quote=source)


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
    Permission.user_require(Permission.User, if_noticed=True),
    Permission.group_require(channel.metadata.level, if_noticed=True),
)
async def get_emoji_pair(app: Ariadne, event: GroupMessage, keyword: RegexResult, source: Source):
    keyword = keyword.result.display[1:].strip()
    if pairs := get_available_pairs(keyword):
        return app.send_message(
            event.sender.group,
            MessageChain(
                Forward(
                    ForwardNode(
                        target=event.sender,
                        time=datetime.now(),
                        message=MessageChain(f"可用 Emoji 组合：\n{', '.join(pairs)}"),
                    )
                )
            ),
            quote=source
        )
    return app.send_message(event.sender.group, MessageChain("没有可用的 Emoji 组合"), quote=source)


@channel.use(ListenerSchema(listening_events=[ApplicationLaunch]))
async def fetch_emoji_update():
    await _download_update()
