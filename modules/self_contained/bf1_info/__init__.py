import re
import time
import uuid
from datetime import date, timedelta
from io import BytesIO
from pathlib import Path

import requests
import zhconv
from PIL import Image, ImageFont, ImageDraw
from bs4 import BeautifulSoup
from creart import create
from graia.ariadne.app import Ariadne
from graia.ariadne.event.message import GroupMessage
from graia.ariadne.event.mirai import NudgeEvent, MemberJoinEvent
from graia.ariadne.message.chain import MessageChain
from graia.ariadne.message.element import Image as GraiaImage, At, Source
from graia.ariadne.message.parser.twilight import (
    Twilight, FullMatch,
    ParamMatch, RegexResult,
    SpacePolicy, PRESERVE,
    UnionMatch
)
from graia.ariadne.model import Group, Member, MemberInfo
from graia.ariadne.util.interrupt import FunctionWaiter
from graia.ariadne.util.saya import listen, decorate, dispatch
from graia.saya import Channel, Saya
from graia.saya.event import SayaModuleInstalled
from graia.scheduler import timers
from graia.scheduler.saya import SchedulerSchema

from core.config import GlobalConfig
from core.control import (
    Permission,
    Function,
    FrequencyLimitation,
    Distribute,
    Config
)
from core.models import saya_model, response_model
from .choose_bg_pic import bg_pic
from .info_cache_manager import InfoCache, InfoCache_weapon, InfoCache_vehicle, InfoCache_stat
from .main_session_auto_refresh import auto_refresh_account
from .record_counter import record
from .utils import *

module_controller = saya_model.get_module_controller()
account_controller = response_model.get_acc_controller()
global_config = create(GlobalConfig)
saya = Saya.current()
# 获取属于这个模组的实例
channel = Channel.current()
channel.name("BF1战绩")
channel.description("战地1战绩功能")
channel.author("13")
channel.metadata = module_controller.get_metadata_from_path(Path(__file__))

bf_aip_url = 'https://sparta-gw.battlelog.com/jsonrpc/pc/api'
bf_aip_header = {
    "User-Agent": "ProtoHttp 1.3/DS 15.1.2.1.0 (Windows)",
    "X-ClientVersion": "release-bf1-lsu35_26385_ad7bf56a_tunguska_all_prod",
    "X-DbId": "Tunguska.Shipping2PC.Win32",
    "X-CodeCL": "3779779",
    "X-DataCL": "3779779",
    "X-SaveGameVersion": "26",
    "X-HostingGameId": "tunguska",
    "X-Sparta-Info": "tenancyRootEnv = unknown;tenancyBlazeEnv = unknown",
    "Connection": "keep-alive",
}

true = True
false = False
null = ''

access_token = None
access_token_time = None
access_token_expires_time = 0
pid_temp_dict = {}
default_account = global_config.functions.get("bf1").get("default_account", 0)
limits = httpx.Limits(max_keepalive_connections=None, max_connections=None)
client = httpx.AsyncClient(limits=limits)
if not os.path.exists(f"./data/battlefield/managerAccount/{default_account}/account.json") or \
        os.path.getsize(f"./data/battlefield/managerAccount/{default_account}/account.json") == 0:
    logger.error(f"bf1默认查询账号cookie未设置请先检查信息,配置路径:./data/battlefield/managerAccount/{default_account}/account.json")


# 根据玩家名字查找pid
async def getPid_byName(player_name: str) -> dict:
    """
    通过玩家的名字来获得pid
    :param player_name: 玩家姓名
    :return: pid-dict
    """
    global access_token, access_token_time, client, access_token_expires_time
    time_start = time.time()
    if access_token is None or (time.time() - access_token_time) >= int(access_token_expires_time):
        logger.info(f"获取token中")
        # 获取token
        with open(f"./data/battlefield/managerAccount/{default_account}/account.json", 'r',
                  encoding='utf-8') as file_temp1:
            data_temp = json.load(file_temp1)
            remid = data_temp["remid"]
            sid = data_temp["sid"]
        cookie = f'remid={remid}; sid={sid}'
        url = 'https://accounts.ea.com/connect/auth?response_type=token&locale=zh_CN&client_id=ORIGIN_JS_SDK&redirect_uri=nucleus%3Arest'
        header = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/86.0.4240.193 Safari/537.36',
            "Connection": "keep-alive",
            'ContentType': 'application/json',
            'Cookie': cookie
        }
        # async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=header, timeout=5)
        token = eval(response.text)["access_token"]
        access_token = token
        access_token_time = time.time()
        access_token_expires_time = eval(response.text)["expires_in"]
        logger.warning(f"token有效时间:{access_token_expires_time}")
    else:
        token = access_token

    # ea-api获取pid
    url = f"https://gateway.ea.com/proxy/identity/personas?namespaceName=cem_ea_id&displayName={player_name}"
    # 头部信息
    head = {
        "Host": "gateway.ea.com",
        "Connection": "keep-alive",
        "Accept": "application/json",
        "X-Expand-Results": "true",
        "Authorization": f"Bearer {token}",
        "Accept-Encoding": "deflate"
    }
    # async with httpx.AsyncClient() as client:
    response = await client.get(url, headers=head, timeout=5)
    response = response.text
    logger.info(f"获取pid耗时:{time.time() - time_start}")
    return eval(response)


# 生成并返回一个uuid
async def get_a_uuid() -> str:
    uuid_result = str(uuid.uuid4())
    return uuid_result


# 获取武器数据
async def get_weapon_data(player_pid: str) -> dict:
    global bf_aip_header, bf_aip_url, client
    session = await record.get_session()
    bf_aip_header["X-Gatewaysession"] = session
    body = {
        "jsonrpc": "2.0",
        "method": "Progression.getWeaponsByPersonaId",
        "params": {
            "game": "tunguska",
            "personaId": str(player_pid)
        },
        "id": "79c1df6e-0616-48a9-96b3-71dd3502c6cd"
    }
    # async with httpx.AsyncClient() as client:
    response = await client.post(bf_aip_url, headers=bf_aip_header, data=json.dumps(body), timeout=5)
    response = eval(response.text)
    return response


# 获取载具数据
async def get_vehicle_data(player_pid: str) -> dict:
    global bf_aip_header, bf_aip_url, client
    session = await record.get_session()
    bf_aip_header["X-Gatewaysession"] = session
    body = {
        "jsonrpc": "2.0",
        "method": "Progression.getVehiclesByPersonaId",
        "params": {
            "game": "tunguska",
            "personaId": str(player_pid)
        },
        "id": await get_a_uuid()
    }
    # async with httpx.AsyncClient() as client:
    response = await client.post(bf_aip_url, headers=bf_aip_header, data=json.dumps(body), timeout=5)
    response = eval(response.text)
    return response


# 获取玩家战报
async def get_player_stat_data(player_pid: str) -> dict:
    global bf_aip_header, bf_aip_url, client
    session = await record.get_session()
    bf_aip_header["X-Gatewaysession"] = session
    body = {
        "jsonrpc": "2.0",
        "method": "Stats.detailedStatsByPersonaId",
        "params": {
            "game": "tunguska",
            "personaId": str(player_pid)
        },
        "id": await get_a_uuid()
    }
    # async with httpx.AsyncClient() as client:
    response = await client.post(bf_aip_url, headers=bf_aip_header, data=json.dumps(body), timeout=5)
    response = eval(response.text)
    return response


# 获取玩家最近游玩服务器
async def get_player_recentServers(player_pid: str) -> dict:
    global bf_aip_header, bf_aip_url, client
    session = await record.get_session()
    bf_aip_header["X-Gatewaysession"] = session
    body = {
        "jsonrpc": "2.0",
        "method": "ServerHistory.mostRecentServers",
        "params": {
            "game": "tunguska",
            "personaId": str(player_pid)
        },
        "id": await get_a_uuid()
    }
    # async with httpx.AsyncClient() as client:
    response = await client.post(bf_aip_url, headers=bf_aip_header, data=json.dumps(body), timeout=5)
    response = eval(response.text)
    return response


# 获取玩家正在游玩的服务器
async def server_playing(player_pid: str) -> str:
    global bf_aip_header, bf_aip_url, client
    session = await record.get_session()
    bf_aip_header["X-Gatewaysession"] = session
    body = {
        "jsonrpc": "2.0",
        "method": "GameServer.getServersByPersonaIds",
        "params":
            {
                "game": "tunguska",
                # pid数组形式
                "personaIds": [player_pid]
            },
        "id": await get_a_uuid()
    }
    # noinspection PyBroadException
    try:
        # async with httpx.AsyncClient() as client:
        response = await client.post(bf_aip_url, headers=bf_aip_header, data=json.dumps(body), timeout=5)
        response = response.text
        # print(response)
        result = eval(response)["result"]
        if type(result["%s" % player_pid]) == str:
            return "玩家未在线/未进入服务器游玩"
        else:
            return result["%s" % player_pid]
    except Exception as e:
        logger.error(e)
        return "获取失败!"


# 获取皮肤列表
async def FullInventory():
    global bf_aip_header, bf_aip_url, client
    session = await record.get_session()
    bf_aip_header["X-Gatewaysession"] = session
    body = {
        "jsonrpc": "2.0",
        "method": "Battlepack.listFullInventory",
        "params": {
            "game": "tunguska",
        },
        "id": await get_a_uuid()
    }
    # async with httpx.AsyncClient() as client:
    response = await client.post(bf_aip_url, headers=bf_aip_header, data=json.dumps(body), timeout=5)
    response = response.text
    return response


# 启动时自动获取token
@listen(SayaModuleInstalled)
async def init_token(event: SayaModuleInstalled):
    if event.channel == channel:
        logger.info(f"初始化token中")
        try:
            await getPid_byName("shlsan13")
            logger.success(f"初始化token成功")
        except:
            logger.error(f"初始化token失败")


# TODO 1.绑定
@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Permission.user_require(Permission.User, if_noticed=True),
    Permission.group_require(channel.metadata.level),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module)
)
@dispatch(
    Twilight([
        "action" @ UnionMatch("-绑定").space(SpacePolicy.PRESERVE),
        "player_name" @ ParamMatch(optional=True).space(PRESERVE)
    ])
)
async def Bind(app: Ariadne, sender: Member, group: Group, player_name: RegexResult,
               source: Source):
    if player_name.result is None:
        await app.send_message(group, MessageChain(
            "你不告诉我游戏名字绑啥呢\n示例:-绑定<你的游戏名字>"
        ), quote=source)
        return False
    player_name = str(player_name.result).replace("+", "").replace(" ", "").replace("<", "").replace(">", "")
    # noinspection PyBroadException
    try:
        player_info = await getPid_byName(player_name)
    except Exception as e:
        logger.error(e)
        await app.send_message(group, MessageChain(
            f"网络出错，请稍后再试"
        ), quote=source)
        return False
    if player_info['personas'] == {}:
        await app.send_message(group, MessageChain(
            f"玩家[{player_name}]不存在"
        ), quote=source)
        return False
    # 创建配置文件
    await record.config_bind(sender.id)
    # 写入绑定信息
    with open(f"./data/battlefield/binds/players/{sender.id}/bind.json", 'w', encoding='utf-8') as file_temp1:
        json.dump(player_info, file_temp1, indent=4)
        await app.send_message(group, MessageChain(
            f"绑定成功!你的信息如下:\n"
            # f"pidId:{player_info['personas']['persona'][0]['pidId']}\n"
            f"Name:{player_info['personas']['persona'][0]['displayName']}\nId:{player_info['personas']['persona'][0]['personaId']}\nuid:{player_info['personas']['persona'][0]['pidId']}"
            # f"name:{player_info['personas']['persona'][0]['name']}"
        ), quote=source)
        # 调用战地查询计数器，绑定记录增加
        await record.bind_counter(sender.id,
                                  f"{player_info['personas']['persona'][0]['pidId']}-{player_info['personas']['persona'][0]['displayName']}")
        # 初始化玩家数据
        scrape_index_tasks = [
            # asyncio.ensure_future(get_player_stat_data(str(player_pid))),
            # asyncio.ensure_future(get_weapon_data(str(player_pid))),
            # asyncio.ensure_future(get_vehicle_data(str(player_pid)))
            asyncio.ensure_future(InfoCache_stat(str(player_info['personas']['persona'][0]['personaId'])).get_data()),
            asyncio.ensure_future(InfoCache_weapon(str(player_info['personas']['persona'][0]['personaId'])).get_data()),
            asyncio.ensure_future(InfoCache_vehicle(str(player_info['personas']['persona'][0]['personaId'])).get_data())
        ]
        # noinspection PyBroadException
        try:
            tasks = asyncio.gather(*scrape_index_tasks)
            await tasks
        except Exception as e:
            logger.error(e)


# TODO 注册背景
@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Permission.user_require(Permission.BotAdmin),
    Permission.group_require(channel.metadata.level),
    FrequencyLimitation.require(channel.module),
)
@dispatch(
    Twilight([
        "action" @ UnionMatch(
            "-注册背景"
        ).space(SpacePolicy.FORCE),
        "qq" @ ParamMatch(optional=False).space(SpacePolicy.FORCE),
        "player_pid" @ ParamMatch(optional=False).space(SpacePolicy.FORCE),
        "bg_num" @ ParamMatch(optional=False).space(SpacePolicy.FORCE),
        "bg_date" @ ParamMatch(optional=False).space(SpacePolicy.PRESERVE),
        # 示例:-注册背景 1247661006
    ])
)
async def bg_reg(app: Ariadne, group: Group, qq: RegexResult, player_pid: RegexResult,
                 bg_num: RegexResult, bg_date: RegexResult, source: Source):
    qq = int(qq.result.display)
    player_pid = int(player_pid.result.display)
    bg_num = int(bg_num.result.display)
    if int(bg_date.result.display) != 0:
        bg_date = int(bg_date.result.display) * 24 * 3600 + time.time()
    else:
        bg_date = 0
    result = bg_pic.register_bg(qq, player_pid, bg_num, bg_date)
    await app.send_message(group, MessageChain(
        result
    ), quote=source)


# 注销背景
@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Permission.user_require(Permission.BotAdmin),
    Permission.group_require(channel.metadata.level),
    FrequencyLimitation.require(channel.module),
)
@dispatch(
    Twilight([
        "action" @ UnionMatch(
            "-注销背景"
        ).space(SpacePolicy.FORCE),
        "player_pid" @ ParamMatch(optional=False).space(SpacePolicy.PRESERVE)
        # 示例:-注销背景 xxx
    ])
)
async def bg_unrg(app: Ariadne, group: Group, player_pid: RegexResult, source: Source):
    player_pid = player_pid.result.display
    result = bg_pic.cancellation_bg(player_pid)
    await app.send_message(group, MessageChain(
        result
    ), quote=source)


# 删除背景
@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Permission.user_require(Permission.User),
    Permission.group_require(channel.metadata.level),
    FrequencyLimitation.require(channel.module),
)
@dispatch(
    Twilight([
        "action" @ UnionMatch(
            "-删除背景"
        ).space(SpacePolicy.PRESERVE),
        "bg_rank" @ ParamMatch(optional=False).space(SpacePolicy.PRESERVE),
        # 示例:-修改背景 1
    ])
)
async def bg_del(app: Ariadne, group: Group, sender: Member, bg_rank: RegexResult,
                 source: Source):
    # noinspection PyBroadException
    try:
        bg_rank = int(bg_rank.result.display)
        if bg_rank <= 0:
            await app.send_message(group, MessageChain(
                f"背景序号需要>=1"
            ), quote=source)
            return
    except Exception as e:
        logger.warning(e)
        await app.send_message(group, MessageChain(
            f"背景序号需要>=1"
        ), quote=source)
        return
    if not record.check_bind(sender.id):
        await app.send_message(group, MessageChain(
            f"请先使用'-绑定+你的游戏名字'进行绑定\n例如:-绑定shlsan13"
        ), quote=source)
        return
    else:
        # noinspection PyBroadException
        try:
            player_pid = await record.get_bind_pid(sender.id)
            # player_name = record.get_bind_name(sender.id)
        except Exception as e:
            logger.error(e)
            await app.send_message(group, MessageChain(
                "绑定信息出错,请重新绑定!"
            ), quote=source)
            return
    bg_path = f'./data/battlefield/players/{player_pid}/bg'
    if not os.path.exists(bg_path):
        await app.send_message(group, MessageChain(
            f"请联系管理员创建背景吧~"
        ), quote=source)
        return
    if not bg_pic.check_date(player_pid):
        await app.send_message(group, MessageChain(
            f"背景已到期~"
        ), quote=source)
        return
    if bg_pic.check_bg_rank(player_pid, bg_rank):
        await app.send_message(group, MessageChain(
            bg_pic.check_bg_rank(player_pid, bg_rank)
        ), quote=source)
        return
    if not bg_pic.check_qq_pid(player_pid, sender.id):
        await app.send_message(group, MessageChain(
            f"无法修改他人的背景哦~"
        ), quote=source)
        return
    file_path = f"{bg_path}/{bg_rank}.png"
    if os.path.exists(file_path):
        try:
            os.remove(file_path)
            await app.send_message(group, MessageChain(
                f"删除背景{bg_rank}成功~"
            ), quote=source)
            return
        except Exception as e:
            await app.send_message(group, MessageChain(
                f"删除背景{bg_rank}失败:{e}"
            ), quote=source)
            return
    else:
        await app.send_message(group, MessageChain(
            f"背景{bg_rank}不存在哦~"
        ), quote=source)
        return

    # 修改背景


