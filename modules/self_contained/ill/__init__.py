import json
import random
from pathlib import Path

from graia.ariadne import Ariadne
from graia.ariadne.event.message import GroupMessage, MessageEvent
from graia.ariadne.message import Source
from graia.ariadne.message.chain import MessageChain
from graia.ariadne.message.element import At
from graia.ariadne.message.parser.twilight import (
    Twilight,
    ElementMatch,
    ParamMatch,
    ElementResult,
    RegexResult, UnionMatch, SpacePolicy,
)
from graia.ariadne.util.saya import listen, decorate, dispatch
from graia.saya import Channel

from core.control import (
    Permission,
    Function,
    FrequencyLimitation,
    Distribute
)
from core.models import saya_model

module_controller = saya_model.get_module_controller()
channel = Channel.current()
channel.name("发病")
channel.description("生成对特定对象的发病文\n在群中发送 `-[发病|发癫] [@target] 内容` 即可，target 未填时默认对自己发病")
channel.author("nullqwertyuiop")
channel.metadata = module_controller.get_metadata_from_path(Path(__file__))


with Path(Path(__file__).parent, "ill_templates.json").open("r", encoding="UTF-8") as f:
    TEMPLATES = json.loads(f.read())["data"]


@listen(GroupMessage)
@dispatch(
    Twilight(
        [
            "action" @ UnionMatch("-发病", "-发癫").space(SpacePolicy.PRESERVE),
            ElementMatch(At, optional=True) @ "at",
            ParamMatch(optional=True) @ "text",
        ]
    )
)
@decorate(
    Distribute.require(),
    FrequencyLimitation.require(channel.module),
    Function.require(channel.module),
    Permission.user_require(Permission.User, if_noticed=True),
    Permission.group_require(channel.metadata.level, if_noticed=True)
)
async def ill(app: Ariadne, event: MessageEvent, at: ElementResult, text: RegexResult, source: Source):
    if at.matched:
        _target: At = at.result
        _target = _target.target
        if _target_member := await app.get_member(event.sender.group, _target):
            target = _target_member.name
        else:
            target = _target
    elif text.matched:
        target = text.result.display
    else:
        target = event.sender.name
    await app.send_message(
        event.sender.group if isinstance(event, GroupMessage) else event.sender,
        MessageChain(random.choice(TEMPLATES).format(target=target)),
        quote=source
    )
