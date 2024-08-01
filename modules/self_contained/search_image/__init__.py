import asyncio
from datetime import datetime
from pathlib import Path

from PicImageSearch import Network, SauceNAO, TraceMoe, Ascii2D, Iqdb, Google, EHentai, BaiDu
from creart import create
from graia.ariadne.app import Ariadne
from graia.ariadne.event.message import GroupMessage
from graia.ariadne.message.chain import MessageChain
from graia.ariadne.message.element import Image, At, ForwardNode, Forward, Source
from graia.ariadne.message.parser.twilight import (
    Twilight, FullMatch,
    ElementMatch, ElementResult,
    SpacePolicy, UnionMatch
)
from graia.ariadne.model import Group, Member
from graia.ariadne.util.saya import listen, decorate, dispatch
from graia.broadcast import Broadcast
from graia.broadcast.interrupt import InterruptControl
from graia.saya import Channel, Saya
from loguru import logger

from core.config import GlobalConfig
from core.control import (
    Permission,
    Function,
    FrequencyLimitation,
    Distribute
)
from core.models import saya_model
from utils.waiter import ImageWaiter

module_controller = saya_model.get_module_controller()
global_config = create(GlobalConfig)
saya = Saya.current()
# 获取属于这个模组的实例
channel = Channel.current()
channel.meta["name"] = "识图"
channel.meta["description"] = "识图、搜番功能"
channel.meta["author"] = "13"
channel.metadata = module_controller.get_metadata_from_path(Path(__file__))


@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level),
    Permission.user_require(Permission.User, if_noticed=True),
)
@dispatch(
    Twilight(
        UnionMatch("-识图", "-搜图").space(SpacePolicy.PRESERVE),
        FullMatch("\n", optional=True),
        "img" @ ElementMatch(Image, optional=False),
    ),
)
async def shiTu(app: Ariadne, group: Group, sender: Member, img: ElementResult, source: Source):
    await app.send_group_message(group, MessageChain("正在搜索，请稍后"), quote=source.id)
    # 获取搜索的图片地址
    img: Image = img.result
    img_url = img.url
    # 使用方法搜索
    scrape_index_tasks = [
        asyncio.ensure_future(fun_saucenao(img_url)),
        # asyncio.ensure_future(fun_ascii2d(img_url)),
        asyncio.ensure_future(fun_iqdb(img_url)),
        asyncio.ensure_future(fun_google(img_url)),
        asyncio.ensure_future(fun_ehentai(img_url)),
        asyncio.ensure_future(fun_baidu(img_url))
    ]
    tasks = asyncio.gather(*scrape_index_tasks, return_exceptions=False)
    try:
        await tasks
    except Exception as e:
        return await app.send_message(group, MessageChain(At(sender.id), f"搜索时出现一个错误!{e}"), quote=source)
    fwd_nodeList = [
        ForwardNode(
            target=sender,
            time=datetime.now(),
            message=item.result()
        ) for item in scrape_index_tasks if item
    ]
    try:
        bot_msg = await app.send_message(group, MessageChain(Forward(nodeList=fwd_nodeList)))
        if bot_msg.id < 0:
            raise Exception("消息风控!")
    except Exception as e:
        logger.warning(e)
        return await app.send_message(group, MessageChain(At(sender.id), "ERROR:工口发生~"), quote=source)
    return await app.send_message(group, MessageChain(At(sender.id), "请点击转发信息查看!"))