@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Permission.user_require(Permission.User),
    Permission.group_require(channel.metadata.level),
    FrequencyLimitation.require(channel.module),
)
@dispatch(
    Twilight(
        [
            "action" @ UnionMatch(
                "-修改背景"
            ).space(SpacePolicy.PRESERVE),
            "bg_rank" @ ParamMatch(optional=False).space(SpacePolicy.PRESERVE)
        ]
        # 示例:-修改背景 1
    )
)
async def bg_change(app: Ariadne, group: Group, sender: Member, bg_rank: RegexResult,
                    source: Source):
    # noinspection PyBroadException
    try:
        bg_rank = int(bg_rank.result.display)
        if bg_rank <= 0:
            await app.send_message(group, MessageChain(
                f"背景序号需要>=1"
            ), quote=source)
            return
    except Exception as e:
        logger.warning(e)
        await app.send_message(group, MessageChain(
            f"背景序号需要>=1"
        ), quote=source)
        return
    if not record.check_bind(sender.id):
        await app.send_message(group, MessageChain(
            f"请先使用'-绑定+你的游戏名字'进行绑定\n例如:-绑定shlsan13"
        ), quote=source)
        return
    else:
        # noinspection PyBroadException
        try:
            player_pid = await record.get_bind_pid(sender.id)
            # player_name = record.get_bind_name(sender.id)
        except Exception as e:
            logger.error(e)
            await app.send_message(group, MessageChain(
                "绑定信息出错,请重新绑定!"
            ), quote=source)
            return
    bg_path = f'./data/battlefield/players/{player_pid}/bg'
    if not os.path.exists(bg_path):
        await app.send_message(group, MessageChain(
            f"请联系管理员创建背景吧~"
        ), quote=source)
        return
    if not bg_pic.check_date(player_pid):
        await app.send_message(group, MessageChain(
            f"背景已到期~"
        ), quote=source)
        return
    if bg_pic.check_bg_rank(player_pid, bg_rank):
        await app.send_message(group, MessageChain(
            bg_pic.check_bg_rank(player_pid, bg_rank)
        ), quote=source)
        return
    if not bg_pic.check_qq_pid(player_pid, sender.id):
        await app.send_message(group, MessageChain(
            f"无法修改他人的背景哦~"
        ), quote=source)
        return
    await app.send_message(group, MessageChain(
        f"请在30秒内发送你要上传的背景~"
    ), quote=source)

    async def waiter_report_pic(waiter_member: Member, waiter_message: MessageChain, waiter_group: Group):
        if group.id == waiter_group.id and waiter_member.id == sender.id:
            say = waiter_message.display.replace(f"{At(app.account)} ", '')
            if say == '[图片]':
                return True, waiter_message
            else:
                return False, waiter_message

    try:
        result, img = await FunctionWaiter(waiter_report_pic, [GroupMessage], block_propagation=True).wait(
            timeout=30)
    except asyncio.exceptions.TimeoutError:
        await app.send_message(group, MessageChain(
            f'操作超时,已自动退出!'), quote=source)
        return

    if result:
        # 如果是图片则下载
        if img.display == '[图片]':
            try:
                img: MessageChain
                img_url: GraiaImage = img[GraiaImage][0]
                img_url = img_url.url
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_3) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/85.0.4183.102 Safari/537.36'
                }
                # noinspection PyBroadException
                try:
                    # async with httpx.AsyncClient() as client:
                    response = await client.get(img_url, headers=headers, timeout=5)
                    r = response
                except Exception as e:
                    logger.error(e)
                    await app.send_message(group, MessageChain(
                        f'获取图片出错,请重新举报!'
                    ), quote=source)
                    return False
                # wb 以二进制打开文件并写入，文件名不存在会创
                file_path = f'./data/battlefield/players/{player_pid}/bg/{bg_rank}.png'
                with open(file_path, 'wb') as f:
                    f.write(r.content)  # 写入二进制内容
                    f.close()
            except Exception as e:
                logger.error(e)
                await app.send_message(group, MessageChain(
                    f'获取图片失败,请重新修改!'
                ), quote=source)
                return False
        await app.send_message(group, MessageChain(
            f"接收到图片,修改成功!"
        ), quote=source)
    else:
        await app.send_message(group, MessageChain(
            f'未识成功别到图片,请重新修改!'
        ), quote=source)


@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Permission.user_require(Permission.User),
    Permission.group_require(channel.metadata.level),
    FrequencyLimitation.require(channel.module),
)
@dispatch(
    Twilight(
        [
            "action" @ UnionMatch(
                "-我的背景"
            ).space(SpacePolicy.PRESERVE)
        ]
        # 示例:-我的背景
    )
)
async def bg_check(app: Ariadne, group: Group, sender: Member, source: Source):
    if not record.check_bind(sender.id):
        await app.send_message(group, MessageChain(
            f"请先使用'-绑定+你的游戏名字'进行绑定\n例如:-绑定shlsan13"
        ), quote=source)
        return
    else:
        # noinspection PyBroadException
        try:
            player_pid = await record.get_bind_pid(sender.id)
            # player_name = record.get_bind_name(sender.id)
        except Exception as e:
            logger.error(e)
            await app.send_message(group, MessageChain(
                "绑定信息出错,请重新绑定!"
            ), quote=source)
            return
    bg_path = f'./data/battlefield/players/{player_pid}/bg'
    if not os.path.exists(bg_path):
        await app.send_message(group, MessageChain(
            f"你还没有拥有背景,请在爱发电查看详情哦:https://afdian.net/a/ss1333"
        ), quote=source)
        return
    if not bg_pic.check_date(player_pid):
        await app.send_message(group, MessageChain(
            f"背景已到期~"
        ), quote=source)
        return
    if not bg_pic.check_qq_pid(player_pid, sender.id):
        await app.send_message(group, MessageChain(
            f"无法查看他人的背景哦~"
        ), quote=source)
        return
    bg_list = os.listdir(bg_path)
    if len(bg_list) != 0:
        temp = Image.new("RGB", (1080 * len(bg_list), 2729))
        draw = ImageDraw.Draw(temp)
        title_font = ImageFont.truetype('./data/battlefield/font/BFText-Regular-SC-19cf572c.ttf', 120)
        for i, bg_item in enumerate(bg_list):
            bg_img = Image.open(f'./data/battlefield/players/{player_pid}/bg/{bg_item}')
            width, height = bg_img.size
            if not (width == 1080 and height == 2729):
                b1 = width / 1080
                b2 = height / 2729
                if b1 < 1 or b2 < 1:
                    倍数 = 1 / b1 if 1 / b1 > 1 / b2 else 1 / b2
                else:
                    倍数 = b1 if b1 < b2 else b2
                # 放大图片
                bg_img = bg_img.resize((int(width * 倍数) + 1, int(height * 倍数) + 1), Image.ANTIALIAS)
                # 裁剪到中心位置
                width, height = bg_img.size
                left = (width - 1080) / 2
                top = (height - 2729) / 2
                right = (width + 1080) / 2
                bottom = (height + 2729) / 2
                bg_img = bg_img.crop((left, top, right, bottom))
            width, height = bg_img.size
            temp.paste(bg_img, (width * i + 1, 0))
            # 背景第几张
            draw.text((width * i + 20, 20), f"{bg_item.replace('.png', '')}", font=title_font, fill=(255, 132, 0))
        temp = temp.convert('RGB')
        bytes_io = BytesIO()
        temp.save(bytes_io, "JPEG")
        message_send = MessageChain(
            f"你当前有{len(bg_list)}张背景:\n",
            GraiaImage(data_bytes=bytes_io.getvalue())
        )
        await app.send_message(group, message_send, quote=source)
        return
    message_send = MessageChain(
        f"你当前没有背景哦~快用'-修改背景 n'来修改吧"
    )
    await app.send_message(group, message_send, quote=source)


# TODO 2:武器
@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Permission.user_require(Permission.User),
    Permission.group_require(channel.metadata.level),
    FrequencyLimitation.require(channel.module),
    Function.require(channel.module),
)
@dispatch(
    Twilight(
        [
            "weapon_type" @ UnionMatch(
                "-武器", "-精英兵", "-轻机枪", "-机枪", "-近战", "-步枪", "-装备", "-配备",
                "-半自动", "-手榴弹", "-手雷", "-霰弹枪", "-驾驶员", "-冲锋枪", "-佩枪",
                "-手枪", "-副武器", "-weapon"
            ).space(SpacePolicy.PRESERVE),
            "player_name" @ ParamMatch(optional=True).space(PRESERVE)
        ]
        # 示例:-武器 shlsan13
    )
)
async def weapon(app: Ariadne, sender: Member, group: Group, player_name: RegexResult,
                 weapon_type: RegexResult, source: Source):
    if player_name.matched:
        # 判断玩家名字存不存在
        player_name = str(player_name.result).replace("+", "").replace(" ", "")
        # noinspection PyBroadException
        try:
            player_info = await getPid_byName(player_name)
        except Exception as e:
            logger.error(e)
            await app.send_message(group, MessageChain(
                f"网络出错，请稍后再试"
            ), quote=source)
            return False
        if player_info['personas'] == {}:
            await app.send_message(group, MessageChain(
                f"玩家[{player_name}]不存在"
            ), quote=source)
            return False
        else:
            player_pid = player_info['personas']['persona'][0]['personaId']
            player_name = player_info['personas']['persona'][0]['displayName']
    else:
        # 检查绑定没有,没有绑定则终止，绑定了就读缓存的pid
        if not record.check_bind(sender.id):
            await app.send_message(group, MessageChain(
                f"请先使用'-绑定+你的游戏名字'进行绑定\n例如:-绑定shlsan13"
            ), quote=source)
            return False
        else:
            # noinspection PyBroadException
            try:
                player_pid = await record.get_bind_pid(sender.id)
                player_name = await record.get_bind_name(sender.id)
            except Exception as e:
                logger.error(e)
                await app.send_message(group, MessageChain(
                    # At(sender.id),
                    "绑定信息过期,请重新绑定!"
                ), quote=source)
                return
    await app.send_message(group, MessageChain(
        # At(sender.id),
        "查询ing"
    ), quote=source)
    start_time = time.time()
    # noinspection PyBroadException
    try:
        # noinspection PyBroadException
        try:
            weapon_data = await InfoCache_weapon(str(player_pid)).get_data()
        except Exception as e:
            logger.error(e)
            await InfoCache_weapon(str(player_pid)).update_cache()
            weapon_data = await InfoCache_weapon(str(player_pid)).get_data()
        item_temp = weapon_data["result"][11]["weapons"].pop()
        weapon_data["result"][11]["weapons"].pop()
        weapon_data["result"][3]["weapons"].append(item_temp)
        item_temp2 = weapon_data["result"][5]["weapons"].pop()
        weapon_data["result"][5]["weapons"].pop()
        weapon_data["result"][3]["weapons"].append(item_temp2)
        weapon_data = weapon_data["result"]
    except Exception as e:
        logger.error(e)
        await app.send_message(group, MessageChain(
            # At(sender.id),
            "网络出错请稍后再试!"
        ), quote=source)
        return False
    end_time = time.time()
    logger.info(f"接口耗时:{end_time - start_time}s")
    weapon_temp = {}
    start_time2 = time.time()
    if str(weapon_type.result) in ["-武器", "-weapon"]:
        for item in weapon_data:
            for item2 in item["weapons"]:
                if item2["stats"]["values"] != {}:
                    if item2["stats"]["values"]["kills"] != 0.0:
                        weapon_temp[zhconv.convert(item2["name"], 'zh-cn')] = [
                            int(item2["stats"]["values"]["kills"]),  # 击杀
                            "{:.2f}".format(
                                item2["stats"]["values"]["kills"] / item2["stats"]["values"]["seconds"] * 60) if
                            item2["stats"]["values"]["seconds"] != 0 else "0",  # kpm
                            "{:.2f}%".format(
                                item2["stats"]["values"]["hits"] / item2["stats"]["values"]["shots"] * 100) if
                            item2["stats"]["values"]["shots"] * 100 != 0 else "0",  # 命中率
                            "{:.2f}%".format(
                                item2["stats"]["values"]["headshots"] / item2["stats"]["values"]["kills"] * 100) if
                            item2["stats"]["values"]["kills"] != 0 else "0",  # 爆头率
                            "{:.2f}".format(item2["stats"]["values"]["hits"] / item2["stats"]["values"]["kills"]) if
                            item2["stats"]["values"]["kills"] != 0 else "0",  # 效率
                            "{:.0f}h".format(item2["stats"]["values"]["seconds"] / 3600),  # 游戏时长
                            item2["imageUrl"].replace("[BB_PREFIX]",
                                                      "https://eaassets-a.akamaihd.net/battlelog/battlebinary")
                        ]
    else:
        weapon_type_temp = int(str(weapon_type.result)
                               .replace("-精英兵", "0").replace("-轻机枪", "1").replace("-机枪", "1")
                               .replace("-近战", "2").replace("-步枪", "3").replace("-装备", "4").replace("-配备", "4")
                               .replace("-半自动", "5").replace("-手榴弹", "6").replace("-手雷", "6")
                               .replace("-霰弹枪", "8").replace("-驾驶员", "9").replace("-冲锋枪", "10")
                               .replace("-佩枪", "11").replace("-手枪", "11").replace("-副武器", "11"))
        for item2 in weapon_data[weapon_type_temp]["weapons"]:
            if item2["stats"]["values"] != {}:
                weapon_temp[zhconv.convert(item2["name"], 'zh-cn')] = [
                    int(item2["stats"]["values"]["kills"]),  # 击杀
                    "{:.2f}".format(item2["stats"]["values"]["kills"] / item2["stats"]["values"]["seconds"] * 60)
                    if item2["stats"]["values"]["seconds"] != 0
                    else "0",  # kpm
                    "{:.2f}%".format(item2["stats"]["values"]["hits"] / item2["stats"]["values"]["shots"] * 100)
                    if item2["stats"]["values"]["shots"] * 100 != 0
                    else "0",  # 命中率
                    "{:.2f}%".format(item2["stats"]["values"]["headshots"] / item2["stats"]["values"]["kills"] * 100)
                    if item2["stats"]["values"]["kills"] != 0
                    else "0",  # 爆头率
                    "{:.2f}".format(item2["stats"]["values"]["hits"] / item2["stats"]["values"]["kills"])
                    if item2["stats"]["values"]["kills"] != 0
                    else "0",  # 效率
                    "{:.1f}h".format(item2["stats"]["values"]["seconds"] / 3600),  # 游戏时长
                    item2["imageUrl"].replace("[BB_PREFIX]", "https://eaassets-a.akamaihd.net/battlelog/battlebinary")
                    # 图片url
                ]
    weapon_temp_sorted = sorted(weapon_temp.items(), key=lambda x: x[1][0], reverse=True)  # 得到元组列表
    # print(weapon_temp_sorted)
    weapon_list = weapon_temp_sorted[:4]
    weapon1 = []
    weapon2 = []
    weapon3 = []
    weapon4 = []
    weapon123 = [weapon1, weapon2, weapon3, weapon4]
    i = 0
    # noinspection PyBroadException
    try:
        while i <= 3:
            weapon_item = weapon123[i]
            weapon_item.append(weapon_list[i][0])
            weapon_item.append(weapon_list[i][1][0])
            weapon_item.append(weapon_list[i][1][1])
            weapon_item.append(weapon_list[i][1][2])
            weapon_item.append(weapon_list[i][1][3])
            weapon_item.append(weapon_list[i][1][4])
            weapon_item.append(weapon_list[i][1][6])
            weapon_item.append(weapon_list[i][1][5])
            i += 1
    except Exception as e:
        logger.error(e)
        await app.send_message(group, MessageChain(
            # At(sender.id),
            "数据不足!"
        ), quote=source)
        return False
    # 头像信息
    # noinspection PyBroadException
    html = None
    if os.path.exists(f"./data/battlefield/players/{player_pid}/avatar.json"):
        try:
            with open(f"./data/battlefield/players/{player_pid}/avatar.json", 'r', encoding='utf-8') as file_temp1:
                html = json.load(file_temp1)
                if html is None:
                    raise Exception
                if "avatar" not in html:
                    raise Exception
        except Exception as e:
            logger.warning(f"未找到玩家{player_name}头像缓存,开始下载{e}")
    if html is None:
        # noinspection PyBroadException
        try:
            # async with httpx.AsyncClient() as client:
            response = await client.get(
                'https://api.gametools.network/bf1/player?name=' + str(player_name) + '&platform=pc', timeout=3)
            html = eval(response.text)
            if "avatar" not in html:
                raise Exception
            if not os.path.exists(f"./data/battlefield/players/{player_pid}"):
                os.makedirs(f"./data/battlefield/players/{player_pid}")
            with open(f"./data/battlefield/players/{player_pid}/avatar.json", 'w', encoding='utf-8') as file_temp1:
                json.dump(html, file_temp1, indent=4)
        except Exception as e:
            logger.error(e)
            # await app.send_message(group, MessageChain(
            #     # At(sender.id),
            #     "网络出错请稍后再试!"
            # ), quote=message[Source][0])
            html = {
                'avatar': "./data/battlefield/pic/avatar/play.jpg",
                'userName': player_name
            }
    end_time2 = time.time()
    logger.info(f'接口2耗时:{end_time2 - start_time2}')
    start_time3 = time.time()

    # 底图选择
    # bg_img = Image.open(await pic_custom(player_pid))
    bg_img = Image.open(bg_pic.choose_bg(player_pid, "weapon"))
    width, height = bg_img.size
    if not (width == 1080 and height == 2729):
        b1 = width / 1080
        b2 = height / 2729
        if b1 < 1 or b2 < 1:
            倍数 = 1 / b1 if 1 / b1 > 1 / b2 else 1 / b2
        else:
            倍数 = b1 if b1 < b2 else b2
        # 放大图片
        bg_img = bg_img.resize((int(width * 倍数) + 1, int(height * 倍数) + 1), Image.ANTIALIAS)
        # 裁剪到中心位置
        width, height = bg_img.size
        left = (width - 1080) / 2
        top = (height - 2729) / 2
        right = (width + 1080) / 2
        bottom = (height + 2729) / 2
        bg_img = bg_img.crop((left, top, right, bottom))
        底图 = Image.open(f"./data/battlefield/pic/bg/底图.png").convert('RGBA')
        bg_img.paste(底图, (0, 0), 底图)

    draw = ImageDraw.Draw(bg_img)
    # 字体路径
    font_path = './data/battlefield/font/BFText-Regular-SC-19cf572c.ttf'
    title_font = ImageFont.truetype(font_path, 50)
    star_font = ImageFont.truetype(font_path, 45)
    time_font = ImageFont.truetype(font_path, 25)
    name_font = ImageFont.truetype(font_path, 45)
    content_font = ImageFont.truetype(font_path, 40)
    # 玩家头像获取
    player_img = await playerPicDownload(html["avatar"], html["userName"])
    # 玩家头像打开
    avatar_img = Image.open(player_img).convert('RGBA')
    # 玩家头像拼接
    bg_img.paste(avatar_img, (64, 91))
    # 玩家ID拼接
    draw.text((300, 225), "ID:%s" % html["userName"], fill='white', font=title_font)
    # 时间拼接
    time_now = time.strftime("%Y/%m/%d-%H:%M", time.localtime(time.time()))
    draw.text((790, 260), time_now, fill='white', font=time_font)
    for i in range(4):
        # 间距 623
        # 武器图片获取
        pic_url = await PicDownload(weapon123[i][6])
        # 打开武器图像
        weapon_png = Image.open(pic_url).convert('RGBA')
        # 拉伸
        weapon_png = weapon_png.resize((588, 147))
        star = str(int(weapon123[i][1] / 100))
        weapons_star = "★"
        # tx_img = Image.open("")
        if weapon123[i][1] >= 10000:
            # 金色
            tx_img = Image.open("./data/battlefield/pic/tx/" + "1.png").convert(
                'RGBA')
            tx_img = tx_img.resize((267, 410))
            bg_img.paste(tx_img, (420, 290 + i * 580), tx_img)
            draw.text((179, 506 + i * 580), weapons_star, font=star_font, fill=(255, 132, 0))
            draw.text((233, 509 + i * 580), star, font=star_font, fill=(255, 132, 0))
        elif 6000 <= weapon123[i][1] < 10000:
            # 蓝色
            tx_img = Image.open("./data/battlefield/pic/tx/" + "2.png").convert(
                'RGBA')
            tx_img = tx_img.resize((267, 410))
            bg_img.paste(tx_img, (420, 290 + i * 580), tx_img)
            draw.text((179, 506 + i * 580), weapons_star, font=star_font, fill=(74, 151, 255))
            draw.text((233, 509 + i * 580), star, font=star_font, fill=(74, 151, 255))
        elif 4000 <= weapon123[i][1] < 6000:
            # 白色
            tx_img = Image.open("./data/battlefield/pic/tx/" + "3.png").convert(
                'RGBA')
            tx_img = tx_img.resize((267, 410))
            bg_img.paste(tx_img, (420, 290 + i * 580), tx_img)
            draw.text((179, 506 + i * 580), weapons_star, font=star_font)
            draw.text((233, 509 + i * 580), star, font=star_font)
        elif 0 <= weapon123[i][1] < 4000:
            draw.text((179, 506 + i * 580), weapons_star, font=star_font)
            draw.text((233, 509 + i * 580), star, font=star_font)
        # 武器图像拼接
        bg_img.paste(weapon_png, (250, 392 + i * 580), weapon_png)
        draw.text((210, 630 + i * 580), weapon123[i][0], font=name_font)
        draw.text((210, 730 + i * 580), "击杀:%d" % weapon123[i][1], font=content_font)
        draw.text((600, 730 + i * 580), "kpm:%s" % weapon123[i][2], font=content_font)
        draw.text((210, 780 + i * 580), "命中率:%s" % weapon123[i][3], font=content_font)
        draw.text((600, 780 + i * 580), "爆头率:%s" % weapon123[i][4], font=content_font)
        draw.text((210, 830 + i * 580), "效率:%s" % weapon123[i][5], font=content_font)
        draw.text((600, 830 + i * 580), "时长:%s" % weapon123[i][7], font=content_font)
    bg_img = bg_img.convert('RGB')
    end_time3 = time.time()
    logger.info(f'画图耗时:{end_time3 - start_time3}')
    logger.info(f"制图总耗时:{end_time3 - start_time}秒")

    start_time4 = time.time()
    bytes_io = BytesIO()
    bg_img.save(bytes_io, "JPEG")
    message_send = MessageChain(GraiaImage(data_bytes=bytes_io.getvalue()))

    # logger.info(message_send)
    await app.send_message(group, message_send, quote=source)
    end_time4 = time.time()
    logger.info(f"发送耗时:{end_time4 - start_time4}秒")
    if end_time4 - start_time4 > 60:
        await app.send_message(group, MessageChain(
            f"发送耗时:{int(end_time4 - start_time4)}秒,似乎被腾讯限制了呢"
        ), quote=source)
    # 武器计数器
    await record.weapon_counter(sender.id, str(player_pid), str(player_name), str(weapon_type.result))
    return True


