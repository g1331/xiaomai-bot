from __future__ import annotations

import asyncio
import json
import random
from collections.abc import Iterable, Mapping
from datetime import datetime, UTC
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal

from loguru import logger
from satori.client import Account
from satori.exception import ActionFailed

from ..context import MessageContext

if TYPE_CHECKING:
    from ..db.repositories import AccountStateRepository

ResponseType = Literal["random", "deterministic"]
_NO_MUTE = object()
_MAX_EVENT_SELECTIONS = 4096
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


AccountKey = tuple[str, str]
AccountInput = Account | str | int | AccountKey


def account_key(account_or_id: object) -> AccountKey:
    """账号内部使用平台限定键；旧命令和路由中的裸 ID 属于 OneBot。"""

    if isinstance(account_or_id, tuple) and len(account_or_id) == 2:
        return (_key(account_or_id[0]), _key(account_or_id[1]))
    if isinstance(account_or_id, str | int):
        value = str(account_or_id)
        if value.startswith("["):
            pair = json.loads(value)
            if not isinstance(pair, list) or len(pair) != 2:
                raise ValueError("账号键必须包含平台和账号 ID")
            return (_key(pair[0]), _key(pair[1]))
        return ("onebot", value)
    platform = getattr(account_or_id, "platform", None) or getattr(
        getattr(account_or_id, "self_info", None), "platform", "onebot"
    )
    return (_key(platform or "onebot"), _key(getattr(account_or_id, "self_id", None)))


