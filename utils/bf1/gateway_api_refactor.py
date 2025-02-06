import aiohttp
import asyncio
import json
import time
import uuid
from typing import Any, Dict, Optional, Union


# 自定义异常
class APIError(Exception):
    """当 API 调用错误时抛出异常"""
    pass


# 统一 HTTP 客户端，支持上下文管理
class HTTPClient:
    def __init__(self, proxy: Optional[str] = None, timeout: int = 10):
        self.proxy = proxy
        self.timeout = timeout
        self.session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self.session:
            await self.session.close()

    async def request(
            self,
            method: str,
            url: str,
            headers: Optional[Dict[str, str]] = None,
            data: Optional[Any] = None,
            ssl: bool = True,
            allow_redirects: bool = True
    ) -> Dict[str, Any]:
        if self.session is None:
            raise RuntimeError("HTTPClient session 未初始化")
        async with self.session.request(
                method=method,
                url=url,
                headers=headers,
                data=data,
                timeout=self.timeout,
                ssl=ssl,
                proxy=self.proxy,
                allow_redirects=allow_redirects
        ) as response:
            text = await response.text()
            try:
                result = json.loads(text)
            except json.JSONDecodeError:
                raise APIError(f"响应非 JSON 格式: {text}")
            if response.status != 200:
                raise APIError(f"HTTP 错误 {response.status}: {result}")
            return result

    async def get_with_headers(
            self,
            url: str,
            headers: Optional[Dict[str, str]] = None,
            ssl: bool = True,
            allow_redirects: bool = False
    ) -> aiohttp.ClientResponse:
        if self.session is None:
            raise RuntimeError("HTTPClient session 未初始化")
        response = await self.session.get(
            url=url,
            headers=headers,
            timeout=self.timeout,
            ssl=ssl,
            proxy=self.proxy,
            allow_redirects=allow_redirects
        )
        return response