# TODO 3:载具
@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Permission.user_require(Permission.User),
    Permission.group_require(channel.metadata.level),
    FrequencyLimitation.require(channel.module),
    Function.require(channel.module),
)
@dispatch(
    Twilight(
        [
            "vehicle_type" @ UnionMatch(
                "-载具", "-地面", "-陆地", "-空中", "-飞机", "-海上", "-海洋", "-定点", "-巨兽",
                "-vehicle"
            ).space(SpacePolicy.PRESERVE),
            "player_name" @ ParamMatch(optional=True).space(PRESERVE)
            # 示例:-载具 shlsan13
        ]
    )
)
async def vehicle(app: Ariadne, sender: Member, group: Group, player_name: RegexResult,
                  vehicle_type: RegexResult,
                  source: Source):
    if player_name.matched:
        # 判断玩家名字存不存在
        player_name = str(player_name.result).replace("+", "").replace(" ", "")
        # noinspection PyBroadException
        try:
            player_info = await getPid_byName(player_name)
        except Exception as e:
            logger.error(e)
            await app.send_message(group, MessageChain(
                f"网络出错，请稍后再试"
            ), quote=source)
            return False
        if player_info['personas'] == {}:
            await app.send_message(group, MessageChain(
                f"玩家[{player_name}]不存在"
            ), quote=source)
            return False
        else:
            player_pid = player_info['personas']['persona'][0]['personaId']
            player_name = player_info['personas']['persona'][0]['displayName']
    else:
        # 检查绑定没有,没有绑定则终止，绑定了就读缓存的pid
        if not record.check_bind(sender.id):
            await app.send_message(group, MessageChain(
                f"请先使用'-绑定+你的游戏名字'进行绑定\n例如:-绑定shlsan13"
            ), quote=source)
            return False
        else:
            # noinspection PyBroadException
            try:
                player_pid = await record.get_bind_pid(sender.id)
                player_name = await record.get_bind_name(sender.id)
            except Exception as e:
                logger.error(e)
                await app.send_message(group, MessageChain(
                    # At(sender.id),
                    "绑定信息过期,请重新绑定!"
                ), quote=source)
                return

    await app.send_message(group, MessageChain(
        # At(sender.id),
        "查询ing"
    ), quote=source)
    start_time = time.time()
    # noinspection PyBroadException
    try:
        # vehicle_data = await get_vehicle_data(str(player_pid))
        # vehicle_data = await InfoCache(str(player_pid), "vehicle").get_data()
        # noinspection PyBroadException
        try:
            vehicle_data = await InfoCache_vehicle(str(player_pid)).get_data()
        except Exception as e:
            logger.error(e)
            await InfoCache_vehicle(str(player_pid)).update_cache()
            vehicle_data = await InfoCache_vehicle(str(player_pid)).get_data()
        vehicle_data = vehicle_data["result"]
    except Exception as e:
        logger.error(e)
        await app.send_message(group, MessageChain(
            # At(sender.id),
            "网络出错请稍后再试!"
        ), quote=source)
        return False
    end_time = time.time()
    logger.info(f"接口耗时:{end_time - start_time}s")
    vehicle_temp = {}
    start_time2 = time.time()
    if str(vehicle_type.result) in ["-载具", "-vehicle"]:
        for item1 in vehicle_data:
            for item2 in item1["vehicles"]:
                vehicle_temp[zhconv.convert(item2["name"], 'zh-cn')] = [
                    int(item2["stats"]["values"]["kills"]),  # 击杀
                    "{:.2f}".format(item2["stats"]["values"]["kills"] / item2["stats"]["values"]["seconds"] * 60)
                    if item2["stats"]["values"]["seconds"] != 0 else "0",
                    # kpm
                    int(item2["stats"]["values"]["destroyed"]),  # 摧毁
                    "{:.2f}h".format(item2["stats"]["values"]["seconds"] / 3600),  # 时长
                    item2["imageUrl"].replace("[BB_PREFIX]", "https://eaassets-a.akamaihd.net/battlelog/battlebinary")
                    # 图片url
                ]
    else:
        vehicle_type_list = [["重型坦克", "巡航坦克", "輕型坦克", "火砲裝甲車", "攻擊坦克", "突擊裝甲車", "地面載具", "马匹"],
                             ["攻擊機", "轟炸機", "戰鬥機", "重型轟炸機", "飛船"],
                             ["船隻", "驅逐艦"],
                             ["定點武器"],
                             ["機械巨獸"]]
        if str(vehicle_type.result) in ["-地面", "-陆地"]:
            vehicle_type_list = vehicle_type_list[0]
        elif str(vehicle_type.result) in ["-空中", "-飞机"]:
            vehicle_type_list = vehicle_type_list[1]
        elif str(vehicle_type.result) in ["-海上", "-海洋"]:
            vehicle_type_list = vehicle_type_list[2]
        elif str(vehicle_type.result) in ["-定点"]:
            vehicle_type_list = vehicle_type_list[3]
        elif str(vehicle_type.result) in ["-巨兽"]:
            vehicle_type_list = vehicle_type_list[4]
        for item1 in vehicle_data:
            if item1["name"] in vehicle_type_list:
                for item2 in item1["vehicles"]:
                    vehicle_temp[zhconv.convert(item2["name"], 'zh-cn')] = [
                        int(item2["stats"]["values"]["kills"]),  # 击杀
                        "{:.2f}".format(
                            item2["stats"]["values"]["kills"] / item2["stats"]["values"]["seconds"] * 60) if
                        item2["stats"]["values"]["seconds"] != 0 else "0",
                        # kpm
                        int(item2["stats"]["values"]["destroyed"]),  # 摧毁
                        "{:.1f}h".format(item2["stats"]["values"]["seconds"] / 3600),  # 时长
                        item2["imageUrl"].replace("[BB_PREFIX]",
                                                  "https://eaassets-a.akamaihd.net/battlelog/battlebinary")  # 图片url
                    ]
                if vehicle_type_list == ["船隻", "驅逐艦"]:
                    item_temp = vehicle_data[15]["vehicles"][2]
                    vehicle_temp[zhconv.convert(item_temp["name"], 'zh-cn')] = [
                        int(item_temp["stats"]["values"]["kills"]),  # 击杀
                        "{:.2f}".format(
                            item_temp["stats"]["values"]["kills"] / item_temp["stats"]["values"]["seconds"] * 60) if
                        item_temp["stats"]["values"]["seconds"] != 0 else "0",
                        # kpm
                        int(item_temp["stats"]["values"]["destroyed"]),  # 摧毁
                        "{:.1f}h".format(item_temp["stats"]["values"]["seconds"] / 3600),  # 时长
                        item_temp["imageUrl"].replace("[BB_PREFIX]",
                                                      "https://eaassets-a.akamaihd.net/battlelog/battlebinary")
                        # 图片url
                    ]
    vehicle_temp_sorted = sorted(vehicle_temp.items(), key=lambda x: x[1][0], reverse=True)  # 得到元组列表
    # print(weapon_temp_sorted)
    vehicle_list = vehicle_temp_sorted[:4]
    vehicle1 = []
    vehicle2 = []
    vehicle3 = []
    vehicle4 = []
    vehicle123 = [vehicle1, vehicle2, vehicle3, vehicle4]
    i = 0
    while i <= 3:
        vehicle_temp = vehicle123[i]
        vehicle_temp.append(vehicle_list[i][0])
        vehicle_temp.append(vehicle_list[i][1][0])
        vehicle_temp.append(vehicle_list[i][1][1])
        vehicle_temp.append(vehicle_list[i][1][2])
        vehicle_temp.append(vehicle_list[i][1][3])
        vehicle_temp.append(vehicle_list[i][1][4])
        i += 1
    # 头像信息
    # noinspection PyBroadException
    html = None
    if os.path.exists(f"./data/battlefield/players/{player_pid}/avatar.json"):
        try:
            with open(f"./data/battlefield/players/{player_pid}/avatar.json", 'r', encoding='utf-8') as file_temp1:
                html = json.load(file_temp1)
                if html is None:
                    raise Exception
                if "avatar" not in html:
                    raise Exception
        except Exception as e:
            logger.warning(f"未找到玩家{player_name}头像缓存,开始下载{e}")
    if html is None:
        # noinspection PyBroadException
        try:
            # async with httpx.AsyncClient() as client:
            response = await client.get(
                'https://api.gametools.network/bf1/player?name=' + str(player_name) + '&platform=pc', timeout=3)
            html = eval(response.text)
            if "avatar" not in html:
                raise Exception
            if not os.path.exists(f"./data/battlefield/players/{player_pid}"):
                os.makedirs(f"./data/battlefield/players/{player_pid}")
            with open(f"./data/battlefield/players/{player_pid}/avatar.json", 'w', encoding='utf-8') as file_temp1:
                json.dump(html, file_temp1, indent=4)
        except Exception as e:
            logger.error(e)
            await app.send_message(group, MessageChain(
                # At(sender.id),
                "网络出错请稍后再试!"
            ), quote=source)
            return False
    end_time2 = time.time()
    logger.info(f'接口2耗时:{end_time2 - start_time2}')
    start_time3 = time.time()
    # 底图选择
    # bg_img = Image.open(await pic_custom(player_pid))
    bg_img = Image.open(bg_pic.choose_bg(player_pid, "weapon"))
    width, height = bg_img.size
    if not (width == 1080 and height == 2729):
        b1 = width / 1080
        b2 = height / 2729
        if b1 < 1 or b2 < 1:
            倍数 = 1 / b1 if 1 / b1 > 1 / b2 else 1 / b2
        else:
            倍数 = b1 if b1 < b2 else b2
        # 放大图片
        bg_img = bg_img.resize((int(width * 倍数) + 1, int(height * 倍数) + 1), Image.ANTIALIAS)
        # 裁剪到中心位置
        width, height = bg_img.size
        left = (width - 1080) / 2
        top = (height - 2729) / 2
        right = (width + 1080) / 2
        bottom = (height + 2729) / 2
        bg_img = bg_img.crop((left, top, right, bottom))
        底图 = Image.open(f"./data/battlefield/pic/bg/底图.png").convert('RGBA')
        bg_img.paste(底图, (0, 0), 底图)
    draw = ImageDraw.Draw(bg_img)
    # 字体路径
    font_path = './data/battlefield/font/BFText-Regular-SC-19cf572c.ttf'
    title_font = ImageFont.truetype(font_path, 50)
    star_font = ImageFont.truetype(font_path, 45)
    time_font = ImageFont.truetype(font_path, 25)
    name_font = ImageFont.truetype(font_path, 45)
    content_font = ImageFont.truetype(font_path, 40)
    # 玩家头像获取
    player_img = await playerPicDownload(html["avatar"], html["userName"])
    # 玩家头像打开
    avatar_img = Image.open(player_img).convert('RGBA')
    # 玩家头像拼接
    bg_img.paste(avatar_img, (64, 91))
    # 玩家ID拼接
    draw.text((300, 225), "ID:%s" % html["userName"], fill='white', font=title_font)
    # 时间拼接
    time_now = time.strftime("%Y/%m/%d-%H:%M", time.localtime(time.time()))
    draw.text((790, 260), time_now, fill='white', font=time_font)
    for i in range(4):
        # 间距 623
        # 武器图片获取
        pic_url = await PicDownload(vehicle123[i][5])
        # 打开武器图像
        weapon_png = Image.open(pic_url).convert('RGBA')
        # 拉伸
        weapon_png = weapon_png.resize((563, 140))
        # 星星数
        star = str(int(vehicle123[i][1] / 100))
        weapons_star = "★"
        # tx_img = Image.open("")
        if vehicle123[i][1] >= 10000:
            # 金色
            tx_img = Image.open("./data/battlefield/pic/tx/" + "1.png").convert(
                'RGBA')
            tx_img = tx_img.resize((267, 410))
            bg_img.paste(tx_img, (420, 290 + i * 580), tx_img)
            draw.text((179, 506 + i * 580), weapons_star, font=star_font, fill=(255, 132, 0))
            draw.text((233, 509 + i * 580), star, font=star_font, fill=(255, 132, 0))
        elif 6000 <= vehicle123[i][1] < 10000:
            # 蓝色
            tx_img = Image.open("./data/battlefield/pic/tx/" + "2.png").convert(
                'RGBA')
            tx_img = tx_img.resize((267, 410))
            bg_img.paste(tx_img, (420, 290 + i * 580), tx_img)
            draw.text((179, 506 + i * 580), weapons_star, font=star_font, fill=(74, 151, 255))
            draw.text((233, 509 + i * 580), star, font=star_font, fill=(74, 151, 255))
        elif 4000 <= vehicle123[i][1] < 6000:
            # 白色
            tx_img = Image.open("./data/battlefield/pic/tx/" + "3.png").convert(
                'RGBA')
            tx_img = tx_img.resize((267, 410))
            bg_img.paste(tx_img, (420, 290 + i * 580), tx_img)
            draw.text((179, 506 + i * 580), weapons_star, font=star_font)
            draw.text((233, 509 + i * 580), star, font=star_font)
        elif 0 <= vehicle123[i][1] < 4000:
            draw.text((179, 506 + i * 580), weapons_star, font=star_font)
            draw.text((233, 509 + i * 580), star, font=star_font)
        # 武器图像拼接
        bg_img.paste(weapon_png, (250, 392 + i * 580), weapon_png)
        draw.text((210, 630 + i * 580), vehicle123[i][0], font=name_font)
        draw.text((210, 730 + i * 580), "击杀:%d" % vehicle123[i][1], font=content_font)
        draw.text((600, 730 + i * 580), "kpm：%s" % vehicle123[i][2], font=content_font)
        draw.text((210, 780 + i * 580), "摧毁：%s" % vehicle123[i][3], font=content_font)
        draw.text((600, 780 + i * 580), "时长：%s" % vehicle123[i][4], font=content_font)
    bg_img = bg_img.convert('RGB')
    bytes_io = BytesIO()
    bg_img.save(bytes_io, "JPEG")
    end_time3 = time.time()
    logger.info(f'画图耗时:{end_time3 - start_time3}')
    start_time4 = time.time()
    await app.send_message(group, MessageChain(
        # At(sender.id),
        GraiaImage(data_bytes=bytes_io.getvalue())
    ), quote=source)
    end_time4 = time.time()
    logger.info(f"发送耗时:{end_time4 - start_time4}秒")
    if end_time4 - start_time4 > 60:
        await app.send_message(group, MessageChain(
            f"发送耗时:{int(end_time4 - start_time4)}秒,似乎被腾讯限制了呢= ="
        ), quote=source)
    # 调用载具计数器
    await record.vehicle_counter(sender.id, str(player_pid), player_name, str(vehicle_type.result))
    return True


