import os
import json
import uuid
from typing import Union

import httpx
from loguru import logger

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
error_code_dict = {
    -32501: "Session无效",
    -32600: "请求格式错误",
    -32601: "请求参数错误",
    -32602: "请求参数错误/不存在",
    -32603: "所用账号没有进行该操作的权限",
    -32855: "Sid不存在",
    -32856: "玩家不存在,请检查玩家名字",
    -32850: "服务器栏位已满/玩家已在栏位",
    -32857: "所用账号没有进行该操作的权限",
    # -32858: "服务器未开启!"
}
error_message_dict = {
    'ServerNotRestartableException': "服务器未开启",
    'InvalidLevelIndexException': "地图编号无效",
    'Invalid Params: no valid session': "session无效,请尝试使用-refresh进行刷新",
    "Invalid Request": "请求格式错误",
    "Method not found": "method不存在",
    "Internal Error: org.apache.thrift.TApplicationException": "无效操作/无权限操作",
    "Internal Error: java.lang.NumberFormatExceptioncom.fasterxml.jackson.core.JsonParseException": "后端错误",
    "Could not find gameserver.": "服务器不存在",
    "RspErrUserIsAlreadyVip()": "该玩家已是vip",
}
true = True
false = False
null = ''

limits = httpx.Limits(max_keepalive_connections=None, max_connections=None)
client = httpx.AsyncClient(limits=limits)


# 生成并返回一个uuid
async def get_a_uuid() -> str:
    uuid_result = str(uuid.uuid4())
    return uuid_result


# 检查一个字符串是否是uuid
def check_uuid4(test_uuid: str, version=4) -> bool:
    """
    传入字符串,返回是否是uuid
    :param test_uuid: str
    :param version: 默认参数
    :return: bool
    """
    try:
        return uuid.UUID(test_uuid).version == version
    except ValueError:
        return False


async def refresh_api_client():
    global client
    del client
    client = httpx.AsyncClient(limits=limits)


# 获取主session
async def get_main_session():
    """
    获取主session
    :return: session
    """
    file_path = os.getcwd().replace("\\modules\\bf1服管",
                                    "") + f'\\data\\battlefield\\managerAccount\\1003517866915\\session.json'
    with open(file_path, 'r', encoding="utf-8") as file_temp2:
        session = json.load(file_temp2)["session"]
        return session


# 搜服务器
async def search_server_by_name(server_name: str) -> list:
    """
    根据服务器名字搜索服务器,api最多返回200个数据
    :param server_name: 服务器名字
    :return: 服务器列表,如果没搜到则为空列表
    """
    session = await get_main_session()
    bf_aip_header["X-Gatewaysession"] = session
    filterJson = {
        # 默认参数
        # "version": 6,
        # "vehicles": {"L": "on",
        #              "A": "on"},
        # "weaponClasses": {"M": "on",
        #                   "S": "on",
        #                   "H": "on",
        #                   "E": "on",
        #                   "LMG": "on",
        #                   "SMG": "on",
        #                   "SAR": "on",
        #                   "SR": "on",
        #                   "KG": "on",
        #                   "SIR": "off"},
        # "slots": {"oneToFive": "on",
        #           "sixToTen": "on"},
        # "kits": {"1": "on",
        #          "2": "on",
        #          "3": "on",
        #          "4": "on",
        #          "HERO": "on"},
        # "misc": {"KC": "on",
        #          "MM": "on",
        #          "FF": "off",
        #          "RH": "on",
        #          "3S": "on",
        #          "MS": "on",
        #          "F": "off",
        #          "NT": "on",
        #          "3VC": "on",
        #          "SLSO": "off",
        #          "BH": "on",
        #          "RWM": "off",
        #          "MV": "on",
        #          "BPL": "off",
        #          "AAR": "on",
        #          "AAS": "on",
        #          "LL": "off",
        #          "LNL": "off",
        #          "UM": "off",
        #          "DSD": "off",
        #          "DTB": "off"},
        # "scales": {"BD2": "on",
        #            "TC2": "on",
        #            "SR2": "on",
        #            "VR2": "on",
        #            "RT1": "on"},
        "name": f"{server_name}"}
    body = {
        "jsonrpc": "2.0",
        "method": "GameServer.searchServers",
        "params": {
            "filterJson": json.dumps(filterJson),
            "game": "tunguska",
            "limit": 200,
        },
        "id": await get_a_uuid()
    }
    try:
        # async with httpx.AsyncClient() as client:
        response = await client.post(bf_aip_url, headers=bf_aip_header, data=json.dumps(body), timeout=3)
    except:
        return "timed out"
    response = response.text
    return eval(response)["result"]["gameservers"]


