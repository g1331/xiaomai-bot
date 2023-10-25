import asyncio
from pathlib import Path

from creart import create
from graia.saya import Saya, Channel
from graia.ariadne.app import Ariadne
from graia.ariadne.event.message import Group, GroupMessage
from graia.ariadne.message.chain import MessageChain, Image
from graia.saya.builtins.broadcast.schema import ListenerSchema
from graia.ariadne.message.parser.twilight import (
    Twilight,
    ArgResult,
    ArgumentMatch, FullMatch
)

from core.models import saya_model
from .utils import gen_counting_down, gen_gif
from core.control import (
    FrequencyLimitation,
    Function,
    Permission,
    Distribute
)

module_controller = saya_model.get_module_controller()
saya = create(Saya)
channel = Channel.current()
#channel.name("WonderingEarthCountingDown")
#channel.author("SAGIRI-kawaii")
channel.metadata = module_controller.get_metadata_from_path(Path(__file__))


@channel.use(
    ListenerSchema(
        listening_events=[GroupMessage],
        inline_dispatchers=[
            Twilight([
                FullMatch("/流浪地球"),
                ArgumentMatch("-t", "-top") @ "top",
                ArgumentMatch("-s", "-start") @ "start",
                ArgumentMatch("-c", "-count") @ "count",
                ArgumentMatch("-e", "-end") @ "end",
                ArgumentMatch("-b", "-bottom") @ "bottom",
                ArgumentMatch("-rgba", optional=True, action="store_true") @ "rgba",
                ArgumentMatch("-gif", optional=True, action="store_true") @ "gif"
            ])
        ],
        decorators=[
            Distribute.require(),
            Function.require(channel.module),
            FrequencyLimitation.require(channel.module, 3),
            Permission.group_require(channel.metadata.level),
            Permission.user_require(Permission.User),
        ]
    )
)
async def wandering_earth_counting_down(
        app: Ariadne, group: Group, top: ArgResult, start: ArgResult, count: ArgResult, end: ArgResult,
        bottom: ArgResult,
        rgba: ArgResult, gif: ArgResult
):
    top = top.result.display
    start = start.result.display
    count = count.result.display
    end = end.result.display
    bottom = bottom.result.display.strip("\"").strip("'")
    if gif.matched and not count.isnumeric():
        return await app.send_group_message(group, MessageChain("生成 gif 时 count 必须为数字！"))
    elif gif.matched and int(count) > 114:
        return await app.send_group_message(group, MessageChain("生成 gif 时 count 最大仅支持114！"))
    content = await asyncio.to_thread(
        gen_gif if gif.matched else gen_counting_down, top, start, count, end, bottom, rgba.matched
    )
    await app.send_group_message(group, MessageChain(Image(data_bytes=content)))