@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level),
    Permission.user_require(Permission.User, if_noticed=True),
)
@dispatch(
    Twilight(
        UnionMatch("-识图", "-搜图").space(SpacePolicy.PRESERVE),
    )
)
async def shiTu_waiter(app: Ariadne, group: Group, sender: Member, source: Source):
    await app.send_message(group, MessageChain('请在30秒内发送要搜索的图片!'), quote=source)

    try:
        result: Image = await asyncio.wait_for(InterruptControl(create(Broadcast)).wait(ImageWaiter(group, sender)), 30)
    except asyncio.exceptions.TimeoutError:
        return await app.send_message(group, MessageChain('操作超时,已自动退出!'), quote=source)

    if result:
        await app.send_message(group, MessageChain('搜索ing'), quote=source)
    else:
        return await app.send_message(
            group, MessageChain('未识别到图片,已自动退出!'), quote=source
        )
    # 获取搜索的图片地址
    img_url = result.url
    # 使用方法搜索
    scrape_index_tasks = [
        asyncio.ensure_future(fun_saucenao(img_url)),
        asyncio.ensure_future(fun_ascii2d(img_url)),
        asyncio.ensure_future(fun_iqdb(img_url)),
        asyncio.ensure_future(fun_google(img_url)),
        asyncio.ensure_future(fun_ehentai(img_url)),
        asyncio.ensure_future(fun_baidu(img_url))
    ]
    tasks = asyncio.gather(*scrape_index_tasks, return_exceptions=False)
    await tasks
    fwd_nodeList = [
        ForwardNode(
            target=sender,
            time=datetime.now(),
            message=item.result(),
        ) for item in scrape_index_tasks if item
    ]
    try:
        bot_msg = await app.send_message(group, MessageChain(Forward(nodeList=fwd_nodeList)))
        if bot_msg.id < 0:
            raise Exception("消息风控!")
    except Exception as e:
        logger.warning(e)
        return await app.send_message(group, MessageChain(At(sender.id), "ERROR:工口发生~"), quote=source)
    return await app.send_message(group, MessageChain(At(sender.id), "请点击转发信息查看!"))


@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level),
    Permission.user_require(Permission.User, if_noticed=True),
)
@dispatch(
    Twilight(
        FullMatch("-搜番"),
        FullMatch("\n", optional=True),
        "img" @ ElementMatch(Image, optional=False),
    )
)
async def souFan(app: Ariadne, group: Group, sender: Member, img: ElementResult, source: Source):
    await app.send_group_message(group, MessageChain("正在搜索，请稍后"), quote=source.id)
    # 获取搜索的图片地址
    img: Image = img.result
    img_url = img.url
    # 使用方法搜索
    scrape_index_tasks = [asyncio.ensure_future(fun_tracemoe(img_url)), ]
    tasks = asyncio.gather(*scrape_index_tasks, return_exceptions=False)
    await tasks
    fwd_nodeList = [
        ForwardNode(
            target=sender,
            time=datetime.now(),
            message=item.result()
        ) for item in scrape_index_tasks if item
    ]
    try:
        bot_msg = await app.send_message(group, MessageChain(Forward(nodeList=fwd_nodeList)))
        if bot_msg.id < 0:
            raise Exception("消息风控!")
    except Exception as e:
        logger.warning(e)
        return await app.send_message(group, MessageChain(At(sender.id), "ERROR:工口发生~"), quote=source)
    return await app.send_message(group, MessageChain(At(sender.id), "请点击转发信息查看!"))


# 指令和图片分开
@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level),
    Permission.user_require(Permission.User, if_noticed=True),
)
@dispatch(
    Twilight(
        FullMatch("-搜番").space(SpacePolicy.PRESERVE),
    )
)
async def souFan_waiter(app: Ariadne, group: Group, sender: Member, source: Source):
    await app.send_message(group, MessageChain('请在30秒内发送要搜索的图片!'), quote=source)

    try:
        result: Image = await asyncio.wait_for(InterruptControl(create(Broadcast)).wait(ImageWaiter(group, sender)), 30)
    except asyncio.exceptions.TimeoutError:
        return await app.send_message(group, MessageChain('操作超时,已自动退出!'), quote=source)

    if result:
        await app.send_message(group, MessageChain('搜索ing'), quote=source)
    else:
        return await app.send_message(
            group, MessageChain('未识别到图片,已自动退出!'), quote=source
        )
    # 获取搜索的图片地址
    img_url = result.url
    # 使用方法搜索
    scrape_index_tasks = [
        asyncio.ensure_future(fun_tracemoe(img_url)),
    ]
    tasks = asyncio.gather(*scrape_index_tasks, return_exceptions=False)
    await tasks
    fwd_nodeList = [
        ForwardNode(
            target=sender,
            time=datetime.now(),
            message=item.result()
        ) for item in scrape_index_tasks if item
    ]
    bot_msg = await app.send_message(group, MessageChain(Forward(nodeList=fwd_nodeList)))
    if bot_msg.id < 0:
        return await app.send_message(group, MessageChain(At(sender.id), "错误!可能消息内容被控!"), quote=source)
    return await app.send_message(group, MessageChain(At(sender.id), "请点击转发信息查看!"))