@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Permission.user_require(Permission.User),
    Permission.group_require(channel.metadata.level),
    FrequencyLimitation.require(channel.module),
    Function.require(channel.module),
)
@dispatch(
    Twilight(
        [
            "vehicle_type" @ UnionMatch(
                "-战绩", "-生涯", "-stat"
            ).space(SpacePolicy.PRESERVE),
            "player_name" @ ParamMatch(optional=True).space(PRESERVE)
            # 示例:-武器 shlsan13
        ]
    )
)
async def player_stat_pic(app: Ariadne, sender: Member, group: Group, player_name: RegexResult,
                          source: Source):
    """
     TODO 4:生涯数据
    """
    global client
    start_time = time.time()
    if player_name.matched:
        # 判断玩家名字存不存在
        player_name = str(player_name.result).replace("+", "").replace(" ", "")
        # noinspection PyBroadException
        try:
            player_info = await getPid_byName(player_name)
        except Exception as e:
            logger.error(e)
            await app.send_message(group, MessageChain(
                f"网络出错，请稍后再试"
            ), quote=source)
            return False
        if player_info['personas'] == {}:
            await app.send_message(group, MessageChain(
                f"玩家[{player_name}]不存在"
            ), quote=source)
            return False
        else:
            player_pid = player_info['personas']['persona'][0]['personaId']
            player_name = player_info['personas']['persona'][0]['displayName']
    else:
        # 检查绑定没有,没有绑定则终止，绑定了就读缓存的pid
        if not record.check_bind(sender.id):
            await app.send_message(group, MessageChain(
                f"请先使用'-绑定+你的游戏名字'进行绑定\n例如:-绑定shlsan13"
            ), quote=source)
            return False
        else:
            # noinspection PyBroadException
            try:
                player_pid = await record.get_bind_pid(sender.id)
                player_name = await record.get_bind_name(sender.id)
            except Exception as e:
                logger.error(e)
                await app.send_message(group, MessageChain(
                    "绑定信息过期,请重新绑定!"
                ), quote=source)
                return
    await app.send_message(group, MessageChain(
        # At(sender.id),
        "查询ing"
    ), quote=source)

    scrape_index_tasks = [
        asyncio.ensure_future(InfoCache_stat(str(player_pid)).get_data()),
        asyncio.ensure_future(InfoCache_weapon(str(player_pid)).get_data()),
        asyncio.ensure_future(InfoCache_vehicle(str(player_pid)).get_data()),
        asyncio.ensure_future(player_stat_bfban_api(player_pid))
    ]
    tasks = asyncio.gather(*scrape_index_tasks)
    # noinspection PyBroadException
    try:
        await tasks
    except Exception as e:
        logger.error(e)
        await app.send_message(group, MessageChain(
            f"查询时出现网络错误!"
        ), quote=source)
        return False

    # player_stat_data = scrape_index_tasks[0].result()["result"]
    # player_stat_data = (await InfoCache(str(player_pid), "stat").get_data())["result"]
    # noinspection PyBroadException
    try:
        # player_stat_data = (await InfoCache(str(player_pid), "stat").get_data())["result"]
        player_stat_data = scrape_index_tasks[0].result()["result"]
    except Exception as e:
        logger.error(e)
        await InfoCache(str(player_pid), "stat").update_cache()
        player_stat_data = (await InfoCache_stat(str(player_pid)).get_data())["result"]

    # 等级信息
    rank_data = "0"
    if rank_data == "0":
        # noinspection PyBroadException
        try:
            # async with httpx.AsyncClient() as client:
            rank_response = await client.get('https://battlefieldtracker.com/bf1/profile/pc/%s' % player_name,
                                             timeout=1)
            rank_temp = rank_response.text
            if rank_temp == 404:
                pass
            else:
                soup = BeautifulSoup(rank_temp, "html.parser")
                for item in soup.find_all("div", class_="details"):
                    rank_data = re.findall(re.compile(r'<span class="title">Rank (.*?)</span>'), str(item))[0]
                    with open(f"./data/battlefield/players/{player_pid}/rank.txt", 'w+',
                              encoding='utf-8') as file_temp1:
                        file_temp1.write(rank_temp)
                        logger.success(f"更新玩家{player_name}等级缓存成功")
        except Exception as e:
            logger.warning(f"获取玩家{player_name}等级失败:{e}")
            if os.path.exists(f"./data/battlefield/players/{player_pid}/"):
                try:
                    with open(f"./data/battlefield/players/{player_pid}/rank.txt", 'r', encoding='utf-8') as file_temp1:
                        rank_temp = file_temp1.read()
                        soup = BeautifulSoup(rank_temp, "html.parser")
                        for item in soup.find_all("div", class_="details"):
                            rank_data = re.findall(re.compile(r'<span class="title">Rank (.*?)</span>'), str(item))[0]
                except Exception as e:
                    logger.warning(f"未找到玩家{player_name}等级缓存:{e}")
            pass

    # bfban查询
    bf_html = scrape_index_tasks[3].result()
    if type(bf_html) == str:
        await app.send_message(group, MessageChain(
            # At(sender.id),
            "获取玩家bfban信息出错,请稍后再试!"
        ), quote=source)
        return
    bf_stat = bf_html
    if_cheat = False
    stat_dict = {
        "0": "未处理",
        "1": "实锤",
        "2": "嫌疑再观察",
        "3": "认为没开",
        "4": "未处理",
        "5": "回复讨论中",
        "6": "等待管理确认",
        "8": "刷枪"
    }
    # 先看下有无案件信息
    if "url" in bf_stat["personaids"][str(player_pid)]:
        bf_url = bf_stat["personaids"][str(player_pid)]["url"]
        bfban_status = stat_dict[str(bf_stat["personaids"][str(player_pid)]["status"])]
        if bf_stat["personaids"][str(player_pid)]["hacker"]:
            if_cheat = True
        # if bf_stat['personaids'][str(player_pid)]['cheatMethods'] != "":
        #     if if_cheat:
        #         cheat_method = f"作弊方式:{bf_stat['personaids'][str(player_pid)]['cheatMethods']}\n"
        #     else:
        #         cheat_method = f"被举报为:{bf_stat['personaids'][str(player_pid)]['cheatMethods']}\n"
    else:
        bf_url = "暂无信息"
        bfban_status = "未查询到联ban信息"
    # 头像信息
    # noinspection PyBroadException
    html = None
    if os.path.exists(f"./data/battlefield/players/{player_pid}/avatar.json"):
        try:
            with open(f"./data/battlefield/players/{player_pid}/avatar.json", 'r', encoding='utf-8') as file_temp1:
                html = json.load(file_temp1)
                if html is None:
                    raise Exception
                if "avatar" not in html:
                    raise Exception
        except Exception as e:
            logger.warning(f"未找到玩家{player_name}头像缓存,开始下载\n{e}")
    if html is None:
        # noinspection PyBroadException
        try:
            # async with httpx.AsyncClient() as client:
            response = await client.get(
                'https://api.gametools.network/bf1/player?name=' + str(player_name) + '&platform=pc', timeout=3)
            html = eval(response.text)
            if "avatar" not in html:
                raise Exception
            if not os.path.exists(f"./data/battlefield/players/{player_pid}"):
                os.makedirs(f"./data/battlefield/players/{player_pid}")
            with open(f"./data/battlefield/players/{player_pid}/avatar.json", 'w', encoding='utf-8') as file_temp1:
                json.dump(html, file_temp1, indent=4)
        except Exception as e:
            logger.error(e)
            await app.send_message(group, MessageChain(
                # At(sender.id),
                "网络出错请稍后再试!"
            ), quote=source)
            return False
    # print(type(html))
    # 头像 姓名 等级 技巧值 KD 步战kd  击杀 死亡 spm kpm 胜率 命中率 爆头率 最远爆头距离 游戏时长
    """
    对应数据类型：
        <class 'str'><class 'str'><class 'int'><class 'float'><class 'float'><class 'float'><class 'int'><class 'int'>
        <class 'float'><class 'float'><class 'str'><class 'str'><class 'str'><class 'float'><class 'str'>
    """

    vehicle_kill = 0
    for item in player_stat_data["vehicleStats"]:
        vehicle_kill += item["killsAs"]
    infantry_kill = player_stat_data['basicStats']['kills'] - vehicle_kill

    data_list = [
        html["avatar"], player_name, rank_data, player_stat_data["basicStats"]["skill"],
        player_stat_data['kdr'],  # 4
        "{:.2f}".format(infantry_kill / player_stat_data['basicStats']["deaths"]) if
        player_stat_data['basicStats']["deaths"] != 0 else infantry_kill,
        player_stat_data['basicStats']['kills'],
        player_stat_data['basicStats']["deaths"], player_stat_data['basicStats']["spm"],  # 8
        player_stat_data['basicStats']["kpm"], "{:.2f}%".format(player_stat_data['basicStats']['wins'] / (
                player_stat_data['basicStats']['losses'] + player_stat_data['basicStats']['wins']) * 100)
        if (player_stat_data['basicStats']['losses'] + player_stat_data['basicStats']['wins']) != 0 else "0",
        # 10
        player_stat_data["accuracyRatio"] * 100, "{:.2f}%".format(
            player_stat_data["headShots"] / player_stat_data['basicStats']['kills'] * 100) if
        player_stat_data['basicStats']['kills'] != 0 else "0%",
        player_stat_data["longestHeadShot"],
        player_stat_data['basicStats']["timePlayed"] / 3600, if_cheat,
        # 15
        0, player_stat_data['basicStats']["wins"], player_stat_data['basicStats']["losses"],
        player_stat_data["favoriteClass"], player_stat_data['killAssists'],  # 20
        player_stat_data["revives"], player_stat_data["repairs"], player_stat_data["highestKillStreak"],
        player_stat_data["heals"], player_stat_data["dogtagsTaken"]
    ]

    data_list[2] = rank_data

    # 武器数据
    # noinspection PyBroadException
    try:
        # weapon_data = await get_weapon_data(str(player_pid))
        # weapon_data = scrape_index_tasks[1].result()
        # weapon_data = await InfoCache(str(player_pid), "weapon").get_data()
        # noinspection PyBroadException
        try:
            # weapon_data = await InfoCache(str(player_pid), "weapon").get_data()
            weapon_data = scrape_index_tasks[1].result()
        except Exception as e:
            logger.error(e)
            await InfoCache(str(player_pid), "weapon").update_cache()
            weapon_data = await InfoCache(str(player_pid), "weapon").get_data()
        item_temp = weapon_data["result"][11]["weapons"].pop()
        weapon_data["result"][11]["weapons"].pop()
        weapon_data["result"][3]["weapons"].append(item_temp)
        weapon_data = weapon_data["result"]
    except Exception as e:
        logger.error(e)
        await app.send_message(group, MessageChain(
            # At(sender.id),
            "获取玩家数据出错,请稍后再试!"
        ), quote=source)
        return False
    weapon_temp = {}
    # start_time2 = time.time()
    for item in weapon_data:
        for item2 in item["weapons"]:
            if item2["stats"]["values"] != {}:
                if item2["stats"]["values"]["kills"] != 0.0:
                    weapon_temp[zhconv.convert(item2["name"], 'zh-cn')] = [
                        int(item2["stats"]["values"]["kills"]),  # 击杀
                        "{:.2f}".format(
                            item2["stats"]["values"]["kills"] / item2["stats"]["values"]["seconds"] * 60) if
                        item2["stats"]["values"]["seconds"] != 0 else "0",  # kpm
                        "{:.2f}%".format(
                            item2["stats"]["values"]["hits"] / item2["stats"]["values"]["shots"] * 100) if
                        item2["stats"]["values"]["shots"] * 100 != 0 else "0",  # 命中率
                        "{:.2f}%".format(
                            item2["stats"]["values"]["headshots"] / item2["stats"]["values"]["kills"] * 100) if
                        item2["stats"]["values"]["kills"] != 0 else "0",  # 爆头率
                        "{:.2f}".format(item2["stats"]["values"]["hits"] / item2["stats"]["values"]["kills"]) if
                        item2["stats"]["values"]["kills"] != 0 else "0",  # 效率

                        item2["imageUrl"].replace("[BB_PREFIX]",
                                                  "https://eaassets-a.akamaihd.net/battlelog/battlebinary",
                                                  ),
                        "{:.0f}h".format(item2["stats"]["values"]["seconds"] / 3600),  # 游戏时长
                    ]
    weapon_temp_sorted = sorted(weapon_temp.items(), key=lambda x: x[1][0], reverse=True)  # 得到元组列表
    # print(weapon_temp_sorted)
    weapon_list = weapon_temp_sorted[:4]
    weapon1 = []
    weapon2 = []
    weapon3 = []
    weapon4 = []
    weapon123 = [weapon1, weapon2, weapon3, weapon4]
    i = 0
    # noinspection PyBroadException
    try:
        while i <= 1:
            weapon_item = weapon123[i]
            weapon_item.append(weapon_list[i][0])
            weapon_item.append(weapon_list[i][1][0])
            weapon_item.append(weapon_list[i][1][1])
            weapon_item.append(weapon_list[i][1][2])
            weapon_item.append(weapon_list[i][1][3])
            weapon_item.append(weapon_list[i][1][4])
            weapon_item.append(weapon_list[i][1][5])
            weapon_item.append(weapon_list[i][1][6])
            i += 1
    except Exception as e:
        logger.error(e)
        await app.send_message(group, MessageChain(
            # At(sender.id),
            "数据不足!"
        ), quote=source)
        return False
    weapon_data = weapon1

    # 载具数据
    # noinspection PyBroadException
    try:
        # vehicle_data = await get_vehicle_data(str(player_pid))
        # vehicle_data = scrape_index_tasks[2].result()
        # noinspection PyBroadException
        try:
            # vehicle_data = await InfoCache(str(player_pid), "vehicle").get_data()
            vehicle_data = scrape_index_tasks[2].result()
        except Exception as e:
            logger.error(e)
            await InfoCache(str(player_pid), "vehicle").update_cache()
            vehicle_data = await InfoCache(str(player_pid), "vehicle").get_data()
        vehicle_data = vehicle_data["result"]
    except Exception as e:
        logger.error(e)
        await app.send_message(group, MessageChain(
            # At(sender.id),
            "获取玩家数据出错,请稍后再试!"
        ), quote=source)
        return False
    vehicle_temp = {}
    for item1 in vehicle_data:
        for item2 in item1["vehicles"]:
            vehicle_temp[zhconv.convert(item2["name"], 'zh-cn')] = [
                int(item2["stats"]["values"]["kills"]),  # 击杀
                "{:.2f}".format(item2["stats"]["values"]["kills"] / item2["stats"]["values"]["seconds"] * 60)
                if item2["stats"]["values"]["seconds"] != 0 else "0",
                # kpm
                int(item2["stats"]["values"]["destroyed"]),  # 摧毁
                "{:.2f}h".format(item2["stats"]["values"]["seconds"] / 3600),  # 时长
                item2["imageUrl"].replace("[BB_PREFIX]", "https://eaassets-a.akamaihd.net/battlelog/battlebinary")
                # 图片url
            ]
    vehicle_temp_sorted = sorted(vehicle_temp.items(), key=lambda x: x[1][0], reverse=True)  # 得到元组列表
    # print(weapon_temp_sorted)
    vehicle_list = vehicle_temp_sorted[:4]
    vehicle1 = []
    vehicle2 = []
    vehicle3 = []
    vehicle4 = []
    vehicle123 = [vehicle1, vehicle2, vehicle3, vehicle4]
    i = 0
    while i <= 1:
        vehicle_temp = vehicle123[i]
        vehicle_temp.append(vehicle_list[i][0])
        vehicle_temp.append(vehicle_list[i][1][0])
        vehicle_temp.append(vehicle_list[i][1][1])
        vehicle_temp.append(vehicle_list[i][1][2])
        vehicle_temp.append(vehicle_list[i][1][3])
        vehicle_temp.append(vehicle_list[i][1][4])
        i += 1
    vehicle_data = vehicle1

    # 制作图片
    # 背景图
    # 底图选择
    # bg_img = Image.open(await pic_custom(player_pid))
    bg_img = Image.open(bg_pic.choose_bg(player_pid, "stat"))
    width, height = bg_img.size
    if not (width == 1080 and height == 2729):
        b1 = width / 1080
        b2 = height / 2729
        if b1 < 1 or b2 < 1:
            倍数 = 1 / b1 if 1 / b1 > 1 / b2 else 1 / b2
        else:
            倍数 = b1 if b1 < b2 else b2
        # 放大图片
        bg_img = bg_img.resize((int(width * 倍数) + 1, int(height * 倍数) + 1), Image.ANTIALIAS)
        # 裁剪到中心位置
        width, height = bg_img.size
        left = (width - 1080) / 2
        top = (height - 2729) / 2
        right = (width + 1080) / 2
        bottom = (height + 2729) / 2
        bg_img = bg_img.crop((left, top, right, bottom))
        底图 = Image.open(f"./data/battlefield/pic/bg/底图2.png").convert('RGBA')
        bg_img.paste(底图, (0, 0), 底图)
    draw = ImageDraw.Draw(bg_img)
    # 字体路径
    font_path = './data/battlefield/font/BFText-Regular-SC-19cf572c.ttf'
    # 设定字体
    title_font = ImageFont.truetype(font_path, 50)
    star_font = ImageFont.truetype(font_path, 45)
    time_font = ImageFont.truetype(font_path, 25)
    name_font = ImageFont.truetype(font_path, 45)
    content_font = ImageFont.truetype(font_path, 40)
    # 等级字体
    rank_font = ImageFont.truetype(r'C:\Windows\Fonts\simhei.TTF', 80)
    # 玩家头像获取
    player_img = await playerPicDownload(html["avatar"], html["userName"])
    # 玩家头像打开
    avatar_img = Image.open(player_img).convert('RGBA')
    # 玩家头像拼接
    bg_img.paste(avatar_img, (64, 91))
    # 玩家ID拼接
    draw.text((300, 225), "ID:%s" % html["userName"], fill='white', font=title_font)
    # 时间拼接
    time_now = time.strftime("%Y/%m/%d-%H:%M", time.localtime(time.time()))
    draw.text((790, 260), time_now, fill='white', font=time_font)
    # 第一个黑框
    # 等级
    if int(data_list[2]) >= 100:
        draw.text((173, 370), data_list[2], fill='white', font=rank_font)
    elif int(data_list[2]) >= 10:
        draw.text((195, 370), data_list[2], fill='white', font=rank_font)
    else:
        draw.text((215, 370), data_list[2], fill='white', font=rank_font)
    # 游戏时长
    draw.text((410, 385), '游戏时长:%.1f小时' % data_list[14], fill='white', font=name_font)
    # 击杀
    draw.text((210, 510), f'击杀:{data_list[6]}', fill='white', font=content_font)
    # 死亡
    draw.text((210, 560), f'死亡:{data_list[7]}', fill='white', font=content_font)
    # kd
    draw.text((213, 610), f'KD:{data_list[4]}', fill='white', font=content_font)
    # 胜局
    draw.text((600, 510), f'胜局:{data_list[17]}', fill='white', font=content_font)
    # 败局
    draw.text((600, 560), f'败局:{data_list[18]}', fill='white', font=content_font)
    # 胜率
    draw.text((600, 610), f'胜率:{data_list[10]}', fill='white', font=content_font)
    # 第二个黑框
    # 兵种
    # 兵种图片打开
    class_img = Image.open('./data/battlefield/pic/classes/%s.png' % data_list[19]).convert('RGBA')
    # 兵种图片拉伸
    class_img = class_img.resize((90, 90), Image.ANTIALIAS)
    # 兵种图片拼接
    bg_img.paste(class_img, (192, 735), class_img)
    # 最佳兵种
    class_dict = {"Assault": "突击兵", "Cavalry": "骑兵", "Medic": "医疗兵",
                  "Pilot": "飞行员", "Scout": "侦察兵", "Support": "支援兵", "Tanker": "坦克手"}
    best_class = class_dict[data_list[19]]
    draw.text((450, 760), f'最佳兵种:{best_class}', fill='white', font=name_font)
    # 协助击杀
    draw.text((210, 890), f'协助击杀:{int(data_list[20])}', fill='white', font=content_font)
    # 复活数
    draw.text((210, 940), f'复活数:{int(data_list[21])}', fill='white', font=content_font)
    # 修理数
    draw.text((210, 990), f'修理数:{int(data_list[22])}', fill='white', font=content_font)
    # 最多连杀
    draw.text((600, 890), f'最高连杀:{int(data_list[23])}', fill='white', font=content_font)
    # 治疗数
    draw.text((600, 940), f'治疗数:{int(data_list[24])}', fill='white', font=content_font)
    # 狗牌数
    draw.text((600, 990), f'狗牌数:{int(data_list[25])}', fill='white', font=content_font)

    # 是否联ban

    if bfban_status != "未查询到联ban信息":
        draw.text((430, 1130), f'联ban信息:{bfban_status}', fill='white', font=name_font)
    else:
        draw.text((417, 1130), f'{bfban_status}', fill='white', font=name_font)

    # KPM
    draw.text((213, 1260), f'KPM:{data_list[9]}', fill='white', font=content_font)
    # 步战KD
    draw.text((210, 1310), f'步战KD:{data_list[5]}', fill='white', font=content_font)
    # 命中率
    draw.text((210, 1360), '命中率:%.2f%%' % data_list[11], fill='white', font=content_font)
    # 最远爆头距离
    draw.text((210, 1410), f'最远爆头距离:{data_list[13]}米', fill='white', font=content_font)
    # SPM
    draw.text((600, 1260), f'SPM:{data_list[8]}', fill='white', font=content_font)
    # 技巧值
    draw.text((600, 1310), f'技巧值:{data_list[3]}', fill='white', font=content_font)
    # 爆头率
    draw.text((600, 1360), f'爆头率:{data_list[12]}', fill='white', font=content_font)
    # bg_img.show()
    # range(4) 0 - 3
    # 最佳武器
    i = 2
    if i == 2:
        # 间距 623
        # 武器图片获取
        pic_url = await PicDownload(weapon_data[6])
        # 打开武器图像
        weapon_png = Image.open(pic_url).convert('RGBA')
        # 拉伸
        weapon_png = weapon_png.resize((588, 147))
        star = str(int(weapon_data[1] / 100))
        weapons_star = "★"
        # tx_img = Image.open("")
        if weapon_data[1] >= 10000:
            # 金色
            tx_img = Image.open("./data/battlefield/pic/tx/" + "1.png").convert(
                'RGBA')
            tx_img = tx_img.resize((267, 410))
            bg_img.paste(tx_img, (420, 290 + i * 580), tx_img)
            draw.text((179, 506 + i * 580), weapons_star, font=star_font, fill=(255, 132, 0))
            draw.text((233, 509 + i * 580), star, font=star_font, fill=(255, 132, 0))
        elif 6000 <= weapon_data[1] < 10000:
            # 蓝色
            tx_img = Image.open("./data/battlefield/pic/tx/" + "2.png").convert(
                'RGBA')
            tx_img = tx_img.resize((267, 410))
            bg_img.paste(tx_img, (420, 290 + i * 580), tx_img)
            draw.text((179, 506 + i * 580), weapons_star, font=star_font, fill=(74, 151, 255))
            draw.text((233, 509 + i * 580), star, font=star_font, fill=(74, 151, 255))
        elif 4000 <= weapon_data[1] < 6000:
            # 白色
            tx_img = Image.open("./data/battlefield/pic/tx/" + "3.png").convert(
                'RGBA')
            tx_img = tx_img.resize((267, 410))
            bg_img.paste(tx_img, (420, 290 + i * 580), tx_img)
            draw.text((179, 506 + i * 580), weapons_star, font=star_font)
            draw.text((233, 509 + i * 580), star, font=star_font)
        elif 0 <= weapon_data[1] < 4000:
            draw.text((179, 506 + i * 580), weapons_star, font=star_font)
            draw.text((233, 509 + i * 580), star, font=star_font)
        # 武器图像拼接
        bg_img.paste(weapon_png, (250, 392 + i * 580), weapon_png)
        draw.text((210, 630 + i * 580), weapon_data[0], font=name_font)
        draw.text((210, 730 + i * 580), "击杀:%d" % weapon_data[1], font=content_font)
        draw.text((600, 730 + i * 580), f"kpm:{weapon_data[2]}", font=content_font)
        draw.text((210, 780 + i * 580), "命中率:%s" % weapon_data[3], font=content_font)
        draw.text((600, 780 + i * 580), "爆头率:%s" % weapon_data[4], font=content_font)
        draw.text((210, 830 + i * 580), "效率:%s" % weapon_data[5], font=content_font)
        draw.text((600, 830 + i * 580), "时长:%s" % weapon_data[7], font=content_font)
    # 最佳载具
    i = 3
    if i == 3:
        # 间距 623
        # 武器图片获取
        pic_url = await PicDownload(vehicle_data[5])
        # 打开武器图像
        weapon_png = Image.open(pic_url).convert('RGBA')
        # 拉伸
        weapon_png = weapon_png.resize((563, 140))
        # 星星数
        star = str(int(vehicle_data[1] / 100))
        weapons_star = "★"
        # tx_img = Image.open("")
        if vehicle_data[1] >= 10000:
            # 金色
            tx_img = Image.open("./data/battlefield/pic/tx/" + "1.png").convert(
                'RGBA')
            tx_img = tx_img.resize((267, 410))
            bg_img.paste(tx_img, (420, 290 + i * 580), tx_img)
            draw.text((179, 506 + i * 580), weapons_star, font=star_font, fill=(255, 132, 0))
            draw.text((233, 509 + i * 580), star, font=star_font, fill=(255, 132, 0))
        elif 6000 <= vehicle_data[1] < 10000:
            # 蓝色
            tx_img = Image.open("./data/battlefield/pic/tx/" + "2.png").convert(
                'RGBA')
            tx_img = tx_img.resize((267, 410))
            bg_img.paste(tx_img, (420, 290 + i * 580), tx_img)
            draw.text((179, 506 + i * 580), weapons_star, font=star_font, fill=(74, 151, 255))
            draw.text((233, 509 + i * 580), star, font=star_font, fill=(74, 151, 255))
        elif 4000 <= vehicle_data[1] < 6000:
            # 白色
            tx_img = Image.open("./data/battlefield/pic/tx/" + "3.png").convert(
                'RGBA')
            tx_img = tx_img.resize((267, 410))
            bg_img.paste(tx_img, (420, 290 + i * 580), tx_img)
            draw.text((179, 506 + i * 580), weapons_star, font=star_font)
            draw.text((233, 509 + i * 580), star, font=star_font)
        elif 0 <= vehicle_data[1] < 4000:
            draw.text((179, 506 + i * 580), weapons_star, font=star_font)
            draw.text((233, 509 + i * 580), star, font=star_font)
        # 武器图像拼接
        bg_img.paste(weapon_png, (250, 392 + i * 580), weapon_png)
        draw.text((210, 630 + i * 580), vehicle_data[0], font=name_font)
        draw.text((210, 730 + i * 580), "击杀:%d" % vehicle_data[1], font=content_font)
        draw.text((600, 730 + i * 580), f"kpm:{vehicle_data[2]}", font=content_font)
        draw.text((210, 780 + i * 580), "摧毁:%s" % vehicle_data[3], font=content_font)
        draw.text((600, 780 + i * 580), f"时长:{vehicle_data[4]}", font=content_font)
    if if_cheat:
        bg_img = bg_img.convert('L')
    bg_img = bg_img.convert('RGB')
    bytes_io = BytesIO()
    bg_img.save(bytes_io, "JPEG")
    end_time = time.time()
    logger.info(f"接口+制图耗时:{end_time - start_time}秒")
    start_time4 = time.time()
    if not if_cheat:
        await app.send_message(group, MessageChain(
            # At(sender.id),
            GraiaImage(data_bytes=bytes_io.getvalue())
        ), quote=source)
    else:
        await app.send_message(group, MessageChain(
            # At(sender.id),
            GraiaImage(data_bytes=bytes_io.getvalue()),
            f"案件地址:{bf_url}"
        ), quote=source)
    end_time4 = time.time()
    if end_time4 - start_time4 > 60:
        await app.send_message(group, MessageChain(
            f"发送耗时:{int(end_time4 - start_time4)}秒,似乎被腾讯限制了呢= ="
        ), quote=source)
    logger.info(f"发送耗时:{end_time4 - start_time4}秒")
    await record.player_stat_counter(sender.id, str(player_pid), str(player_name))


