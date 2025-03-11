import json
import random
import re
from pathlib import Path

import httpx
from graia.ariadne.app import Ariadne
from graia.ariadne.event.message import GroupMessage
from graia.ariadne.message.chain import MessageChain
from graia.ariadne.message.element import Image, Plain, Voice, FlashImage, App, Forward
from graia.ariadne.message.parser.twilight import (
    RegexResult,
    ElementResult,
    Twilight,
    RegexMatch,
    ElementMatch,
)
from graia.ariadne.model import Group
from graia.saya import Channel, Saya
from graia.saya.builtins.broadcast import ListenerSchema
from loguru import logger

from core.control import Permission, Function, Distribute
from core.models import saya_model
from .library.b23_extract import b23_extract
from .library.bilibili_request import get_b23_url
from .library.draw_bili_image import binfo_image_create
from .utils import (
    get_video_info,
    b23_url_extract,
    math,
    info_json_dump,
    gen_img,
    url_vid_extract,
)

module_controller = saya_model.get_module_controller()
saya = Saya.current()
channel = Channel.current()
channel.meta["name"] = "BilibiliResolve"
channel.meta["description"] = "自动解析消息中的B站链接、小程序"
channel.meta["author"] = "13"
channel.metadata = module_controller.get_metadata_from_path(Path(__file__))

avid_re = r"(av|AV)(\d{1,12})"
bvid_re = "[Bb][Vv]1([0-9a-zA-Z]{2})4[1y]1[0-9a-zA-Z]7([0-9a-zA-Z]{2})"
b23_re = r"(https?://)?b23.tv/\w+"
url_re = r"(https?://)?www.bilibili.com/video/.+(\?[\w\W]+)?"
p = re.compile(f"({avid_re})|({bvid_re})")


@channel.use(
    ListenerSchema(
        listening_events=[GroupMessage],
        inline_dispatchers=[
            Twilight(
                [
                    RegexMatch(avid_re, optional=True) @ "av",
                    RegexMatch(bvid_re, optional=True) @ "bv",
                    RegexMatch(b23_re, optional=True) @ "b23url",
                    RegexMatch(url_re, optional=True) @ "url",
                    ElementMatch(App, optional=True) @ "bapp",
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
async def bilibili_resolve_text(
    app: Ariadne,
    group: Group,
    message: MessageChain,
    av: RegexResult,
    bv: RegexResult,
    b23url: RegexResult,
    url: RegexResult,
    bapp: ElementResult,
):
    if (
        message.has(Image)
        or message.has(Voice)
        or message.has(FlashImage)
        or message.has(Forward)
    ):
        return

    resolve_choice = random.randint(0, 100)
    # Bbot解析
    if resolve_choice > 50:
        message_str = message.as_persistent_string()
        if "b23.tv" in message_str:
            message_str = await b23_extract(message_str) or message_str
        _p = re.compile(r"av(\d{1,15})|BV(1[A-Za-z0-9]{2}4.1.7[A-Za-z0-9]{2})")
        video_number = _p.search(message_str)
        if video_number:
            video_number = video_number[0]
        video_info = await video_info_get(video_number) if video_number else None
        if video_info:
            if video_info["code"] != 0:
                return await app.send_group_message(
                    group, MessageChain([Plain("视频不存在或解析失败")])
                )
            else:
                ...
            try:
                logger.info(f"开始生成视频信息图片：{video_info['data']['aid']}")
                b23_url = await get_b23_url(
                    f"https://www.bilibili.com/video/{video_info['data']['bvid']}"
                )
                try:
                    image = binfo_image_create(video_info, b23_url)
                    return await app.send_group_message(
                        group,
                        MessageChain(
                            Image(data_bytes=image),
                            f"\n{b23_url}",
                        ),
                    )
                except Exception as e:  # noqa
                    logger.exception("视频解析 API 调用出错")
                    logger.error(e)
            except Exception as e:  # noqa
                logger.exception("视频解析 API 调用出错")
                logger.error(e)
        return
    # SAGIRI-BOT解析
    if av.matched or bv.matched:
        vid = message.display
    elif b23url.matched or bapp.matched:
        if bapp.matched:
            bapp = bapp.result.dict()
            content = json.loads(bapp.get("content", {}))
            content = content.get("meta", {}).get("detail_1", {})
            if content.get("title") == "哔哩哔哩":
                b23url = content.get("qqdocurl")
            else:
                content = json.loads(bapp.get("content", {}))
                content = content.get("meta", {}).get("news", {})
                if "哔哩哔哩" in content.get("desc", ""):
                    b23url = content.get("jumpUrl")
                else:
                    return
        else:
            b23url = message.display
        if not (msg_str := await b23_url_extract(b23url)):
            return
        vid = p.search(msg_str).group()
    elif url.matched:
        vid = url_vid_extract(message.display)
        if not vid:
            return
    else:
        return
    video_info = await get_video_info(vid)
    if video_info["code"] == -404:
        return await app.send_message(group, MessageChain("视频不存在"))
    elif video_info["code"] != 0:
        error_text = f"解析B站视频 {vid} 时出错👇\n错误代码：{video_info['code']}\n错误信息：{video_info['message']}"
        logger.error(error_text)
        return await app.send_message(group, MessageChain(error_text))
    else:
        video_info = info_json_dump(video_info["data"])
        img = await gen_img(video_info)
        await app.send_group_message(
            group,
            MessageChain(
                Image(data_bytes=img),
                Plain(
                    f"\n{video_info.title}\n"
                    f"UP主：{video_info.up_name}\n"
                    f"{math(video_info.views)}播放 {math(video_info.likes)}赞\n"
                    f"链接：https://b23.tv/{video_info.bvid}"
                ),
            ),
        )


async def video_info_get(vid_id):
    async with httpx.AsyncClient() as client:
        if vid_id[:2] == "av":
            video_info = await client.get(
                f"https://api.bilibili.com/x/web-interface/view?aid={vid_id[2:]}"
            )
            video_info = video_info.json()
        elif vid_id[:2] == "BV":
            video_info = await client.get(
                f"https://api.bilibili.com/x/web-interface/view?bvid={vid_id}"
            )
            video_info = video_info.json()
        else:
            raise ValueError("视频 ID 格式错误，只可为 av 或 BV")
        return video_info
