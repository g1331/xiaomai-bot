# 根据玩家名字查找pid
import json
import time
import uuid
from pathlib import Path

import aiofiles
import httpx
import yaml
from creart import create
from loguru import logger

from core.config import GlobalConfig

global_config = create(GlobalConfig)
default_account = global_config.bf1.get("default_account", 0)
limits = httpx.Limits(max_keepalive_connections=None, max_connections=None)
client = httpx.AsyncClient(limits=limits)
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
    "Connection": "Keep-Alive"
}

true = True
false = False
null = ''
access_token = None
access_token_time = None
access_token_expires_time = 0
blocked_acc_path = Path.cwd().parent / "blocked.yaml"


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
    head = {  # 头部信息
        "Host": "gateway.ea.com",
        "Connection": "keep-alive",
        "Accept": "application/json",
        "X-Expand-Results": "true",
        "Authorization": f"Bearer {token}",
        "Accept-Encoding": "deflate",
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


async def get_session() -> str:
    """
    获取主session
    :return: session
    """
    file_path = f'./data/battlefield/managerAccount/{default_account}/session.json'
    async with aiofiles.open(file_path, 'r', encoding="utf-8") as file_temp:
        session = json.loads(await file_temp.read())["session"]
        return session


# 获取玩家正在游玩的服务器
async def server_playing(player_pid: str) -> str:
    global bf_aip_header, bf_aip_url, client
    session = await get_session()
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


async def app_blocked(account: int):
    async with aiofiles.open(blocked_acc_path, "r", encoding="utf-8") as file:
        acc_data = yaml.safe_load(await file.read())
        return account in acc_data["accounts"]
