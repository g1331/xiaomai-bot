from pathlib import Path
from typing import Union

import aiohttp
from graia.ariadne.app import Ariadne
from graia.ariadne.event.message import GroupMessage
from graia.ariadne.message import Source
from graia.ariadne.message.chain import MessageChain
from graia.ariadne.message.element import Image, Forward
from graia.ariadne.message.parser.twilight import RegexResult, Twilight, RegexMatch
from graia.ariadne.model import Group
from graia.saya import Channel, Saya
from graia.saya.builtins.broadcast import ListenerSchema

from core.control import (
    Permission,
    Function,
    Distribute
)
from core.models import saya_model

module_controller = saya_model.get_module_controller()
saya = Saya.current()
channel = Channel.current()
channel.name("GithubCard")
channel.description("自动解析消息中的Github链接转为图片")
channel.author("13")
channel.metadata = module_controller.get_metadata_from_path(Path(__file__))

url_re = r"https?://github\.com/([^/]+/[^/]+)"


@channel.use(
    ListenerSchema(
        listening_events=[GroupMessage],
        inline_dispatchers=[
            Twilight([
                RegexMatch(url_re) @ "url",
            ])
        ],
        decorators=[
            Distribute.require(),
            Function.require(channel.module),
            Permission.group_require(channel.metadata.level),
            Permission.user_require(Permission.User, if_noticed=False),
        ],
    )
)
async def github_card(app: Ariadne, group: Group, message: MessageChain, source: Source, url: RegexResult):
    if message.has(Image) or message.has(Forward):
        return
    url = url.result.display
    image_url = await get_github_reposity_information(url)
    await app.send_group_message(
        group,
        MessageChain(
            Image(url=image_url)
        ),
        quote=source
    )


async def get_github_reposity_information(url: str) -> Union[str, None]:
    try:
        s_r = url.replace("https://github.com/", "").split("/")
        UserName, RepoName = s_r[0], s_r[1]
    except Exception:
        return None
    headers = {
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.107 Safari/537.36"}
    async with aiohttp.ClientSession() as session:
        async with session.get(f"https://api.github.com/users/{UserName}", headers=headers, timeout=5) as response:
            RawData = await response.json()
            AvatarUrl = RawData["avatar_url"]
            return f"https://image.thum.io/get/width/1280/crop/640/viewportWidth/1280/png/noanimate/https://socialify.git.ci/{UserName}/{RepoName}/image?description=1&font=Rokkitt&language=1&name=1&owner=1&pattern=Circuit%20Board&theme=Light&logo={AvatarUrl}"