# TODO 5:最近
@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Permission.user_require(Permission.User),
    Permission.group_require(channel.metadata.level),
    FrequencyLimitation.require(channel.module),
    Function.require(channel.module),
)
@dispatch(
    Twilight(
        [
            "message" @ UnionMatch(
                "-最近"
            ).space(SpacePolicy.PRESERVE),
            "player_name" @ ParamMatch(optional=True).space(PRESERVE)
            # 示例:-武器 shlsan13
        ]
    )
)
async def recent(app: Ariadne, sender: Member, group: Group, player_name: RegexResult,
                 source: Source):
    if player_name.matched:
        # 判断玩家名字存不存在
        player_name = str(player_name.result).replace("+", "").replace(" ", "")
        # noinspection PyBroadException
        try:
            player_info = await getPid_byName(player_name)
        except Exception as e:
            logger.error(e)
            await app.send_message(group, MessageChain(
                f"网络出错，请稍后再试!"
            ), quote=source)
            return False
        if player_info['personas'] == {}:
            await app.send_message(group, MessageChain(
                f"玩家[{player_name}]不存在"
            ), quote=source)
            return False
        else:
            player_pid = player_info['personas']['persona'][0]['personaId']
            player_name = player_info['personas']['persona'][0]['displayName']
    else:
        # 检查绑定没有,没有绑定则终止，绑定了就读缓存的pid
        if not record.check_bind(sender.id):
            await app.send_message(group, MessageChain(
                f"请先使用'-绑定+你的游戏名字'进行绑定\n例如:-绑定shlsan13"
            ), quote=source)
            return False
        else:
            # noinspection PyBroadException
            try:
                player_pid = await record.get_bind_pid(sender.id)
                player_name = await record.get_bind_name(sender.id)
            except Exception as e:
                logger.error(e)
                await app.send_message(group, MessageChain(
                    # At(sender.id),
                    "绑定信息过期,请重新绑定!"
                ), quote=source)
                return
    await app.send_message(group, MessageChain(
        # At(sender.id),
        "查询ing"
    ), quote=source)
    # 组合网页地址
    try:
        start_time = time.time()
        url = "https://battlefieldtracker.com/bf1/profile/pc/" + player_name
        head_temp = {
            "Connection": "keep-alive",
        }
        # async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=head_temp, timeout=10)
        end_time = time.time()
        html = response.text
        # 处理网页超时
        if html == "timed out":
            raise Exception
        elif html == {}:
            raise Exception

        soup = BeautifulSoup(html, "html.parser")  # 查找符合要求的字符串 形成列表
        for item in soup.find_all("div", class_="card-body player-sessions"):
            # 输出检查
            # print(item)
            # 转换成字符串用正则来挑选数据
            item = str(item)
            data_list = []
            # 只要前3组数据
            i = 0
            c = 0
            re_time = re.compile(r'<span data-livestamp="(.*?).000Z"></span></h4>')
            re_spm = re.compile(r'<div>(.*?)</div>')
            re_kd = re.compile(r'<div>(.*?)</div>')
            re_kpm = re.compile(r'<div>(.*?)</div>')
            re_time_play = re.compile(r'<div>(.*?)</div>')
            count = len(re.findall(re_spm, item)) / 6
            while i < count and i < 3:
                data = ["", "", "", "", "", "", ""]
                time_point = re.findall(re_time, item)[0 + i]
                time_point = time_point.replace("T", " ")
                spm = re.findall(re_spm, item)[0 + c]
                kd = re.findall(re_kd, item)[1 + c]
                kpm = re.findall(re_kpm, item)[2 + c]
                time_play = re.findall(re_time_play, item)[5 + c]
                data[1] = time_point + "\n"
                data[2] = "SPM:" + spm + "\n"
                data[3] = "KD:" + kd + "\n"
                data[4] = "KPM" + kpm + "\n"
                data[5] = "游玩时长:" + time_play + "\n"
                data[6] = "=" * 11 + "\n"
                data_list.append(data)
                i += 1
                c += 6
            data_list[-1][-1] = data_list[-1][-1].replace("\n", "")
            # if if_blocked(app.account):
            #     await app.send_message(
            #         group,
            #         await MessageChainUtils.messagechain_to_img(
            #             MessageChain(
            #                 data_list
            #             )
            #         ), quote=message[Source][0]
            #     )
            #     return
            await app.send_message(group, MessageChain(
                data_list
            ), quote=source)
            await record.recent_counter(sender.id, str(player_pid), str(player_name))
            logger.info(f'查询最近耗时:{end_time - start_time}')
            return True
        await app.send_message(group, MessageChain(
            "没有查询到最近记录哦~"
        ), quote=source)
        return
    except Exception as e:
        logger.warning(e)
        await app.send_message(group, MessageChain(
            "网络出错，请稍后再试!"
        ), quote=source)


