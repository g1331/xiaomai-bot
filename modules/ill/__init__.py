import json
import random
from pathlib import Path

from graia.ariadne import Ariadne
from graia.ariadne.event.message import GroupMessage, MessageEvent
from graia.ariadne.message.chain import MessageChain
from graia.ariadne.message.element import At, Source
from graia.ariadne.message.parser.twilight import (
    Twilight,
    FullMatch,
    ElementMatch,
    ParamMatch,
    ElementResult,
    RegexResult, UnionMatch, SpacePolicy,
)
from graia.ariadne.model import Group
from graia.saya import Channel
from graia.saya.builtins.broadcast import ListenerSchema

from modules.DuoQHandle import DuoQ
from modules.PermManager import Perm
from modules.Switch import Switch

channel = Channel.current()
channel.name("发病")
channel.description("生成对特定对象的发病文\n在群中发送 `-[发病|发癫] [@target] 内容` 即可，target 未填时默认对自己发病")
channel.author("nullqwertyuiop")

with Path(Path(__file__).parent, "ill_templates.json").open("r", encoding="UTF-8") as f:
    TEMPLATES = json.loads(f.read())["data"]


@channel.use(
    ListenerSchema(
        [GroupMessage,
         # FriendMessage
         ],
        inline_dispatchers=[
            Twilight(
                [
                    "action" @ UnionMatch("-发病", "-发癫").space(
                        SpacePolicy.PRESERVE),
                    ElementMatch(At, optional=True) @ "at",
                    ParamMatch(optional=True) @ "text",
                ]
            )
        ],
        decorators=[
            Switch.require("发病"),
            Perm.require(),
            DuoQ.require()
        ],
    )
)
async def ill(app: Ariadne, event: MessageEvent, at: ElementResult, text: RegexResult):
    if at.matched:
        _target = at.result.target
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
    )


@channel.use(ListenerSchema(listening_events=[GroupMessage],
                            decorators=[
                                Perm.require(),
                                DuoQ.require()
                            ],
                            inline_dispatchers=[
                                Twilight(
                                    [
                                        FullMatch("-help 发病")
                                    ]
                                )
                            ]))
async def manager_help(app: Ariadne, group: Group, message: MessageChain):
    await app.send_message(group, MessageChain(
        f"插件名:{channel.meta['name']}\n"
        f"插件作者:{channel.meta['author']}\n"
        f"插件描述:{channel.meta['description']}"
    ), quote=message[Source][0])
