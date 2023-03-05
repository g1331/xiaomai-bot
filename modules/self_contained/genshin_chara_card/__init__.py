import asyncio
import re
import time
from pathlib import Path

import aiohttp
import pypinyin
from bs4 import BeautifulSoup
from graia.ariadne.app import Ariadne
from graia.ariadne.event.lifecycle import ApplicationLaunched
from graia.ariadne.event.message import Group, GroupMessage
from graia.ariadne.message.chain import MessageChain
from graia.ariadne.message.element import Source, Image
from graia.ariadne.message.parser.twilight import RegexResult
from graia.ariadne.message.parser.twilight import Twilight, FullMatch, SpacePolicy, ParamMatch
from graia.saya import Channel
from graia.saya.builtins.broadcast.schema import ListenerSchema
from graiax.playwright import PlaywrightBrowser
from loguru import logger
from playwright._impl._api_types import TimeoutError

from core.control import (
    Permission,
    Function,
    FrequencyLimitation,
    Distribute
)
from core.models import saya_model

module_controller = saya_model.get_module_controller()

channel = Channel.current()
channel.name("GenshinCharaCard")
channel.author("SAGIRI-kawaii")
channel.description("一个原神角色卡查询插件，在群中发送 `/原神角色卡 UID 角色名` 即可")
channel.metadata = module_controller.get_metadata_from_path(Path(__file__))

characters = {}


@channel.use(
    ListenerSchema(
        listening_events=[GroupMessage],
        inline_dispatchers=[
            Twilight([
                FullMatch("-原神角色卡"),
                "uid" @ ParamMatch(optional=False).space(SpacePolicy.FORCE),
                "chara" @ ParamMatch(optional=False)
            ])
        ],
        decorators=[
            Distribute.require(),
            Function.require(channel.module),
            FrequencyLimitation.require(channel.module, 3),
            Permission.group_require(channel.metadata.level, if_noticed=True),
            Permission.user_require(Permission.User, if_noticed=True),
        ],
    )
)
async def genshin_chara_card(app: Ariadne, group: Group, source: Source, uid: RegexResult, chara: RegexResult):
    start_time = time.time()
    uid = uid.result.display
    chara = chara.result.display.strip()
    chara_pinyin = "".join(pypinyin.lazy_pinyin(chara))
    if not uid.isdigit():
        return await app.send_message(group, MessageChain("非法uid"), quote=source)
    if not characters:
        await app.send_message(group, MessageChain("正在初始化角色列表"), quote=source)
        _ = await init_chara_list()
        await app.send_message(group, MessageChain("初始化完成"), quote=source)
    await app.send_message(group, MessageChain("查询ing"), quote=source)
    if chara_pinyin not in characters:
        return await app.send_message(group, MessageChain(f"角色列表中未找到角色：{chara}，请检查拼写"), quote=source)
    url = f"https://enka.shinshin.moe/u/{uid}"
    browser = Ariadne.current().launch_manager.get_interface(PlaywrightBrowser)
    async with browser.page() as page:
        try:
            await page.goto(url, wait_until="networkidle", timeout=100000)
            await page.set_viewport_size({"width": 2560, "height": 1080})
            await page.evaluate(
                "document.getElementsByClassName('Dropdown-list')[0].children[13].dispatchEvent(new Event('click'));"
            )
            html = await page.inner_html(".CharacterList")
            soup = BeautifulSoup(html, "html.parser")
            styles = [figure["style"] for figure in soup.find_all("figure")]
            if all(characters[chara_pinyin] not in style.lower() for style in styles):
                return await app.send_message(
                    group,
                    MessageChain(
                        f"未找到角色{chara} | {chara_pinyin}！只查询到这几个呢（只能查到展柜里有的呢）："
                        f"{'、'.join([k for k, v in characters.items() if any(v in style.lower() for style in styles)])}"
                    ),
                    quote=source,
                )
            index = -1
            chara_src = ""
            for i, style in enumerate(styles):
                if characters[chara_pinyin] in style.lower():
                    index = i
                    chara_src = style
                    break
            if index == -1 or not chara_src:
                return await app.send_message(group, MessageChain("获取角色头像div失败！"), quote=source)
            await page.locator(f"div.avatar.svelte-jlfv30 >> nth={index}").click()
            await asyncio.sleep(1)
            await page.get_by_role("button", name=re.compile("下载", re.IGNORECASE)).click()
            await page.evaluate("document.getElementsByClassName('toolbar')[0].remove()")
            async with page.expect_download() as download_info:
                for _ in range(3):
                    try:
                        await page.get_by_role("button", name=re.compile("下载", re.IGNORECASE)).click(timeout=10000)
                    except TimeoutError:
                        pass
            path = await (await download_info.value).path()
            await app.send_message(
                group,
                MessageChain([
                    f"耗时:{round(time.time() - start_time, 2)}秒\n",
                    Image(path=path),
                ]),
                quote=source,
            )
        except Exception as e:
            logger.error(e)
            await app.send_message(group, MessageChain("没有查询到数据哦qwq"), quote=source)


async def init_chara_list():
    global characters
    url = "https://genshin.honeyhunterworld.com/fam_chars/?lang=CHS"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            html = await resp.text()
    datas = re.findall(r"sortable_data.push\(\[(.*?)]\)", html, re.S)
    data = datas[0].replace(r"\"", '"').replace(r"\\", "\\").replace(r"\/", "/")
    cs = data[1:-1].split("],[")
    for c in cs:
        chn_name = re.findall(r'<img loading="lazy" alt="(.+?)"', c, re.S)[0]
        chn_name = chn_name.encode().decode("unicode_escape")
        en_name = re.findall(r'<a href="/(.+?)_.+/?lang=CHS"', c, re.S)[0]
        characters["".join(pypinyin.lazy_pinyin(chn_name))] = en_name.lower()
    print(characters)


@channel.use(ListenerSchema(listening_events=[ApplicationLaunched]))
async def init():
    if not characters:
        logger.debug("正在初始化原神角色列表")
        _ = await init_chara_list()
        logger.success("原神角色列表初始化完成")