# TODO 6:对局
@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Permission.user_require(Permission.User),
    Permission.group_require(channel.metadata.level),
    FrequencyLimitation.require(channel.module),
    Function.require(channel.module),
)
@dispatch(
    Twilight(
        [
            "message" @ UnionMatch(
                "-对局"
            ).space(SpacePolicy.PRESERVE),
            "player_name" @ ParamMatch(optional=True).space(PRESERVE)
            # 示例:-武器 shlsan13
        ]
    )
)
async def matches(app: Ariadne, sender: Member, group: Group, player_name: RegexResult,
                  src: Source):
    if player_name.matched:
        # 判断玩家名字存不存在
        player_name = str(player_name.result).replace("+", "").replace(" ", "")
        # noinspection PyBroadException
        try:
            player_info = await getPid_byName(player_name)
        except Exception as e:
            logger.error(e)
            await app.send_message(group, MessageChain(
                f"网络出错，请稍后再试!"
            ), quote=src)
            return False
        if player_info['personas'] == {}:
            await app.send_message(group, MessageChain(
                f"玩家[{player_name}]不存在"
            ), quote=src)
            return False
        else:
            player_pid = player_info['personas']['persona'][0]['personaId']
            player_name = player_info['personas']['persona'][0]['displayName']
    else:
        # 检查绑定没有,没有绑定则终止，绑定了就读缓存的pid
        if not record.check_bind(sender.id):
            await app.send_message(group, MessageChain(
                f"请先使用'-绑定+你的游戏名字'进行绑定\n例如:-绑定shlsan13"
            ), quote=src)
            return False
        else:
            # noinspection PyBroadException
            try:
                player_pid = await record.get_bind_pid(sender.id)
                player_name = await record.get_bind_name(sender.id)
            except Exception as e:
                logger.error(e)
                await app.send_message(group, MessageChain(
                    # At(sender.id),
                    "绑定信息过期,请重新绑定!"
                ), quote=src)
                return
    await app.send_message(group, MessageChain(
        "查询ing"
    ), quote=src)
    # try:
    # 获取数据
    start_time = time.time()
    player_data = []
    # noinspection PyBroadException
    try:
        url1 = 'https://battlefieldtracker.com/bf1/profile/pc/' + player_name + '/matches'
        header = {
            "Connection": "keep-alive"
        }
        # async with httpx.AsyncClient() as client:
        response = await client.get(url1, headers=header, timeout=5)
    except Exception as e:
        logger.warning(e)
        await app.send_message(group, MessageChain(
            "网络出错,请稍后再试!"
        ), quote=src)
        return False

    end_time = time.time()
    logger.info(f"获取对局列表耗时:{end_time - start_time}")
    html1 = response.text
    # 处理网页超时
    if html1 == "timed out":
        raise Exception
    elif html1 == {}:
        raise Exception
    elif html1 == 404:
        raise Exception
    soup = BeautifulSoup(html1, "html.parser")  # 查找符合要求的字符串 形成列表
    matches_list = []
    # for i in soup.find_all("p", class_="description"):
    #     player_data.append("".join(re.findall(re.compile(r'<p class="description">(.*?)</p>'), str(i))))
    # player_data = player_data[:3]
    header = {
        "Connection": "keep-alive"
    }
    for item in soup.find_all("div", class_="card matches"):
        matches_list = re.findall(re.compile(r'href="(.*?)"'), str(item))[:3]  # 前几个对局数据
    if len(matches_list) == 0:
        await app.send_message(group, MessageChain(
            '查询失败'
        ), quote=src)
        return False
    start_time2 = time.time()
    scrape_index_tasks = []
    # noinspection PyBroadException
    try:
        # 并发前n个地址，并获取其中的数据
        # async with httpx.AsyncClient(headers=header) as client:
        for item2 in matches_list:
            url_temp = 'https://battlefieldtracker.com' + item2
            scrape_index_tasks.append(asyncio.ensure_future(client.get(url_temp, headers=header, timeout=10)))
        await asyncio.gather(*scrape_index_tasks)
    except Exception as e:
        logger.error(e)
        await app.send_message(group, MessageChain(
            "网络出错，请稍后再试!"
        ), quote=src)
        return False
    end_time2 = time.time()
    logger.info(f"对局耗时:{end_time2 - start_time2}")
    start_time3 = time.time()
    for result in scrape_index_tasks:
        response = result.result()
        html2 = response.text
        if html2 == "timed out":
            raise Exception
        elif html2 == 404:
            raise Exception
        soup = BeautifulSoup(html2, "html.parser")
        for item in soup.find_all("div", class_="activity-details"):
            # 日期
            player_data.append(
                "游玩日期:" + re.findall(re.compile(r'<span class="date">(.*?)</span>'), str(item))[0] + '\n')
            # 服务器名字
            player_data.append(
                "服务器:" +
                re.findall(re.compile(r'<small class="hidden-sm hidden-xs">(.*?)</small></h2>'), str(item))[0][:20]
                + '\n'
            )
            # 模式名
            player_data.append(re.findall(re.compile(r'<span class="type">(.*?)</span>'), str(item))[0]
                               .replace("BreakthroughLarge0", "行动模式").replace("Frontlines", "前线")
                               .replace("Domination", "抢攻").replace("Team Deathmatch", "团队死斗")
                               .replace("War Pigeons", "战争信鸽").replace("Conquest", "征服")
                               .replace("AirAssault0", "空中突袭").replace("Rush", "突袭")
                               .replace("Breakthrough", "闪击行动") + '-')
            # 地图名
            player_data.append(
                re.findall(re.compile(r'<h2 class="map-name">(.*?)<small class="hidden-sm hidden-xs">'), str(item))[0]
                .replace("Galicia", "加利西亚").replace("Giant's Shadow", "庞然闇影").replace("Brusilov Keep", "勃鲁西洛夫关口")
                .replace("Rupture", "决裂").replace("Soissons", "苏瓦松").replace("Amiens", "亚眠")
                .replace("St. Quentin Scar", "圣康坦的伤痕").replace("Argonne Forest", "阿尔贡森林")
                .replace("Ballroom Blitz", "宴厅").replace("MP_Harbor", "泽布吕赫").replace("River Somme", "索姆河")
                .replace("Prise de Tahure", "攻占托尔").replace("Fao Fortress", "法欧堡").replace("Achi Baba", "2788")
                .replace("Cape Helles", "海丽丝峡").replace("Tsaritsyn", "察里津").replace("Volga River", "窝瓦河")
                .replace("Empire's Edge", "帝国边境").replace("ŁUPKÓW PASS", "武普库夫山口")
                .replace("Verdun Heights", "凡尔登高地").replace("Fort De Vaux", "垃圾厂")
                .replace("Sinai Desert", "西奈沙漠").replace("Monte Grappa", "拉粑粑山").replace("Suez", "苏伊士")
                .replace("Albion", "阿尔比恩").replace("Caporetto", "卡波雷托").replace("Passchendaele", "帕斯尚尔")
                .replace("Nivelle Nights", "尼维尔之夜").replace("MP_Naval", "黑尔戈兰湾").replace("", "")
                + '\n')
        # 此时player_data已有服务器名字 游玩的时间 模式-地图名字
        # 玩家对局数据
        for item2 in soup.find_all("div", class_="player active"):
            soup2 = item2
            Time_data = 0
            score_data = []
            for i2 in soup2.find_all("div", class_="quick-stats"):
                # 数组 分别是得分 击杀 死亡 协助 K/D
                # name_data = re.findall(re.compile(r'<div class="name">(.*?)</div>'), str(i2))
                score_data = re.findall(re.compile(r'<div class="value">(.*?)</div>'), str(i2))
                Time_data = re.findall(re.compile(r'<span class="player-subline">([\s\S]*?)</span>'), str(item2))[0] \
                    .replace("\r", "").replace("\n", "").replace("Played for ", "").replace(" ", "")
                # 时间
            # 转换成秒数

            # noinspection PyBroadException
            try:
                Time_data_int = int(Time_data[:Time_data.find("m")]) * 60 + int(
                    Time_data[Time_data.find("m") + 1:Time_data.find("s")])
            except Exception as e:
                logger.warning(e)
                Time_data_int = 1
            # 得分
            Score_data = score_data[0]

            # SPM
            # noinspection PyBroadException
            try:
                Spm_data = int(Score_data.replace(",", "")) / int(Time_data_int / 60)
            except Exception as e:
                logger.warning(e)
                Spm_data = 0
            # 击杀
            Kill_data = score_data[1]

            # KPM
            # noinspection PyBroadException
            try:
                Kpm_data = int(Kill_data) / int(Time_data_int / 60)
            except Exception as e:
                logger.warning(e)
                Kpm_data = 0
            # 死亡数
            Death_data = score_data[2]
            # KD
            KD_data = score_data[4]
            if KD_data != '-':
                KD_data = int(Kill_data) / int(Death_data) if int(Death_data) != 0 else 1
            player_data.append(f'击杀:{Kill_data}\t')
            player_data.append(f'死亡:{Death_data}\n')
            if KD_data != '-':
                player_data.append('KD:%.2f\t' % KD_data)
            else:
                player_data.append(f'KD:{KD_data}\t')
            player_data.append(f'得分:{Score_data}\n')
            player_data.append(f'KPM:{Kpm_data:.2f}\t')
            player_data.append(f'SPM:{Spm_data:.2f}\n')
            player_data.append(f'游玩时长:{int(Time_data_int / 60)}分{Time_data_int % 60}秒\n')
            player_data.append("=" * 20 + "\n")
    # noinspection PyBroadException
    try:
        player_data[-1] = player_data[-1].replace("\n", '')
    except Exception as e:
        logger.error(e)
        await app.send_message(group, MessageChain(
            f"对局数据为空QAQ"
        ), quote=src)
        return
    end_time3 = time.time()
    logger.info(f"解析对局数据耗时:{end_time3 - start_time3}")
    player_data[-1] = player_data[-1].replace("\n", "")

    # await app.send_message(
    #     group,
    #     await MessageChainUtils.messagechain_to_img(
    #         MessageChain(
    #             player_data
    #         )
    #     ), quote=message[Source][0]
    # )

    await app.send_message(group, MessageChain(
        player_data
    ), quote=src)
    await record.matches_counter(sender.id, str(player_pid), str(player_name))
    return True


# TODO:天眼查
@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Permission.user_require(Permission.User),
    Permission.group_require(channel.metadata.level),
    FrequencyLimitation.require(channel.module),
    Function.require(channel.module),
)
@dispatch(
    Twilight(
        [
            "message" @ UnionMatch(
                "-天眼查"
            ).space(SpacePolicy.PRESERVE),
            "player_name" @ ParamMatch(optional=True).space(PRESERVE)
            # 示例:-天眼查 shlsan13
        ]
    )
)
async def player_tyc(app: Ariadne, sender: Member, group: Group, player_name: RegexResult,
                     source: Source):
    if player_name.matched:
        # 判断玩家名字存不存在
        player_name = str(player_name.result).replace("+", "").replace(" ", "")
        # noinspection PyBroadException
        try:
            player_info = await getPid_byName(player_name)
        except Exception as e:
            logger.error(e)
            await app.send_message(group, MessageChain(
                f"网络出错，请稍后再试"
            ), quote=source)
            return False
        if player_info['personas'] == {}:
            await app.send_message(group, MessageChain(
                f"玩家[{player_name}]不存在"
            ), quote=source)
            return False
        else:
            player_pid = player_info['personas']['persona'][0]['personaId']
            player_name = player_info['personas']['persona'][0]['displayName']
    else:
        # 检查绑定没有,没有绑定则终止，绑定了就读缓存的pid
        if not record.check_bind(sender.id):
            await app.send_message(group, MessageChain(
                f"请先使用'-绑定+你的游戏名字'进行绑定\n例如:-绑定shlsan13"
            ), quote=source)
            return False
        else:
            # noinspection PyBroadException
            try:
                player_pid = await record.get_bind_pid(sender.id)
                player_name = await record.get_bind_name(sender.id)
            except Exception as e:
                logger.error(e)
                await app.send_message(group, MessageChain(
                    # At(sender.id),
                    "绑定信息过期,请重新绑定!"
                ), quote=source)
                return
    await app.send_message(group, MessageChain(
        "查询ing"
    ), quote=source)

    data_list = ["=" * 20 + '\n', '玩家姓名:%s\n' % player_name, '玩家ID:%s\n' % player_pid, "=" * 20 + '\n', ]

    scrape_index_tasks = [
        asyncio.ensure_future(get_player_recentServers(player_pid)),
        asyncio.ensure_future(tyc_waterGod_api(player_pid)),
        asyncio.ensure_future(tyc_record_api(player_pid)),
        asyncio.ensure_future(tyc_bfban_api(player_pid)),
        asyncio.ensure_future(tyc_bfeac_api(player_name)),
        asyncio.ensure_future(server_playing(player_pid)),
        asyncio.ensure_future(tyc_check_vban(player_pid)),
    ]
    tasks = asyncio.gather(*scrape_index_tasks)
    try:
        await tasks
    except Exception as e:
        logger.error(e)
        await app.send_message(group, MessageChain(
            f"网络出错,请稍后再试!"
            # graia_Image(path='./data/bqb/狐务器无响应.jpg')
        ), quote=source)
        return False
    # 最近游玩服务器
    # noinspection PyBroadException
    try:
        recent_play_list = scrape_index_tasks[0].result()
        if type(recent_play_list) == dict:
            data_list.append("最近游玩:\n")
            i = 0
            if len(recent_play_list["result"]) >= 3:
                while i <= 2:
                    data_list.append(recent_play_list["result"][i]["name"][:25] + "\n")
                    i += 1
            else:
                for item in recent_play_list["result"]:
                    data_list.append(item["name"][:25] + "\n")
            data_list.append("=" * 20 + '\n')
    except Exception as e:
        logger.error(f"获取最近游玩出错:{e}")
        pass

    # 水神api
    # noinspection PyBroadException
    try:
        # vban检查
        vban_info = scrape_index_tasks[6].result()
        vban_num = None
        if type(vban_info) == str:
            pass
        else:
            vban_num = len(vban_info["vban"])
        html1 = scrape_index_tasks[1].result().text
        if html1 == 404:
            raise Exception
        html1 = eval(html1)
        if html1["status"]:
            player_server = len(html1["result"][0]["data"])
            player_admin = len(html1["result"][1]["data"])
            player_vip = len(html1["result"][2]["data"])
            player_ban = len(html1["result"][3]["data"])
            data_list.append("拥有服务器数:%s\n" % player_server)
            data_list.append("管理服务器数:%s\n" % player_admin)
            data_list.append("服务器封禁数:%s\n" % player_ban)
            if vban_num is not None:
                data_list.append(f"VBAN数:{vban_num}\n")
            data_list.append("VIP数:%s\n" % player_vip)
            data_list.append("详细情况:https://bf.s-wg.net/#/player?pid=%s\n" % player_pid)
            data_list.append("=" * 20 + '\n')
    except Exception as e:
        logger.error(f"获取水神api出错:{e}")
        pass

    # 战绩软件api
    # noinspection PyBroadException
    try:
        record_html = eval(scrape_index_tasks[2].result().text)
        browse = record_html["data"]["browse"]
        hacker = record_html["data"]["hacker"]
        doubt = record_html["data"]["doubt"]
        data_list.append("战绩软件查询结果:\n")
        data_list.append(f"浏览量:{browse} ")
        data_list.append(f"外挂标记:{hacker} ")
        data_list.append(f"怀疑标记:{doubt}\n")
        data_list.append("=" * 20 + '\n')
    except Exception as e:
        logger.error(f"获取战绩软件出错:{e}")
        pass

    # bfban查询
    # noinspection PyBroadException
    bf_html = None
    try:
        bf_html = scrape_index_tasks[3].result().text
        if bf_html == "timed out":
            raise Exception(f"网络出错")
        elif bf_html == {}:
            raise Exception(f"网络出错")
        bf_stat = eval(bf_html)
        stat_dict = {
            "0": "未处理",
            "1": "实锤",
            "2": "嫌疑再观察",
            "3": "认为没开",
            "4": "回收站",
            "5": "回复讨论中",
            "6": "等待管理确认",
            "8": "刷枪"
        }
        # 先看下有无案件信息
        if "url" in bf_stat["personaids"][str(player_pid)]:
            bf_url = bf_stat["personaids"][str(player_pid)]["url"]
            data_list.append("查询到BFBAN信息:\n")
            data_list.append(f"案件地址:{bf_url}\n")
            data_list.append(f'状态:{stat_dict[str(bf_stat["personaids"][str(player_pid)]["status"])]}\n')
            if bf_stat['personaids'][str(player_pid)]['cheatMethods'] != "":
                if bf_stat["personaids"][str(player_pid)]["hacker"]:
                    data_list.append(f"作弊方式:{bf_stat['personaids'][str(player_pid)]['cheatMethods']}\n")
                else:
                    data_list.append(f"被举报为:{bf_stat['personaids'][str(player_pid)]['cheatMethods']}\n")
            data_list.append("=" * 20 + '\n')
        else:
            # pass
            data_list.append("未查询到BFBAN信息\n")
            data_list.append("=" * 20 + '\n')
    except Exception as e:
        logger.error(f"获取bfban信息出错:{e}")
        logger.error(f"{bf_html}")

        pass

    # bfeac查询
    # noinspection PyBroadException
    try:
        eac_stat_dict = {
            0: "未处理",
            1: "已封禁",
            2: "证据不足",
            3: "自证通过",
            4: "自证中",
            5: "刷枪",
        }
        eac_response = eval(scrape_index_tasks[4].result().text)
        if eac_response["data"] != "":
            data = eac_response["data"][0]
            case_id = data["case_id"]
            case_url = f"https://bfeac.com/#/case/{case_id}"
            eac_status = eac_stat_dict[data["current_status"]]
            data_list.append("查询到BFEAC信息:\n")
            data_list.append(f"案件地址:{case_url}\n")
            data_list.append(f"状态:{eac_status}\n")
            data_list.append("=" * 20 + '\n')
        else:
            data_list.append("未查询到BFEAC信息\n")
            data_list.append("=" * 20 + '\n')
    except Exception as e:
        logger.error(f"获取bfeac信息出错:{e}")
        pass
    # 正在游玩
    server_name = scrape_index_tasks[5].result()
    if type(server_name) == str:
        data_list.append("正在游玩:\n")
        data_list.append(server_name)
        data_list.append("\n")
        data_list.append("=" * 20)
    else:
        server_name = server_name["name"]
        data_list.append("正在游玩:\n%s\n" % server_name)
        data_list.append("=" * 20)

    await app.send_message(group, MessageChain(
        data_list
    ), quote=source)
    await record.tyc_counter(sender.id, player_pid, player_name)
    return


