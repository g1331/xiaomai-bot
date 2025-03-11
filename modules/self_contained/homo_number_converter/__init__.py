from pathlib import Path

from graia.saya import Channel
from graia.ariadne import Ariadne
from graia.ariadne.message.element import Source
from graia.saya.builtins.broadcast import ListenerSchema
from graia.ariadne.event.message import Group, GroupMessage
from graia.ariadne.message.parser.twilight import (
    Twilight,
    RegexMatch,
    RegexResult,
    FullMatch,
)

from core.models import saya_model
from .utils import get_expression
from core.control import Permission, Function, FrequencyLimitation, Distribute

module_controller = saya_model.get_module_controller()
channel = Channel.current()
channel.metadata = module_controller.get_metadata_from_path(Path(__file__))


@channel.use(
    ListenerSchema(
        listening_events=[GroupMessage],
        inline_dispatchers=[
            Twilight(
                [
                    FullMatch("-homo"),
                    RegexMatch(r"-?\d+\.?(\d+)?") @ "real",
                    RegexMatch(r"(\+|-)\d+\.?(\d+)?i", optional=True) @ "imaginary",
                ]
            )
        ],
        decorators=[
            Distribute.require(),
            Function.require(channel.module),
            FrequencyLimitation.require(channel.module),
            Permission.group_require(channel.metadata.level),
            Permission.user_require(Permission.User),
        ],
    )
)
async def homo_number_converter(
    app: Ariadne,
    group: Group,
    real: RegexResult,
    imaginary: RegexResult,
    source: Source,
):
    imaginary_expression = (
        get_expression(imaginary.result.display.strip()[:-1])
        if imaginary.matched
        else None
    )
    left_expression = f"{real.result.display.strip()}"
    left_expression += (
        f"{imaginary.result.display.strip()}=" if imaginary.matched else "="
    )
    await app.send_group_message(
        group,
        left_expression
        + get_expression(real.result.display.strip())
        + (f"+({imaginary_expression})i" if imaginary_expression else ""),
        quote=source,
    )
