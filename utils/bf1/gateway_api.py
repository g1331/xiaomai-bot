import asyncio
import json
import time
import uuid
from typing import Union

import aiohttp
import httpx
from loguru import logger


async def get_a_uuid() -> str:
    """返回一个uuid"""
    return str(uuid.uuid4())


class bf1_api(object):

    def __init__(self, pid: int, remid: str = None, sid: str = None, session: str = None):
        self.pid = pid
        self.remid = remid
        self.sid = sid
        self.session = session
        self.check_login = False
        self.access_token = None
        self.authcode = None
        # 获取token的时间
        self.access_token_time = time.time()
        # token过期的时间
        self.access_token_expires_time = 0
        self.BB_PREFIX = "https://eaassets-a.akamaihd.net/battlelog/battlebinary"
        self.api_url = 'https://sparta-gw.battlelog.com/jsonrpc/pc/api'
        self.api_header = {
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
        self.body = {
            "jsonrpc": "2.0",
            "method": str,
            "params": {
                "game": "tunguska"
            },
            "id": str
        }
        self.error_code_dict = {
            -32501: "Session失效",
            -32504: "连接超时",
            -34501: "找不到服务器",
            -32601: "方法不存在",
            -32602: "请求无效/格式错误",
            -35150: "战队不存在",
            -35160: "无权限",
            -32603: "此code为多个错误共用,请查阅error_msg_dict",
            # -32850: "服务器栏位已满/玩家已在栏位",
            -32851: "服务器不存在/已过期",
            -32856: "玩家不存在",
            -32857: "无法处置管理员",
            -32858: "服务器未开启",
        }
        self.error_msg_dict = {
            "Internal Error: org.apache.thrift.TApplicationException": "一般错误/无权限/无法处置管理员",
            "Internal Error: java.lang.NumberFormatException": "EA后端未知错误",
            "Internal Error: java.lang.NullPointerException": "EA后端未知错误",
            "Invalid Params: no valid session": "Session无效",
            "Authentication failed": "登录失败",
            "com.fasterxml.jackson.core.JsonParseException": "JSON解析失败",
            "RspErrInvalidMapRotationId()": "地图组不存在",
            "ServerNotRestartableException": "服务器未开启",
            "InvalidLevelIndexException": "地图编号无效",
            "RspErrUserIsAlreadyVip()": "玩家已经是VIP了",
        }
        self.filter_dict = {
            # 所有值都是可选的, 要什么写什么就行, 在getGameData有详细的
            "name": "",  # 服务器名
            "serverType": {  # 服务器类型
                "OFFICIAL": "on",  # 官服
                "RANKED": "on",  # 私服
                "UNRANKED": "on",  # 私服(不计战绩)
                "PRIVATE": "on"  # 密码服
            },
            "maps": {  # 地图
                "MP_MountainFort": "on",
                "MP_Forest": "on",
                "MP_ItalianCoast": "on",
                "MP_Chateau": "on",
                "MP_Scar": "on",
                "MP_Desert": "on",
                "MP_Amiens": "on",
                "MP_London": "on",
                "MP_Blitz": "on",
                "MP_Alps": "on",
                "MP_River": "on",
                "MP_Hell": "on",
                "MP_Offensive": "on",
                "MP_Ridge": "on",
                "MP_Naval": "on",
                "MP_Harbor": "on",
                "MP_Beachhead": "on",
                "MP_Volga": "on",
                "MP_Tsaritsyn": "on",
                "MP_Valley": "on",
                "MP_Ravines": "on",
                "MP_Suez": "on",
                "MP_FaoFortress": "on",
                "MP_Giant": "on",
                "MP_Fields": "on",
                "MP_Graveyard": "on",
                "MP_Underworld": "on",
                "MP_Verdun": "on",
                "MP_Trench": "on",
                "MP_ShovelTown": "on",
                "MP_Bridge": "on",
                "MP_Islands": "on"
            },
            "gameModes": {  # 模式
                "ZoneControl": "on",
                "AirAssault": "on",
                "TugOfWar": "on",
                "Domination": "on",
                "Breakthrough": "on",
                "Rush": "on",
                "TeamDeathMatch": "on",
                "BreakthroughLarge": "on",
                "Possession": "on",
                "Conquest": "on"
            },
            "vehicles": {  # 载具
                "L": "on",  # 地面
                "A": "on"  # 空中
            },
            "weaponClasses": {
                "M": "on",  # 刀
                "S": "on",  # 喷子
                "H": "on",  # 手枪
                "E": "on",  # 爆炸物
                "LMG": "on",  # 机枪
                "SMG": "on",  # 冲锋枪
                "SAR": "on",  # 半自动
                "SR": "on",  # 狙
                "KG": "on",  # 兵种装备
                "SIR": "off"  # 制式
            },
            "slots": {  # 空位
                "oneToFive": "on",  # 1-5
                "sixToTen": "on",  # 6-10
                "none": "on",  # 无
                "tenPlus": "on",  # 10+
                "all": "on",  # 全部
                "spectator": "on"  # 观战
            },
            "regions": {  # 地区
                "OC": "on",  # 大洋
                "Asia": "on",  # 亚
                "EU": "on",  # 欧
                "Afr": "on",  # 非
                "AC": "on",  # 南极洲(真有人吗)
                "SAm": "on",  # 南美
                "NAm": "on"  # 北美
            },
            "kits": {  # 兵种 四大兵种和精英
                "1": "on",
                "2": "on",
                "3": "on",
                "4": "on",
                "HERO": "on"
            },
            "misc": {  # 自己看getGameData去,懒得打了
                "KC": "on",
                "MM": "on",
                "FF": "off",
                "RH": "on",
                "3S": "on",
                "MS": "on",
                "F": "off",
                "NT": "on",
                "3VC": "on",
                "SLSO": "off",
                "BH": "on",
                "RWM": "off",
                "MV": "on",
                "BPL": "off",
                "AAR": "on",
                "AAS": "on",
                "LL": "off",
                "LNL": "off",
                "UM": "off",
                "DSD": "off",
                "DTB": "off"
            },
            "scales": {
                "BD2": "on",
                "TC2": "on",
                "SR2": "on",
                "VR2": "on",
                "RT1": "on"
            },
            "gameSizes": {  # 服务器最大人数
                "10": "on",
                "16": "on",
                "24": "on",
                "32": "on",
                "40": "on",
                "48": "on",
                "64": "on"
            },
            "tickRates": {  # 帧率
                "30": "on",
                "60": "on",
                "120": "on",
                "144": "on"
            }
        }

    # api调用
    async def check_session_expire(self) -> bool:
        """过期返回True,否则返回False"""
        if not self.session:
            return True
        if (not self.remid) or (not self.pid):
            data = await self.Companion_isLoggedIn()
            if not data.get('result').get('isLoggedIn'):
                self.check_login = False
                return True
            else:
                self.check_login = True
                return False
        return (
                not self.check_login
                or self.access_token is None
                or (time.time() - self.access_token_time)
                >= int(self.access_token_expires_time)
        )

    async def get_session(self) -> str:
        if (not self.remid) or (not self.pid):
            # logger.warning(f"BF1账号{self.pid}未登录!请传入remid和sid使用login进行登录!")
            return str(self.session)
        if await self.check_session_expire():
            return str(await self.login(self.remid, self.sid))
        else:
            return str(self.session)

    async def get_api_header(self) -> dict:
        self.api_header["X-Gatewaysession"] = await self.get_session()
        return self.api_header

    async def api_call(self, body: dict) -> Union[dict, str]:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                        url=self.api_url,
                        headers=await self.get_api_header(),
                        data=json.dumps(body),
                        timeout=10,
                        ssl=False
                ) as response:
                    return await self.error_handle(await response.json())
        except asyncio.exceptions.TimeoutError:
            return "网络超时!"

    # 玩家信息相关
    async def login(self, remid: str, sid: str) -> str:
        """
        使用remid和sid登录，返回session
        :param remid: 玩家登录时cookie的remid
        :param sid: 玩家登录时cookie的sid
        :return: 成功登录后的session
        """
        logger.debug(f"BF1账号{self.pid}登录ing\nremid={remid}\nsid={sid}")
        self.remid = remid
        self.sid = sid
        # 获取access_token
        url = 'https://accounts.ea.com/connect/auth?client_id=ORIGIN_JS_SDK&response_type=token&redirect_uri=nucleus%3Arest&prompt=none&release_type=prod'
        header = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/86.0.4240.193 Safari/537.36',
            'ContentType': 'application/json',
            'Cookie': f'remid={self.remid}; sid={self.sid}'
        }
        async with aiohttp.ClientSession() as session:
            response = await session.get(
                url=url,
                headers=header,
                timeout=10,
                ssl=False
            )
        try:
            res = eval(await response.text())
            logger.debug(res)
            self.access_token = res["access_token"]
            self.access_token_expires_time = res["expires_in"]
            logger.success(f"获取access_token成功!access_token:{self.access_token}")
        except Exception as e:
            logger.error(e)
            logger.error(await response.text())
            logger.error(f"BF1账号{self.pid}登录刷新session失败!")
            return await response.text()
        # 获取authcode
        url2 = f"https://accounts.ea.com/connect/auth?access_token={self.access_token}&client_id=sparta-backend-as-user-pc&response_type=code&release_type=prod"
        header2 = {
            "UserAgent": "Mozilla / 5.0 EA Download Manager Origin/ 10.5.94.46774",
            'Cookie': f'remid={self.remid}; sid={self.sid}',
            "localeInfo": "zh_TW",
            "X-Origin-Platform": "PCWIN"
        }
        try:
            async with httpx.AsyncClient() as client:
                response2 = await client.get(url2, headers=header2)
            authcode = response2.headers['location']
            authcode = authcode[authcode.rfind('=') + 1:]
            logger.success(f"获取authcode成功!authcode:{authcode}")
        except Exception as e:
            logger.error(f"获取authcode失败!{e}")
            return None
        # 使用authcode登录获取session
        login_info = await self.Authentication_getEnvIdViaAuthCode(authcode)
        # 如果返回的是str说明出错了
        if isinstance(login_info, str):
            logger.error(login_info)
            logger.error(f"BF1账号:{self.pid}登录刷新session失败!")
            return await response.text()
        self.session = login_info.get("result", {}).get("sessionId")
        self.pid = login_info.get("result", {}).get("personaId")
        self.access_token_time = time.time()
        self.check_login = True
        logger.success(f"BF1账号{self.pid}登录并获取session成功!")
        from utils.bf1.database import BF1DB
        await BF1DB.bf1account.update_bf1account_loginInfo(int(self.pid), self.remid, self.sid, self.session)
        return self.session

    async def getBlazeAuthcode(self, remid: str = None, sid: str = None) -> str:
        if not remid:
            remid = self.remid
        if not sid:
            sid = self.sid
        url = 'https://accounts.ea.com/connect/auth?client_id=GOS-BlazeServer-BFTUN-PC&response_type=code&prompt=none'
        header = {
            'Connection': 'keep-alive',
            'User-Agent': 'Mozilla/5.0 EA Download Manager Origin/10.5.88.45577',
            'Host': 'accounts.ea.com',
            'Accept': '*/*',
            'X-Origin-Platform': 'PCWIN',
            'localeInfo': 'zh_TW',
            'Accept-Language': 'zh-TW',
            'Cookie': f'remid={remid}; sid={sid}'
        }
        async with aiohttp.ClientSession() as session:
            response = await session.get(
                url=url,
                headers=header,
                timeout=60,
                ssl=False
            )
        try:
            res = str(response.url)
            self.authcode = res.replace('http://127.0.0.1/success?code=', "")
            return self.authcode
        except Exception as e:
            logger.error(e)
            logger.error(await response.text())
            logger.error(f"BF1账号{self.pid}登录获取authcode失败!")
            return await response.text()

    async def Authentication_getEnvIdViaAuthCode(self, authcode) -> dict:
        """
        登录获取session和pid
        result:
            {
                sessionId: "",  //要用的SessionId
                personaId: ""   //所登录账号的pid
                ...
            }
        """
        body = {
            "jsonrpc": "2.0",
            "method": "Authentication.getEnvIdViaAuthCode",
            "params": {"authCode": f"{authcode}", "locale": "zh-tw"},
            "id": await get_a_uuid(),
        }
        header = {
            "Host": "sparta-gw.battlelog.com",
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
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(self.api_url, headers=header, data=json.dumps(body), timeout=10) as response:
                    return await self.error_handle(await response.json())
        except asyncio.exceptions.TimeoutError:
            return "网络超时!"

    async def Onboarding_welcomeMessage(self) -> dict:
        """
        欢迎信息
        :return:
        example:
            {
                'jsonrpc': '2.0',
                'id': '46314004-ed49-40e3-bce0-cc515500ad33',
                'result':
                    {
                        'firstMessage': 'SHlSAN13，快樂星期六。',
                        'secondMessage': None
                    }
            }
        """
        return await self.api_call(
            {
                "jsonrpc": "2.0",
                "method": "Onboarding.welcomeMessage",
                "params": {
                    "game": "tunguska",
                    "minutesToUTC": -480
                },
                "id": await get_a_uuid()
            }
        )

    async def getPersonasByName(self, player_name: str) -> dict:
        """
        根据名字获取Personas
        :param player_name:
        :return:
        """
        url = f"https://gateway.ea.com/proxy/identity/personas?namespaceName=cem_ea_id&displayName={player_name}"
        # 头部信息
        head = {
            "Host": "gateway.ea.com",
            "Connection": "keep-alive",
            "Accept": "application/json",
            "X-Expand-Results": "true",
            "Authorization": f"Bearer {self.access_token}",
            "Accept-Encoding": "deflate"
        }
        try:
            async with aiohttp.ClientSession() as session:
                response = await session.get(
                    url=url,
                    headers=head,
                    timeout=10,
                    ssl=False
                )
                return await response.json()
        except asyncio.exceptions.TimeoutError:
            return "网络超时!"

    async def getPersonasByIds(self, personaIds: list[Union[int, str]]) -> dict:
        """
        根据pid获取Personas
        :param personaIds: PID列表
        :return:
        example:
            {
                "result": {
                    "1004048906256": {
                        "platform": "pc",
                        "nucleusId": "1008047106256",
                        "personaId": "1004048906256",
                        "platformId": "1008047106256",
                        "displayName": "bilibili22",
                        "avatar": "https://secure.download.dm.origin.com/production/avatar/prod/userAvatar/31177301/208x208.PNG",
                        "accountId": "0"
                    }
                }
            }
        """
        return await self.api_call(
            {
                "jsonrpc": "2.0",
                "method": "RSP.getPersonasByIds",
                "params": {
                    "game": "tunguska",
                    "personaIds": personaIds if isinstance(personaIds, list) else [personaIds]
                },
                "id": await get_a_uuid()
            }
        )

    async def Companion_isLoggedIn(self):
        """
        检查是否登录
        :return:
            {
                'jsonrpc': '2.0',
                'id': '708ca124-0569-4c48-8457-9801f7250702',
                'result': {
                    'isLoggedIn': False,
                    'nucleusHost':
                    'accounts.ea.com',
                    'frontend': 'https://eaassets-a.akamaihd.net/battlelog/bfcompanionprod/static/main/bundles/4569f32f'
                }
            }
        """
        return await self.api_call(
            {
                "jsonrpc": "2.0",
                "method": "Companion.isLoggedIn",
                "id": await get_a_uuid()
            }
        )

    async def Companion_isLoggedIn_noLogin(self):
        body = {
            "jsonrpc": "2.0",
            "method": "Companion.isLoggedIn",
            "id": await get_a_uuid()
        }
        self.api_header["X-Gatewaysession"] = self.session
        logger.debug("调用api:Companion.isLoggedIn")
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                        url=self.api_url,
                        headers=self.api_header,
                        data=json.dumps(body),
                        timeout=10,
                        ssl=False
                ) as response:
                    return await self.error_handle(await response.json())
        except asyncio.exceptions.TimeoutError:
            return "网络超时!"

    # 返回数据前进行错误处理
    async def error_handle(self, data: dict) -> Union[dict, str]:
        """
        错误处理
            {
                "jsonrpc": "2.0",
                "id": "5550a321-f899-4912-8625-966f29a77a6a",
                "error": {
                    "message": "Invalid Params: no valid session",
                    "code": -32501
                }
            }
        :param data: api获得的返回数据
        :return: 成功:返回dict，失败:返回str
        """
        if not (error_data := data.get("error")):
            return data
        if error_msg := self.error_msg_dict.get(str(error_data.get("message")), error_data.get("message")):
            return error_msg
        elif error_msg := self.error_code_dict.get(error_data.get("code"), error_data.get("code")):
            if error_data.get("code") == -32501:
                self.check_login = False
                logger.warning(f"BF1账号{self.pid}session失效,尝试重新登录")
                await self.login(self.remid, self.sid)
            logger.error(error_msg)
            return error_msg
        else:
            error_msg = f"未知错误!code:{error_data.get('code')},msg:{error_data.get('message')}"
            logger.error(error_msg)
            return error_msg