# 获取服务器信息
async def get_server_details(server_gameid: str) -> dict or str:
    """
    根据服务器gameid获得服务器信息
    :param server_gameid: 服务器gameid
    :return: 如果gameid正确，返回字典，错误则返回''
    """
    session = await get_main_session()
    bf_aip_header["X-Gatewaysession"] = session
    body = {
        "jsonrpc": "2.0",
        "method": "GameServer.getServerDetails",
        "params": {
            "game": "tunguska",
            "gameId": server_gameid
        },
        "id": await get_a_uuid()
    }
    try:
        # async with httpx.AsyncClient() as client:
        response = await client.post(bf_aip_url, headers=bf_aip_header, data=json.dumps(body), timeout=3)
        response = response.text
    except:
        return ""
    try:
        return eval(response)["result"]
    except:
        return ''


# 获取服务器详细信息
async def get_server_fulldetails(server_gameid: str) -> dict or str:
    """
    根据服务器gameid获得服务器的详细信息
    :param server_gameid: 服务器gameid
    :return: 字典,如果gameid错误返回''
    """
    session = await get_main_session()
    bf_aip_header["X-Gatewaysession"] = session
    body = {
        "jsonrpc": "2.0",
        "method": "GameServer.getFullServerDetails",
        "params": {
            "game": "tunguska",
            "gameId": server_gameid
        },
        "id": await get_a_uuid()
    }
    try:
        # async with httpx.AsyncClient() as client:
        response = await client.post(bf_aip_url, headers=bf_aip_header, data=json.dumps(body), timeout=5)
    except:
        return ''
    response = response.text
    try:
        return eval(response)["result"]
    except:
        return ''


# 获取服务器rsp信息
async def rsp_getServerDetails(server_id: int, session: str) -> dict or str:
    """
    使用管理账号获取服务器的rsp信息
    :param session: 管理session
    :param server_id: 服务器serverid
    :return: 正常返回字dict，错误返回str
    """
    bf_aip_header["X-Gatewaysession"] = session
    body = {
        "jsonrpc": "2.0",
        "method": "RSP.getServerDetails",
        "params": {
            "game": "tunguska",
            "serverId": server_id
        },
        "id": await get_a_uuid()
    }
    # async with httpx.AsyncClient() as client:
    response = await client.post(bf_aip_url, headers=bf_aip_header, data=json.dumps(body), timeout=3)
    response = response.text
    try:
        return eval(response)["result"]
    except KeyError:
        code = eval(response)["error"]['code']
        return error_code_dict[code]
    except:
        return "未知错误"


# 添加服务器管理员
async def rsp_addServerAdmin(server_id: int, session: str, player_name: str) -> dict or str:
    """
    添加服务器管理员-需要服主账号
    :param server_id: 服务器serverid
    :param session: session
    :param player_name: 玩家名字
    :return: 成功返回dict,失败返回信息str
    """
    bf_aip_header["X-Gatewaysession"] = session
    body = {
        "jsonrpc": "2.0",
        "method": "RSP.addServerAdmin",
        "params": {
            "game": "tunguska",
            "serverId": server_id,
            # "personaId": player_pid,
            "personaName": player_name
        },
        "id": await get_a_uuid()
    }
    # async with httpx.AsyncClient() as client:
    response = await client.post(bf_aip_url, headers=bf_aip_header, data=json.dumps(body), timeout=3)
    response = response.text
    try:
        return eval(response)["result"]
    except KeyError:
        code = eval(response)["error"]['code']
        error_message = eval(response)['error']['message']
        try:
            try:
                error_message = error_message_dict[error_message]
                return f"{error_code_dict[code]}\n错误信息:{error_message}"
            except:
                return f"{error_code_dict[code]}"
        except KeyError:
            return f"未知错误:{code}\n错误信息:{error_message}"
    except:
        return "未知错误"


