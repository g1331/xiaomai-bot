import re
from pathlib import Path

import httpx
from graia.ariadne.app import Ariadne
from graia.ariadne.event.message import GroupMessage
from graia.ariadne.message.chain import MessageChain
from graia.ariadne.message.element import Image, Plain, Voice, FlashImage
from graia.ariadne.model import Group
from graia.ariadne.util.saya import listen, decorate
from graia.saya import Channel, Saya
from loguru import logger

from core.control import (
    Permission,
    Function,
    Distribute
)
from core.models import saya_model
from .library.b23_extract import b23_extract
from .library.bilibili_request import get_b23_url
from .library.draw_bili_image import binfo_image_create

module_controller = saya_model.get_module_controller()
saya = Saya.current()
channel = Channel.current()
channel.name("BilibiliResolve")
channel.description("自动解析消息中的B站链接、小程序")
channel.author("13")
channel.metadata = module_controller.get_metadata_from_path(Path(__file__))


@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    Permission.group_require(channel.metadata.level),
    Permission.user_require(Permission.User, if_noticed=False),
)
async def bilibili_main(
        app: Ariadne, group: Group, message: MessageChain
):
    if message.has(Image) or message.has(Voice) or message.has(FlashImage):
        return

    message_str = message.as_persistent_string()
    if "b23.tv" in message_str:
        message_str = await b23_extract(message_str) or message_str
    p = re.compile(r"av(\d{1,15})|BV(1[A-Za-z0-9]{2}4.1.7[A-Za-z0-9]{2})")
    video_number = p.search(message_str)
    if video_number:
        video_number = video_number[0]
    video_info = await video_info_get(video_number) if video_number else None
    if video_info:
        if video_info["code"] != 0:
            # await Interval.manual(member.id)
            return await app.send_group_message(group, MessageChain([Plain("视频不存在或解析失败")]))
        else:
            ...
            # await Interval.manual(int(video_info["data"]["aid"]))
        try:
            logger.info(f"开始生成视频信息图片：{video_info['data']['aid']}")
            b23_url = await get_b23_url(
                f"https://www.bilibili.com/video/{video_info['data']['bvid']}"
            )
            try:
                image = binfo_image_create(video_info, b23_url)
                await app.send_group_message(
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