async def fun_saucenao(file_url: str) -> MessageChain | None:
    if not global_config.functions.get("image_search", {}).get("saucenao_key"):
        return MessageChain("未填写saucenao_apikey")
    async with Network() as client:
        # saucenao搜图
        api_key = global_config.functions.get("image_search", {}).get("saucenao_key")
        saucenao = SauceNAO(client=client, api_key=api_key)
        try:
            resp = await saucenao.search(url=file_url)
        except Exception as e:
            logger.warning(e)
            return None
        if len(resp.raw) == 0:
            return None
        else:
            return MessageChain(
                f"saucenao结果:\n"
                f"相似度: {resp.raw[0].similarity}\n"
                f"标题: {resp.raw[0].title}\n"
                f"地址:{resp.raw[0].url}\n"
                f"作者: {resp.raw[0].author}\n"
                f"作者地址: {resp.raw[0].author_url}\n"
                f"缩略图:\n", Image(url=resp.raw[0].thumbnail)
            )


async def fun_tracemoe(file_url: str) -> MessageChain | None:
    # tracemoe搜番
    async with Network() as client:
        tracemoe = TraceMoe(client=client, mute=False, size=None)
        try:
            resp = await tracemoe.search(url=file_url)
        except Exception as e:
            logger.error(e)
            return MessageChain("tracemoe搜索出错!")
        if len(resp.raw) == 0:
            return None
        else:
            return MessageChain(
                f"tracemoe结果:\n"
                f"搜索的帧总数: {resp.frameCount}\n"
                f"匹配的anilistID: {resp.raw[0].anilist}\n"
                f"匹配的MyAnimelistID: {resp.raw[0].idMal}\n"
                f"番剧国际名字: {resp.raw[0].title_native}\n"
                f"番剧罗马音名字: {resp.raw[0].title_romaji}\n"
                f"番剧英文名字: {resp.raw[0].title_english}\n"
                f"备用英文标题: {resp.raw[0].synonyms}\n"
                f"番剧中文名字: {resp.raw[0].title_chinese}\n"
                f"是否R18: {resp.raw[0].isAdult}\n"
                f"找到匹配项的文件名: {resp.raw[0].filename}\n"
                f"估计的匹配的番剧的集数: {resp.raw[0].episode}\n"
                f"匹配场景的开始时间: {resp.raw[0].From}\n"
                f"匹配场景的结束时间: {resp.raw[0].To}\n"
                f"相似度: {resp.raw[0].similarity}\n"
                f"预览视频地址: {resp.raw[0].video}\n"
                f"缩略图:\n",
                Image(url=resp.raw[0].image),
            )


async def fun_ascii2d(file_url: str) -> MessageChain | None:
    # ascii2d搜图
    async with Network() as client:
        bovw = True  # 是否使用特征检索
        ascii2d = Ascii2D(client=client, bovw=bovw)
        try:
            resp = await ascii2d.search(url=file_url)
        except Exception as e:
            logger.error(e)
            return MessageChain("ascii2d搜索出错!")
        if len(resp.raw) == 0:
            return None
        else:
            return MessageChain(
                f"ascii2d结果:\n"
                f"标题: {resp.raw[0].title}\n"
                f"作者: {resp.raw[0].author}\n"
                f"作者地址: {resp.raw[0].author_url}\n"
                f"作品地址: {resp.raw[0].url}\n"
                f"原图长宽，类型，大小: {resp.raw[0].detail}\n"
                f"缩略图:\n", Image(url=resp.raw[0].thumbnail)
            )


