import json
import httpx
from creart import create
from core.config import GlobalConfig

global_config = create(GlobalConfig)
default_account = global_config.functions.get("bf1").get("default_account", 0)
true = True
false = False
null = ''


async def tyc_bfeac_api(player_name):
    check_eacInfo_url = f"https://api.bfeac.com/case/EAID/{player_name}"
    header = {
        "Connection": "keep-alive"
    }
    async with httpx.AsyncClient() as client:
        response = await client.get(check_eacInfo_url, headers=header, timeout=10)
    return response


# 根据玩家名字查找pid
async def getPid_byName(player_name: str) -> dict:
    """
    通过玩家的名字来获得pid
    :param player_name: 玩家姓名
    :return: pid-dict
    """
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
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=header, timeout=5)
    token = eval(response.text)["access_token"]

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
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=head, timeout=5)
    response = response.text
    return eval(response)