# 删除服务器管理员
async def rsp_removeServerAdmin(server_id: int, session: str, player_pid: int) -> dict or str:
    """
    删除服务器管理员
    :param server_id: 服务器serverid
    :param session: session
    :param player_pid: 玩家pid
    :return:
    """
    bf_aip_header["X-Gatewaysession"] = session
    body = {
        "jsonrpc": "2.0",
        "method": "RSP.removeServerAdmin",
        "params": {
            "game": "tunguska",
            "serverId": server_id,
            "personaId": player_pid,
            # "personaName": player_name
        },
        "id": await get_a_uuid()
    }
    # async with httpx.AsyncClient() as client:
    response = await client.post(bf_aip_url, headers=bf_aip_header, data=json.dumps(body), timeout=10)
    response = response.text
    try:
        return eval(response)["result"]
    except KeyError:
        code = eval(response)["error"]['code']
        error_message = eval(response)['error']['message']
        try:
            try:
                error_message = error_message_dict[error_message]
                return f"{error_code_dict[code]}\n错误信息:{error_message}"
            except:
                return f"{error_code_dict[code]}"
        except KeyError:
            return f"未知错误:{code}\n错误信息:{error_message}"
    except:
        return "未知错误"


# 踢人
async def rsp_kickPlayer(server_gameid: str, session: str, player_pid: int, reason: str) -> dict or str:
    """
    从服务器踢出玩家，只能用玩家pid
    :param server_gameid: 服务器gameid
    :param reason: 踢出原因
    :param session: session
    :param player_pid: 玩家pid
    :return: 踢出成功返回dict，失败返回信息
    """
    bf_aip_header["X-Gatewaysession"] = session
    body = {
        "jsonrpc": "2.0",
        "method": "RSP.kickPlayer",
        "params": {
            "game": "tunguska",
            "gameId": server_gameid,
            "personaId": player_pid,
            "reason": reason
            # "personaName": player_name
        },
        "id": await get_a_uuid()
    }
    # async with httpx.AsyncClient() as client:
    response = await client.post(bf_aip_url, headers=bf_aip_header, data=json.dumps(body), timeout=10)
    response = response.text
    try:
        return eval(response)["result"]
    except KeyError:
        code = eval(response)["error"]['code']
        error_message = eval(response)['error']['message']
        try:
            try:
                error_message = error_message_dict[error_message]
                return f"{error_code_dict[code]}\n错误信息:{error_message}"
            except:
                return f"{error_code_dict[code]}"
        except KeyError:
            return f"未知错误:{code}\n错误信息:{error_message}"
    except:
        return "未知错误"


# 添加ban
async def rsp_addServerBan(server_id: int, session: str, player_name: str = None,
                           player_pid: str = None) -> dict or str:
    """
    为服务器添加ban位，玩家名字和玩家pid都可以
    :param player_pid: 玩家pid
    :param server_id: 服务器serverid
    :param session: session
    :param player_name: 玩家名字
    :return:
    """
    if not check_uuid4(session):
        return session
    bf_aip_header["X-Gatewaysession"] = session
    if not player_pid:
        body = {
            "jsonrpc": "2.0",
            "method": "RSP.addServerBan",
            "params": {
                "game": "tunguska",
                "serverId": server_id,
                "personaName": player_name,
            },
            "id": await get_a_uuid()
        }
    else:
        body = {
            "jsonrpc": "2.0",
            "method": "RSP.addServerBan",
            "params": {
                "game": "tunguska",
                "serverId": server_id,
                "personaId": player_pid,
                # "personaName": player_name
            },
            "id": await get_a_uuid()
        }
    try:
        # async with httpx.AsyncClient() as client:
        response = await client.post(bf_aip_url, headers=bf_aip_header, data=json.dumps(body), timeout=10)
    except:
        return "网络出错!"
    response = response.text
    try:
        return eval(response)["result"]
    except KeyError:
        code = eval(response)["error"]['code']
        error_message = eval(response)['error']['message']
        try:
            try:
                error_message = error_message_dict[error_message]
                return f"{error_code_dict[code]}\n错误信息:{error_message}"
            except:
                return f"{error_code_dict[code]}"
        except KeyError:
            return f"未知错误:{code}\n错误信息:{error_message}"
    except Exception as e:
        return f"未知错误:{e}"