class Game(bf1_api):
    """进出服务器"""

    async def reserveSlot(self, gameId: Union[int, str]) -> dict:
        """
        进入服务器
        :param gameId: 服务器gameId
        :return:
        """
        return await self.api_call(
            {
                "jsonrpc": "2.0",
                "method": "Game.reserveSlot",
                "params": {
                    "game": "tunguska",
                    "gameId": gameId,
                    "gameProtocolVersion": "3779779",
                    "currentGame": "tunguska",
                    "settings": {"role": "spectator"}
                },
                "id": await get_a_uuid()
            }
        )

    async def leaveGame(self, gameId: Union[int, str]) -> dict:
        """
        退出服务器
        :param gameId: 服务器gameId
        :return:
            {
                "jsonrpc": "2.0", //卡了可以用
                "id": "ce457dd1-1aec-4224-8988-96320310f022",
                "result": "success"
            }
        """
        return await self.api_call(
            {
                "jsonrpc": "2.0",
                "method": "Game.leaveGame",
                "params": {
                    "game": "tunguska",
                    "gameId": gameId,
                },
                "id": await get_a_uuid()
            }
        )


class Progression(bf1_api):

    async def getDogtagsByPersonaId(self, personaId: Union[int, str]) -> dict:
        """
        获取狗牌
        :param personaId: PID
        :return:
        example:
            {
                "jsonrpc": "2.0",
                "id": "d5c0a08c-5a23-45e5-916d-7986cae0814a",
                "result": [
                    {
                        "name": "進度",
                        "sortOrder": -1,
                        "dogtags": [
                            {
                                "name": "初顯身手",
                                "description": "我想我不小心攔截到要給其他人的訊息了。滿滿的密語和謎團，真是太有趣了。我實在無法忍住不多看幾眼。",
                                "index": 77,
                                "imageUrl": "[BB_PREFIX]/gamedata/Tunguska/25/80/df082-e75062ac.png",
                                "unlockId": "df082",
                                "category": "進度",
                                "progression": {
                                    "valueNeeded": 1.0,
                                    "valueAcquired": 1.0,
                                    "unlocked": true
                                },
                        ]
                    }
                ]
            }
        """
        return await self.api_call(
            {
                "jsonrpc": "2.0",
                "method": "Progression.getDogtagsByPersonaId",
                "params": {
                    "game": "tunguska",
                    "personaId": personaId
                },
                "id": await get_a_uuid()
            }
        )

    async def getMedalsByPersonaId(self, personaId: Union[int, str]) -> dict:
        """
        获取勋章
        :param personaId: PID
        :return:
        example:
            {
                "jsonrpc": "2.0",
                "id": "92308960-6f9d-4224-95b1-28a1afcb967b",
                "result": [
                    {
                        "name": "載具",
                        "awards": [
                            {
                                "code": "m05",
                                "name": "優異奧古斯都勳章",
                                "description": "進行坦克兵種專屬任務。",
                                "imageUrl": "[BB_PREFIX]/gamedata/tunguska/18/35/M05-ee23aa30.png",
                                "progression": {
                                    "valueNeeded": 1.0,
                                    "valueAcquired": 0.0,
                                    "unlocked": false
                                },
                                "unlocks": [],
                                "dependencies": [],
                                "stages": [
                                    {
                                        "code": "m05a",
                                        "name": "癱瘓 3 台履帶車",
                                        "description": "癱瘓 3 台履帶車",
                                        "imageUrl": "",
                                        "progression": {
                                            "valueNeeded": 1.0,
                                            "valueAcquired": 1.0,
                                            "unlocked": true
                                        },
                                        "unlocks": null,
                                        "dependencies": null,
                                        "stages": null,
                                        "criterias": [
                                            {
                                                "code": "c_m05a_vehTrack__m_g",
                                                "name": "",
                                                "awardName": null,
                                                "progression": {
                                                    "valueNeeded": 3.0,
                                                    "valueAcquired": 3.0,
                                                    "unlocked": true
                                                },
                                                "criteriaType": null
                                            }
                                        ],
                                        "codexEntry": null,
                                        "images": {
                                            "Png256xANY": "",
                                            "Small": ""
                                        },
                                        "expansions": [],
                                        "score": 5000,
                                        "dependencyRequired": null,
                                        "criteriaRequired": null
                                    },
        """
        return await self.api_call(
            {
                "jsonrpc": "2.0",
                "method": "Progression.getMedalsByPersonaId",
                "params": {
                    "game": "tunguska",
                    "personaId": personaId
                },
                "id": await get_a_uuid()
            }
        )

    async def getWeaponsByPersonaId(self, personaId: Union[int, str]) -> dict:
        """
        获取武器
        :param personaId: PID
        :return:
        example:
            {
                "jsonrpc": "2.0",
                "id": "92308960-6f9d-4224-95b1-28a1afcb967b",
                "result": [
                    {
                        "name": "載具",
                        "awards": [
                            {
                                "code": "m05",
                                "name": "優異奧古斯都勳章",
                                "description": "進行坦克兵種專屬任務。",
                                "imageUrl": "[BB_PREFIX]/gamedata/tunguska/18/35/M05-ee23aa30.png",
                                "progression": {
                                    "valueNeeded": 1.0,
                                    "valueAcquired": 0.0,
                                    "unlocked": false
                                },
                            ...
                        ]
                    }
                ]
            }
        """
        return await self.api_call(
            {
                "jsonrpc": "2.0",
                "method": "Progression.getWeaponsByPersonaId",
                "params": {
                    "game": "tunguska",
                    "personaId": personaId
                },
                "id": await get_a_uuid()
            }
        )

    async def getVehiclesByPersonaId(self, personaId: Union[int, str]) -> dict:
        """
        获取载具
        :param personaId: PID
        :return:
        example:
            {
                "jsonrpc": "2.0",
                "id": "92308960-6f9d-4224-95b1-28a1afcb967b",
                "result": [
                    {
                        "name": "載具",
                        "awards": [
                            {
                                "code": "m05",
                                "name": "優異奧古斯都勳章",
                                "description": "進行坦克兵種專屬任務。",
                                "imageUrl": "[BB_PREFIX]/gamedata/tunguska/18/35/M05-ee23aa30.png",
                                "progression": {
                                    "valueNeeded": 1.0,
                                    "valueAcquired": 0.0,
                                    "unlocked": false
                                },
                            ...
                        ]
                    }
                ]
            }
        """
        return await self.api_call(
            {
                "jsonrpc": "2.0",
                "method": "Progression.getVehiclesByPersonaId",
                "params": {
                    "game": "tunguska",
                    "personaId": personaId
                },
                "id": await get_a_uuid()
            }
        )


