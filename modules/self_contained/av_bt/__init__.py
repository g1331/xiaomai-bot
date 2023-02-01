import asyncio
from pathlib import Path

import aiohttp
from bs4 import BeautifulSoup
from creart import create
from graia.ariadne import Ariadne
from graia.ariadne.event.message import GroupMessage
from graia.ariadne.message import Source
from graia.ariadne.message.chain import MessageChain
from graia.ariadne.message.element import Image
from graia.ariadne.message.parser.twilight import Twilight, WildcardMatch, RegexResult, ArgumentMatch, ArgResult, \
    FullMatch
from graia.ariadne.model.relationship import Group, Member
from graia.ariadne.util.saya import listen, decorate, dispatch
from graia.broadcast.interrupt import InterruptControl
from graia.saya import Channel, Saya
from graiax.playwright import PlaywrightBrowser

from core.config import GlobalConfig
from core.control import Distribute, Function, Permission, FrequencyLimitation
from core.models import saya_model
from utils.waiter import ConfirmWaiter

module_controller = saya_model.get_module_controller()
saya = Saya.current()
channel = Channel.current()
channel.name("AVBT")
channel.author("SAGIRI-kawaii")
channel.author("移植by十三")
channel.metadata = module_controller.get_metadata_from_path(Path(__file__))
global_config = create(GlobalConfig)
inc = InterruptControl(saya.broadcast)
url = "https://sukebei.nyaa.si"
proxy = global_config.proxy if global_config.proxy != "proxy" else None


@listen(GroupMessage)
@dispatch(
    Twilight([
        FullMatch("-av"),
        ArgumentMatch("-i", "-image", action="store_true") @ "has_img",
        WildcardMatch() @ "keyword"
    ])
)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module, 6),
    Permission.group_require(channel.metadata.level, if_noticed=True),
    Permission.user_require(Permission.User, if_noticed=False),
)
async def av_bt(app: Ariadne, group: Group, has_img: ArgResult, keyword: RegexResult, source: Source, member: Member):
    keyword = keyword.result.display.strip()
    if not keyword:
        return
    await app.send_message(
        group, MessageChain(
            "查询ing"
        ), quote=source
    )
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{url}/?q={keyword}", proxy=proxy) as resp:
            html = await resp.read()
        soup = BeautifulSoup(html, "html.parser")
        try:
            href = soup.find("table").find("tbody").find("tr").find_all("a")[1]["href"]
        except (AttributeError, IndexError):
            return await app.send_message(
                group, MessageChain(
                    "没有找到结果!"
                ), quote=source
            )
        view_url = url + href
        async with session.get(view_url, proxy=proxy) as resp:
            html = await resp.read()
        soup = BeautifulSoup(html, "html.parser")
        panels = soup.find_all("div", {"class": "panel"})[:-1]
        magnet = panels[0].find("div", {"class": "panel-footer"}).find_all("a")[1]["href"]
        browser = Ariadne.current().launch_manager.get_interface(PlaywrightBrowser)
        async with browser.page() as page:
            await page.goto(view_url, wait_until="networkidle", timeout=100000)
            await page.evaluate("document.getElementById('dd4ce992-766a-4df0-a01d-86f13e43fd61').remove()")
            await page.evaluate("document.getElementById('e7a3ddb6-efae-4f74-a719-607fdf4fa1a1').remove()")
            await page.evaluate("document.getElementById('comments').remove()")
            await page.evaluate("document.getElementsByTagName('nav')[0].remove()")
            await page.evaluate("document.getElementsByTagName('footer')[0].remove()")
            if not has_img.matched:
                await page.evaluate("var a = document.getElementsByClassName('panel')[1].getElementsByTagName('img');while(a.length > 0){a[0].remove()}")
            else:
                await app.send_message(group, MessageChain(f"注意!该消息内容可能包含NSFW信息,是否继续查看?(y/n)"), quote=source)
                try:
                    if not await asyncio.wait_for(inc.wait(ConfirmWaiter(group, member)), 30):
                        return await app.send_group_message(group, MessageChain("取消查看成功~"), quote=source)
                except asyncio.TimeoutError:
                    return await app.send_group_message(group, MessageChain("回复等待超时,进程退出"), quote=source)
            content = await page.screenshot(full_page=True)
        return await app.send_message(
            group, MessageChain([
                Image(data_bytes=content),
                f"\n{magnet}"
            ]),
            quote=source
        )
