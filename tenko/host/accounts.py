from __future__ import annotations

import random
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Literal

from satori.client import Account
from satori.exception import ActionFailed

from ..context import MessageContext

ResponseType = Literal["random", "deterministic"]
_NO_MUTE = object()
_GROUP_PERMISSION_LEVELS = {
    "member": 16,
    "user": 16,
    "admin": 32,
    "administrator": 32,
    "owner": 64,
    "群员": 16,
    "管理员": 32,
    "群主": 64,
}


def _key(value: object) -> str:
    if value is None:
        raise ValueError("账号或群 ID 不能为空")
    return str(value)


def _account_id(account_or_id: Account | object) -> str:
    if isinstance(account_or_id, str | int):
        return _key(account_or_id)
    return _key(getattr(account_or_id, "self_id", None))


def _account_default_availability(account: Account) -> bool:
    """从 Satori 登录状态推断初始状态；生命周期回调可随后显式更新。"""

    status = getattr(getattr(account, "self_info", None), "status", None)
    status_name = str(getattr(status, "name", status)).lower()
    if status_name in {"offline", "disconnect", "disconnected"}:
        return False

    connected = getattr(account, "connected", None)
    if connected is not None and hasattr(connected, "is_set"):
        if connected.is_set():
            return True
        # Account objects created by Satori start with an ONLINE Login status,
        # before the client has had a chance to set ``connected``.
        if status_name and status_name not in {"online", "connect", "reconnect"}:
            return False
    return True