class ScrapExchange(bf1_api):
    async def getOffers(self) -> dict:
        """
        获取交换信息
        :return:
        """
        return await self.api_call(
            {
                "jsonrpc": "2.0",
                "method": "ScrapExchange.getOffers",
                "params": {
                    "game": "tunguska",
                },
                "id": await get_a_uuid()
            }
        )


class CampaignOperations(bf1_api):
    async def getPlayerCampaignStatus(self) -> dict:
        """
        获取战役信息
        :return:
        """
        return await self.api_call(
            {
                "jsonrpc": "2.0",
                "method": "CampaignOperations.getPlayerCampaignStatus",
                "params": {
                    "game": "tunguska",
                },
                "id": await get_a_uuid()
            }
        )


class Stats(bf1_api):
    async def detailedStatsByPersonaId(self, personaId: Union[int, str]) -> dict:
        """
        获取战绩
        :param personaId: PID
        :return:
        example:
            {
                "jsonrpc": "2.0",
                "id": "ecdadcc9-5702-43a1-a1ba-55c868b8c016",
                "result": {
                    "basicStats": {
                        "timePlayed": 1356380,
                        "wins": 847,
                        "losses": 969,
                        "kills": 25096,
                        "deaths": 27948,
                        "kpm": 1.11,
                        "spm": 1548.79,
                        "skill": 237.14,
                        "soldierImageUrl": "https://eaassets-a.akamaihd.net/battlelog/bb/bf4/soldier/large/ch-assault-oceanicgreen-425698c4.png",
                        "rank": null,
                        "rankProgress": null,
                        "freemiumRank": null,
                        "completion": [],
                        "highlights": null,
                        "highlightsByType": null,
                        "equippedDogtags": null
                    },
                    ...
                }
            }
        """
        return await self.api_call(
            {
                "jsonrpc": "2.0",
                "method": "Stats.detailedStatsByPersonaId",
                "params": {
                    "game": "tunguska",
                    "personaId": personaId
                },
                "id": await get_a_uuid()
            }
        )