# 移除ban
async def rsp_removeServerBan(server_id: int, session: str, player_pid: str) -> dict or str:
    """
    为服务器移除ban位，只能用玩家pid
    :param player_pid: 玩家pid
    :param server_id: 服务器serverid
    :param session: session
    :return: 成功返回dict,失败返回str
    """
    if not check_uuid4(session):
        return session
    bf_aip_header["X-Gatewaysession"] = session
    body = {
        "jsonrpc": "2.0",
        "method": "RSP.removeServerBan",
        "params": {
            "game": "tunguska",
            "serverId": server_id,
            "personaId": player_pid
        },
        "id": await get_a_uuid()
    }
    try:
        # async with httpx.AsyncClient() as client:
        response = await client.post(bf_aip_url, headers=bf_aip_header, data=json.dumps(body), timeout=10)
    except:
        return "网络错误!"
    response = response.text
    try:
        return eval(response)["result"]
    except KeyError:
        code = eval(response)["error"]['code']
        error_message = eval(response)['error']['message']
        try:
            try:
                error_message = error_message_dict[error_message]
                return f"{error_code_dict[code]}\n错误信息:{error_message}"
            except:
                return f"{error_code_dict[code]}"
        except KeyError:
            return f"未知错误:{code}\n错误信息:{error_message}"
    except:
        return "未知错误"


# 添加vip
async def rsp_addServerVip(server_id: int, session: str, player_name: str) -> dict or str:
    """
    添加服务器vip
    :param server_id: 服务器serverid
    :param session: session
    :param player_name: 玩家名字
    :return: 成功返回dict,失败返回str
    """
    bf_aip_header["X-Gatewaysession"] = session
    body = {
        "jsonrpc": "2.0",
        "method": "RSP.addServerVip",
        "params": {
            "game": "tunguska",
            "serverId": server_id,
            "personaName": player_name
        },
        "id": await get_a_uuid()
    }
    # async with httpx.AsyncClient() as client:
    response = await client.post(bf_aip_url, headers=bf_aip_header, data=json.dumps(body), timeout=10)
    response = response.text
    try:
        return eval(response)["result"]
    except KeyError:
        code = eval(response)["error"]['code']
        error_message = eval(response)['error']['message']
        try:
            try:
                error_message = error_message_dict[error_message]
                return f"{error_code_dict[code]}\n错误信息:{error_message}"
            except:
                return f"{error_code_dict[code]}"
        except KeyError:
            return f"未知错误:{code}\n错误信息:{error_message}"
    except:
        return "未知错误"


# 移除vip
async def rsp_removeServerVip(server_id: int, session: str, player_pid: str) -> dict or str:
    """
    移除服务器vip，只能用玩家pid
    :param server_id:serverid
    :param session: session
    :param player_pid: 玩家pid
    :return: 成功返回dict,失败返回str
    """
    bf_aip_header["X-Gatewaysession"] = session
    body = {
        "jsonrpc": "2.0",
        "method": "RSP.removeServerVip",
        "params": {
            "game": "tunguska",
            "serverId": server_id,
            "personaId": player_pid
        },
        "id": await get_a_uuid()
    }
    # async with httpx.AsyncClient() as client:
    response = await client.post(bf_aip_url, headers=bf_aip_header, data=json.dumps(body), timeout=10)
    response = response.text
    try:
        return eval(response)["result"]
    except KeyError:
        code = eval(response)["error"]['code']
        error_message = eval(response)['error']['message']
        try:
            try:
                error_message = error_message_dict[error_message]
                return f"{error_code_dict[code]}\n错误信息:{error_message}"
            except:
                return f"{error_code_dict[code]}"
        except KeyError:
            return f"未知错误:{code}\n错误信息:{error_message}"
    except:
        return "未知错误"