# 统一 JSON-RPC 客户端，构造请求并动态生成链式调用接口
class JSONRPCClient:
    def __init__(self, http_client: HTTPClient, base_url: str):
        self.http_client = http_client
        self.base_url = base_url
        # 统一默认的 headers（各模块均可复用）
        self.default_headers = {
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

    async def jsonrpc_call(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """调用 JSON-RPC 接口

        Args:
            method (str): 接口名称，例如 "Game.reserveSlot"。
            params (Dict[str, Any]): 接口参数字典。

        Returns:
            Dict[str, Any]: 返回的 JSON 数据字典。

        Raises:
            APIError: 如果调用发生错误则抛出异常。
        """
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": str(uuid.uuid4())
        }
        data = json.dumps(payload)
        result = await self.http_client.request(
            "POST",
            self.base_url,
            headers=self.default_headers,
            data=data,
        )
        if "error" in result:
            raise APIError(f"调用 {method} 出错: {result['error']}")
        return result

# 新增各个大类 API 接口，并在方法中提供详细文档
from typing import Union

class GameAPI:
    """
    游戏相关 API 接口
    Methods:
         reserve_slot: 预留进入服务器的槽位.
         leave_game: 退出服务器.
    """
    def __init__(self, jsonrpc_client: JSONRPCClient) -> None:
        self.jsonrpc_client = jsonrpc_client

    async def reserve_slot(self, *, game: str, gameId: Union[int, str],
                           gameProtocolVersion: str, currentGame: str,
                           settings: dict) -> dict:
        """预留进入服务器的槽位

        Args:
            game (str): 游戏名称，例如 "tunguska"。
            gameId (Union[int, str]): 服务器ID。
            gameProtocolVersion (str): 协议版本，例如 "3779779"。
            currentGame (str): 当前游戏名称。
            settings (dict): 服务器设置字典，如 {"role": "spectator"}。

        Returns:
            dict: 接口调用返回的结果字典。
        """
        return await self.jsonrpc_client.jsonrpc_call(
            "Game.reserveSlot",
            {
                "game": game,
                "gameId": gameId,
                "gameProtocolVersion": gameProtocolVersion,
                "currentGame": currentGame,
                "settings": settings,
            }
        )

    async def leave_game(self, *, game: str, gameId: Union[int, str]) -> dict:
        """退出服务器

        Args:
            game (str): 游戏名称，例如 "tunguska"。
            gameId (Union[int, str]): 服务器ID。

        Returns:
            dict: 调用成功时返回的结果字典。
        """
        return await self.jsonrpc_client.jsonrpc_call(
            "Game.leaveGame",
            {"game": game, "gameId": gameId}
        )

# 可以依照相同模式增加其他大类接口，例如AuthenticationAPI, CompanionAPI等
# class AuthenticationAPI:
#     """认证相关接口，包含详细的参数说明"""
#     def __init__(self, jsonrpc_client: JSONRPCClient):
#         self.jsonrpc_client = jsonrpc_client
#     async def login(self, *, remid: str, sid: str) -> dict:
#         """
#         登录接口
#         参数:
#             remid: 用户的 remid
#             sid: 用户的 sid
#         返回:
#             dict: 登录返回数据
#         """
#         return await self.jsonrpc_client.jsonrpc_call(
#             "Authentication.login",
#             {"remid": remid, "sid": sid}
#         )

# 聚合多类 API 的外层接口
class BF1API:
    """
    聚合所有 API 接口的大类，支持 “大类.小类” 的方式调用。
    Attributes:
         game: 游戏相关接口
         # auth: 认证相关接口
         # companion: 同伴相关接口
         # ...其他模块可在此扩展
    """
    def __init__(self, jsonrpc_client: JSONRPCClient):
        self.game = GameAPI(jsonrpc_client)
        # 可继续添加其他大类：
        # self.auth = AuthenticationAPI(jsonrpc_client)
        # self.companion = CompanionAPI(jsonrpc_client)
        # ...


# 认证模块，支持 session 模式和登录模式
class Authentication:
    def __init__(
            self,
            jsonrpc_client: JSONRPCClient,
            http_client: HTTPClient,
            *,
            session: Optional[str] = None,
            remid: Optional[str] = None,
            sid: Optional[str] = None
    ):
        self.jsonrpc_client = jsonrpc_client
        self.http_client = http_client
        self.session = session
        self.remid = remid
        self.sid = sid
        self.access_token: Optional[str] = None
        self.access_token_expires_in: Optional[int] = None
        self.access_token_time: float = 0
        self.authcode: Optional[str] = None
        self.pid: Optional[int] = None

    async def companion_is_logged_in(self) -> bool:
        try:
            result = await self.jsonrpc_client.jsonrpc_call("Companion.isLoggedIn", {})
            return result.get("result", {}).get("isLoggedIn", False)
        except APIError:
            return False

    async def ensure_session(self) -> str:
        if self.session:
            if await self.companion_is_logged_in():
                return self.session
            if self.remid and self.sid:
                return await self.login()
            else:
                raise APIError("session 无效且缺少 remid/sid，无法刷新")
        else:
            if self.remid and self.sid:
                return await self.login()
            else:
                raise APIError("缺少 session 与 remid/sid，无法进行身份验证")

    async def get_access_token(self) -> str:
        """获取访问令牌

        通过向账户服务器发送请求，获取 access_token。

        Returns:
            str: 返回获取到的 access_token。

        Raises:
            APIError: 如果未能成功获取 access_token，则抛出异常。
        """
        url = (
            "https://accounts.ea.com/connect/auth?client_id=ORIGIN_JS_SDK&response_type=token&"
            "redirect_uri=nucleus%3Arest&prompt=none&release_type=prod"
        )
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/86.0.4240.193 Safari/537.36",
            "Content-Type": "application/json",
            "Cookie": f"remid={self.remid}; sid={self.sid}" if self.remid and self.sid else ""
        }
        result = await self.http_client.request("GET", url, headers=headers)
        if "error" in result:
            raise APIError(f"获取 access_token 失败: {result['error']}")
        self.access_token = result.get("access_token")
        self.access_token_expires_in = int(result.get("expires_in", 0))
        self.access_token_time = time.time()
        if not self.access_token:
            raise APIError(f"获取 access_token 失败, 返回结果: {result}")
        return self.access_token

    async def refresh_authcode(self) -> str:
        """刷新 authcode

        如果未获取到 access_token，则首先调用 get_access_token()，
        然后发送请求刷新 authcode，并从响应头中获取 authcode。

        Returns:
            str: 获取到的 authcode 字符串。

        Raises:
            APIError: 如果刷新过程中出现 HTTP 错误或未获得 authcode时抛出异常。
        """
        if not self.access_token:
            await self.get_access_token()
        url = (
            f"https://accounts.ea.com/connect/auth?access_token={self.access_token}"
            "&client_id=sparta-backend-as-user-pc&response_type=code&release_type=prod"
        )
        headers = {
            "User-Agent": "Mozilla/5.0 EA Download Manager Origin/10.5.94.46774",
            "Cookie": f"remid={self.remid}; sid={self.sid}" if self.remid and self.sid else "",
            "localeInfo": "zh_TW",
            "X-Origin-Platform": "PCWIN"
        }
        response = await self.http_client.get_with_headers(url, headers=headers,  allow_redirects=False)
        if response.status not in (302, 303):
            text = await response.text()
            raise APIError(f"刷新 authcode 时 HTTP 错误 {response.status}: {text}")
        location = response.headers.get("location")
        if not location:
            raise APIError("未在响应头中找到 location，无法获取 authcode")
        self.authcode = location[location.rfind('=') + 1:]
        return self.authcode

    async def get_session_via_authcode(self) -> str:
        """通过 authcode 获取 session

        发送 JSON-RPC 请求，通过 authcode 获取 session 和 personaId。

        Returns:
            str: 返回获取到的 session 字符串。

        Raises:
            APIError: 如果返回结果中未包含有效的 session，则抛出异常。
        """
        if not self.authcode:
            await self.refresh_authcode()
        result = await self.jsonrpc_client.jsonrpc_call("Authentication.getEnvIdViaAuthCode",
                                                        {"authCode": self.authcode, "locale": "zh-tw"})
        res = result.get("result", {})
        self.session = res.get("sessionId")
        self.pid = res.get("personaId")
        if not self.session:
            raise APIError("获取 session 失败")
        return self.session

    async def login(self) -> str:
        """登录获取 session

        按顺序调用 get_access_token()、refresh_authcode()、和 get_session_via_authcode()，
        以完成登录流程。

        Returns:
            str: 登录成功后返回的 session 字符串。
        """
        await self.get_access_token()
        await self.refresh_authcode()
        session = await self.get_session_via_authcode()
        return session


# 高层 BF1 API 客户端，支持单账号操作；多账号管理可由外部管理器实现
class BF1APIClient:
    def __init__(
            self,
            *,
            base_url: str = "https://sparta-gw.battlelog.com/jsonrpc/pc/api",
            remid: Optional[str] = None,
            sid: Optional[str] = None,
            session: Optional[str] = None,
            proxy: Optional[str] = None
    ):
        self.base_url = base_url
        self.proxy = proxy
        self.remid = remid
        self.sid = sid
        self.session = session

        self.http_client = HTTPClient(proxy=self.proxy)
        self.jsonrpc_client = JSONRPCClient(self.http_client, base_url=self.base_url)
        self.auth = Authentication(
            self.jsonrpc_client,
            self.http_client,
            session=self.session,
            remid=self.remid,
            sid=self.sid
        )
        # 使用新的聚合接口
        self.api = BF1API(self.jsonrpc_client)

    async def __aenter__(self):
        await self.http_client.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.http_client.__aexit__(exc_type, exc, tb)

    async def ensure_session(self) -> str:
        return await self.auth.ensure_session()