class ServerHistory(bf1_api):
    async def mostRecentServers(self, personaId: Union[int, str]) -> dict:
        """
        最近游玩
        :param personaId: PID
        :return:
        example:
            {
                "jsonrpc": "2.0",
                "id": "76d4b1c7-bc92-46a3-8fc3-6846513edda3",
                "result": [
                    //游戏信息列表
                ]
            }
        """
        return await self.api_call(
            {
                "jsonrpc": "2.0",
                "method": "ServerHistory.mostRecentServers",
                "params": {
                    "game": "tunguska",
                    "personaId": personaId
                },
                "id": await get_a_uuid()
            }
        )


class Gamedata(bf1_api):
    async def getGameData(self) -> dict:
        """
        获取游戏信息
        :return:
        example:
            {
                "jsonrpc": "2.0",
                "id": "910b234b-9165-4c6f-a88f-2d7b07f68b66",
                "result": { //各种翻译和图片 反正很长 [BB_PREFIX]在登录那里有
                    "gameModes": [
                        {
                            "name": "Rush",
                            "shortName": "R",
                            "prettyName": "突襲",
                            "filterKey": "Rush",
                            "shortFilterKey": "R",
                            "imageUrl": "[BB_PREFIX]/gamedata/Tunguska/74/45/mode_rush.jpg-4a2d4478.jpg",
                            "images": {
                                "Jpg1000xANY": "[BB_PREFIX]/gamedata/Tunguska/84/2/mode_rush.jpg-acfe9ca7.jpg",
                                "Png480xANY": "[BB_PREFIX]/gamedata/Tunguska/98/122/mode_rush.jpg-627a86c6.png",
                                "Small": "[BB_PREFIX]/gamedata/Tunguska/100/86/mode_rush.jpg-9caaccd0.jpg",
                                "Large": "[BB_PREFIX]/gamedata/Tunguska/84/2/mode_rush.jpg-acfe9ca7.jpg",
                                "Jpg100xANY": "[BB_PREFIX]/gamedata/Tunguska/100/86/mode_rush.jpg-9caaccd0.jpg",
                                "Medium": "[BB_PREFIX]/gamedata/Tunguska/74/45/mode_rush.jpg-4a2d4478.jpg",
                                "Jpg480xANY": "[BB_PREFIX]/gamedata/Tunguska/74/45/mode_rush.jpg-4a2d4478.jpg",
                                "Png100xANY": "[BB_PREFIX]/gamedata/Tunguska/75/66/mode_rush.jpg-4b426d8d.png"
                            },
                    ...
        """
        return await self.api_call(
            {
                "jsonrpc": "2.0",
                "method": "Gamedata.getGameData",
                "params": {
                    "game": "tunguska"
                },
                "id": await get_a_uuid()
            }
        )


