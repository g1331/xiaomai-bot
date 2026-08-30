from __future__ import annotations

import inspect
import re
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from loguru import logger
from satori.client import Account

from ..context import MessageContext
from .accounts import AccountRegistry, account_registry
from .perm import Permission, PermissionChecker

"""宿主侧平台动作服务。

标准动作只调用 Satori ``Account.protocol`` 的原生方法；已安装的
``satori-python-adapter-onebot11`` 会负责把这些方法转换为 OneBot 11 action。
因此插件不需要知道 OneBot 请求格式，也不会绕过 Entari/Satori 的协议边界。

OneBot 11 没有标准 capability 查询 action。这里采用账号×能力的懒探测：第一次
调用成功记为可用，真正的平台级不支持/失败才记为不可用；群内权限不足只记录失败
而不会锁死该账号在其他群的能力。显式配置和运行时覆盖优先于学习结果。
"""


class ActionCapability(str, Enum):
    """Tenko 暴露给插件的逻辑能力名。"""

    SEND_GROUP_MESSAGE = "send_group_message"
    MEMBER_MUTE = "member_mute"
    GROUP_MUTE = "group_mute"
    MESSAGE_DELETE = "message_delete"
    MEMBER_KICK = "member_kick"
    GROUP_ESSENCE = "group_essence"
    GROUP_LEAVE = "group_leave"
    GROUP_LIST = "group_list"


Capability = ActionCapability


# 这些 action 名只属于宿主协议接缝。插件只依赖 ActionCapability 和下方服务
# 方法，避免在业务层复制 OneBot action 字符串或参数形状。
_ONEBOT_ACTIONS = {
    ActionCapability.SEND_GROUP_MESSAGE: "send_group_msg",
    ActionCapability.MEMBER_MUTE: "set_group_ban",
    # OneBot 11 的全体禁言 action 是 set_group_whole_ban，而不是单人禁言 action。
    ActionCapability.GROUP_MUTE: "set_group_whole_ban",
    ActionCapability.MESSAGE_DELETE: "delete_msg",
    ActionCapability.MEMBER_KICK: "set_group_kick",
    ActionCapability.GROUP_ESSENCE: "set_essence_msg",
    ActionCapability.GROUP_LEAVE: "set_group_leave",
    ActionCapability.GROUP_LIST: "get_group_list",
}

_CAPABILITY_ALIASES = {
    action: capability for capability, action in _ONEBOT_ACTIONS.items()
}
_MAX_BAN_SECONDS = 30 * 24 * 60 * 60
_ID_PATTERN = re.compile(r"^\d+$")


def _key(value: object, label: str) -> str:
    if value is None:
        raise ValueError(f"{label}不能为空")
    normalized = str(value)
    if not normalized:
        raise ValueError(f"{label}不能为空")
    return normalized


def _numeric_id(value: object, label: str) -> tuple[str, int]:
    normalized = _key(value, label)
    if not _ID_PATTERN.fullmatch(normalized):
        raise ValueError(f"{label}必须是数字")
    return normalized, int(normalized)


def _capability(value: str | ActionCapability) -> ActionCapability:
    if isinstance(value, ActionCapability):
        return value
    try:
        return ActionCapability(value)
    except ValueError:
        try:
            return _CAPABILITY_ALIASES[value]
        except KeyError as exc:
            raise ValueError(f"未知平台能力: {value}") from exc


def _retcode(value: object) -> int | str | None:
    if value is None or isinstance(value, int | str):
        return value
    return str(value)


def _is_failed_receipt(value: Mapping[str, object]) -> bool:
    status = str(value.get("status", "")).lower()
    if status in {"failed", "error"}:
        return True
    retcode = value.get("retcode")
    return retcode is not None and str(retcode).lower() not in {"0", "ok"}