def account_reference(key: AccountKey) -> str:
    """保留既有 OneBot 路由格式；其他平台编码为无歧义的二元 JSON。"""

    return key[1] if key[0] == "onebot" else json.dumps(key, ensure_ascii=False)


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
        # 由 Satori 创建的 Account 对象初始为 ONLINE Login 状态，此时 client
        # 还没有机会设置 ``connected``。
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

    def __init__(self, repository: AccountStateRepository | None = None) -> None:
        self._accounts: dict[AccountKey, Account] = {}
        self._availability: dict[AccountKey, bool] = {}
        self._disabled: set[AccountKey] = set()
        self._groups: dict[str, list[AccountKey]] = {}
        self._response_types: dict[str, ResponseType] = {}
        self._deterministic_accounts: dict[str, AccountKey] = {}
        self._muted_until: dict[tuple[AccountKey, str], datetime | None] = {}
        self._group_permissions: dict[tuple[AccountKey, str], int] = {}
        self._event_selections: dict[tuple[str, str], AccountKey] = {}
        self._repository = repository
        self._ready = repository is None
        self._persist_task = None
        self._persist_requested = False
        self._persist_lock: asyncio.Lock | None = None

    @property
    def ready(self) -> bool:
        """返回账号路由数据库快照是否可安全用于发送。"""

        return self._ready

    def configure(self, repository: AccountStateRepository | None = None) -> None:
        """配置 repository 并清空本次运行的路由快照。"""

        if self._persist_task is not None and not self._persist_task.done():
            self._persist_task.cancel()
        self._persist_task = None
        self._repository = repository
        self._disabled = set()
        self._groups = {}
        self._response_types = {}
        self._deterministic_accounts = {}
        self._persist_requested = False
        self._persist_lock = None
        self._ready = repository is None

    def mark_unavailable(self) -> None:
        """清空不可用数据库状态，阻止故障时继续使用账号路由。"""

        self._groups = {}
        self._response_types = {}
        self._deterministic_accounts = {}
        self._ready = False

    async def initialize(
        self, repository: AccountStateRepository | None = None
    ) -> None:
        """从 repository 恢复有序群路由和响应策略。"""

        if repository is not None:
            self._repository = repository
        if self._repository is None:
            self._ready = True
            return

        try:
            snapshot = await self._repository.load_state()
        except Exception:
            self.mark_unavailable()
            raise

        groups: dict[str, list[AccountKey]] = {}
        for row in snapshot.routes:
            members = groups.setdefault(row.group_id, [])
            if account_key(row.account_id) not in members:
                members.append(account_key(row.account_id))

        response_types: dict[str, ResponseType] = {}
        deterministic_accounts: dict[str, AccountKey] = {}
        try:
            for row in snapshot.responses:
                if row.response_type not in {"random", "deterministic"}:
                    raise ValueError(f"群 {row.group_id} 的响应类型非法")
                response_types[row.group_id] = row.response_type
                if row.deterministic_account is not None:
                    deterministic_accounts[row.group_id] = account_key(
                        row.deterministic_account
                    )
        except Exception:
            self.mark_unavailable()
            raise

        self._groups = groups
        self._response_types = {
            group_id: response_types.get(group_id, "random") for group_id in groups
        }
        self._deterministic_accounts = {
            group_id: account_id
            for group_id, account_id in deterministic_accounts.items()
            if account_id in groups.get(group_id, ())
        }
        self._ready = True

    def _route_available(self) -> bool:
        return self._ready

    def _state_records(self) -> tuple[tuple[object, ...], tuple[object, ...]]:
        from ..db.repositories import AccountResponseRecord, AccountRouteRecord

        routes = tuple(
            AccountRouteRecord(
                group_id=group_id,
                account_id=account_reference(account_id),
                position=position,
            )
            for group_id, members in self._groups.items()
            for position, account_id in enumerate(members)
        )
        responses = tuple(
            AccountResponseRecord(
                group_id=group_id,
                response_type=self._response_types.get(group_id, "random"),
                deterministic_account=self.deterministic_account_for_group(group_id),
            )
            for group_id in self._groups
        )
        return routes, responses

    async def persist_state(self) -> None:
        """将当前账号路由快照原子替换到状态表。"""

        if self._repository is None:
            if not self._ready:
                from ..db.errors import DatabaseUnavailableError

                raise DatabaseUnavailableError("账号路由数据库不可用")
            return
        if not self._ready:
            from ..db.errors import DatabaseUnavailableError

            raise DatabaseUnavailableError("账号路由数据库尚未就绪")
        if self._persist_lock is None:
            self._persist_lock = asyncio.Lock()
        async with self._persist_lock:
            routes, responses = self._state_records()
            try:
                await self._repository.replace_state(routes, responses)
            except Exception:
                self.mark_unavailable()
                raise

    def _request_persist(self) -> None:
        """在同步事件入口之后安排一次异步快照刷新。"""

        if self._repository is None or not self._ready:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._persist_requested = True
        if self._persist_task is None or self._persist_task.done():
            self._persist_task = loop.create_task(self._drain_persistence())

    async def _drain_persistence(self) -> None:
        while self._persist_requested and self._ready:
            self._persist_requested = False
            try:
                await self.persist_state()
            except Exception as error:
                logger.exception("账号路由状态保存失败: {}", error)
                self._persist_requested = False
        self._persist_task = None

    async def flush_persistence(self) -> None:
        """等待同步事件入口安排的账号状态写入完成。"""

        task = self._persist_task
        if task is not None:
            await task

    @property
    def accounts(self) -> Mapping[str, Account]:
        """返回只读账号引用映射；OneBot 保留裸 ID，其他平台带平台限定。"""

        return MappingProxyType(
            {account_reference(key): value for key, value in self._accounts.items()}
        )

    @property
    def group_ids(self) -> tuple[str, ...]:
        """返回已建立路由的群 ID，顺序与首次绑定顺序一致。"""

        if not self._route_available():
            return ()
        return tuple(self._groups)

    def register(
        self,
        account: Account,
        *,
        available: bool | None = None,
        groups: Iterable[str | int] = (),
    ) -> str:
        """注册或更新一个 Satori 账号，并可同时绑定群。

        同一平台和 `self_id` 的重新注册用于覆盖重连后产生的新句柄；已有群绑定
        会保留，除非调用方显式解绑。`available=None` 时读取 Satori 登录
        状态作为初始值，生命周期事件应使用 :meth:`set_available` 明确更新。
        """

        account_id = account_key(account)
        self._accounts[account_id] = account
        self._availability[account_id] = (
            _account_default_availability(account) if available is None else available
        )
        for group_id in groups:
            self.bind_group(group_id, account_id)
        return account_reference(account_id)

    def unregister(self, account_or_id: AccountInput) -> Account | None:
        """注销账号并移除它参与的所有群路由。"""

        account_id = account_key(account_or_id)
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
        self._request_persist()
        return account

    def get(self, account_id: AccountInput) -> Account | None:
        """按平台限定键、账户对象或旧 OneBot ID 获取账号句柄。"""

        return self._accounts.get(account_key(account_id))

    def set_available(self, account_or_id: AccountInput, available: bool) -> None:
        """更新账号是否参与路由；未注册账号不能单独创建状态。"""

        account_id = account_key(account_or_id)
        if account_id not in self._accounts:
            raise KeyError(f"账号未注册: {account_id}")
        self._availability[account_id] = available

    def is_available(self, account_or_id: AccountInput) -> bool:
        """返回账号是否已注册且当前可用。"""

        account_id = account_key(account_or_id)
        return self.is_online(account_id) and account_id not in self._disabled

    def is_online(self, account_or_id: object) -> bool:
        """连接状态独立于管理停用状态。"""

        return self._availability.get(account_key(account_or_id), False)

    def set_enabled(self, account_or_id: object, enabled: bool) -> None:
        if type(enabled) is not bool:
            raise TypeError("enabled 必须是布尔值")
        key = account_key(account_or_id)
        if enabled:
            self._disabled.discard(key)
        else:
            self._disabled.add(key)

    def is_enabled(self, account_or_id: object) -> bool:
        return account_key(account_or_id) not in self._disabled

    @staticmethod
    def _mute_expired(until: datetime) -> bool:
        now = datetime.now(UTC) if until.tzinfo else datetime.now()
        return until <= now

    def set_muted(
        self,
        account_id: AccountInput,
        group_id: str | int,
        muted: bool,
        *,
        until: datetime | None = None,
    ) -> None:
        """设置账号在指定群的禁言状态，过期时间由查询时惰性清理。"""

        normalized_account = account_key(account_id)
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

    def is_muted(self, account_id: AccountInput, group_id: str | int) -> bool:
        """查询账号在指定群是否仍被禁言，并惰性恢复已到期状态。"""

        mute_key = (account_key(account_id), _key(group_id))
        until = self._muted_until.get(mute_key, _NO_MUTE)
        if until is _NO_MUTE:
            return False
        if until is not None and self._mute_expired(until):
            del self._muted_until[mute_key]
            return False
        return True

    def mute_until(
        self, account_id: AccountInput, group_id: str | int
    ) -> datetime | None:
        """返回当前禁言到期时间；永久禁言和未禁言都返回 ``None``。"""

        if not self.is_muted(account_id, group_id):
            return None
        return self._muted_until.get((account_key(account_id), _key(group_id)))

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
        account_id: AccountInput,
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

    def bind_group(self, group_id: str | int, account_or_id: AccountInput) -> None:
        """把已注册账号加入群路由，并保持注册顺序。"""

        normalized_group = _key(group_id)
        account_id = account_key(account_or_id)
        if not self._route_available():
            return
        if account_id not in self._accounts:
            raise KeyError(f"账号未注册: {account_id}")
        members = self._groups.setdefault(normalized_group, [])
        changed = account_id not in members
        if account_id not in members:
            members.append(account_id)
        self._deterministic_accounts.setdefault(normalized_group, account_id)
        self._response_types.setdefault(normalized_group, "random")
        if changed:
            self._request_persist()

    def unbind_group(self, group_id: str | int, account_or_id: AccountInput) -> bool:
        """移除一个账号的群路由；返回是否确实移除了绑定。"""

        normalized_group = _key(group_id)
        account_id = account_key(account_or_id)
        if not self._route_available():
            return False
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
        self._request_persist()
        return True

    def bound_accounts_for_group(self, group_id: str | int) -> tuple[Account, ...]:
        """返回群已绑定的全部账号，包含离线或被禁言账号供状态查询。"""

        if not self._route_available():
            return ()
        normalized_group = _key(group_id)
        members = self._groups.get(normalized_group, ())
        return tuple(
            account
            for account_id in members
            if (account := self._accounts.get(account_id)) is not None
        )

    def online_accounts_for_group(self, group_id: str | int) -> tuple[Account, ...]:
        """返回群内在线账号，包含被禁言账号供管理动作候选使用。"""

        return tuple(
            account
            for account in self.bound_accounts_for_group(group_id)
            if self.is_available(account)
        )

    def groups_for_account(self, account_id: AccountInput) -> tuple[str, ...]:
        """返回账号参与的群 ID，顺序与首次绑定顺序一致。"""

        if not self._route_available():
            return ()
        normalized_account = account_key(account_id)
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
        account_or_id: AccountInput,
        group_id: str | int,
        permission: int | str,
    ) -> None:
        """记录账号在群内的管理权限，供管理动作选择执行账号。"""

        account_id = account_key(account_or_id)
        normalized_group = _key(group_id)
        if account_id not in self._accounts:
            raise KeyError(f"账号未注册: {account_id}")
        self._group_permissions[(account_id, normalized_group)] = (
            self._group_permission_level(permission)
        )

    # 这些别名保持调用方对“账号×群”关系的自然命名，不复制第二份状态。
    set_account_group_permission = set_group_permission

    def group_permission(
        self, account_or_id: AccountInput, group_id: str | int
    ) -> int | None:
        return self._group_permissions.get((account_key(account_or_id), _key(group_id)))

    account_group_permission = group_permission

    def management_accounts_for_group(
        self, group_id: str | int, *, minimum: int = 32
    ) -> tuple[Account, ...]:
        """返回在线且已知达到管理权限的群账号。"""

        normalized_group = _key(group_id)
        return tuple(
            account
            for account in self.online_accounts_for_group(normalized_group)
            if (level := self.group_permission(account, normalized_group)) is not None
            and level >= minimum
        )

    def response_type_for_group(self, group_id: str | int) -> ResponseType | None:
        """返回群响应策略；未建立群路由时返回 ``None``。"""

        if not self._route_available():
            return None
        normalized_group = _key(group_id)
        if normalized_group not in self._groups:
            return None
        return self._response_types.get(normalized_group, "random")

    def deterministic_account_for_group(self, group_id: str | int) -> str | None:
        """返回群 deterministic 策略当前指定的账号 ID。"""

        if not self._route_available():
            return None
        normalized_group = _key(group_id)
        key = self._deterministic_accounts.get(normalized_group)
        return account_reference(key) if key is not None else None

    def accounts_for_group(
        self, group_id: str | int, *, available_only: bool = True
    ) -> tuple[Account, ...]:
        """返回群对应的账号句柄，默认只返回可用账号。"""

        if not self._route_available():
            return ()
        normalized_group = _key(group_id)
        members = self._groups.get(normalized_group, ())
        return tuple(
            account
            for account_id in members
            if (account := self._accounts.get(account_id)) is not None
            and not self.is_muted(account_id, normalized_group)
            and (not available_only or self.is_available(account_id))
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
        self._request_persist()

    def set_deterministic_account(
        self, group_id: str | int, account_or_id: AccountInput
    ) -> None:
        """设置 deterministic 策略指定的账号。"""

        normalized_group = _key(group_id)
        account_id = account_key(account_or_id)
        if account_id not in self._groups.get(normalized_group, ()):
            raise KeyError(f"账号未绑定到群 {normalized_group}: {account_id}")
        self._deterministic_accounts[normalized_group] = account_id
        self._request_persist()

    def clear_deterministic_account(self, group_id: str | int) -> None:
        """清除显式 deterministic 账号并恢复群绑定顺序的默认账号。"""

        normalized_group = _key(group_id)
        members = self._groups.get(normalized_group)
        if not members:
            raise KeyError(f"群未绑定账号: {normalized_group}")
        self._deterministic_accounts[normalized_group] = members[0]
        self._request_persist()

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

    def select_for_event(
        self, group_id: str | int, *, source_id: object | None = None
    ) -> Account | None:
        """为同一消息事件缓存 random 选路，确保多账号只处理一次。"""

        normalized_group = _key(group_id)
        available = self.accounts_for_group(normalized_group)
        if not available:
            return None
        if self._response_types.get(normalized_group, "random") == "deterministic":
            return self.select_account(normalized_group)
        if source_id is None:
            return random.choice(available)

        selection_key = (normalized_group, str(source_id))
        selected_id = self._event_selections.get(selection_key)
        if selected_id is not None:
            selected = self._accounts.get(selected_id)
            if selected in available:
                return selected
            # 这个选择属于当前消息。选定账号离线或被禁言后不要重新选路，否则
            # 迟到的重复事件可能会被第二个账号处理。
            return None
        selected = random.choice(available)
        self._event_selections[selection_key] = account_key(selected)
        if len(self._event_selections) > _MAX_EVENT_SELECTIONS:
            oldest_key = next(iter(self._event_selections))
            del self._event_selections[oldest_key]
        return selected

    def select_for_context(
        self, context: MessageContext, *, source_id: int | float | None = None
    ) -> Account | None:
        """按消息上下文选择响应账号；私聊沿用事件所属账号。"""

        if context.chat_type == "group":
            return self.select_account(context.channel_id, source_id=source_id)
        key = (context.platform, context.account_id)
        if self.is_available(key):
            return self.get(key)
        return None


account_registry = AccountRegistry()