async def fun_iqdb(file_url: str) -> MessageChain | None:
    # iqdb搜图
    async with Network() as client:
        iqdb = Iqdb(client=client)
        try:
            resp = await iqdb.search(url=file_url)
        except Exception as e:
            logger.error(e)
            return MessageChain("iqdb搜索出错!")
        if len(resp.raw) == 0:
            return None
        try:
            return MessageChain(
                f"iqdb结果:\n"
                f"说明: {resp.raw[0].content}\n"
                f"来源地址: {resp.raw[0].url}\n"
                f"相似度: {resp.raw[0].similarity}\n"
                f"图片大小: {resp.raw[0].size}\n"
                f"图片来源: {resp.raw[0].source}\n"
                f"其他图片来源: {resp.raw[0].other_source}\n"
                f"SauceNAO搜图链接: {resp.saucenao_url}\n"
                f"Ascii2d搜图链接: {resp.ascii2d_url}\n"
                f"TinEye搜图链接: {resp.tineye_url}\n"
                f"Google搜图链接: {resp.google_url}\n"
                f"相似度低的结果个数: {len(resp.more)}\n"
                f"缩略图:\n", Image(url=resp.raw[0].thumbnail)
            )
        except Exception as e:
            logger.error(e)
            return None


async def fun_google(file_url: str) -> MessageChain | None:
    # google搜图
    async with Network() as client:
        google = Google(client=client)
        try:
            resp = await google.search(url=file_url)
        except Exception as e:
            logger.error(e)
            return MessageChain("google搜索出错!")
        if len(resp.raw) == 0:
            return None
        try:
            return MessageChain(
                f"google结果:\n"
                f"当前页: {resp.page_number}\n"
                f"标题: {resp.raw[0].title}\n"
                f"地址: {resp.raw[0].url}\n"
                f"总页数: {len(resp.pages)}\n"
                f"缩略图:{resp.raw[0].thumbnail}",
            )
        except Exception as e:
            logger.error(e)
            return None


async def fun_ehentai(file_url: str) -> MessageChain | None:
    # ehentai搜图
    async with Network() as client:
        # cookies = None  # 注意：如果要使用 EXHentai 搜索，需要提供 cookies
        # ex = False  # 是否使用 EXHentai 搜索
        ehentai = EHentai(client=client)
        try:
            resp = await ehentai.search(url=file_url)
        except Exception as e:
            logger.error(e)
            return MessageChain("ehentai搜索出错!")
        if len(resp.raw) == 0:
            return MessageChain(
                f"ehentai结果:\n"
                f"未搜索到!"
            )
        try:
            return MessageChain(
                f"ehentai结果:\n"
                f"搜索结果链接: {resp.url}\n"
                f"标题: {resp.raw[0].title}\n"
                f"地址: {resp.raw[0].url}\n"
                f"分类: {resp.raw[0].type}\n"
                f"日期: {resp.raw[0].date}\n"
                f"标签: {resp.raw[0].tags}\n"
                f"缩略图:\n", Image(url=resp.raw[0].thumbnail)
            )
        except Exception as e:
            logger.error(e)
            return None


async def fun_baidu(file_url: str) -> MessageChain | None:
    # baidu搜图
    async with Network() as client:
        baidu = BaiDu(client=client)
        try:
            resp = await baidu.search(url=file_url)
        except Exception as e:
            logger.error(e)
            return MessageChain("baidu搜索出错!")
        if len(resp.raw) == 0:
            return MessageChain(
                f"baidu结果:\n"
                f"未搜索到!"
            )
        try:
            return MessageChain(
                f"baidu结果:\n"
                f"图片所在网页地址: {resp.raw[0].url}\n"
                f"缩略图:\n", Image(url=resp.raw[0].thumbnail)
            )
        except Exception as e:
            logger.error(e)
            return None