class GameServer(bf1_api):

    async def searchServers(self, server_name: str, limit: int = 200, filter_dict=None) -> dict:
        """
        搜索服务器
        :return:
        example:
            {
                "jsonrpc": "2.0",
                "id": "73abcad5-070c-4a45-98cf-9575e14db01d",
                "result": {
                    "gameservers": [
                        {
                            "gameId": "7570304910075",
                            "guid": "f9161325-ac4e-46f3-83e4-14796d5b97f5",
                            "protocolVersion": "3779779",
                            "name": "[DICE] Custom - B2B FL - OC - #11721005",
                            "description": "",
                            "region": "OC",
                            "country": "",
                    ...
        """
        if filter_dict:
            filter_dict = json.dumps(filter_dict)
        else:
            temp = self.filter_dict
            temp["name"] = server_name
            filter_dict = json.dumps(temp)
        return await self.api_call(
            {
                "jsonrpc": "2.0",
                "method": "GameServer.searchServers",
                "params": {
                    "game": "tunguska",
                    "limit": limit,
                    "filterJson": filter_dict,
                },
                "id": await get_a_uuid()
            }
        )

    async def getServerDetails(self, gameId: Union[int, str]) -> dict:
        """
        服务器信息
        :param gameId: 服务器gameId
        :return:
        example:
            {
                "jsonrpc": "2.0",
                "id": "90f7f3e3-b21f-4554-87fd-32815dc92198",
                "result": {
                    "gameId": "7013912860192",
                    "guid": "188ab7fc-3108-46a6-8f60-49dd321beaa5",
                    "protocolVersion": "3779779",
                    "name": "[Baka] | Operation & Lv>30 | QQ:966391786",
                    "description": "歡迎來Baka服遊玩！群號966391786內有群主女裝！服務器禁止 開掛 孤兒車 卡距離防空火箭炮 結束ez等無素質行為 若喜歡本服請收藏加群！",
                    "region": "Asia",
                    "country": "JP",
                    "ranked": false,
                    "slots": {
                        "Queue": {
                            "current": 0,
                            "max": 10
                        },
                        "Soldier": {
                            "current": 0,
                            "max": 64
                        },
                        "Spectator": {
                            "current": 0,
                            "max": 4
                    ...
        """
        return await self.api_call(
            {
                "jsonrpc": "2.0",
                "method": "GameServer.getServerDetails",
                "params": {
                    "game": "tunguska",
                    "gameId": gameId
                },
                "id": await get_a_uuid()
            }
        )

    async def getFullServerDetails(self, gameId: Union[int, str]) -> dict:
        """
        服务器完整信息
        :param gameId: 服务器gameId
        :return:
        example:
            {
                "jsonrpc": "2.0", //这个东西好用, 但是三个中有一个获取不到就会炸, 出问题试试单独的
                "id": "ee72c6cf-b092-46dd-90df-3ef3b0c953b1",
                "result": { //战地5没有这个, 也没有RSP
                    "serverInfo": {
                        //游戏信息, 同GameServer.getServerDetails
                    },
                    "rspInfo": {
                        //RSP信息, 同RSP.getServerDetails, 但没有密码
                    },
                    "platoonInfo": {
                        //战队信息, 同Platoons.getPlatoonForRspServer
                    }
                }
            }
        """
        return await self.api_call(
            {
                "jsonrpc": "2.0",
                "method": "GameServer.getFullServerDetails",
                "params": {
                    "game": "tunguska",
                    "gameId": gameId
                },
                "id": await get_a_uuid()
            }
        )

    async def getServersByPersonaIds(self, personaIds: list[Union[int, str]]) -> dict:
        """
        获取正在游玩的服务器
        :param personaIds: PID列表
        :return:
        example:
            {
                "jsonrpc": "2.0",
                "id": "4540a758-4a24-4574-bd3f-c257fd2df0ac",
                "result": {
                    "1004048906256": null, //如果有的话就是游戏信息
                    "1005880910785": null
                }
            }
        """
        if not isinstance(personaIds, list):
            personaIds = [personaIds]
        return await self.api_call(
            {
                "jsonrpc": "2.0",
                "method": "GameServer.getServersByPersonaIds",
                "params": {
                    "game": "tunguska",
                    "personaIds": personaIds
                },
                "id": await get_a_uuid()
            }
        )


