import datetime
import re

import aiohttp
import httpx
from graia.ariadne.app import Ariadne
from graia.ariadne.event.message import GroupMessage
from graia.ariadne.message.chain import MessageChain
from graia.ariadne.message.element import Image, Plain, Voice, FlashImage, Source
from graia.ariadne.message.parser.twilight import Twilight, FullMatch, RegexResult, RegexMatch
from graia.ariadne.model import Group
from graia.saya import Channel, Saya
from graia.saya.builtins.broadcast.schema import ListenerSchema
from loguru import logger

from modules.DuoQHandle import DuoQ
from modules.PermManager import Perm
from modules.Switch import Switch
from util.text_engine.elements import Text
from util.text_engine.text_engine import TextEngine
from .library.b23_extract import b23_extract
from .library.bilibili_request import get_b23_url
from .library.draw_bili_image import binfo_image_create

saya = Saya.current()
channel = Channel.current()


@channel.use(ListenerSchema(listening_events=[GroupMessage],
                            decorators=[
                                Switch.require("哔哩哔哩"),
                                Perm.require(),
                                DuoQ.require()
                            ]))
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


@channel.use(
    ListenerSchema(
        listening_events=[GroupMessage],
        inline_dispatchers=[
            Twilight([RegexMatch("[1-7]") @ "days", FullMatch("日内新番")])
        ],
        decorators=[
            Switch.require("哔哩哔哩"),
            Perm.require(),
            DuoQ.require()
        ],
    )
)
async def bilibili_bangumi_scheduler(app: Ariadne, group: Group, days: RegexResult):
    days = int(days.result.display)
    await app.send_group_message(group, await formatted_output_bangumi(days))


async def get_new_bangumi_json() -> dict:
    """
    Get json data from bilibili

    Args:

    Examples:
        data = await get_new_bangumi_json()

    Return:
        dict:data get from bilibili
    """
    url = "https://bangumi.bilibili.com/web_api/timeline_global"
    headers = {
        "accept": "application/json, text/plain, */*",
        "accept-encoding": "gzip, deflate",
        "accept-language": "zh-CN,zh;q=0.9",
        "origin": "https://www.bilibili.com",
        "referer": "https://www.bilibili.com/",
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-site",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_14_6) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/85.0.4183.121 Safari/537.36 ",
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(url=url, headers=headers) as resp:
            result = await resp.json()
    return result


async def get_formatted_new_bangumi_json() -> list:
    """
    Format the json data

    Args:

    Examples:
        data = get_formatted_new_bangumi_json()

    Returns:
        {
            "title": str,
            "cover": str,
            "pub_index": str,
            "pub_time": str,
            "url": str
        }
    """
    all_bangumi_data = await get_new_bangumi_json()
    all_bangumi_data = all_bangumi_data["result"][-7:]
    formatted_bangumi_data = []

    for bangumi_data in all_bangumi_data:
        temp_bangumi_data_list = []
        for data in bangumi_data["seasons"]:
            temp_bangumi_data_dict = {
                "title": data["title"],
                "cover": data["cover"],
                "pub_index": data["delay_index"] + " (本周停更)"
                if data["delay"]
                else data["pub_index"],
                "pub_time": data["pub_time"],
                "url": data["url"],
            }

            temp_bangumi_data_list.append(temp_bangumi_data_dict)
        formatted_bangumi_data.append(temp_bangumi_data_list)

    return formatted_bangumi_data


async def formatted_output_bangumi(days: int) -> MessageChain:
    """
    Formatted output json data

    Args:
        days: The number of days to output(1-7)

    Examples:
        data_str = formatted_output_bangumi(7)

    Return:
        MessageChain
    """
    formatted_bangumi_data = await get_formatted_new_bangumi_json()
    temp_output_substring = ["------BANGUMI------\n\n"]
    now = datetime.datetime.now()
    for index in range(days):
        temp_output_substring.append(now.strftime("%m-%d"))
        temp_output_substring.append("即将播出：")
        for data in formatted_bangumi_data[index]:
            temp_output_substring.append(
                "\n%s %s %s\n" % (data["pub_time"], data["title"], data["pub_index"])
            )
        temp_output_substring.append("\n\n----------------\n\n")
        now += datetime.timedelta(days=1)

    content = "".join(temp_output_substring)
    return MessageChain([Image(data_bytes=TextEngine([Text(content)]).draw())])


@channel.use(ListenerSchema(listening_events=[GroupMessage],
                            decorators=[Perm.require(),
                                        DuoQ.require()],
                            inline_dispatchers=[
                                Twilight(
                                    [
                                        FullMatch("-help 哔哩哔哩")
                                    ]
                                )
                            ]))
async def manager_help(app: Ariadne, group: Group, message: MessageChain):
    await app.send_message(group, MessageChain(
        f"1.自动解析群消息b站链接\n"
        f"2.一个可以获取BiliBili7日内新番时间表的插件,在群内发送 `[1-7]日内新番` 即可"
    ), quote=message[Source][0])