# 换边
async def rsp_movePlayer(server_gameid: str, session: str, player_pid: int, index: int = 0) -> str:
    """
    挪人
    :param player_pid: 玩家pid
    :param session: session
    :param server_gameid: 服务器gameid
    :param index: 不用
    :return: str
    """
    global client
    if index == 0:
        # 获取服务器玩家名单
        # async with httpx.AsyncClient() as client:
        response = await client.get("https://api.gametools.network/bf1/players/?gameid=" + server_gameid, timeout=10)
        player_list_html = response.text
        if player_list_html == 404:
            return "获取玩家列表失败!"
        elif player_list_html == "":
            return "获取玩家列表失败!"
        player_list_html = eval(player_list_html)
        if player_list_html == 404:
            return "获取玩家列表失败!"
        elif player_list_html == {}:
            return "获取玩家列表失败!"
        elif player_list_html == "":
            return "获取玩家列表失败!"
        team1_list = []
        team2_list = []
        if len(player_list_html["teams"][0]["players"]) == 0:
            pass
        else:
            for item in player_list_html["teams"][0]["players"]:
                team1_list.append(item["player_id"])
        if len(player_list_html["teams"][1]["players"]) == 0:
            pass
        else:
            for item in player_list_html["teams"][1]["players"]:
                team2_list.append(item["player_id"])
        if player_pid in team1_list:
            index = 1
        if player_pid in team2_list:
            index = 2
        if index == 0:
            return "未在服务器内找到该玩家"
        logger.warning(f"目标队伍:{index}")
    # 编辑body
    body = {
        "jsonrpc": "2.0",
        "method": "RSP.movePlayer",
        "params": {
            "game": "tunguska",
            "gameId": "%s" % server_gameid,
            # 玩家所在的队伍id!!!
            "teamId": index,
            "personaId": player_pid,
            "forceKill": true,
            "moveParty": false
        },
        "id": await get_a_uuid()
    }
    bf_aip_header["X-Gatewaysession"] = session
    # async with httpx.AsyncClient() as client:
    response = await client.post(bf_aip_url, headers=bf_aip_header, data=json.dumps(body), timeout=5)
    response = response.text
    try:
        result = eval(response)["result"]["success"]
        if result:
            return "成功更换至队伍:%s" % index
        else:
            return "执行失败"
    except:
        code = eval(response)["error"]['code']
        error_message = eval(response)['error']['message']
        try:
            try:
                error_message = error_message_dict[error_message]
                return f"{error_code_dict[code]}\n错误信息:{error_message}"
            except:
                return f"{error_code_dict[code]}"
        except KeyError:
            return f"未知错误:{code},可能服务器未开启!\n错误信息:{error_message}"


# 换图
async def rsp_changeMap(server_guid: str, session: str, index: Union[int, str]):
    """
    更换服务器地图
    :param server_guid: 服务器guid
    :param session: session
    :param index: 地图序号
    :return: 成功-dict,失败-str
    """
    body = {
        "jsonrpc": "2.0",
        "method": "RSP.chooseLevel",
        "params": {
            "game": "tunguska",
            "persistedGameId": "%s" % server_guid,
            "levelIndex": "%s" % index,
        },
        "id": await get_a_uuid()
    }
    bf_aip_header["X-Gatewaysession"] = session
    try:
        # async with httpx.AsyncClient() as client:
        response = await client.post(bf_aip_url, headers=bf_aip_header, data=json.dumps(body), timeout=5)
    except:
        return "网络超时!"
    response = response.text
    try:
        return eval(response)["result"]
    except KeyError:
        code = eval(response)["error"]['code']
        error_message = eval(response)['error']['message']
        try:
            try:
                error_message = error_message_dict[error_message]
                return f"{error_code_dict[code]}\n错误信息:{error_message}"
            except:
                return f"{error_code_dict[code]}"
        except KeyError:
            return f"未知错误:{code},可能服务器未开启!\n错误信息:{error_message}"
    except:
        return "未知错误"
