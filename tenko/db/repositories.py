"""Tenko 数据库 repository。

repository 只持有官方 database service 提供的异步 session 工厂，不把
SQLAlchemy 查询对象暴露给宿主或插件调用方。
"""

from __future__ import annotations

import sqlite3
from collections.abc import AsyncIterator, Callable, Iterable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.exc import (
    DBAPIError,
    DisconnectionError,
    InterfaceError,
    NoSuchModuleError,
    OperationalError,
)

from .errors import (
    DatabaseUnavailableError,
    InvalidGroupPermissionError,
    InvalidGroupSettingError,
    InvalidPermissionError,
)
from .ids import to_database_id
from .models import (
    AccountResponseState,
    AccountRoute,
    FeatureState,
    GroupPerm,
    GroupSetting,
    MemberPerm,
    RateLimitEvent,
    RateLimitSubjectState,
    StartupTime,
)

_SessionFactory = Callable[[], Any]
_session_factory: _SessionFactory | None = None
_MEMBER_PERMISSIONS = frozenset({-1, 0, 16, 32, 64, 128, 256})
_GROUP_PERMISSIONS = frozenset({0, 1, 2, 3})
_RESPONSE_TYPES = frozenset({"random", "deterministic"})
_PERMISSION_TYPES = frozenset({"default", "admin"})
_UNAVAILABLE_SQLALCHEMY_ERRORS = (
    DisconnectionError,
    InterfaceError,
    NoSuchModuleError,
    OperationalError,
)


def configure_session_factory(factory: _SessionFactory | None) -> None:
    """配置全局 repository 使用的异步 session 工厂。"""

    global _session_factory
    if factory is not None and not callable(factory):
        raise TypeError("数据库 session 工厂必须是可调用对象或 None")
    _session_factory = factory


def configure_database_service(service: Any | None) -> None:
    """将官方 ``SqlalchemyService`` 接入全局 repository。"""

    if service is None:
        configure_session_factory(None)
        return
    factory = getattr(service, "get_session", None)
    if not callable(factory):
        raise DatabaseUnavailableError(
            "官方 database service 尚未提供 get_session 工厂"
        )
    configure_session_factory(factory)


def _is_database_unavailable(error: BaseException) -> bool:
    if isinstance(error, DatabaseUnavailableError):
        return True
    if isinstance(
        error, ConnectionError | TimeoutError | OSError | sqlite3.OperationalError
    ):
        return True
    if isinstance(error, _UNAVAILABLE_SQLALCHEMY_ERRORS):
        return True
    if isinstance(error, DBAPIError):
        return bool(error.connection_invalidated)
    if isinstance(error, ImportError):
        module_name = getattr(error, "name", None)
        return bool(
            module_name
            and module_name in {"sqlalchemy", "aiosqlite"}
            or "No module named 'sqlalchemy'" in str(error)
        )
    return False