class AccountRegistry:
    """管理 Satori 账号句柄以及群到账号的响应路由。

    这个注册表隔离的是“Satori 账号生命周期 + 群路由”边界：宿主只保存
    `Account` 句柄和运行时状态，不引入 Ariadne `AccountController` 的对象、
    服务连接表或成员查询协议。群成员关系由上层在收到账号/群列表后通过
    :meth:`bind_group` 提供，注册表本身不主动调用协议 API。
    """

    def __init__(self) -> None:
        self._accounts: dict[str, Account] = {}
        self._availability: dict[str, bool] = {}
        self._groups: dict[str, list[str]] = {}
        self._response_types: dict[str, ResponseType] = {}
        self._deterministic_accounts: dict[str, str] = {}
        self._muted_until: dict[tuple[str, str], datetime | None] = {}
        self._group_permissions: dict[tuple[str, str], int] = {}

    @property
    def accounts(self) -> Mapping[str, Account]:
        """返回只读的 self_id 到 Satori 账号句柄映射。"""

        return MappingProxyType(self._accounts)

    @property
    def group_ids(self) -> tuple[str, ...]:
        """返回已建立路由的群 ID，顺序与首次绑定顺序一致。"""

        return tuple(self._groups)

    def register(
        self,
        account: Account,
        *,
        available: bool | None = None,
        groups: Iterable[str | int] = (),
    ) -> str:
        """注册或更新一个 Satori 账号，并可同时绑定群。

        同一 `self_id` 的重新注册用于覆盖重连后产生的新句柄；已有群绑定
        会保留，除非调用方显式解绑。`available=None` 时读取 Satori 登录
        状态作为初始值，生命周期事件应使用 :meth:`set_available` 明确更新。
        """

        account_id = _account_id(account)
        self._accounts[account_id] = account
        self._availability[account_id] = (
            _account_default_availability(account) if available is None else available
        )
        for group_id in groups:
            self.bind_group(group_id, account_id)
        return account_id

    def unregister(self, account_or_id: Account | str | int) -> Account | None:
        """注销账号并移除它参与的所有群路由。"""

        account_id = _account_id(account_or_id)
        account = self._accounts.pop(account_id, None)
        self._availability.pop(account_id, None)
        for mute_key in tuple(self._muted_until):
            if mute_key[0] == account_id:
                del self._muted_until[mute_key]
        for permission_key in tuple(self._group_permissions):
            if permission_key[0] == account_id:
                del self._group_permissions[permission_key]
        for group_id in tuple(self._groups):
            members = self._groups[group_id]
            self._groups[group_id] = [
                candidate for candidate in members if candidate != account_id
            ]
            if not self._groups[group_id]:
                del self._groups[group_id]
                self._response_types.pop(group_id, None)
                self._deterministic_accounts.pop(group_id, None)
            elif self._deterministic_accounts.get(group_id) == account_id:
                self._deterministic_accounts[group_id] = self._groups[group_id][0]
        return account

    def get(self, account_id: str | int) -> Account | None:
        """按 `self_id` 获取账号句柄。"""

        return self._accounts.get(_key(account_id))

    def set_available(
        self, account_or_id: Account | str | int, available: bool
    ) -> None:
        """更新账号是否参与路由；未注册账号不能单独创建状态。"""

        account_id = _account_id(account_or_id)
        if account_id not in self._accounts:
            raise KeyError(f"账号未注册: {account_id}")
        self._availability[account_id] = available

    def is_available(self, account_or_id: Account | str | int) -> bool:
        """返回账号是否已注册且当前可用。"""

        account_id = _account_id(account_or_id)
        return self._availability.get(account_id, False)

    @staticmethod
    def _mute_expired(until: datetime) -> bool:
        now = datetime.now(timezone.utc) if until.tzinfo else datetime.now()
        return until <= now

    def set_muted(
        self,
        account_id: Account | str | int,
        group_id: str | int,
        muted: bool,
        *,
        until: datetime | None = None,
    ) -> None:
        """设置账号在指定群的禁言状态，过期时间由查询时惰性清理。"""

        normalized_account = _account_id(account_id)
        normalized_group = _key(group_id)
        if normalized_account not in self._accounts:
            raise KeyError(f"账号未注册: {normalized_account}")
        if not isinstance(muted, bool):
            raise TypeError("muted 必须是布尔值")
        if until is not None and not isinstance(until, datetime):
            raise TypeError("until 必须是 datetime 或 None")

        mute_key = (normalized_account, normalized_group)
        if muted:
            self._muted_until[mute_key] = until
        else:
            self._muted_until.pop(mute_key, None)

    def is_muted(self, account_id: Account | str | int, group_id: str | int) -> bool:
        """查询账号在指定群是否仍被禁言，并惰性恢复已到期状态。"""

        mute_key = (_account_id(account_id), _key(group_id))
        until = self._muted_until.get(mute_key, _NO_MUTE)
        if until is _NO_MUTE:
            return False
        if until is not None and self._mute_expired(until):
            del self._muted_until[mute_key]
            return False
        return True

    def mute_until(
        self, account_id: Account | str | int, group_id: str | int
    ) -> datetime | None:
        """返回当前禁言到期时间；永久禁言和未禁言都返回 ``None``。"""

        if not self.is_muted(account_id, group_id):
            return None
        return self._muted_until.get((_account_id(account_id), _key(group_id)))

    @staticmethod
    def _is_group_send_failure(failure: BaseException | Mapping[str, object]) -> bool:
        """识别 OneBot action 失败回执，不把普通异常误判为禁言。"""

        if isinstance(failure, Mapping):
            candidates: Iterable[object] = (failure,)
        elif isinstance(failure, ActionFailed):
            candidates = failure.args
        else:
            return False

        for candidate in candidates:
            if not isinstance(candidate, Mapping):
                continue
            status = str(candidate.get("status", "")).lower()
            retcode = candidate.get("retcode")
            if status == "failed" or (
                retcode is not None and str(retcode) not in {"0", "ok"}
            ):
                return True
        return False

    def observe_send_failure(
        self,
        account_id: Account | str | int,
        group_id: str | int,
        failure: BaseException | Mapping[str, object],
    ) -> bool:
        """消费群发送 action 失败接缝，并在失败回执明确时标记禁言。

        调用方必须只在群 ``send_group_msg`` 对应的 Satori action 失败后调用；
        该边界让 OneBot 11 的回执成为状态来源，而不会把任意发送异常升级为
        群级禁言状态。NapCat 的具体 retcode 组合仍待实测确认。
        """

        if not self._is_group_send_failure(failure):
            return False
        self.set_muted(account_id, group_id, True)
        return True

    def bind_group(
        self, group_id: str | int, account_or_id: Account | str | int
    ) -> None:
        """把已注册账号加入群路由，并保持注册顺序。"""

        normalized_group = _key(group_id)
        account_id = _account_id(account_or_id)
        if account_id not in self._accounts:
            raise KeyError(f"账号未注册: {account_id}")
        members = self._groups.setdefault(normalized_group, [])
        if account_id not in members:
            members.append(account_id)
        self._deterministic_accounts.setdefault(normalized_group, account_id)
        self._response_types.setdefault(normalized_group, "random")

    def unbind_group(
        self, group_id: str | int, account_or_id: Account | str | int
    ) -> bool:
        """移除一个账号的群路由；返回是否确实移除了绑定。"""

        normalized_group = _key(group_id)
        account_id = _account_id(account_or_id)
        members = self._groups.get(normalized_group)
        if not members or account_id not in members:
            return False

        members.remove(account_id)
        self._muted_until.pop((account_id, normalized_group), None)
        self._group_permissions.pop((account_id, normalized_group), None)
        if not members:
            del self._groups[normalized_group]
            self._response_types.pop(normalized_group, None)
            self._deterministic_accounts.pop(normalized_group, None)
        elif self._deterministic_accounts.get(normalized_group) == account_id:
            self._deterministic_accounts[normalized_group] = members[0]
        return True

    def bound_accounts_for_group(self, group_id: str | int) -> tuple[Account, ...]:
        """返回群已绑定的全部账号，包含离线或被禁言账号供状态查询。"""

        normalized_group = _key(group_id)
        members = self._groups.get(normalized_group, ())
        return tuple(
            account
            for account_id in members
            if (account := self._accounts.get(account_id)) is not None
        )

    def groups_for_account(self, account_id: Account | str | int) -> tuple[str, ...]:
        """返回账号参与的群 ID，顺序与首次绑定顺序一致。"""

        normalized_account = _account_id(account_id)
        return tuple(
            group_id
            for group_id, members in self._groups.items()
            if normalized_account in members
        )

    @staticmethod
    def _group_permission_level(permission: int | str) -> int:
        if isinstance(permission, str):
            normalized = permission.strip().lower()
            if normalized in _GROUP_PERMISSION_LEVELS:
                return _GROUP_PERMISSION_LEVELS[normalized]
            try:
                permission = int(normalized)
            except ValueError as exc:
                raise ValueError(f"未知群成员权限: {permission}") from exc
        if isinstance(permission, bool) or not isinstance(permission, int):
            raise TypeError("群成员权限必须是整数或角色名称")
        return permission

    def set_group_permission(
        self,
        account_or_id: Account | str | int,
        group_id: str | int,
        permission: int | str,
    ) -> None:
        """记录账号在群内的管理权限，供管理动作选择执行账号。"""

        account_id = _account_id(account_or_id)
        normalized_group = _key(group_id)
        if account_id not in self._accounts:
            raise KeyError(f"账号未注册: {account_id}")
        self._group_permissions[(account_id, normalized_group)] = (
            self._group_permission_level(permission)
        )

    # 这些别名保持调用方对“账号×群”关系的自然命名，不复制第二份状态。
    set_account_group_permission = set_group_permission

    def group_permission(
        self, account_or_id: Account | str | int, group_id: str | int
    ) -> int | None:
        return self._group_permissions.get((_account_id(account_or_id), _key(group_id)))

    account_group_permission = group_permission

    def management_accounts_for_group(
        self, group_id: str | int, *, minimum: int = 32
    ) -> tuple[Account, ...]:
        """返回在线、未被禁言且已知达到管理权限的群账号。"""

        normalized_group = _key(group_id)
        return tuple(
            account
            for account in self.accounts_for_group(normalized_group)
            if (level := self.group_permission(account, normalized_group)) is not None
            and level >= minimum
        )

    def response_type_for_group(self, group_id: str | int) -> ResponseType | None:
        """返回群响应策略；未建立群路由时返回 ``None``。"""

        normalized_group = _key(group_id)
        if normalized_group not in self._groups:
            return None
        return self._response_types.get(normalized_group, "random")

    def deterministic_account_for_group(self, group_id: str | int) -> str | None:
        """返回群 deterministic 策略当前指定的账号 ID。"""

        normalized_group = _key(group_id)
        return self._deterministic_accounts.get(normalized_group)

    def accounts_for_group(
        self, group_id: str | int, *, available_only: bool = True
    ) -> tuple[Account, ...]:
        """返回群对应的账号句柄，默认只返回可用账号。"""

        normalized_group = _key(group_id)
        members = self._groups.get(normalized_group, ())
        return tuple(
            account
            for account_id in members
            if (account := self._accounts.get(account_id)) is not None
            and not self.is_muted(account_id, normalized_group)
            and (not available_only or self._availability.get(account_id, False))
        )

    def set_response_type(
        self, group_id: str | int, response_type: ResponseType
    ) -> None:
        """设置群的随机或 deterministic 响应策略。"""

        if response_type not in {"random", "deterministic"}:
            raise ValueError("response_type 必须是 'random' 或 'deterministic'")
        normalized_group = _key(group_id)
        if normalized_group not in self._groups:
            raise KeyError(f"群未绑定账号: {normalized_group}")
        self._response_types[normalized_group] = response_type

    def set_deterministic_account(
        self, group_id: str | int, account_or_id: Account | str | int
    ) -> None:
        """设置 deterministic 策略指定的账号。"""

        normalized_group = _key(group_id)
        account_id = _account_id(account_or_id)
        if account_id not in self._groups.get(normalized_group, ()):
            raise KeyError(f"账号未绑定到群 {normalized_group}: {account_id}")
        self._deterministic_accounts[normalized_group] = account_id

    def select_account(
        self,
        group_id: str | int,
        *,
        source_id: int | float | None = None,
    ) -> Account | None:
        """依据群策略选择一个可用账号。

        random 策略在给出 `source_id` 时使用旧宿主的 `round(source_id) % n`
        规则，因此同一消息在多个事件分发点可以得到相同账号；未给出时使用
        随机选择。deterministic 策略指定账号不可用时返回 `None`，避免静默
        改由另一账号响应。
        """

        normalized_group = _key(group_id)
        available = self.accounts_for_group(normalized_group)
        if not available:
            return None

        if self._response_types.get(normalized_group, "random") == "deterministic":
            account_id = self._deterministic_accounts.get(normalized_group)
            if (
                account_id is None
                or not self.is_available(account_id)
                or self.is_muted(account_id, normalized_group)
            ):
                return None
            return self._accounts.get(account_id)

        if source_id is None:
            return random.choice(available)
        return available[round(source_id) % len(available)]

    def select_for_context(
        self, context: MessageContext, *, source_id: int | float | None = None
    ) -> Account | None:
        """按消息上下文选择响应账号；私聊沿用事件所属账号。"""

        if context.chat_type == "group":
            return self.select_account(context.channel_id, source_id=source_id)
        if self.is_available(context.account_id):
            return self.get(context.account_id)
        return None


account_registry = AccountRegistry()
