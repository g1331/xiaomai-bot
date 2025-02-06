import asyncio
from typing import Dict, List, Optional

from utils.bf1.gateway_api_refactor import BF1APIClient


class BF1AccountManager:
    """多账户管理类

    用于在程序运行期间管理多个 BF1 账户实例，
    并提供账户添加、获取、登录状态检查等操作。

    Attributes:
        _accounts (Dict[int, BF1APIClient]): 存储账户实例的字典，以 pid 为键。
    """

    def __init__(self) -> None:
        self._accounts: Dict[int, BF1APIClient] = {}

    async def add_account(
            self,
            *,
            remid: Optional[str] = None,
            sid: Optional[str] = None,
            session: Optional[str] = None,
            provided_pid: Optional[int] = None,
            proxy: Optional[str] = None
    ) -> "BF1APIClient":
        """添加账户实例，并尝试登录

        账户登录流程：
            1. 如果存在 session 但无 remid，则调用接口检查 session 是否有效，并获取真实 pid；
            2. 如果既无 session 也无 remid，则无法工作；
            3. 如果同时存在 session 与 remid，则先验证 session 有效性，若无效则使用 remid/sid 登录刷新 session；
            4. 登录后获取的 pid 与 provided_pid（若传入）必须一致，否则报错。

        Args:
            remid (Optional[str]): 登录使用的 remid。
            sid (Optional[str]): 登录使用的 sid。
            session (Optional[str]): 可选的 session 值。
            provided_pid (Optional[int]): 用户提供的 pid（可选），用于校验实际登录的 pid。
            proxy (Optional[str]): 可选的代理设置。

        Returns:
            BF1APIClient: 成功登录后的账户实例.

        Raises:
            APIError: 登录失败或 pid 校验不一致时抛出异常。
        """
        # 创建客户端实例（pid暂不传入）
        client = BF1APIClient(remid=remid, sid=sid, session=session, proxy=proxy)
        async with client:
            # 尝试确保登录并获取有效 session（内部会根据条件调用 login() 刷新 session）
            await client.ensure_session()
        # 从登录后的认证模块获取真实 pid
        actual_pid = client.auth.pid
        if actual_pid is None:
            raise Exception("未能获取有效的 pid，账户无法工作")
        if provided_pid is not None and provided_pid != actual_pid:
            raise Exception(f"提供的 pid ({provided_pid}) 与实际 pid ({actual_pid}) 不匹配")
        # 使用实际 pid 作为 key 存储账户
        self._accounts[actual_pid] = client
        return client

    def get_account(self, pid: int) -> Optional[BF1APIClient]:
        """获取指定 pid 的账户实例

        Args:
            pid (int): 账户的 pid。

        Returns:
            Optional[BF1APIClient]: 存在则返回账户实例，否则返回 None。
        """
        return self._accounts.get(pid)

    def list_accounts(self) -> List[BF1APIClient]:
        """列出所有账户实例

        Returns:
            List[BF1APIClient]: 所有账户实例的列表。
        """
        return list(self._accounts.values())

    async def remove_account(self, pid: int) -> None:
        """移除指定 pid 的账户实例

        Args:
            pid (int): 账户的 pid。
        """
        client = self._accounts.pop(pid, None)
        if client:
            # 如有需要，可在此关闭客户端连接
            await client.__aexit__(None, None, None)

    async def ensure_all_logged_in(self) -> None:
        """确保所有账户均已登录

        对所有账户调用 ensure_session 方法，检查并刷新登录状态。
        """
        tasks = []
        for client in self._accounts.values():
            tasks.append(client.ensure_session())
        await asyncio.gather(*tasks)