def _permission(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise InvalidPermissionError(f"成员权限必须是整数，收到 {value!r}")
    normalized = int(value)
    if normalized not in _MEMBER_PERMISSIONS:
        raise InvalidPermissionError(
            f"成员权限必须是 -1、0、16、32、64、128 或 256，收到 {value!r}"
        )
    return normalized


def _group_permission(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise InvalidGroupPermissionError(f"群等级必须是整数，收到 {value!r}")
    normalized = int(value)
    if normalized not in _GROUP_PERMISSIONS:
        raise InvalidGroupPermissionError(f"群等级必须是 0、1、2 或 3，收到 {value!r}")
    return normalized


class _Repository:
    def __init__(self, session_factory: _SessionFactory | None = None) -> None:
        if session_factory is not None and not callable(session_factory):
            raise TypeError("数据库 session 工厂必须是可调用对象或 None")
        self.session_factory = session_factory

    def _factory(self) -> _SessionFactory:
        factory = self.session_factory or _session_factory
        if factory is None:
            raise DatabaseUnavailableError("Tenko 数据库 session 工厂未配置")
        return factory

    @asynccontextmanager
    async def _session(self) -> AsyncIterator[Any]:
        try:
            factory = self._factory()
            async with factory() as session:
                try:
                    yield session
                except Exception:
                    await session.rollback()
                    raise
        except DatabaseUnavailableError:
            raise
        except Exception as error:
            if not _is_database_unavailable(error):
                raise
            raise DatabaseUnavailableError(
                f"Tenko 数据库不可用: {type(error).__name__}: {error}"
            ) from error


class MemberPermRepository(_Repository):
    """MemberPerm 的读写 repository。"""

    async def get_permission(
        self, group_id: str | int, user_id: str | int
    ) -> int | None:
        group = to_database_id(group_id, "群 ID")
        user = to_database_id(user_id, "用户 ID")
        async with self._session() as session:
            return await session.scalar(
                select(MemberPerm.perm).where(
                    MemberPerm.group_id == group,
                    MemberPerm.qq == user,
                )
            )

    async def set_permission(
        self, group_id: str | int, user_id: str | int, permission: int
    ) -> None:
        group = to_database_id(group_id, "群 ID")
        user = to_database_id(user_id, "用户 ID")
        normalized_permission = _permission(permission)
        async with self._session() as session:
            row = await session.get(MemberPerm, (group, user))
            if row is None:
                session.add(
                    MemberPerm(
                        group_id=group,
                        qq=user,
                        perm=normalized_permission,
                    )
                )
            else:
                row.perm = normalized_permission
            await session.commit()

    async def delete_permission(self, group_id: str | int, user_id: str | int) -> bool:
        group = to_database_id(group_id, "群 ID")
        user = to_database_id(user_id, "用户 ID")
        async with self._session() as session:
            result = await session.execute(
                delete(MemberPerm).where(
                    MemberPerm.group_id == group,
                    MemberPerm.qq == user,
                )
            )
            await session.commit()
            return bool(result.rowcount)

    async def list_group_permissions(
        self, group_id: str | int
    ) -> tuple[MemberPerm, ...]:
        group = to_database_id(group_id, "群 ID")
        async with self._session() as session:
            result = await session.scalars(
                select(MemberPerm)
                .where(MemberPerm.group_id == group)
                .order_by(MemberPerm.perm.desc(), MemberPerm.qq)
            )
            return tuple(result.all())

    async def list_bot_admins(self) -> tuple[int, ...]:
        async with self._session() as session:
            result = await session.scalars(
                select(MemberPerm.qq)
                .where(MemberPerm.perm == 128)
                .order_by(MemberPerm.qq)
            )
            return tuple(result.all())

    async def list_global_blacklist(self) -> tuple[int, ...]:
        async with self._session() as session:
            result = await session.scalars(
                select(MemberPerm.qq)
                .where(
                    MemberPerm.group_id == 0,
                    MemberPerm.perm == -1,
                )
                .order_by(MemberPerm.qq)
            )
            return tuple(result.all())

    async def list_group_blacklist(self, group_id: str | int) -> tuple[int, ...]:
        group = to_database_id(group_id, "群 ID")
        async with self._session() as session:
            result = await session.scalars(
                select(MemberPerm.qq)
                .where(
                    MemberPerm.group_id == group,
                    MemberPerm.perm == 0,
                )
                .order_by(MemberPerm.qq)
            )
            return tuple(result.all())

    # 常用的短别名保持调用方语义清晰，同时不复制实现。
    get = get_permission
    set = set_permission
    delete = delete_permission
    list_by_group = list_group_permissions
    bot_admin_ids = list_bot_admins
    global_blacklist = list_global_blacklist


class GroupPermRepository(_Repository):
    """GroupPerm 的群等级、名称和 active 状态 repository。"""

    async def get(self, group_id: str | int) -> GroupPerm | None:
        group = to_database_id(group_id, "群 ID")
        async with self._session() as session:
            return await session.get(GroupPerm, group)

    async def get_permission(self, group_id: str | int) -> int | None:
        row = await self.get(group_id)
        return None if row is None else row.perm

    async def set(
        self,
        group_id: str | int,
        permission: int,
        *,
        group_name: str | None = None,
        active: bool | None = None,
    ) -> None:
        group = to_database_id(group_id, "群 ID")
        normalized_permission = _group_permission(permission)
        if group_name is not None and not isinstance(group_name, str):
            raise TypeError("群名称必须是字符串或 None")
        if active is not None and type(active) is not bool:
            raise TypeError("active 必须是布尔值或 None")
        async with self._session() as session:
            row = await session.get(GroupPerm, group)
            if row is None:
                row = GroupPerm(
                    group_id=group,
                    group_name=group_name or str(group),
                    perm=normalized_permission,
                    active=True if active is None else active,
                )
                session.add(row)
            else:
                row.perm = normalized_permission
                if group_name is not None:
                    row.group_name = group_name
                if active is not None:
                    row.active = active
            await session.commit()

    async def set_active(self, group_id: str | int, active: bool) -> None:
        if type(active) is not bool:
            raise TypeError("active 必须是布尔值")
        row = await self.get(group_id)
        if row is None:
            await self.set(group_id, 1, active=active)
            return
        await self.set(
            group_id,
            row.perm,
            group_name=row.group_name,
            active=active,
        )

    async def set_group_name(self, group_id: str | int, group_name: str) -> None:
        if not isinstance(group_name, str) or not group_name:
            raise ValueError("群名称必须是非空字符串")
        row = await self.get(group_id)
        if row is None:
            await self.set(group_id, 1, group_name=group_name)
            return
        await self.set(
            group_id,
            row.perm,
            group_name=group_name,
            active=row.active,
        )

    async def list_vip(self) -> tuple[GroupPerm, ...]:
        async with self._session() as session:
            result = await session.scalars(
                select(GroupPerm)
                .where(GroupPerm.perm == 2)
                .order_by(GroupPerm.group_id)
            )
            return tuple(result.all())


class GroupSettingRepository(_Repository):
    """GroupSetting 的频控、响应策略和权限类型 repository。"""

    async def get(self, group_id: str | int) -> GroupSetting | None:
        group = to_database_id(group_id, "群 ID")
        async with self._session() as session:
            return await session.get(GroupSetting, group)

    async def set(
        self,
        group_id: str | int,
        *,
        frequency_limitation: bool | None = None,
        response_type: str | None = None,
        permission_type: str | None = None,
    ) -> None:
        group = to_database_id(group_id, "群 ID")
        if frequency_limitation is not None and type(frequency_limitation) is not bool:
            raise TypeError("frequency_limitation 必须是布尔值或 None")
        if response_type is not None and response_type not in _RESPONSE_TYPES:
            raise InvalidGroupSettingError(
                "response_type 必须是 random 或 deterministic"
            )
        if permission_type is not None and permission_type not in _PERMISSION_TYPES:
            raise InvalidGroupSettingError("permission_type 必须是 default 或 admin")
        async with self._session() as session:
            row = await session.get(GroupSetting, group)
            if row is None:
                row = GroupSetting(
                    group_id=group,
                    frequency_limitation=(
                        True if frequency_limitation is None else frequency_limitation
                    ),
                    response_type=response_type or "random",
                    permission_type=permission_type or "default",
                )
                session.add(row)
            else:
                if frequency_limitation is not None:
                    row.frequency_limitation = frequency_limitation
                if response_type is not None:
                    row.response_type = response_type
                if permission_type is not None:
                    row.permission_type = permission_type
            await session.commit()

    async def set_frequency_limitation(
        self, group_id: str | int, enabled: bool
    ) -> None:
        await self.set(group_id, frequency_limitation=enabled)

    async def set_response_type(self, group_id: str | int, response_type: str) -> None:
        await self.set(group_id, response_type=response_type)

    async def set_permission_type(
        self, group_id: str | int, permission_type: str
    ) -> None:
        await self.set(group_id, permission_type=permission_type)


@dataclass(frozen=True, slots=True)
class FeatureStateRecord:
    """repository 返回的功能开关状态记录。"""

    plugin_name: str
    group_id: str | None
    enabled: bool | None
    maintenance: bool


class FeatureStateRepository(_Repository):
    """Tenko 功能开关状态 repository。"""

    async def list_states(self) -> tuple[FeatureStateRecord, ...]:
        async with self._session() as session:
            result = await session.scalars(
                select(FeatureState).order_by(
                    FeatureState.plugin_name, FeatureState.group_id
                )
            )
            return tuple(
                FeatureStateRecord(
                    plugin_name=row.plugin_name,
                    group_id=row.group_id or None,
                    enabled=row.enabled,
                    maintenance=bool(row.maintenance),
                )
                for row in result.all()
            )

    async def replace_states(self, states: Iterable[FeatureStateRecord]) -> None:
        rows = tuple(states)
        async with self._session() as session:
            await session.execute(delete(FeatureState))
            session.add_all(
                FeatureState(
                    plugin_name=row.plugin_name,
                    group_id=row.group_id or "",
                    enabled=row.enabled,
                    maintenance=row.maintenance,
                )
                for row in rows
            )
            await session.commit()

    list = list_states
    replace = replace_states


@dataclass(frozen=True, slots=True)
class AccountRouteRecord:
    """repository 返回的有序账号路由记录。"""

    group_id: str
    account_id: str
    position: int


@dataclass(frozen=True, slots=True)
class AccountResponseRecord:
    """repository 返回的群响应策略记录。"""

    group_id: str
    response_type: str
    deterministic_account: str | None


@dataclass(frozen=True, slots=True)
class AccountStateSnapshot:
    """账号路由和响应策略的一致性快照。"""

    routes: tuple[AccountRouteRecord, ...]
    responses: tuple[AccountResponseRecord, ...]


class AccountStateRepository(_Repository):
    """Tenko 账号群路由及响应策略 repository。"""

    async def load_state(self) -> AccountStateSnapshot:
        async with self._session() as session:
            route_result = await session.scalars(
                select(AccountRoute).order_by(
                    AccountRoute.group_id, AccountRoute.position
                )
            )
            response_result = await session.scalars(
                select(AccountResponseState).order_by(AccountResponseState.group_id)
            )
            return AccountStateSnapshot(
                routes=tuple(
                    AccountRouteRecord(
                        group_id=row.group_id,
                        account_id=row.account_id,
                        position=row.position,
                    )
                    for row in route_result.all()
                ),
                responses=tuple(
                    AccountResponseRecord(
                        group_id=row.group_id,
                        response_type=row.response_type,
                        deterministic_account=row.deterministic_account,
                    )
                    for row in response_result.all()
                ),
            )

    async def replace_state(
        self,
        routes: Iterable[AccountRouteRecord],
        responses: Iterable[AccountResponseRecord],
    ) -> None:
        route_rows = tuple(routes)
        response_rows = tuple(responses)
        async with self._session() as session:
            await session.execute(delete(AccountRoute))
            await session.execute(delete(AccountResponseState))
            session.add_all(
                AccountRoute(
                    group_id=row.group_id,
                    account_id=row.account_id,
                    position=row.position,
                )
                for row in route_rows
            )
            session.add_all(
                AccountResponseState(
                    group_id=row.group_id,
                    response_type=row.response_type,
                    deterministic_account=row.deterministic_account,
                )
                for row in response_rows
            )
            await session.commit()

    load = load_state
    replace = replace_state


@dataclass(frozen=True, slots=True)
class RateLimitEventRecord:
    """repository 返回的限流窗口事件记录。"""

    group_id: str
    user_id: str
    occurred_at: float
    weight: int


@dataclass(frozen=True, slots=True)
class RateLimitSubjectRecord:
    """repository 返回的限流用户状态记录。"""

    group_id: str
    user_id: str
    cooldown_until: float | None
    blacklist_until: float | None


@dataclass(frozen=True, slots=True)
class RateLimitStateSnapshot:
    """限流窗口和到期状态的一致性快照。"""

    events: tuple[RateLimitEventRecord, ...]
    subjects: tuple[RateLimitSubjectRecord, ...]


class RateLimitRepository(_Repository):
    """Tenko 命令限流状态 repository。"""

    async def load_state(self) -> RateLimitStateSnapshot:
        async with self._session() as session:
            event_result = await session.scalars(
                select(RateLimitEvent).order_by(RateLimitEvent.id)
            )
            subject_result = await session.scalars(
                select(RateLimitSubjectState).order_by(
                    RateLimitSubjectState.group_id,
                    RateLimitSubjectState.user_id,
                )
            )
            return RateLimitStateSnapshot(
                events=tuple(
                    RateLimitEventRecord(
                        group_id=row.group_id,
                        user_id=row.user_id,
                        occurred_at=float(row.occurred_at),
                        weight=int(row.weight),
                    )
                    for row in event_result.all()
                ),
                subjects=tuple(
                    RateLimitSubjectRecord(
                        group_id=row.group_id,
                        user_id=row.user_id,
                        cooldown_until=(
                            None
                            if row.cooldown_until is None
                            else float(row.cooldown_until)
                        ),
                        blacklist_until=(
                            None
                            if row.blacklist_until is None
                            else float(row.blacklist_until)
                        ),
                    )
                    for row in subject_result.all()
                ),
            )

    async def replace_state(
        self,
        events: Iterable[RateLimitEventRecord],
        subjects: Iterable[RateLimitSubjectRecord],
    ) -> None:
        event_rows = tuple(events)
        subject_rows = tuple(subjects)
        async with self._session() as session:
            await session.execute(delete(RateLimitEvent))
            await session.execute(delete(RateLimitSubjectState))
            session.add_all(
                RateLimitEvent(
                    group_id=row.group_id,
                    user_id=row.user_id,
                    occurred_at=row.occurred_at,
                    weight=row.weight,
                )
                for row in event_rows
            )
            session.add_all(
                RateLimitSubjectState(
                    group_id=row.group_id,
                    user_id=row.user_id,
                    cooldown_until=row.cooldown_until,
                    blacklist_until=row.blacklist_until,
                )
                for row in subject_rows
            )
            await session.commit()

    load = load_state
    replace = replace_state


class StartupTimeRepository(_Repository):
    """启动耗时样本 repository。"""

    async def list_durations(self) -> tuple[float, ...]:
        async with self._session() as session:
            result = await session.scalars(
                select(StartupTime.duration).order_by(StartupTime.id)
            )
            return tuple(float(value) for value in result.all())

    async def record(self, duration: float) -> None:
        async with self._session() as session:
            session.add(StartupTime(duration=duration))
            await session.commit()

    list = list_durations


member_perm_repository = MemberPermRepository()
group_perm_repository = GroupPermRepository()
group_setting_repository = GroupSettingRepository()
feature_state_repository = FeatureStateRepository()
account_state_repository = AccountStateRepository()
rate_limit_repository = RateLimitRepository()
startup_time_repository = StartupTimeRepository()


async def get_member_permission(group_id: str | int, user_id: str | int) -> int | None:
    return await member_perm_repository.get_permission(group_id, user_id)


async def get_group_permission(group_id: str | int) -> int | None:
    return await group_perm_repository.get_permission(group_id)


async def get_bot_admin_ids() -> tuple[int, ...]:
    return await member_perm_repository.list_bot_admins()


__all__ = [
    "GroupPermRepository",
    "GroupSettingRepository",
    "MemberPermRepository",
    "AccountResponseRecord",
    "AccountRouteRecord",
    "AccountStateRepository",
    "AccountStateSnapshot",
    "FeatureStateRecord",
    "FeatureStateRepository",
    "RateLimitEventRecord",
    "RateLimitRepository",
    "RateLimitStateSnapshot",
    "RateLimitSubjectRecord",
    "StartupTimeRepository",
    "account_state_repository",
    "configure_database_service",
    "configure_session_factory",
    "feature_state_repository",
    "get_bot_admin_ids",
    "get_group_permission",
    "get_member_permission",
    "group_perm_repository",
    "group_setting_repository",
    "member_perm_repository",
    "rate_limit_repository",
    "startup_time_repository",
]