# 查询
# TODO: 举报到eac
@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Permission.user_require(Permission.GroupAdmin),
    Permission.group_require(channel.metadata.level),
    FrequencyLimitation.require(channel.module),
    Function.require(channel.module),
    Config.require("functions.bf1.apikey"),
)
@dispatch(
    Twilight(
        [
            "message" @ UnionMatch(
                "-举报"
            ).space(SpacePolicy.PRESERVE),
            "player_name" @ ParamMatch(optional=False).space(PRESERVE)
        ]
    )
)
async def report(app: Ariadne, sender: Member, group: Group, player_name: RegexResult,
                 source: Source):
    global client
    # TODO 1.查验id是否有效
    player_name = player_name.result.display
    # noinspection PyBroadException
    try:
        player_info = await getPid_byName(player_name)
    except Exception as e:
        logger.error(e)
        await app.send_message(group, MessageChain(
            f"网络出错，请稍后再试"
        ), quote=source)
        return False
    if player_info['personas'] == {}:
        await app.send_message(group, MessageChain(
            f"玩家[{player_name}]不存在"
        ), quote=source)
        return False
    else:
        player_pid = player_info['personas']['persona'][0]['personaId']
        player_name = player_info['personas']['persona'][0]['displayName']
        # player_uid = player_info['personas']['persona'][0]['pidId']

    await app.send_message(group, MessageChain(
        f"注意:请勿随意、乱举报,“垃圾”举报将会影响eac的处理效率,同时将撤销bot的使用"
    ), quote=source)
    # TODO 2.查验是否已经有举报信息
    check_eacInfo_url = f"https://api.bfeac.com/case/EAID/{player_name}"
    header = {
        "Connection": "Keep-Alive"
    }
    # noinspection PyBroadException
    try:
        await app.send_message(group, MessageChain(
            f"查询信息ing"
        ), quote=source)
        # async with httpx.AsyncClient() as client:
        response = await client.get(check_eacInfo_url, headers=header, timeout=10)
        response = eval(response.text)
    except Exception as e:
        logger.error(e)
        await app.send_message(group, MessageChain(
            f"网络出错，请稍后再试"
        ), quote=source)
        return False
    if response["data"] != "":
        data = response["data"][0]
        case_id = data["case_id"]
        case_url = f"https://bfeac.com/#/case/{case_id}"
        await app.send_message(group, MessageChain(
            f"查询到已有案件信息如下:\n",
            case_url
        ), quote=source)
        return

    # TODO 3.选择举报类型 1/5,其他则退出
    # report_type = 0
    # await app.send_message(group, MessageChain(
    #     f"请在10秒内发送举报的游戏:1"
    # ), quote=message[Source][0])
    #
    # async def waiter_report_type(waiter_member: Member, waiter_group: Group,
    #                              waiter_message: MessageChain):
    #     if waiter_member.id == sender.id and waiter_group.id == group.id:
    #         choices = ["1"]
    #         say = waiter_message.display
    #         if say in choices:
    #             return True, waiter_member.id, say
    #         else:
    #             return False, waiter_member.id, say
    #
    # try:
    #     result, operator, report_type = await FunctionWaiter(waiter_report_type, [GroupMessage],
    #                                                          block_propagation=True).wait(timeout=10)
    # except asyncio.exceptions.TimeoutError:
    #     await app.send_message(group, MessageChain(
    #         f'操作超时,请重新举报!'), quote=message[Source][0])
    #     return
    # if result:
    #     await app.send_message(group, MessageChain(
    #         f"已获取到举报的游戏:bf{report_type},请在30秒内发送举报的理由(不带图片)!"
    #     ), quote=message[Source][0])
    # else:
    #     await app.send_message(group, MessageChain(
    #         f"获取到举报的游戏:{report_type}无效的选项,已退出举报!"
    #     ), quote=message[Source][0])
    #     return False

    # TODO 4.发送举报的理由
    # report_reason = None
    await app.send_message(group, MessageChain(
        f"请在30秒内发送举报的理由(请一次描述完且不带图片!!!)"
    ), quote=source)
    saying = None

    async def waiter_report_reason(waiter_member: Member, waiter_group: Group,
                                   waiter_message: MessageChain):
        if waiter_member.id == sender.id and waiter_group.id == group.id:
            nonlocal saying
            saying = waiter_message.display
            return waiter_member.id, f"<p>{saying}</p>"

    try:
        operator, report_reason = await FunctionWaiter(waiter_report_reason, [GroupMessage],
                                                       block_propagation=True).wait(timeout=30)
    except asyncio.exceptions.TimeoutError:
        await app.send_message(group, MessageChain(
            f'操作超时,请重新举报!'), quote=source)
        return
    if "[图片]" in saying:
        return await app.send_message(group, MessageChain(
            f"获取举报理由失败,请重新举报!"
        ), quote=source)
    await app.send_message(group, MessageChain(
        f"获取到举报理由:{saying}\n若需补充图片请在30秒内发送一张图片,无图片则发送'确认'以提交举报。"
    ), quote=source)

    # TODO 5.发送举报的图片,其他则退出

    list_pic = []
    # remove_list = []
    # data = ()
    if_confirm = False
    while not if_confirm:
        if len(list_pic) == 0:
            pass
        else:
            await app.send_message(group, MessageChain(
                f"收到{len(list_pic)}张图片,如需添加请继续发送图片,否则发送'确认'以提交举报。"
            ), quote=source)

        async def waiter_report_pic(waiter_member: Member, waiter_message: MessageChain, waiter_group: Group):
            nonlocal if_confirm  # 内部函数修改外部函数的变量
            if group.id == waiter_group.id and waiter_member.id == sender.id:
                say = waiter_message.display.replace(f"{At(app.account)} ", '')
                if say == '[图片]':
                    return True, waiter_message
                elif say == "确认":
                    if_confirm = True
                    return True, waiter_message
                else:
                    return False, waiter_message

        try:
            result, img = await FunctionWaiter(waiter_report_pic, [GroupMessage], block_propagation=True).wait(
                timeout=30)
        except asyncio.exceptions.TimeoutError:
            await app.send_message(group, MessageChain(
                f'操作超时,已自动退出!'), quote=source)
            return

        if result:
            # 如果是图片则下载
            if img.display == '[图片]':
                try:
                    img_url: GraiaImage = img[GraiaImage]
                    img_url = img_url.url
                    headers = {
                        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_3) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/85.0.4183.102 Safari/537.36'
                    }
                    # noinspection PyBroadException
                    try:
                        # async with httpx.AsyncClient() as client:
                        response = await client.get(img_url, headers=headers, timeout=5)
                        r = response
                    except Exception as e:
                        logger.error(e)
                        await app.send_message(group, MessageChain(
                            f'获取图片出错,请重新举报!'
                        ), quote=source)
                        return False
                    # wb 以二进制打开文件并写入，文件名不存在会创
                    file_name = int(time.time())
                    file_path = f'./data/battlefield/Temp/{file_name}.png'
                    with open(file_path, 'wb') as f:
                        f.write(r.content)  # 写入二进制内容
                        f.close()

                    # 获取图床
                    # tc_url = "https://www.imgurl.org/upload/aws_s3"
                    tc_url = "https://api.bfeac.com/inner_api/upload_image"
                    tc_files = {'file': open(file_path, 'rb')}
                    # tc_data = {'file': tc_files}
                    apikey = global_config.functions.get("bf1", {}).get("apikey", "")
                    tc_headers = {
                        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/103.0.0.0 Safari/537.36',
                        "apikey": apikey
                    }
                    try:
                        # async with httpx.AsyncClient() as client:
                        response = await client.post(tc_url, files=tc_files, headers=tc_headers)
                        # response = requests.post(tc_url, files=tc_files, data=tc_data, headers=tc_headers)
                    except Exception as e:
                        logger.error(e)
                        await app.send_message(group, MessageChain(
                            f'获取图片图床失败,请重新举报!'
                        ), quote=source)
                        return False
                    json_temp = response.json()

                    # img_temp = f"<img src = '{json_temp['data']}' />"
                    img_temp = f'<img class="img-fluid" src="{json_temp["data"]}">'
                    report_reason += img_temp
                    list_pic.append(json_temp['data'])
                    # noinspection PyBroadException
                    try:
                        os.remove(file_path)
                    except Exception as e:
                        logger.error(e)
                        pass
                except Exception as e:
                    logger.error(response)
                    logger.error(e)
                    await app.send_message(group, MessageChain(
                        f'获取图片图床失败,请重新举报!'
                    ), quote=source)
                    return False
            # 是确认则提交
            if img.display == '确认':
                await app.send_message(group, MessageChain(
                    f"提交举报ing"
                ), quote=source)
                # 调用接口
                report_result = eval(await report_Interface(
                    player_name, report_reason, sender.id, global_config.functions.get("bf1", {}).get("apikey", "")
                ))
                if type(report_result["data"]) == int:
                    try:
                        with open(f"./data/battlefield/report_log/data.json", "r", encoding="utf-8") as file1:
                            log_data = json.load(file1)
                            log_data["data"].append(
                                {
                                    "time": time.time(),
                                    "operatorQQ": sender.id,
                                    "caseId": report_result['data'],
                                    "sourceGroupId": f"{group.id}",
                                }
                            )
                            with open(f"./data/battlefield/report_log/data.json", "r", encoding="utf-8") as file2:
                                json.dump(log_data, file2, indent=4, ensure_ascii=False)
                    except Exception as e:
                        logger.error(f"日志出错:{e}")
                    await app.send_message(group, MessageChain(
                        f"举报成功!案件地址:https://bfeac.com/?#/case/{report_result['data']}"
                    ), quote=source)
                    await record.report_counter(sender.id, player_pid, player_name)
                    return True
                else:
                    await app.send_message(group, MessageChain(
                        f"举报结果:{report_result}"
                    ), quote=source)
                    return
        else:
            await app.send_message(group, MessageChain(
                f'未识成功别到图片,请重新举报!'
            ), quote=source)
            return False


# bfstat
@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Permission.user_require(Permission.GroupAdmin),
    Permission.group_require(channel.metadata.level),
    FrequencyLimitation.require(channel.module),
    Function.require(channel.module),
)
@dispatch(
    Twilight(
        [
            FullMatch("-bfstat")
        ]
    )
)
async def bf_status(app: Ariadne, group: Group, source: Source):
    # 获取绑定玩家数量数量
    bind_path = "data/battlefield/binds/players"
    bind_counters = len(os.listdir(bind_path))
    record_counters = await get_record_counters(bind_path)
    url = "https://api.gametools.network/bf1/status/?platform=pc"
    head = {
        "Connection": "Keep-Alive"
    }
    # noinspection PyBroadException
    try:
        # async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=head, timeout=5)
        html = eval(response.text)
        if 'errors' in html:
            # {'errors': ['Error connecting to the database']}
            await app.send_message(group, MessageChain(
                f"{html['errors'][0]}"
            ), quote=source)
            return
        data: dict = html["regions"][0]
    except Exception:
        data = None
    if data:
        await app.send_message(group, MessageChain(
            f"当前在线:{data.get('amounts').get('soldierAmount')}\n",
            f"服务器数:{data.get('amounts').get('serverAmount')}\n",
            f"排队总数:{data.get('amounts').get('queueAmount')}\n",
            f"观众总数:{data.get('amounts').get('spectatorAmount')}\n",
            f"=" * 13, "\n",
            "私服(官服):\n",
            f"服务器:{int(data.get('amounts').get('communityServerAmount'))}({int(data.get('amounts').get('diceServerAmount'))})\n",
            f"人数:{int(data.get('amounts').get('communitySoldierAmount'))}({int(data.get('amounts').get('diceSoldierAmount'))})\n",
            f"排队:{int(data.get('amounts').get('communityQueueAmount'))}({int(data.get('amounts').get('diceQueueAmount'))})\n",
            f"观众:{int(data.get('amounts').get('communitySpectatorAmount'))}({int(data.get('amounts').get('diceSpectatorAmount'))})\n",
            f"=" * 13, "\n",
            f"征服:{data.get('modes').get('Conquest')}\t",
            f"行动:{data.get('modes').get('BreakthroughLarge')}\n",
            f"前线:{data.get('modes').get('TugOfWar')}\t",
            f"突袭:{data.get('modes').get('Rush')}\n",
            f"抢攻:{data.get('modes').get('Domination')}\t",
            f"闪击行动:{data.get('modes').get('Breakthrough')}\n",
            f"团队死斗:{data.get('modes').get('TeamDeathMatch')}\t",
            f"战争信鸽:{data.get('modes').get('Possession')}\n",
            f"空中突袭:{data.get('modes').get('AirAssault')}\n",
            f"空降补给:{data.get('modes').get('ZoneControl')}\n",
            f"=" * 13, "\n"
                       f"当前绑定玩家数:{bind_counters}\n"
                       f"累计查询数:{record_counters}"
        ), quote=source)
    else:
        await app.send_message(group, MessageChain(
            f"当前绑定玩家数:{bind_counters}\n"
            f"累计查询数:{record_counters}"
        ), quote=source)


# TODO: 查询统计
@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Permission.user_require(Permission.User),
    Permission.group_require(channel.metadata.level),
    FrequencyLimitation.require(channel.module),
    Function.require(channel.module),
)
@dispatch(
    Twilight(
        [FullMatch("-信息").space(PRESERVE)]
    )
)
async def bf_checkCounter(app: Ariadne, sender: Member, group: Group, source: Source):
    if not record.check_bind(sender.id):
        await app.send_message(group, MessageChain(
            f"没有找到你的信息!\n请先使用'-绑定+你的游戏名字'进行绑定\n例如:-绑定shlsan13"
        ), quote=source)
        return False
    try:
        player_pid = await record.get_bind_pid(sender.id)
        player_name = await record.get_bind_name(sender.id)
        player_uid = await record.get_bind_uid(sender.id)
    except Exception as e:
        logger.error(e)
        await app.send_message(group, MessageChain(
            # At(sender.id),
            "绑定信息出错,请重新绑定!"
        ), quote=source)
        return
    bind_info = await record.get_bind_counter(sender.id)
    weapon_info = await record.get_weapon_counter(sender.id)
    vehicle_info = await record.get_vehicle_counter(sender.id)
    stat_info = await record.get_stat_counter(sender.id)
    recent_info = await record.get_recent_counter(sender.id)
    matches_info = await record.get_matches_counter(sender.id)
    tyc_info = await record.get_tyc_counter(sender.id)
    report_info = await record.get_report_counter(sender.id)
    await app.send_message(group, MessageChain(
        f"你的信息如下:\n"
        f"Id:{player_name}\n"
        f"Pid:{player_pid}\n"
        f"Uid:{player_uid}\n"
        f"绑定次数:{len(bind_info)}\n",
        f"举报次数:{len(report_info)}\n" if report_info else '',
        f"天眼查次数:{len(tyc_info)}\n" if tyc_info else '',
        f"查询武器次数:{len(weapon_info)}\n"
        f"查询载具次数:{len(vehicle_info)}\n"
        f"查询生涯次数:{len(stat_info)}\n"
        f"查询最近次数:{len(recent_info)}\n"
        f"查询对局次数:{len(matches_info)}"
    ), quote=source)


notice_counter = 0


# TODO 9:自动刷新session
@channel.use(SchedulerSchema(timers.every_custom_minutes(10)))  # 每10分钟执行一次
async def auto_refresh_session(app: Ariadne):
    logger.info("定时检测session开始")
    global bf_aip_header, bf_aip_url, notice_counter
    session = await record.get_session()
    bf_aip_header["X-Gatewaysession"] = session
    body = {
        "jsonrpc": "2.0",
        "method": "Companion.isLoggedIn",
        "params": {
            "game": "tunguska",
            "locale": "zh-cn"
        },
        "id": "9e4459ff-0149-4a11-858a-871960af9639"
    }
    # noinspection PyBroadException
    try:
        response = requests.post(bf_aip_url, headers=bf_aip_header, data=json.dumps(body), timeout=3)
        response = eval(response.text)["result"]["isLoggedIn"]
        if response:
            logger.info("session正常")
            return
        else:
            i = 1
            while i <= 3:
                # noinspection PyBroadException
                try:
                    logger.info("开始刷新session")
                    from main_session_auto_refresh import auto_refresh_account
                    result = await auto_refresh_account()
                    if result == "刷新成功":
                        logger.success("session自动刷新成功")
                    else:
                        logger.warning("session自动刷新失败")
                    break
                except Exception as e:
                    logger.error(f"session刷新失败:{e}")
                    i += 1
            else:
                if notice_counter <= 3:
                    await app.send_friend_message(await app.get_friend(global_config.Master), MessageChain(
                        "战地一默认查询账号session更新失败,请检查账号信息"
                    ))
                    notice_counter += 1
    except Exception as e:
        logger.warning(f"自动刷新session网络请求失败:{e}")


# 自动刷新client
@channel.use(SchedulerSchema(timers.every_custom_minutes(20)))
async def auto_refresh_client():
    global client
    # noinspection PyBroadException
    try:
        del client
        client = httpx.AsyncClient(limits=limits)
        logger.success("刷新bf1战绩client成功")
    except Exception as e:
        logger.error(f"刷新bf1战绩client失败:{e}")


async def refresh_main_account(app: Ariadne, group: Group, source: Source):
    i = 1
    while i <= 3:
        try:
            result = await auto_refresh_account()
            if result == "刷新成功":
                await app.send_message(group, MessageChain(
                    f"刷新成功"
                ), quote=source)
                return
            else:
                await app.send_message(group, MessageChain(
                    f"刷新失败:{result}"
                ), quote=source)
            break
        except Exception as e:
            await app.send_message(group, MessageChain(
                f"刷新失败:{e}"
            ), quote=source)
            i += 1
    else:
        await app.send_friend_message(await app.get_friend(global_config.Master), MessageChain(
            "session更新失败，请检查账号信息"
        ))


# 手动刷新
@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Permission.user_require(Permission.BotAdmin),
    Permission.group_require(channel.metadata.level),
    FrequencyLimitation.require(channel.module),
    Function.require(channel.module),
)
@dispatch(
    Twilight(
        [FullMatch("-refresh main").space(PRESERVE)]
    )
)
async def refresh_main_session(app: Ariadne, group: Group, source: Source):
    await app.send_message(group, MessageChain(
        f"刷新ing"
    ), quote=source)
    global bf_aip_header, bf_aip_url
    try:
        session = await record.get_session()
        bf_aip_header["X-Gatewaysession"] = session
    except:
        await refresh_main_account(app, group, source)
    body = {
        "jsonrpc": "2.0",
        "method": "Companion.isLoggedIn",
        "params": {
            "game": "tunguska",
            "locale": "zh-cn"
        },
        "id": "9e4459ff-0149-4a11-858a-871960af9639"
    }
    try:
        response = requests.post(bf_aip_url, headers=bf_aip_header, data=json.dumps(body), timeout=3)
        response = eval(response.text)["result"]["isLoggedIn"]
        if response:
            await app.send_message(group, MessageChain(
                f"session正常"
            ), quote=source)
            return
        else:
            await refresh_main_account(app, group, source)
    except Exception as e:
        await app.send_message(group, MessageChain(
            f"刷新失败:{e}"
        ), quote=source)