class RSP(bf1_api):
    """服管相关"""

    async def RSPgetServerDetails(self, serverId: Union[int, str]) -> dict:
        """
        服务器RSP信息
        :param serverId: serverId
        :return:
        example:
            {
                "jsonrpc": "2.0", //需要管理员, 能看到服务器密码
                "id": "50d1b766-5e5c-4037-8d07-1da9ed5cdbc1",
                "result": {
                    "adminList": [
                        {
                            "platform": "pc",
                            "nucleusId": "1011592110785",
                            "personaId": "1005880910785",
                            "platformId": "1011592110785",
                            "displayName": "B_bili33",
                            "avatar": "https://secure.download.dm.origin.com/production/avatar/prod/userAvatar/36306620/208x208.PNG",
                            "accountId": "0"
                        }
                    ],
                    "vipList": [],
                    "bannedList": [],
                    "mapRotations": [
                        {
                    ...
        """
        return await self.api_call(
            {
                "jsonrpc": "2.0",
                "method": "RSP.getServerDetails",
                "params": {
                    "game": "tunguska",
                    "serverId": serverId
                },
                "id": await get_a_uuid()
            }
        )

    async def kickPlayer(self, gameId: Union[int, str], personaId, reason: str) -> dict:
        """
        踢人
        :param gameId: 服务器gameId
        :param reason: 踢出原因
        :param personaId: 玩家PID
        :return:
        example:
            {
                "jsonrpc": "2.0", //只要PID存在就会成功
                "id": "f936d186-d454-43c3-82ba-1aeb212dc7ac",
                "result": {
                    "personaId": "1005880910785", //这个是管理员的PID, 不是被踢的
                    "reason": "hack"
                }
            }
        """
        if len(reason.encode("utf-8")) > 32:
            return "原因字数过长!(限32字节)"
        return await self.api_call(
            {
                "jsonrpc": "2.0",
                "method": "RSP.kickPlayer",
                "params": {
                    "game": "tunguska",
                    "personaId": personaId,
                    "gameId": gameId,
                    "reason": reason

                },
                "id": await get_a_uuid()
            }
        )

    async def chooseLevel(self, persistedGameId: str, levelIndex: Union[int, str]) -> dict:
        """
        换图
        :param levelIndex: 地图序号
        :param persistedGameId: 服务器guid
        最近游玩
        :return:
            {
                "jsonrpc": "2.0",
                "id": "f936d186-d454-43c3-82ba-1aeb212dc7ac",
                "result": {
                    "personaId": "1005880910785", //这个是管理员的PID, 不是被踢的
                    "reason": "hack"
                }
            }
        """
        return await self.api_call(
            {
                "jsonrpc": "2.0",
                "method": "RSP.chooseLevel",
                "params": {
                    "game": "tunguska",
                    "persistedGameId": persistedGameId,
                    "levelIndex": levelIndex
                },
                "id": await get_a_uuid()
            }
        )

    async def addServerAdmin(self, personaId: Union[int, str], serverId: Union[int, str]) -> dict:
        """
        上管理
        :param serverId:
        :param personaId:
        最近游玩
        :return:
            {
                "jsonrpc": "2.0",
                "id": "437a88b0-b011-4f61-8cdf-5df0313f037b",
                "result": {
                    "env": {
                        "rootEnv": "prod_default",
                        "blazeEnv": "prod_default",
                        "game": "tunguska",
                        "platform": "pc"
                    }
                }
            }
        """
        return self.api_call(
            {
                "jsonrpc": "2.0",
                "method": "RSP.addServerAdmin",
                "params": {
                    "game": "tunguska",
                    "personaId": personaId,
                    "serverId": serverId
                },
                "id": await get_a_uuid()
            }
        )

    async def removeServerAdmin(self, personaId: Union[int, str], serverId: Union[int, str]) -> dict:
        """
        下管理
        :param serverId:
        :param personaId:
        最近游玩
        :return:
            {
                "jsonrpc": "2.0",
                "id": "437a88b0-b011-4f61-8cdf-5df0313f037b",
                "result": {
                    "env": {
                        "rootEnv": "prod_default",
                        "blazeEnv": "prod_default",
                        "game": "tunguska",
                        "platform": "pc"
                    }
                }
            }
        """
        return await self.api_call(
            {
                "jsonrpc": "2.0",
                "method": "RSP.removeServerAdmin",
                "params": {
                    "game": "tunguska",
                    "personaId": personaId,
                    "serverId": serverId
                },
                "id": await get_a_uuid()
            }
        )

    async def addServerVip(self, personaId: Union[int, str], serverId: Union[int, str]) -> dict:
        """
        上VIP
        :param serverId:
        :param personaId:
        最近游玩
        :return:
            {
                "jsonrpc": "2.0",
                "id": "437a88b0-b011-4f61-8cdf-5df0313f037b",
                "result": {
                    "env": {
                        "rootEnv": "prod_default",
                        "blazeEnv": "prod_default",
                        "game": "tunguska",
                        "platform": "pc"
                    }
                }
            }
        """
        return await self.api_call(
            {
                "jsonrpc": "2.0",
                "method": "RSP.addServerVip",
                "params": {
                    "game": "tunguska",
                    "personaId": personaId,
                    "serverId": serverId
                },
                "id": await get_a_uuid()
            }
        )

    async def removeServerVip(self, personaId: Union[int, str], serverId: Union[int, str]) -> dict:
        """
        下VIP
        :param serverId:
        :param personaId:
        最近游玩
        :return:
            {
                "jsonrpc": "2.0",
                "id": "437a88b0-b011-4f61-8cdf-5df0313f037b",
                "result": {
                    "env": {
                        "rootEnv": "prod_default",
                        "blazeEnv": "prod_default",
                        "game": "tunguska",
                        "platform": "pc"
                    }
                }
            }
        """
        return await self.api_call(
            {
                "jsonrpc": "2.0",
                "method": "RSP.removeServerVip",
                "params": {
                    "game": "tunguska",
                    "personaId": personaId,
                    "serverId": serverId
                },
                "id": await get_a_uuid()
            }
        )

    async def addServerBan(self, personaId: Union[int, str], serverId: Union[int, str]) -> dict:
        """
        上Ban
        :param serverId:
        :param personaId:
        最近游玩
        :return:
            {
                "jsonrpc": "2.0",
                "id": "437a88b0-b011-4f61-8cdf-5df0313f037b",
                "result": {
                    "env": {
                        "rootEnv": "prod_default",
                        "blazeEnv": "prod_default",
                        "game": "tunguska",
                        "platform": "pc"
                    }
                }
            }
        """
        return await self.api_call(
            {
                "jsonrpc": "2.0",
                "method": "RSP.addServerBan",
                "params": {
                    "game": "tunguska",
                    "personaId": personaId,
                    "serverId": serverId
                },
                "id": await get_a_uuid()
            }
        )

    async def removeServerBan(self, personaId: Union[int, str], serverId: Union[int, str]) -> dict:
        """
        下Ban
        :param serverId:
        :param personaId:
        最近游玩
        :return:
            {
                "jsonrpc": "2.0",
                "id": "437a88b0-b011-4f61-8cdf-5df0313f037b",
                "result": {
                    "env": {
                        "rootEnv": "prod_default",
                        "blazeEnv": "prod_default",
                        "game": "tunguska",
                        "platform": "pc"
                    }
                }
            }
        """
        return await self.api_call(
            {
                "jsonrpc": "2.0",
                "method": "RSP.removeServerBan",
                "params": {
                    "game": "tunguska",
                    "personaId": personaId,
                    "serverId": serverId
                },
                "id": await get_a_uuid()
            }
        )

    async def updateServer(self, serverId: Union[int, str], config: dict = None) -> dict:
        """
        修改配置
        :param config:
        :param serverId:
        :return:
            {
                "jsonrpc": "2.0",
                "id": "437a88b0-b011-4f61-8cdf-5df0313f037b",
                "result": {
                    "env": {
                        "rootEnv": "prod_default",
                        "blazeEnv": "prod_default",
                        "game": "tunguska",
                        "platform": "pc"
                    }
                }
            }
        """
        if not config:
            config = {  # 除了注释的都是不能动的
                "deviceIdMap": {
                    "machash": "31f1a313-2a0c-474b-9d2d-ec2954823ea4"  # 随便写
                },
                "game": "tunguska",
                "serverId": serverId,  # 服务器ServerId
                "bannerSettings": {
                    "bannerUrl": "",
                    "clearBanner": True
                },
                "mapRotation": {
                    "maps": [  # 地图池
                        {
                            "gameMode": "TOW0",
                            "mapName": "MP_MountainFort"
                        },
                        {
                            "gameMode": "TOW0",
                            "mapName": "MP_Amiens"
                        },
                        {
                            "gameMode": "TOW0",
                            "mapName": "MP_Chateau"
                        },
                        {
                            "gameMode": "TOW0",
                            "mapName": "MP_ShovelTown"
                        },
                        {
                            "gameMode": "TOW0",
                            "mapName": "MP_Graveyard"
                        },
                        {
                            "gameMode": "TOW0",
                            "mapName": "MP_Desert"
                        },
                        {
                            "gameMode": "TOW0",
                            "mapName": "MP_Scar"
                        },
                        {
                            "gameMode": "TOW0",
                            "mapName": "MP_Suez"
                        },
                        {
                            "gameMode": "TOW0",
                            "mapName": "MP_Trench"
                        },
                        {
                            "gameMode": "TOW0",
                            "mapName": "MP_Forest"
                        },
                        {
                            "gameMode": "TOW0",
                            "mapName": "MP_Underworld"
                        },
                        {
                            "gameMode": "TOW0",
                            "mapName": "MP_Fields"
                        },
                        {
                            "gameMode": "TOW0",
                            "mapName": "MP_Verdun"
                        }
                    ],
                    "rotationType": "",
                    "mod": "32",
                    "name": "0",
                    "description": "",
                    "id": "100"
                },
                "serverSettings": {
                    "name": "Frontline Test Server",  # 服务器名 需低于64字节
                    "description": "",  # 简介 需低于256字符且低于512字节
                    "message": "",
                    "password": "1234",  # 密码
                    "bannerUrl": "",
                    "mapRotationId": "100",
                    "customGameSettings": "{\"version\":10,\"kits\":{\"8\":\"off\",\"4\":\"on\",\"9\":\"off\",\"5\":\"off\",\"6\":\"off\",\"HERO\":\"on\",\"1\":\"on\",\"2\":\"on\",\"7\":\"off\",\"3\":\"on\"},\"vehicles\":{\"L\":\"on\",\"A\":\"on\"},\"weaponClasses\":{\"E\":\"on\",\"SIR\":\"off\",\"SAR\":\"on\",\"KG\":\"on\",\"M\":\"on\",\"LMG\":\"on\",\"SMG\":\"on\",\"H\":\"on\",\"S\":\"on\",\"SR\":\"on\"},\"serverType\":{\"SERVER_TYPE_RANKED\":\"on\"},\"misc\":{\"RWM\":\"off\",\"UM\":\"off\",\"LL\":\"off\",\"AAS\":\"off\",\"LNL\":\"off\",\"3S\":\"off\",\"KC\":\"off\",\"MV\":\"off\",\"BH\":\"on\",\"F\":\"off\",\"MM\":\"on\",\"DTB\":\"on\",\"FF\":\"off\",\"RH\":\"on\",\"3VC\":\"on\",\"SLSO\":\"off\",\"DSD\":\"on\",\"AAR\":\"off\",\"NT\":\"on\",\"BPL\":\"off\",\"MS\":\"on\"},\"scales\":{\"RT3\":\"off\",\"BD3\":\"off\",\"VR3\":\"off\",\"BD4\":\"off\",\"BD2\":\"on\",\"TC1\":\"off\",\"SR1\":\"off\",\"SR2\":\"on\",\"VR2\":\"off\",\"RT1\":\"on\",\"BD1\":\"off\",\"RT5\":\"off\",\"RT2\":\"off\",\"TC2\":\"on\",\"TC3\":\"off\",\"SR3\":\"off\",\"RT4\":\"off\",\"VR1\":\"on\"}}"
                    # 自定义设置, GameData那有
                }
            }
        return await self.api_call(
            config
        )

    async def movePlayer(self, gameId: Union[int, str], personaId: Union[int, str], teamId: int) -> dict:
        """
        移动玩家
        :param gameId:
        :param personaId:
        :param teamId:
        :return:
        """
        return await self.api_call(
            {
                "jsonrpc": "2.0",
                "method": "RSP.movePlayer",
                "params": {
                    "game": "tunguska",
                    "gameId": gameId,
                    "teamId": teamId,
                    "personaId": personaId,
                    "forceKill": True,
                    "moveParty": False
                },
                "id": await get_a_uuid()
            }
        )