def _mapping_from(
    value: object, *, failed_only: bool = False
) -> Mapping[str, object] | None:
    """从 Satori ActionFailed 或测试回执中取出 OneBot 风格 mapping。"""

    candidates: list[object] = []
    if isinstance(value, Mapping):
        candidates.append(value)
    elif isinstance(value, BaseException):
        candidates.extend(value.args)

    for candidate in candidates:
        if isinstance(candidate, Mapping):
            if not failed_only or _is_failed_receipt(candidate):
                return candidate
        if isinstance(candidate, BaseException):
            nested = _mapping_from(candidate, failed_only=failed_only)
            if nested is not None:
                return nested
    return None


def _fields_from_text(detail: str) -> tuple[str | None, int | str | None]:
    status_match = re.search(r"status[=:]['\"]?(\w+)", detail, re.IGNORECASE)
    retcode_match = re.search(r"retcode[=:]['\"]?([\w-]+)", detail, re.IGNORECASE)
    status = status_match.group(1).lower() if status_match else None
    raw_retcode = retcode_match.group(1) if retcode_match else None
    if raw_retcode is not None and raw_retcode.isdigit():
        return status, int(raw_retcode)
    return status, raw_retcode


@dataclass(frozen=True, slots=True)
class ActionFailure:
    """一次 action 失败的可观测快照。"""

    account_id: str
    capability: ActionCapability
    action: str
    status: str | None = None
    retcode: int | str | None = None
    data: Any = None
    message: str | None = None
    wording: str | None = None
    echo: str | int | None = None
    error_type: str | None = None
    detail: str | None = None
    raw: Any = field(default=None, repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class ActionReceipt:
    """统一的成功回执；``data`` 是 Satori 原生 action 的返回数据。"""

    account_id: str
    capability: ActionCapability
    action: str
    status: str = "ok"
    retcode: int | str = 0
    data: Any = None


class ActionServiceError(RuntimeError):
    """动作服务拒绝执行或平台回执失败。"""

    def __init__(self, message: str, *, failure: ActionFailure | None = None):
        super().__init__(message)
        self.failure = failure
        self.record = failure


class ActionPermissionDenied(ActionServiceError):
    """调用方未达到旧宿主要求的群/成员权限。"""


class ActionAccountUnavailable(ActionServiceError):
    """账号未注册或当前不在线。"""


class ActionTargetUnavailable(ActionServiceError):
    """目标群路由当前不可用，例如账号在该群处于禁言状态。"""


class ActionCapabilityUnavailable(ActionServiceError):
    """能力被显式禁用或已由失败回执标记为不可用。"""


class ActionExecutionError(ActionServiceError):
    """Satori/OneBot action 执行后收到失败回执或异常。"""


# 这些别名让宿主调用方可以使用更接近业务语义的名字，同时不引入第二套异常。
CapabilityUnavailableError = ActionCapabilityUnavailable
AccountUnavailableError = ActionAccountUnavailable


class ActionService:
    """统一发出平台动作并维护账号级 capability 状态。

    该抽象隔离的是“业务插件的管理意图”和“Satori/OneBot action 接缝”：它不是
    对 ``Account.protocol`` 的无语义转发，而是负责权限、账号可用性、能力学习、
    OneBot 回执归一化和失败观测。标准动作仍由安装版本的 Satori 原生 API 执行，
    扩展动作则集中通过 ``protocol.internal`` 进入适配器提供的内部 action 路由。
    """

    def __init__(
        self,
        registry: AccountRegistry | None = None,
        permission_checker: PermissionChecker | None = None,
        capability_overrides: Mapping[str, Mapping[str, bool]] | None = None,
    ) -> None:
        self.registry = registry or account_registry
        self.permission_checker = permission_checker or PermissionChecker()
        self._learned: dict[tuple[str, ActionCapability], bool] = {}
        self._overrides: dict[tuple[str, ActionCapability], bool] = {}
        self._failures: list[ActionFailure] = []
        if capability_overrides is not None:
            self.configure_capability_overrides(capability_overrides)

    @property
    def failures(self) -> tuple[ActionFailure, ...]:
        """返回只读的失败记录快照。"""

        return tuple(self._failures)

    @property
    def last_failure(self) -> ActionFailure | None:
        return self._failures[-1] if self._failures else None

    def configure_capability_overrides(
        self, overrides: Mapping[str, Mapping[str, bool]]
    ) -> None:
        """替换显式 capability 覆盖；配置优先于首次调用的学习结果。"""

        if not isinstance(overrides, Mapping):
            raise TypeError("capability_overrides 必须是 mapping")
        normalized: dict[tuple[str, ActionCapability], bool] = {}
        for account_id, account_overrides in overrides.items():
            if not isinstance(account_overrides, Mapping):
                raise TypeError("每个账号的 capability_overrides 必须是 mapping")
            account_key = _key(account_id, "账号 ID")
            for capability, enabled in account_overrides.items():
                if type(enabled) is not bool:
                    raise TypeError("capability 覆盖值必须是布尔值")
                normalized[(account_key, _capability(str(capability)))] = enabled
        self._overrides = normalized

    def set_capability(
        self,
        account_id: str | int,
        capability: str | ActionCapability,
        available: bool,
        *,
        override: bool = False,
    ) -> None:
        """设置运行时能力状态；``override=True`` 时不会被失败回执改写。"""

        if type(available) is not bool:
            raise TypeError("available 必须是布尔值")
        key = (_key(account_id, "账号 ID"), _capability(capability))
        if override:
            self._overrides[key] = available
        else:
            self._learned[key] = available

    def capability_status(
        self, account_id: str | int, capability: str | ActionCapability
    ) -> bool | None:
        """返回 ``True``、``False`` 或尚未探测的 ``None``。"""

        key = (_key(account_id, "账号 ID"), _capability(capability))
        return self._overrides.get(key, self._learned.get(key))

    async def authorize(
        self,
        context: MessageContext | None,
        required: int,
        *,
        checker: PermissionChecker | None = None,
    ) -> bool:
        """按旧 ``core.control`` 数值语义检查群状态和成员权限。"""

        if context is None:
            raise ActionPermissionDenied("管理动作缺少消息权限上下文")
        permission = checker or self.permission_checker
        if not await permission.require_group_perm(context, Permission.ActiveGroup):
            raise ActionPermissionDenied("当前群不可用")
        if not await permission.require_perm(context, required):
            raise ActionPermissionDenied("权限不足")
        return True

    def _account(self, account_or_id: Account | str | int) -> tuple[str, Account]:
        account_id = _key(getattr(account_or_id, "self_id", account_or_id), "账号 ID")
        account = self.registry.get(account_id)
        if account is None or not self.registry.is_available(account_id):
            raise ActionAccountUnavailable(f"账号不可用: {account_id}")
        return account_id, account

    def _capability_allowed(
        self, account_id: str, capability: ActionCapability
    ) -> None:
        status = self.capability_status(account_id, capability)
        if status is False:
            action = _ONEBOT_ACTIONS[capability]
            logger.warning(
                "platform capability unavailable: account={} capability={} action={}",
                account_id,
                capability.value,
                action,
            )
            raise ActionCapabilityUnavailable(
                f"账号 {account_id} 不支持平台能力 {capability.value}"
            )

    @staticmethod
    def _failure(
        account_id: str,
        capability: ActionCapability,
        exception: BaseException,
    ) -> ActionFailure:
        action = _ONEBOT_ACTIONS[capability]
        response = _mapping_from(exception, failed_only=False)
        detail = str(exception)
        status = None
        retcode: int | str | None = None
        if response is not None:
            status = (
                str(response.get("status"))
                if response.get("status") is not None
                else None
            )
            retcode = _retcode(response.get("retcode"))
        else:
            status, retcode = _fields_from_text(detail)
        return ActionFailure(
            account_id=account_id,
            capability=capability,
            action=action,
            status=status,
            retcode=retcode,
            data=response.get("data") if response is not None else None,
            message=(
                str(response["message"])
                if response and response.get("message") is not None
                else None
            ),
            wording=(
                str(response["wording"])
                if response and response.get("wording") is not None
                else None
            ),
            echo=(response.get("echo") if response is not None else None),
            error_type=type(exception).__name__,
            detail=detail,
            raw=exception,
        )

    @staticmethod
    def _failure_from_response(
        account_id: str,
        capability: ActionCapability,
        response: Mapping[str, object],
    ) -> ActionFailure:
        return ActionFailure(
            account_id=account_id,
            capability=capability,
            action=_ONEBOT_ACTIONS[capability],
            status=(
                str(response["status"]) if response.get("status") is not None else None
            ),
            retcode=_retcode(response.get("retcode")),
            data=response.get("data"),
            message=(
                str(response["message"])
                if response.get("message") is not None
                else None
            ),
            wording=(
                str(response["wording"])
                if response.get("wording") is not None
                else None
            ),
            echo=response.get("echo"),
            error_type="OneBotReceipt",
            detail=str(dict(response)),
            raw=response,
        )

    @staticmethod
    def _is_permission_failure(failure: ActionFailure) -> bool:
        """识别群内权限不足，避免把账号能力错误锁定到全局。"""

        error_type = (failure.error_type or "").lower()
        if any(
            word in error_type for word in ("forbidden", "permission", "unauthorized")
        ):
            return True
        status = (failure.status or "").lower()
        if status in {"forbidden", "unauthorized", "permission_denied", "403"}:
            return True
        details = " ".join(
            value.lower()
            for value in (failure.message, failure.wording, failure.detail)
            if value
        )
        return any(
            phrase in details
            for phrase in (
                "permission",
                "forbidden",
                "unauthorized",
                "access denied",
                "not allowed",
                "no permission",
                "权限",
                "无权",
                "不允许",
                "禁止",
                "管理员权限",
            )
        )

    @staticmethod
    def _is_transient_failure(failure: ActionFailure) -> bool:
        """识别连接/超时等暂态错误，避免它们污染账号能力学习结果。"""

        raw = failure.raw
        if isinstance(raw, ConnectionError | TimeoutError | OSError):
            return True
        error_type = (failure.error_type or "").lower()
        if any(
            word in error_type
            for word in ("connection", "timeout", "network", "tempor")
        ):
            return True
        details = " ".join(
            value.lower()
            for value in (failure.message, failure.wording, failure.detail)
            if value
        )
        return any(
            phrase in details
            for phrase in ("connection timed out", "network unavailable", "暂时不可用")
        )

    def _remember_failure(self, failure: ActionFailure) -> None:
        self._failures.append(failure)
        key = (failure.account_id, failure.capability)
        if (
            key not in self._overrides
            and not self._is_permission_failure(failure)
            and not self._is_transient_failure(failure)
        ):
            self._learned[key] = False
        logger.warning(
            "platform action failed: account={} capability={} action={} "
            "status={} retcode={} message={} wording={} echo={}",
            failure.account_id,
            failure.capability.value,
            failure.action,
            failure.status,
            failure.retcode,
            failure.message,
            failure.wording,
            failure.echo,
        )

    def _remember_success(self, account_id: str, capability: ActionCapability) -> None:
        key = (account_id, capability)
        if key not in self._overrides:
            self._learned[key] = True

    @staticmethod
    def _management_level(value: object) -> int | None:
        """从 Satori Member 或 OneBot 原始群成员信息读取角色等级。"""

        if isinstance(value, Mapping):
            nested = value.get("data")
            if isinstance(nested, Mapping):
                value = nested
            if isinstance(value, Mapping):
                raw = value.get("permission", value.get("role"))
                if raw is not None:
                    value = raw
        if value is not None and not isinstance(value, Mapping):
            raw = str(value).lower()
            if raw in {"owner", "群主"}:
                return int(Permission.GroupOwner)
            if raw in {"admin", "administrator", "管理员"}:
                return int(Permission.GroupAdmin)
            if raw in {"member", "user", "群员"}:
                return int(Permission.User)
            try:
                return int(value)
            except (TypeError, ValueError):
                pass
        roles = getattr(value, "roles", ())
        level = int(Permission.User)
        found = False
        for role in roles:
            role_level = ActionService._management_level(getattr(role, "id", role))
            if role_level is not None:
                level = max(level, role_level)
                found = True
        return level if found else None

    async def _discover_group_permission(
        self, account: Account, group_id: str
    ) -> int | None:
        """按当前协议能力懒读取候选账号在群内的角色。"""

        known = self.registry.group_permission(account, group_id)
        if known is not None:
            return known
        protocol = account.protocol
        result: object | None = None
        # The OneBot adapter's Satori ``guild_member_get`` currently builds a
        # Member without copying the raw ``role`` field.  Prefer the standard
        # raw API inside this host boundary so Administrator/Owner discovery
        # is based on the actual platform response; retain the typed Satori
        # method as a fallback for other adapters.
        internal = getattr(protocol, "internal", None)
        member_get = getattr(protocol, "guild_member_get", None)
        try:
            if callable(internal):
                _, group_number = _numeric_id(group_id, "群 ID")
                _, user_number = _numeric_id(account.self_id, "账号 ID")
                result = internal(
                    "get_group_member_info",
                    group_id=group_number,
                    user_id=user_number,
                )
                if inspect.isawaitable(result):
                    result = await result
            elif callable(member_get):
                result = member_get(group_id, account.self_id)
                if inspect.isawaitable(result):
                    result = await result
            else:
                return None
        except Exception as error:
            logger.debug(
                "Could not discover group permission: account={} group={} error={}",
                account.self_id,
                group_id,
                error,
            )
            return None

        level = self._management_level(result)
        if level is not None:
            self.registry.set_group_permission(account, group_id, level)
        return level

    async def _management_candidates(
        self,
        primary_id: str,
        primary: Account,
        group_id: str | None,
    ) -> list[tuple[str, Account]]:
        candidates = [(primary_id, primary)]
        if group_id is None:
            return candidates
        for account in self.registry.online_accounts_for_group(group_id):
            account_id = _key(account.self_id, "账号 ID")
            if account_id == primary_id:
                continue
            level = await self._discover_group_permission(account, group_id)
            if level is not None and level >= int(Permission.GroupAdmin):
                candidates.append((account_id, account))
        return candidates

    @staticmethod
    def _execution_error(failure: ActionFailure, cause: BaseException | None = None):
        error = ActionExecutionError(
            f"平台动作失败: {failure.action} ({failure.retcode or failure.detail})",
            failure=failure,
        )
        if cause is not None:
            error.__cause__ = cause
        return error

    async def _invoke(
        self,
        account_or_id: Account | str | int,
        capability: str | ActionCapability,
        caller: Callable[[Any], Awaitable[Any]],
        *,
        context: MessageContext | None,
        required: int,
        permission_checker: PermissionChecker | None = None,
        send_group_id: str | None = None,
        management_group_id: str | None = None,
    ) -> ActionReceipt:
        await self.authorize(context, required, checker=permission_checker)
        account_id, account = self._account(account_or_id)
        normalized_capability = _capability(capability)
        candidates = await self._management_candidates(
            account_id, account, management_group_id
        )
        last_error: ActionServiceError | None = None
        for candidate_index, (current_id, current_account) in enumerate(candidates):
            try:
                self._capability_allowed(current_id, normalized_capability)
            except ActionCapabilityUnavailable as error:
                last_error = error
                if candidate_index + 1 < len(candidates):
                    continue
                raise

            try:
                response = await caller(current_account.protocol)
            except Exception as exc:
                failure = self._failure(current_id, normalized_capability, exc)
                self._remember_failure(failure)
                if send_group_id is not None:
                    self.registry.observe_send_failure(current_id, send_group_id, exc)
                error = self._execution_error(failure, exc)
                if (
                    management_group_id is not None
                    and self._is_permission_failure(failure)
                    and candidate_index + 1 < len(candidates)
                ):
                    last_error = error
                    continue
                raise error from exc

            if isinstance(response, Mapping) and _is_failed_receipt(response):
                failure = self._failure_from_response(
                    current_id, normalized_capability, response
                )
                self._remember_failure(failure)
                if send_group_id is not None:
                    self.registry.observe_send_failure(
                        current_id, send_group_id, response
                    )
                error = self._execution_error(failure)
                if (
                    management_group_id is not None
                    and self._is_permission_failure(failure)
                    and candidate_index + 1 < len(candidates)
                ):
                    last_error = error
                    continue
                raise error

            status = "ok"
            retcode: int | str = 0
            data = response
            if isinstance(response, Mapping) and (
                "status" in response or "retcode" in response
            ):
                status = str(response.get("status", "ok"))
                retcode = _retcode(response.get("retcode", 0)) or 0
                data = response.get("data")
            self._remember_success(current_id, normalized_capability)
            if send_group_id is not None and self.registry.get(current_id) is not None:
                self.registry.set_muted(current_id, send_group_id, False)
            return ActionReceipt(
                account_id=current_id,
                capability=normalized_capability,
                action=_ONEBOT_ACTIONS[normalized_capability],
                status=status,
                retcode=retcode,
                data=data,
            )
        if last_error is not None:
            raise last_error
        raise ActionExecutionError("没有可用的平台动作执行账号")

    @staticmethod
    async def _collect_group_ids(result: object) -> tuple[str, ...]:
        """兼容 Satori IterablePageResult 和测试中的普通返回值。"""

        items: list[object] = []
        if hasattr(result, "__aiter__"):
            async for item in result:  # type: ignore[union-attr]
                items.append(item)
        else:
            data = getattr(result, "data", result)
            if isinstance(data, Mapping):
                data = data.get("data", data.get("groups", ()))
            if isinstance(data, str | bytes) or data is None:
                data = ()
            elif isinstance(data, Iterable):
                items.extend(data)
            else:
                items.append(data)

        group_ids: list[str] = []
        for item in items:
            if isinstance(item, Mapping):
                group_id = item.get("id", item.get("group_id"))
            else:
                group_id = getattr(item, "id", item)
            if group_id is not None:
                normalized = str(group_id)
                if normalized and normalized not in group_ids:
                    group_ids.append(normalized)
        return tuple(group_ids)

    async def get_group_list(
        self, account_or_id: Account | str | int
    ) -> tuple[str, ...]:
        """通过 Satori ``guild_list`` 读取账号当前群列表。"""

        account_id, account = self._account(account_or_id)
        capability = ActionCapability.GROUP_LIST
        self._capability_allowed(account_id, capability)
        try:
            result = account.protocol.guild_list()
            if inspect.isawaitable(result):
                result = await result
            if isinstance(result, Mapping) and _is_failed_receipt(result):
                failure = self._failure_from_response(account_id, capability, result)
                self._remember_failure(failure)
                raise self._execution_error(failure)
            group_ids = await self._collect_group_ids(result)
        except ActionExecutionError:
            raise
        except Exception as exc:
            failure = self._failure(account_id, capability, exc)
            self._remember_failure(failure)
            raise self._execution_error(failure, exc) from exc
        self._remember_success(account_id, capability)
        return group_ids

    async def list_groups(self, account_or_id: Account | str | int) -> tuple[str, ...]:
        """``get_group_list`` 的业务友好别名。"""

        return await self.get_group_list(account_or_id)

    discover_groups = list_groups

    @staticmethod
    def _duration(value: object) -> int:
        if type(value) is not int:
            raise ValueError("禁言时长必须是整数秒")
        if not 0 <= value <= _MAX_BAN_SECONDS:
            raise ValueError("禁言时长范围必须是 0 到 2592000 秒")
        return value

    async def mute_member(
        self,
        account_or_id: Account | str | int,
        group_id: str | int,
        user_id: str | int,
        duration: int,
        *,
        context: MessageContext | None,
        permission_checker: PermissionChecker | None = None,
    ) -> ActionReceipt:
        """按 OneBot 标准时长（秒）禁言群成员。"""

        group, _ = _numeric_id(group_id, "群 ID")
        user, _ = _numeric_id(user_id, "用户 ID")
        seconds = self._duration(duration)
        return await self._invoke(
            account_or_id,
            ActionCapability.MEMBER_MUTE,
            lambda protocol: protocol.guild_member_mute(group, user, float(seconds)),
            context=context,
            required=Permission.GroupAdmin,
            permission_checker=permission_checker,
            management_group_id=group,
        )

    async def unmute_member(
        self,
        account_or_id: Account | str | int,
        group_id: str | int,
        user_id: str | int,
        *,
        context: MessageContext | None,
        permission_checker: PermissionChecker | None = None,
    ) -> ActionReceipt:
        """使用标准 duration=0 解除群成员禁言。"""

        receipt = await self.mute_member(
            account_or_id,
            group_id,
            user_id,
            0,
            context=context,
            permission_checker=permission_checker,
        )
        if self.registry.get(user_id) is not None:
            self.registry.set_muted(user_id, group_id, False)
        return receipt

    async def mute_group(
        self,
        account_or_id: Account | str | int,
        group_id: str | int,
        enabled: bool,
        *,
        context: MessageContext | None,
        permission_checker: PermissionChecker | None = None,
    ) -> ActionReceipt:
        """启用或关闭全体禁言，复用 Satori ``channel_mute``。"""

        if type(enabled) is not bool:
            raise TypeError("enabled 必须是布尔值")
        group, _ = _numeric_id(group_id, "群 ID")
        return await self._invoke(
            account_or_id,
            ActionCapability.GROUP_MUTE,
            lambda protocol: protocol.channel_mute(group, 60.0 if enabled else 0.0),
            context=context,
            required=Permission.GroupAdmin,
            permission_checker=permission_checker,
            management_group_id=group,
        )

    async def unmute_group(
        self,
        account_or_id: Account | str | int,
        group_id: str | int,
        *,
        context: MessageContext | None,
        permission_checker: PermissionChecker | None = None,
    ) -> ActionReceipt:
        """关闭全体禁言；底层仍使用标准的全体禁言动作并传入关闭状态。"""

        return await self.mute_group(
            account_or_id,
            group_id,
            False,
            context=context,
            permission_checker=permission_checker,
        )

    async def delete_message(
        self,
        account_or_id: Account | str | int,
        message_id: str | int,
        *,
        channel_id: str | int | None = None,
        context: MessageContext | None,
        permission_checker: PermissionChecker | None = None,
    ) -> ActionReceipt:
        """撤回消息；OneBot adapter 会把 Satori channel/message ID 转为标准参数。"""

        message, _ = _numeric_id(message_id, "消息 ID")
        target_channel = channel_id
        if target_channel is None and context is not None:
            target_channel = context.channel_id
        channel, _ = _numeric_id(target_channel, "频道 ID")
        return await self._invoke(
            account_or_id,
            ActionCapability.MESSAGE_DELETE,
            lambda protocol: protocol.message_delete(channel, message),
            context=context,
            required=Permission.GroupAdmin,
            permission_checker=permission_checker,
            management_group_id=channel,
        )

    async def kick_member(
        self,
        account_or_id: Account | str | int,
        group_id: str | int,
        user_id: str | int,
        *,
        context: MessageContext | None,
        permission_checker: PermissionChecker | None = None,
        reject_add_request: bool = False,
    ) -> ActionReceipt:
        """踢出群成员；``reject_add_request`` 对应 OneBot 标准可选字段。"""

        if type(reject_add_request) is not bool:
            raise TypeError("reject_add_request 必须是布尔值")
        group, _ = _numeric_id(group_id, "群 ID")
        user, _ = _numeric_id(user_id, "用户 ID")
        return await self._invoke(
            account_or_id,
            ActionCapability.MEMBER_KICK,
            lambda protocol: protocol.guild_member_kick(
                group, user, permanent=reject_add_request
            ),
            context=context,
            required=Permission.GroupAdmin,
            permission_checker=permission_checker,
            management_group_id=group,
        )

    async def set_essence(
        self,
        account_or_id: Account | str | int,
        message_id: str | int,
        *,
        context: MessageContext | None,
        permission_checker: PermissionChecker | None = None,
    ) -> ActionReceipt:
        """调用 NapCat 群精华扩展；扩展回执仍待第⑧步实测确认。"""

        message, message_number = _numeric_id(message_id, "消息 ID")
        del message  # 保留字符串校验结果，扩展参数按 OneBot 标准使用整数。
        return await self._invoke(
            account_or_id,
            ActionCapability.GROUP_ESSENCE,
            lambda protocol: protocol.internal(
                _ONEBOT_ACTIONS[ActionCapability.GROUP_ESSENCE],
                message_id=message_number,
            ),
            context=context,
            required=Permission.GroupAdmin,
            permission_checker=permission_checker,
            management_group_id=(context.channel_id if context is not None else None),
        )

    async def leave_group(
        self,
        account_or_id: Account | str | int,
        group_id: str | int,
        *,
        context: MessageContext | None,
        permission_checker: PermissionChecker | None = None,
        dismiss: bool = False,
    ) -> ActionReceipt:
        """调用 OneBot 退群扩展；``dismiss`` 保留标准字段语义。"""

        if type(dismiss) is not bool:
            raise TypeError("dismiss 必须是布尔值")
        group, group_number = _numeric_id(group_id, "群 ID")
        del group
        return await self._invoke(
            account_or_id,
            ActionCapability.GROUP_LEAVE,
            lambda protocol: protocol.internal(
                _ONEBOT_ACTIONS[ActionCapability.GROUP_LEAVE],
                group_id=group_number,
                is_dismiss=dismiss,
            ),
            context=context,
            required=Permission.BotAdmin,
            permission_checker=permission_checker,
        )

    async def send_group_message(
        self,
        account_or_id: Account | str | int,
        group_id: str | int,
        content: str,
        *,
        context: MessageContext | None,
        permission_checker: PermissionChecker | None = None,
    ) -> ActionReceipt:
        """通过 Satori ``send_message`` 向群发送文本，并观察发送失败回执。"""

        if not isinstance(content, str) or not content:
            raise ValueError("公告内容不能为空")
        group, _ = _numeric_id(group_id, "群 ID")
        return await self._invoke(
            account_or_id,
            ActionCapability.SEND_GROUP_MESSAGE,
            lambda protocol: protocol.send_message(group, content),
            context=context,
            required=Permission.BotAdmin,
            permission_checker=permission_checker,
            send_group_id=group,
        )


CapabilityAwareActionService = ActionService
action_service = ActionService()


__all__ = [
    "ActionCapability",
    "ActionCapabilityUnavailable",
    "ActionAccountUnavailable",
    "ActionExecutionError",
    "ActionFailure",
    "ActionPermissionDenied",
    "ActionReceipt",
    "ActionService",
    "ActionServiceError",
    "ActionTargetUnavailable",
    "AccountUnavailableError",
    "Capability",
    "CapabilityAwareActionService",
    "CapabilityUnavailableError",
    "action_service",
]