# TODO 战役信息
@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Permission.user_require(Permission.User),
    Permission.group_require(channel.metadata.level),
    FrequencyLimitation.require(channel.module),
    Function.require(channel.module),
)
@dispatch(
    Twilight(
        [
            "message" @ UnionMatch(
                "-战役", "-行动"
            ).space(SpacePolicy.PRESERVE)
            # 示例:-战役
        ]
    )
)
async def op_info(app: Ariadne, group: Group, source: Source):
    global bf_aip_header, bf_aip_url
    session = await record.get_session()
    bf_aip_header["X-Gatewaysession"] = session
    body = {
        "jsonrpc": "2.0",
        "method": "CampaignOperations.getPlayerCampaignStatus",
        "params": {
            "game": "tunguska"
        },
        "id": await get_a_uuid()
    }
    # noinspection PyBroadException
    try:
        # async with httpx.AsyncClient() as client:
        response = await client.post(bf_aip_url, headers=bf_aip_header, data=json.dumps(body), timeout=5)
    except Exception as e:
        logger.error(e)
        await app.send_message(group, MessageChain(
            f"网络超时,请稍后再试!"
        ), quote=source)
        return
    # url2 = eval(response.text)['result']["firstBattlepack"]['images']
    # for key in url2:
    #     url3 = 'https://sparta-gw.battlelog.com/jsonrpc/pc/api' + url2[key].replace('[BB_PREFIX]', '')
    op_data = eval(response.text)
    if op_data["result"] == '':
        await app.send_message(group, MessageChain(
            f"当前无进行战役信息!"
        ), quote=source)
        return
    return_list = []
    from time import strftime, gmtime
    return_list.append(zhconv.convert(f"战役名称:{op_data['result']['name']}\n", "zh-cn"))
    # return_list.append(zhconv.convert(f'战役描述:{op_data["result"]["shortDesc"]}\n', "zh-cn"))
    return_list.append('战役地点:')
    for key in op_data["result"]:
        if key.startswith("op") and op_data["result"][key] != "":
            return_list.append(zhconv.convert(f'{op_data["result"][key]["name"]} ', "zh-cn"))
    return_list.append(strftime("\n剩余时间:%d天%H小时%M分", gmtime(op_data["result"]["minutesRemaining"] * 60)))
    await app.send_message(group, MessageChain(
        return_list
    ), quote=source)


# TODO 图片交换
@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Permission.user_require(Permission.User),
    Permission.group_require(channel.metadata.level),
    FrequencyLimitation.require(channel.module),
    Function.require(channel.module),
)
@dispatch(
    Twilight(
        [
            "message" @ UnionMatch(
                "-交换"
            ).space(SpacePolicy.PRESERVE)
            # 示例:-交换
        ]
    )
)
async def Scrap_Exchange(app: Ariadne, sender: Member, group: Group):
    global bf_aip_header, bf_aip_url
    # TODO 1.如果今天不是周一,就获取缓存里的图片,如果是周一且时间在20:00至24:00之间,就制图
    i = 0
    file_path = f'./data/battlefield/exchange/{(date.today() + timedelta(days=i)).strftime("%#m月%#d日")}.png'
    while (not os.path.exists(file_path)) and (i >= -31):
        i -= 1
        file_path = f'./data/battlefield/exchange/{(date.today() + timedelta(days=i)).strftime("%#m月%#d日")}.png'
    await app.send_message(group, MessageChain(
        At(sender), GraiaImage(path=file_path), f"\n更新日期:{file_path[file_path.rfind('/') + 1:].replace('.png', '')}"
    ))
    jh_time = (date.today() + timedelta(days=0)).strftime("%#m月%#d日")
    session = await record.get_session()
    bf_aip_header["X-Gatewaysession"] = session
    body = {
        "jsonrpc": "2.0",
        "method": "ScrapExchange.getOffers",
        "params": {
            "game": "tunguska",
        },
        "id": await get_a_uuid()
    }
    try:
        # async with httpx.AsyncClient() as client:
        response = await client.post(bf_aip_url, headers=bf_aip_header, data=json.dumps(body), timeout=5)
    except Exception as e:
        logger.error(e)
        return
    SE_data = eval(response.text)
    i = 0
    file_path_temp = f'./data/battlefield/exchange/{(date.today() + timedelta(days=i)).strftime("%#m月%#d日")}.json'
    while (not os.path.exists(file_path_temp)) and (i >= -31):
        i -= 1
        file_path_temp = f'./data/battlefield/exchange/{(date.today() + timedelta(days=i)).strftime("%#m月%#d日")}.json'
    if file_path_temp:
        with open(file_path_temp, 'r', encoding="utf-8") as file1:
            data_temp = json.load(file1)['result']
            if data_temp == SE_data.get("result", SE_data):
                logger.info("交换未更新")
                return
    with open(f'./data/battlefield/exchange/{jh_time}.json', 'w', encoding="utf-8") as file1:
        json.dump(SE_data, file1, indent=4)
    SE_data_list = SE_data["result"]["items"]
    # 创建一个交换物件的列表列表，元素列表的元素有价格，皮肤名字，武器名字，品质，武器图片
    SE_list = []
    for item in SE_data_list:
        temp_list = [item["price"], zhconv.convert(item["item"]["name"], 'zh-cn')]
        # 处理成简体
        temp_list.append(zhconv.convert(item["item"]["parentName"] + "外观", 'zh-cn')) \
            if item["item"]["parentName"] != "" \
            else temp_list.append(zhconv.convert(item["item"]["parentName"], 'zh-cn'))
        temp_list.append(
            item["item"]["rarenessLevel"]["name"].replace("Superior", "传奇").replace("Enhanced",
                                                                                    "精英").replace(
                "Standard", "特殊"))
        temp_list.append(
            item["item"]["images"]["Png1024xANY"].replace(
                "[BB_PREFIX]", "https://eaassets-a.akamaihd.net/battlelog/battlebinary"
            )
        )
        SE_list.append(temp_list)
    # 保存/获取皮肤图片路径
    i = 0
    while i < len(SE_list):
        SE_list[i][4] = await download_skin(SE_list[i][4])
        i += 1
    # 制作图片,总大小:2351*1322,黑框间隔为8,黑框尺寸220*292，第一张黑框距左边界39，上边界225，武器尺寸为180*45,第一个钱币图片的位置是72*483
    # 交换的背景图
    bg_img = Image.open('./data/battlefield/pic/bg/SE_bg.png')
    draw = ImageDraw.Draw(bg_img)

    # 字体路径
    font_path = './data/battlefield/font/BFText-Regular-SC-19cf572c.ttf'
    price_font = ImageFont.truetype(font_path, 18)
    seName_font = ImageFont.truetype(font_path, 13)
    seSkinName_font = ImageFont.truetype(font_path, 18)
    # 保存路径
    SavePic = f"./data/battlefield/exchange/{jh_time}.png"
    x = 59
    y = 340
    for i in range(len(SE_list)):
        while y + 225 < 1322:
            while x + 220 < 2351 and i < len(SE_list):
                if SE_list[i][3] == "特殊":
                    i += 1
                    continue
                # 从上到下分别是武器图片、武器名字、皮肤名字、品质、价格
                # [300, '魯特斯克戰役', 'SMG 08/18', '特殊', 'https://eaassets-a.akamaihd.net/battlelog/battlebinary/gamedata/Tunguska/123/1/U_MAXIMSMG_BATTLEPACKS_FABERGE_T1S3_LARGE-7b01c879.png']
                # 打开交换图像
                SE_png = Image.open(SE_list[i][4]).convert('RGBA')
                # 武器名字
                draw.text((x, y + 52), SE_list[i][2], (169, 169, 169), font=seName_font)
                # 皮肤名字
                draw.text((x, y + 79), SE_list[i][1], (255, 255, 255), font=seSkinName_font)
                # 如果品质为传奇则品质颜色为(255, 132, 0)，精英则为(74, 151, 255)，特殊则为白色
                XD_skin_list = [
                    "菲姆", "菲姆特", "索得格雷",
                    "巴赫馬奇", "菲力克斯穆勒", "狼人", "黑貓",
                    "苟白克", "比利‧米契尔", "在那边", "飞蛾扑火", "佛伦",
                    "默勒谢什蒂", "奥伊图兹", "埃丹", "滨海努瓦耶勒", "唐登空袭",
                    "青春誓言", "德塞夫勒", "克拉奥讷之歌", "芙萝山德斯", "死去的君王",
                    "波佐洛", "奧提加拉山", "奧托‧迪克斯", "保罗‧克利", "阿莫斯‧怀德",
                    "集合点", "法兰兹‧马克", "风暴", "我的机枪", "加利格拉姆", "多贝尔多",
                    "茨纳河", "莫纳斯提尔", "科巴丁", "德•奇里诃", "若宫丸", "波珀灵厄",
                    "K连", "玛德蓉", "巨马", "罗曼诺卡夫", "薩利卡米什", "贝利库尔隧道",
                    "史特拉姆", "阿道戴", "克里夫兰", "家乡套件", "夏日套件", "监禁者",
                    "罗曼诺夫卡", "阿涅森", "波珀灵厄", "威玛猎犬", "齐格飞防线",
                    "华盛顿", "泰罗林猎犬", "怪奇之物", "法兰兹‧马克", "风暴"
                ]
                if SE_list[i][3] == "传奇":
                    if SE_list[i][0] in [270, 300]:
                        draw.text((x, y + 110), f"{SE_list[i][3]}(限定)", (255, 132, 0), font=price_font)
                    elif SE_list[i][1] in XD_skin_list:
                        draw.text((x, y + 110), f"{SE_list[i][3]}(限定)", (255, 132, 0), font=price_font)
                    else:
                        draw.text((x, y + 110), SE_list[i][3], (255, 132, 0), font=price_font)
                    # 打开特效图像
                    tx_png = Image.open('./data/battlefield/pic/tx/1.png').convert('RGBA')
                elif SE_list[i][1] in XD_skin_list:
                    draw.text((x, y + 110), f"{SE_list[i][3]}(限定)", (255, 132, 0), font=price_font)
                    # 打开特效图像
                    tx_png = Image.open('./data/battlefield/pic/tx/2.png').convert('RGBA')
                else:
                    draw.text((x, y + 110), SE_list[i][3], (74, 151, 255), font=price_font)
                    # 打开特效图像
                    tx_png = Image.open('./data/battlefield/pic/tx/2.png').convert('RGBA')
                # 特效图片拉伸
                tx_png = tx_png.resize((100, 153), Image.ANTIALIAS)
                # 特效图片拼接
                bg_img.paste(tx_png, (x + 36, y - 105), tx_png)
                # 武器图片拉伸
                SE_png = SE_png.resize((180, 45), Image.ANTIALIAS)
                # 武器图片拼接
                bg_img.paste(SE_png, (x, y - 45), SE_png)
                # 价格
                draw.text((x + 24, y + 134), str(SE_list[i][0]), (255, 255, 255), font=price_font)
                x += 228
                i += 1
                # bg_img.show()
            y += 298
            x = 59
    bg_img.save(SavePic, 'png', quality=100)
    logger.info("更新交换缓存成功!")


# 被戳回复小标语
@listen(NudgeEvent)
async def NudgeReply(app: Ariadne, event: NudgeEvent):
    if event.group_id and event.target == app.account and module_controller.if_module_switch_on(
            channel.module, event.group_id
    ):
        gl = random.randint(0, 99)
        if gl > 2:
            file_path = f"./data/battlefield/小标语/data.json"
            with open(file_path, 'r', encoding="utf-8") as file1:
                data = json.load(file1)['result']
                a = random.choice(data)['name']
                send = zhconv.convert(a, 'zh-cn')
        else:
            bf_dic = [
                "你知道吗,小埋最初的灵感来自于胡桃-by水神",
                f"当武器击杀达到40⭐图片会发出白光,60⭐时为紫光,当达到100⭐之后会发出耀眼的金光~",
            ]
            send = random.choice(bf_dic)
        return await app.send_group_message(
            event.group_id, MessageChain(
                At(event.supplicant), '\n', send
            )
        )


# TODO bf1百科
@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Permission.user_require(Permission.User),
    Permission.group_require(channel.metadata.level),
    FrequencyLimitation.require(channel.module),
    Function.require(channel.module),
)
@dispatch(
    Twilight(
        [
            "message" @ UnionMatch("-bf1百科").space(SpacePolicy.PRESERVE),
            "item_index" @ ParamMatch(optional=True).space(PRESERVE)
            # 示例:-bf1百科 12
        ]
    )
)
async def bf1_wiki(app: Ariadne, group: Group, message: MessageChain, item_index: RegexResult,
                   source: Source):
    resv_message = message.display.replace(" ", '').replace("-bf1百科", "").replace("+", "")
    if resv_message == "":
        await app.send_message(group, MessageChain(
            f"回复 -bf1百科+类型 可查看对应信息\n支持类型:武器、载具、战略、战争、全世界"
            # graia_Image(url=send_temp[1])
        ), quote=source)
        return True
    if resv_message == "武器":
        await app.send_message(group, MessageChain(
            GraiaImage(path="./data/battlefield/pic/百科/百科武器.jpg")
        ), quote=source)
        return True
    if resv_message == "载具":
        await app.send_message(group, MessageChain(
            GraiaImage(path="./data/battlefield/pic/百科/百科载具.jpg")
        ), quote=source)
        return True
    if resv_message == "战略":
        await app.send_message(group, MessageChain(
            GraiaImage(path="./data/battlefield/pic/百科/百科战略.jpg")
        ), quote=source)
        return True
    if resv_message == "战争":
        await app.send_message(group, MessageChain(
            GraiaImage(path="./data/battlefield/pic/百科/百科战争.jpg")
        ), quote=source)
        return True
    if resv_message == "全世界":
        await app.send_message(group, MessageChain(
            GraiaImage(path="./data/battlefield/pic/百科/百科全世界.jpg")
        ), quote=source)
        return True
    # TODO -bf1百科 序号 ->先读缓存 如果没有就制图
    # 如果序号不对就寄
    # noinspection PyBroadException
    try:
        item_index = int(str(item_index.result)) - 1
        if item_index > 309 or item_index < 0:
            raise Exception
    except Exception as e:
        logger.error(e)
        await app.send_message(group, MessageChain(
            f"请检查序号范围:1~310"
        ), quote=source)
        return True
    file_path = f"./data/battlefield/百科/data.json"
    with open(file_path, 'r', encoding="utf-8") as file1:
        wiki_data = json.load(file1)["result"]
    item_list = []
    # i = 1
    for item in wiki_data:
        for item2 in item["awards"]:
            item_list.append(item2)
    wiki_item = eval(zhconv.convert(str(item_list[item_index]), 'zh-cn'))
    item_path = f"./data/battlefield/pic/百科/{wiki_item['code']}.png"
    if os.path.exists(item_path):
        await app.send_message(group, MessageChain(
            GraiaImage(path=item_path)
        ), quote=source)
        return True
    await app.send_message(group, MessageChain(
        f"查询ing"
    ), quote=source)
    # 底图选择
    if len(wiki_item["codexEntry"]["description"]) < 500:
        bg_img_path = f"./data/battlefield/pic/百科/百科短底.png"
        bg2_img_path = f"./data/battlefield/pic/百科/百科短.png"
        n_number = 704
    elif 900 > len(wiki_item["codexEntry"]["description"]) > 500:
        bg_img_path = f"./data/battlefield/pic/百科/百科中底.png"
        bg2_img_path = f"./data/battlefield/pic/百科/百科中.png"
        n_number = 1364
    else:
        bg_img_path = f"./data/battlefield/pic/百科/百科长底.png"
        bg2_img_path = f"./data/battlefield/pic/百科/百科长.png"
        n_number = 2002
    bg_img = Image.open(bg_img_path)
    bg2_img = Image.open(bg2_img_path)
    draw = ImageDraw.Draw(bg_img)
    # 百科图片下载
    wiki_pic_path = await download_wiki_pic(
        wiki_item['codexEntry']['images']['Png640xANY'].replace("[BB_PREFIX]",
                                                                "https://eaassets-a.akamaihd.net/battlelog/battlebinary")
    )
    if wiki_pic_path is None:
        await app.send_message(group, MessageChain(
            f"图片下载失败,请稍后再试!"
        ), quote=source)
        return True
    wiki_pic = Image.open(wiki_pic_path)
    # 拼接百科图片
    bg_img.paste(wiki_pic, (37, 37), wiki_pic)
    # 拼接第二层背景图
    bg_img.paste(bg2_img, (0, 0), bg2_img)

    # 颜色
    # 左下角浅灰黄
    # 164，155，108
    # 右边橘色
    # 195，150，60

    # 字体路径
    font_path = './data/battlefield/font/BFText-Regular-SC-19cf572c.ttf'
    # font_path = r'C:\Windows\Fonts\simkai.ttf'
    font1 = ImageFont.truetype(font_path, 30)
    font2 = ImageFont.truetype(font_path, 38)
    font3 = ImageFont.truetype(font_path, 30)
    font4 = ImageFont.truetype(font_path, 20)
    font5 = ImageFont.truetype(font_path, 22)
    # name_font = ImageFont.truetype(font_path, 45)
    # content_font = ImageFont.truetype(font_path, 40)
    # 先制作左下角的文字
    draw.text((60, 810), wiki_item['codexEntry']['category'], (164, 155, 108), font=font1)
    draw.text((60, 850), wiki_item['name'], (164, 155, 108), font=font2)
    # 右边上面的文字
    draw.text((730, 40), wiki_item['codexEntry']['category'], font=font3)
    draw.text((730, 75), wiki_item['name'], (255, 255, 255), font=font2)
    draw.text((730, 133), wiki_item['criterias'][0]['name'], (195, 150, 60), font=font4)
    new_input = ""
    i = 0
    for letter in wiki_item['codexEntry']['description']:
        if letter == "\n":
            new_input += letter
            i = 0
        elif i * 11 % n_number == 0 or (i + 1) * 11 % n_number == 0:
            new_input += '\n'
            i = 0
        i += get_width(ord(letter))
        new_input += letter
    # draw.text((730, 160), re.sub(r"(.{32})", "\\1\n", wiki_item['codexEntry']['description']), font=font5)
    # draw.text((730, 160), wiki_item['codexEntry']['description'], font=font5)
    draw.text((730, 160), new_input, font=font5)
    bg_img.save(item_path, 'png', quality=100)
    await app.send_message(group, MessageChain(
        GraiaImage(path=item_path)
    ), quote=source)
    return True


@listen(MemberJoinEvent)
async def auto_modify(app: Ariadne, event: MemberJoinEvent):
    member = event.member
    group = event.member.group
    if not module_controller.if_module_switch_on(channel.module, group):
        return
    target_app, target_group = await account_controller.get_app_from_total_groups(group.id, ["Administrator", "Owner"])
    if not (target_app and target_group):
        return
    if app.account != target_app.account:
        return
    app = target_app
    group = target_group
    bind_result = record.check_bind(member.id)
    if bind_result:
        try:
            player_name_bind = await record.get_bind_name(member.id)
            await app.modify_member_info(member, MemberInfo(name=player_name_bind))
            return await app.send_message(group, MessageChain(
                At(member), f"已自动将你的名片修改为:{player_name_bind}!"
            ))
        except Exception as e:
            logger.error(e)