class Platoons(bf1_api):
    """
    战队相关
    """

    async def getPlatoonForRspServer(self, serverId: Union[int, str]) -> dict:
        """
        服务器战队信息
        :param serverId: serverId
        :return:
        example:
            {
                "jsonrpc": "2.0",
                "id": "40fd85b8-7dda-45f2-b9c0-8feb49f25265",
                "result": {
                    "guid": "030cf13a-8452-4838-aec3-edc26934acf2",
                    "name": "BakaServer",
                    "size": 100,
                    "joinConfig": {
                        "canApplyMembership": false,
                        "isFreeJoin": true
                    },
                    "description": null,
                    "tag": "Baka",
                    "emblem": "https://eaassets-a.akamaihd.net/battlelog/bf-emblems/prod_default/ugc/453/495/3289737051/[SIZE].[FORMAT]?v=1628495354",
                    "verified": false,
                    "creatorId": "1004048906256",
                    "dateCreated": 1628495516
                }
            }
        """
        return await self.api_call(
            {
                "jsonrpc": "2.0",
                "method": "Platoons.getPlatoonForRspServer",
                "params": {
                    "game": "tunguska",
                    "serverId": serverId
                },
                "id": await get_a_uuid()
            }
        )

    async def getActiveTagsByPersonaIds(self, personaIds: list[Union[int, str]]) -> dict:
        """
        获取代表战队图章
        :param personaIds: PID列表
        :return:
        eg:
        {
            "jsonrpc": "2.0",
            "id": "5550a321-f899-4912-8625-966f29a77a6a",
            "result": {
                "1004198901469": "EA",
                "1003517866915": ""
            }
        }
        """
        return await self.api_call(
            {
                "jsonrpc": "2.0",
                "method": "Platoons.getActiveTagsByPersonaIds",
                "params": {
                    "personaIds": personaIds
                },
                "id": await get_a_uuid()
            }
        )

    async def getActivePlatoon(self, personaId: Union[int, str]) -> dict:
        """
        获取玩家所在战队
        :param personaId:
        :return:
        eg:
        {
            "jsonrpc": "2.0",
            "id": "5550a321-f899-4912-8625-966f29a77a6a",
            "result": {
                "guid": "66485c9e-01a9-4aeb-a30d-f02488fa357c",
                "name": "Electronic Arts",
                "size": 68,
                "joinConfig": {
                    "canApplyMembership": false,
                    "isFreeJoin": false
                },
                "description": "Employees of Electronic Arts - Invite Only.",
                "tag": "EA",
                "emblem": "https://eaassets-a.akamaihd.net/battlelog/bf-emblems/prod_default/exclusive/[SIZE]/EA.[FORMAT]",
                "verified": true,
                "creatorId": "173507079",
                "dateCreated": 1490805628
            }
        }

        """
        return await self.api_call(
            {
                "jsonrpc": "2.0",
                "method": "Platoons.getActivePlatoon",
                "params": {
                    "personaId": personaId
                },
                "id": await get_a_uuid()
            }
        )

    async def getPlatoon(self, platoon_guid: str) -> dict:
        """
        获取战队信息
        :param platoon_guid:
        :return:
        eg:
        {
            "jsonrpc": "2.0",
            "id": "3d5c46cd-63d8-4035-9598-bd7984e963a1",
            "result": {
                "guid": "66485c9e-01a9-4aeb-a30d-f02488fa357c",
                "name": "Electronic Arts",
                "size": 68,
                "joinConfig": {
                    "canApplyMembership": false,
                    "isFreeJoin": false
                },
                "description": "Employees of Electronic Arts - Invite Only.",
                "tag": "EA",
                "emblem": "https://eaassets-a.akamaihd.net/battlelog/bf-emblems/prod_default/exclusive/[SIZE]/EA.[FORMAT]",
                "verified": true,
                "creatorId": "173507079",
                "dateCreated": 1490805628
            }
        }
        """
        return await self.api_call(
            {
                "jsonrpc": "2.0",
                "method": "Platoons.getPlatoon",
                "params": {"guid": platoon_guid},
                "id": await get_a_uuid()
            }
        )

    async def getPlatoons(self, personaId: Union[int, str]) -> dict:
        """
        获取玩家所在战排列表
        :param personaId:
        :return:
        """
        return await self.api_call(
            {
                "jsonrpc": "2.0",
                "method": "Platoons.getPlatoons",
                "params": {"personaId": personaId},
                "id": await get_a_uuid()
            }
        )

    async def getServersWithPlayers(self, platoon_guid: str) -> dict:
        """
        获取战队正在游玩的服务器
        :param platoon_guid:
        :return:
        eg:
        {
            "jsonrpc": "2.0",
            "id": "5550a321-f899-4912-8625-966f29a77a6a",
            "result": [
                {
                    "server": {
                        "gameId": "8623425550964",
                        "guid": "8389408e-214c-4f4c-8e5f-d6af7a7f8782",
                        "protocolVersion": "3779779",
                        "name": "[op]Operation/no limit/noob welcome/qq:192704059",
                        "description": "歡迎所有原批，本服為無限制服務器",
                        "region": "Asia",
                        "country": "JP",
                        "ranked": false,
                        "slots": {
                            "Soldier": {
                                "current": 64,
                                "max": 64
                            },
                            "Spectator": {
                                "current": 0,
                                "max": 4
                            },
                            "Queue": {
                                "current": 2,
                                "max": 10
                            }
                        },
                        "mapName": "MP_Forest",
                        "mapNamePretty": "阿爾貢森林",
                        "mapMode": "BreakthroughLarge",
                        "mapModePretty": "行動模式",
                        "mapImageUrl": "[BB_PREFIX]/gamedata/Tunguska/33/69/MP_Forest_LandscapeLarge-dfbbe910.jpg",
                        "mapExpansion": {
                            "name": "DEFAULT",
                            "mask": 1,
                            "license": "",
                            "prettyName": ""
                        },
                        "expansions": [
                            {
                                "name": "DEFAULT",
                                "mask": 1,
                                "license": "",
                                "prettyName": ""
                            },
                            {
                                "name": "XPACK0",
                                "mask": 2,
                                "license": "xp0",
                                "prettyName": "龐然闇影"
                            },
                            {
                                "name": "XPACK1",
                                "mask": 4,
                                "license": "xp1",
                                "prettyName": "誓死堅守"
                            },
                            {
                                "name": "XPACK2",
                                "mask": 8,
                                "license": "xp2",
                                "prettyName": "以沙皇之名"
                            },
                            {
                                "name": "XPACK3",
                                "mask": 16,
                                "license": "xp3",
                                "prettyName": "力挽狂瀾"
                            },
                            {
                                "name": "XPACK4",
                                "mask": 32,
                                "license": "xp4",
                                "prettyName": "啟示錄"
                            }
                        ],
                        "game": "tunguska",
                        "platform": "pc",
                        "passwordProtected": false,
                        "ip": "",
                        "pingSiteAlias": "nrt",
                        "isFavorite": false,
                        "custom": false,
                        "preset": "",
                        "tickRate": 60,
                        "serverType": "RANKED",
                        "experience": "",
                        "officialExperienceId": "",
                        "operationIndex": 0,
                        "mixId": null,
                        "serverMode": null,
                        "ownerId": null,
                        "playgroundId": null,
                        "overallGameMode": null,
                        "mapRotation": [],
                        "secret": "",
                        "settings": {}
                    },
                    "platoon": {
                        "guid": "66485c9e-01a9-4aeb-a30d-f02488fa357c",
                        "name": "Electronic Arts",
                        "size": 68,
                        "tag": "EA",
                        "emblem": "https://eaassets-a.akamaihd.net/battlelog/bf-emblems/prod_default/exclusive/[SIZE]/EA.[FORMAT]",
                        "verified": true,
                        "displayMembers": [
                            {
                                "personaId": "1002944411826",
                                "platformId": "1005642811826",
                                "role": "role-2",
                                "displayName": "Leader_Qne",
                                "avatar": "",
                                "accountId": "0"
                            }
                        ]
                    }
                },
                {
                    "server": {
                        "gameId": "8623425650203",
                        "guid": "ae639590-440d-481c-9fed-985b4b93ea2e",
                        "protocolVersion": "3779779",
                        "name": "SHUAQIANG",
                        "description": "你好",
                        "region": "Asia",
                        "country": "JP",
                        "ranked": false,
                        "slots": {
                            "Soldier": {
                                "current": 5,
                                "max": 64
                            },
                            "Spectator": {
                                "current": 0,
                                "max": 4
                            },
                            "Queue": {
                                "current": 0,
                                "max": 10
                            }
                        },
                        "mapName": "MP_Islands",
                        "mapNamePretty": "阿爾比恩",
                        "mapMode": "Conquest",
                        "mapModePretty": "征服",
                        "mapImageUrl": "[BB_PREFIX]/gamedata/Tunguska/55/40/MP_Islands_LandscapeLarge-c9d8272b.jpg",
                        "mapExpansion": {
                            "name": "XPACK2",
                            "mask": 8,
                            "license": "xp2",
                            "prettyName": "以沙皇之名"
                        },
                        "expansions": [
                            {
                                "name": "XPACK2",
                                "mask": 8,
                                "license": "xp2",
                                "prettyName": "以沙皇之名"
                            }
                        ],
                        "game": "tunguska",
                        "platform": "pc",
                        "passwordProtected": false,
                        "ip": "",
                        "pingSiteAlias": "nrt",
                        "isFavorite": false,
                        "custom": true,
                        "preset": "",
                        "tickRate": 60,
                        "serverType": "RANKED",
                        "experience": "",
                        "officialExperienceId": "",
                        "operationIndex": 8,
                        "mixId": null,
                        "serverMode": null,
                        "ownerId": null,
                        "playgroundId": null,
                        "overallGameMode": null,
                        "mapRotation": [],
                        "secret": "",
                        "settings": {}
                    },
                    "platoon": {
                        "guid": "66485c9e-01a9-4aeb-a30d-f02488fa357c",
                        "name": "Electronic Arts",
                        "size": 68,
                        "tag": "EA",
                        "emblem": "https://eaassets-a.akamaihd.net/battlelog/bf-emblems/prod_default/exclusive/[SIZE]/EA.[FORMAT]",
                        "verified": true,
                        "displayMembers": [
                            {
                                "personaId": "1004807814705",
                                "platformId": "1009542214705",
                                "role": "role-2",
                                "displayName": "Azuki_Azusa",
                                "avatar": "",
                                "accountId": "0"
                            }
                        ]
                    }
                }
            ]
        }
        """
        return await self.api_call(
            {
                "jsonrpc": "2.0",
                "method": "Platoons.getServersWithPlayers",
                "params": {"game": "tunguska", "guid": platoon_guid},
                "id": await get_a_uuid()
            }
        )


