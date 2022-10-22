# 用于公共查询的账号信息
import asyncio
import json
import os

import httpx
import requests
from loguru import logger

true = True
false = False
null = ''
client = httpx.AsyncClient()

# 这里的1003517866915是一个用来支持战绩查询的账号pid
async def auto_refresh_account(player_pid: str = "1003517866915"):
    global client
    # with open(os.getcwd().replace(f"modules\Battlefield",
    #                               fr"\data\battlefield\managerAccount\{player_pid}\account.json"), 'r'
    #         , encoding='utf-8') as file_temp1:
    logger.warning(f"刷新[{player_pid}]session中")
    with open(fr".\data\battlefield\managerAccount\{player_pid}\account.json", 'r'
            , encoding='utf-8') as file_temp1:
        data_temp = json.load(file_temp1)
        remid = data_temp["remid"]
        sid = data_temp["sid"]
    # 获取token
    url = 'https://accounts.ea.com/connect/auth?client_id=ORIGIN_JS_SDK&response_type=token&redirect_uri=nucleus%3Arest&prompt=none&release_type=prod'
    header = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/86.0.4240.193 Safari/537.36',
        'ContentType': 'application/json',
        'Cookie': f'remid={remid}; sid={sid}'
    }
    # async with httpx.AsyncClient() as client:
    response = await client.get(url, headers=header)
    try:  # print(response.text)
        logger.warning(response.text)
        token = eval(response.text)["access_token"]
        # print(token)
    except Exception as e:
        return response.text

    # 获取authcode
    url2 = "https://accounts.ea.com/connect/auth?access_token=" + token + "&client_id=sparta-backend-as-user-pc&response_type=code&release_type=prod"
    header2 = {
        "UserAgent": "Mozilla / 5.0 EA Download Manager Origin/ 10.5.94.46774",
        'Cookie': f'remid={remid}; sid={sid}',
        "localeInfo": "zh_TW",
        "X-Origin-Platform": "PCWIN"
    }
    # async with httpx.AsyncClient() as client:
    response2 = await client.get(url2, headers=header2)
    logger.warning(response2.text)
    authcode = response2.headers['location']
    authcode = authcode[authcode.rfind('=') + 1:]
    # print(authcode)

    # 获取session
    url3 = 'https://sparta-gw.battlelog.com/jsonrpc/pc/api?Authentication.getEnvIdViaAuthCode'
    body = {
        "jsonrpc": "2.0",
        "method": "Authentication.getEnvIdViaAuthCode",
        "params": {
            "authCode": "%s" % authcode,
            "locale": "zh-tw",
        },
        "id": "086ca921-02bb-42a0-8df5-df9087da0a5c"
    }
    header3 = {
        "Host": "sparta-gw.battlelog.com",
        "Content-Length": "291",
        # "Content-Length": str(len(body)),
        "Connection": "close",
        "User-Agent": "ProtoHttp 1.3/DS 15.1.2.1.0 (Windows)",
        "X-Guest": "no-session-id",
        "X-ClientVersion": "release-bf1-lsu35_26385_ad7bf56a_tunguska_all_prod",
        "X-DbId": "Tunguska.Shipping2PC.Win32",
        "X-CodeCL": "3779779",
        "X-DataCL": "3779779",
        "X-SaveGameVersion": "26",
        "X-HostingGameId": "tunguska",
        "X-Sparta-Info": "tenancyRootEnv = unknown;tenancyBlazeEnv = unknown",
    }
    response3 = requests.post(url3, headers=header3, data=json.dumps(body))
    # print(response3.text)
    true = True
    null = ''
    session = eval(response3.text)["result"]["sessionId"]
    with open(fr".\data\battlefield\managerAccount\{player_pid}\session.json", 'w'
            , encoding="utf-8") as file_temp2:
        dict_temp = {"session": session}
        json.dump(dict_temp, file_temp2, indent=4)
        return "刷新成功"

# asyncio.run(auto_refresh_account())
