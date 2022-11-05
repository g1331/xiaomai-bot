import re
import aiohttp
from graia.ariadne.app import Ariadne
from graia.ariadne.event.message import Group, GroupMessage
from graia.ariadne.message.chain import MessageChain
from graia.ariadne.message.element import Source, Image, Plain
from graia.ariadne.message.parser.twilight import FullMatch, RegexResult, WildcardMatch
from graia.ariadne.message.parser.twilight import Twilight
from graia.saya import Saya, Channel
from graia.saya.builtins.broadcast.schema import ListenerSchema
from loguru import logger

from modules.DuoQHandle import DuoQ
from modules.PermManager import Perm
from modules.Switch import Switch

saya = Saya.current()
channel = Channel.current()
channel.name("setu")
channel.author("13")
channel.description("一个简单的lolicon插件，在群里发送 '-st tag' 即可")

true = True
false = False
null = ''


@channel.use(
    ListenerSchema(
        listening_events=[GroupMessage],
        inline_dispatchers=[
            Twilight([
                FullMatch("-st"),
                WildcardMatch().flags(re.DOTALL) @ "keyword",
            ])
        ],
        decorators=[
            Perm.require(),
            Switch.require("涩图"),
            DuoQ.require()
        ],
    )
)
async def Setu_main(
        app: Ariadne, group: Group, source: Source, keyword: RegexResult
):
    try:
        await app.send_group_message(
            group, await get_result("".join(i.text for i in keyword.result[Plain]).strip()), quote=source
        )
    except Exception as e:
        logger.warning(e)
        await app.send_group_message(
            group, MessageChain(
                f"ERROR:消息风控~"
            ), quote=source
        )


async def get_result(tag: str):
    api_url = f"https://api.lolicon.app/setu/v2?tag={tag}"
    async with aiohttp.ClientSession() as client:
        res = await (await client.get(url=api_url, timeout=3)).json()
    if res["error"] == "":
        if len(res["data"]) != 0:
            data = res["data"][0]
            title = data["title"]
            author = data["author"]
            pid = data["pid"]
            uid = data["uid"]
            pic_url = data["urls"]["original"]
            return MessageChain(
                Image(url=pic_url), "\n",
                f"标题:{title}\n"
                f"PID:{pid}\n"
                f"作者:{author}\n"
                f"UID:{uid}"
            )
        return MessageChain(f"没有搜索到任何内容呢~")
    else:
        return MessageChain(res["error"])


@channel.use(ListenerSchema(listening_events=[GroupMessage],
                            decorators=[Perm.require(),
                                        DuoQ.require()],
                            inline_dispatchers=[
                                Twilight(
                                    [
                                        FullMatch("-help 涩图")
                                    ]
                                )
                            ]))
async def manager_help(app: Ariadne, group: Group, message: MessageChain):
    await app.send_message(group, MessageChain(
        f"插件名:{channel.meta['name']}\n"
        f"插件作者:{channel.meta['author']}\n"
        f"插件描述:{channel.meta['description']}"
    ), quote=message[Source][0])