class Emblems(bf1_api):
    """
    图章
    """

    async def getEquippedEmblem(self, personaId: Union[int, str]) -> dict:
        """
        获取玩家当前装备的图章
        :param personaId:
        :return:
        eg:
        {
            "jsonrpc": "2.0",
            "id": "5550a321-f899-4912-8625-966f29a77a6a",
            "result": "https://eaassets-a.akamaihd.net/battlelog/bf-emblems/prod_default/exclusive/[SIZE]/EA.[FORMAT]"
        }
        推荐 SIZE: 128/512 FORMAT: PNG
        如果没有装备图章则result为null
        """
        return await self.api_call(
            {
                "jsonrpc": "2.0",
                "method": "Emblems.getEquippedEmblem",
                "params": {
                    "personaId": personaId,
                    "platform": "pc"
                },
                "id": await get_a_uuid()
            }
        )


class Loadout(bf1_api):
    """
    装备
    """

    async def getEquippedDogtagsByPersonaId(self, personaId: Union[int, str]) -> dict:
        return await self.api_call(
            {
                "jsonrpc": "2.0",
                "method": "Loadout.getEquippedDogtagsByPersonaId",
                "params": {"game": "tunguska", "personaId": personaId},
                "id": await get_a_uuid()
            }
        )


class InstanceExistsError(Exception):
    """Raised when an instance already exists for the given pid."""
    pass


class api_instance(
    Game, Progression, Stats, ServerHistory, Gamedata,
    GameServer, RSP, Platoons, ScrapExchange, CampaignOperations
):
    # 存储所有实例的字典
    instances = {}

    def __init__(self, pid: int, remid: str = None, sid: str = None, session: str = None):
        # 如果实例已经存在，则抛出异常，否则创建一个新实例
        if pid in api_instance.instances:
            raise InstanceExistsError(f"api_instance already exists for pid: {pid}")
        super().__init__(pid=pid, remid=remid, sid=sid, session=session)

        # 将实例添加到字典中
        api_instance.instances[pid] = self

    # 使用单例模式，让每个pid只有一个实例
    @staticmethod
    def get_api_instance(pid, remid=None, sid=None, session=None) -> "api_instance":
        # 如果实例已经存在，则返回它，否则创建一个新实例
        pid = str(pid)
        if pid not in api_instance.instances:
            api_instance.instances[pid] = api_instance(pid, remid, sid, session)
        return api_instance.instances[pid]


"""
使用示例:

1.获取一个账号实例
    account = api_instance.get_api_instance(pid)
2.使用cookie登录,登录后会自动刷新session
    await account.login(remid="xxx", sid="xxx")
3.调用功能
    data = await account.xxx...
4.如果返回结果不是dict类型说明有错,否则处理获得的数据
    if not isinstance(data, dict):
        logger.error(data)
        return data
    处理获得的数据:
        ...
"""
