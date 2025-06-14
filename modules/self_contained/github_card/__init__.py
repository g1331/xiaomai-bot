from pathlib import Path

from graia.ariadne.app import Ariadne
from graia.ariadne.event.message import GroupMessage
from graia.ariadne.message import Source
from graia.ariadne.message.chain import MessageChain
from graia.ariadne.message.element import Image, Forward
from graia.ariadne.message.parser.twilight import RegexResult, Twilight, RegexMatch
from graia.ariadne.model import Group
from graia.saya import Channel, Saya
from graia.saya.builtins.broadcast import ListenerSchema

from core.control import Permission, Function, Distribute
from core.models import saya_model

module_controller = saya_model.get_module_controller()
saya = Saya.current()
channel = Channel.current()
channel.meta["name"] = "GithubCard"
channel.meta["description"] = "自动解析消息中的Github链接转为图片"
channel.meta["author"] = "13"
channel.metadata = module_controller.get_metadata_from_path(Path(__file__))

url_re = r"https?://github\.com/.*"


@channel.use(
    ListenerSchema(
        listening_events=[GroupMessage],
        inline_dispatchers=[
            Twilight(
                [
                    RegexMatch(url_re) @ "url",
                ]
            )
        ],
        decorators=[
            Distribute.require(),
            Function.require(channel.module),
            Permission.group_require(channel.metadata.level),
            Permission.user_require(Permission.User, if_noticed=False),
        ],
    )
)
async def github_card(
    app: Ariadne, group: Group, message: MessageChain, source: Source, url: RegexResult
):
    if message.has(Image) or message.has(Forward):
        return
    url = url.result.display
    image_url = await get_github_reposity_information(url)
    await app.send_group_message(
        group, MessageChain(Image(url=image_url)), quote=source
    )


async def get_github_reposity_information(url: str) -> str | None:
    from urllib.parse import urlparse
    
    parsed_url = urlparse(url)
    if parsed_url.hostname != "github.com":
        return None
    
    cleaned_url = parsed_url.path
    return f"https://opengraph.githubassets.com/c9f4179f4d560950b2355c82aa2b7750bffd945744f9b8ea3f93cc24779745a0{cleaned_url}"
