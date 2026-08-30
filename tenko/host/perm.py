from __future__ import annotations

import inspect
import sqlite3
from collections.abc import Iterable
from enum import IntEnum
from typing import Any

from arclet.entari.config import EntariConfig

from ..context import MessageContext
from loguru import logger

# Deliberately left unset at import time. Tests and a host bootstrapper may inject
# a reader here; the normal path imports core.orm only when a database lookup is
# actually needed.
orm: Any | None = None

_DATABASE_IMPORT_ROOTS = (
    "sqlalchemy",
    "core.orm",
    "aiosqlite",
    "asyncpg",
    "aiomysql",
    "psycopg2",
)
_SQLALCHEMY_CONNECTION_ERRORS = {
    "DisconnectionError",
    "InterfaceError",
    "NoSuchModuleError",
    "OperationalError",
    "TimeoutError",
}


def _is_database_unavailable(error: BaseException) -> bool:
    """判断异常是否属于数据库依赖/连接不可用，而不是业务逻辑错误。"""

    if isinstance(error, ImportError):
        module_name = getattr(error, "name", None)
        if module_name and any(
            module_name == root or module_name.startswith(f"{root}.")
            for root in _DATABASE_IMPORT_ROOTS
        ):
            return True
        message = str(error)
        return "No module named 'sqlalchemy'" in message or (
            "sqlalchemy" in message and "cannot import" in message
        )

    if isinstance(
        error, ConnectionError | TimeoutError | OSError | sqlite3.OperationalError
    ):
        return True

    for error_type in type(error).__mro__:
        if error_type.__module__ != "sqlalchemy.exc":
            continue
        if error_type.__name__ in _SQLALCHEMY_CONNECTION_ERRORS:
            return True
        if error_type.__name__ == "DBAPIError":
            return bool(getattr(error, "connection_invalidated", False))
    return False


class Permission(IntEnum):
    """Tenko 侧的成员权限数值，保持旧 `core.control.Permission` 的协议。"""

    GlobalBlack = -1
    GroupBlack = 0
    User = 16
    Member = 16
    GroupAdmin = 32
    Administrator = 32
    GroupOwner = 64
    Owner = 64
    BotAdmin = 128
    Master = 256
    InactiveGroup = 0
    ActiveGroup = 1
    VipGroup = 2
    TestGroup = 3


PermissionLevel = Permission


class GroupPermission(IntEnum):
    """Tenko 侧的群等级数值，保持旧 `core.control.Permission` 的协议。"""

    InactiveGroup = 0
    ActiveGroup = 1
    VipGroup = 2
    TestGroup = 3


GroupLevel = GroupPermission

_ROLE_LEVELS = {
    "member": Permission.User,
    "admin": Permission.GroupAdmin,
    "administrator": Permission.GroupAdmin,
    "owner": Permission.GroupOwner,
}


def _key(value: object) -> str:
    if value is None:
        raise ValueError("权限主体 ID 不能为空")
    return str(value)


def _database_key(value: object) -> int | str:
    normalized = _key(value)
    try:
        return int(normalized)
    except ValueError:
        return normalized


def _scalar(result: object) -> object | None:
    if result is None:
        return None
    if isinstance(result, dict):
        if "perm" in result:
            return result["perm"]
        if len(result) == 1:
            return next(iter(result.values()))
    if isinstance(result, tuple | list):
        return result[0] if result else None
    mapping = getattr(result, "_mapping", None)
    if mapping is not None:
        if "perm" in mapping:
            return mapping["perm"]
        if len(mapping) == 1:
            return next(iter(mapping.values()))
    try:
        return result[0]  # SQLAlchemy Row and similar row objects.
    except (IndexError, KeyError, TypeError):
        return result


def _level(result: object) -> int | None:
    value = _scalar(result)
    if value is None:
        return None
    return int(value)


class PermissionRegistry:
    """保存宿主侧身份配置和无需数据库的权限覆盖。

    该注册表隔离 Satori `MessageContext` 与旧数据库/配置来源：它只维护
    Tenko 运行时明确提供的 master、BotAdmin、成员和群等级，不复制
    `core.control` 的 Graia 事件注入协议。`PermissionChecker` 会优先读取
    只读数据库记录，再使用这里的值作为没有数据库记录时的运行时来源。
    """

    def __init__(
        self,
        *,
        master_id: str | int | None = None,
        bot_admin_ids: Iterable[str | int] = (),
    ) -> None:
        self.master_id = None if master_id is None else _key(master_id)
        self.bot_admin_ids = {_key(user_id) for user_id in bot_admin_ids}
        self._user_levels: dict[tuple[str, str], int] = {}
        self._group_levels: dict[str, int] = {}

    def set_user_level(
        self, group_id: str | int | None, user_id: str | int, level: int
    ) -> None:
        """设置群内或全局（`group_id=0`）的运行时成员权限。"""

        normalized_group = "0" if group_id is None else _key(group_id)
        self._user_levels[(normalized_group, _key(user_id))] = int(level)

    def set_group_level(self, group_id: str | int, level: int) -> None:
        """设置群的运行时等级覆盖。"""

        self._group_levels[_key(group_id)] = int(level)

    def user_level(self, group_id: str | int | None, user_id: str | int) -> int | None:
        normalized_group = "0" if group_id is None else _key(group_id)
        return self._user_levels.get((normalized_group, _key(user_id)))

    def group_level(self, group_id: str | int) -> int | None:
        return self._group_levels.get(_key(group_id))


class PermissionChecker:
    """基于消息上下文执行成员和群权限判断。

    `database` 需要提供旧 `core.orm.orm` 使用的异步 `fetch_one`，可选提供
    `fetch_all`；显式注入时会收到轻量 tuple 查询描述，便于测试而不把
    SQLAlchemy 引入 Tenko。未显式注入数据库且未提供注册表时，实际检查才
    延迟导入 `core.orm.orm`，并且本类只调用读取方法，不执行任何写入。
    """

    def __init__(
        self,
        registry: PermissionRegistry | None = None,
        database: Any | None = None,
    ) -> None:
        self.registry = registry or PermissionRegistry()
        self._legacy_database = database is None and registry is None and orm is None
        self._database = database if database is not None else orm
        self._bot_admins_from_database: set[str] | None = None
        self._database_unavailable = False
        self._database_failure_reason: str | None = None
        self._database_warning_groups: set[str] = set()

    def _get_database(self) -> Any:
        if self._database is None and self._legacy_database:
            from core.orm import orm as legacy_orm

            self._database = legacy_orm
        if self._database is None:
            raise RuntimeError("权限检查未配置数据库或运行时权限来源")
        return self._database

    def _statement(self, kind: str, *values: object) -> object:
        if self._legacy_database:
            from sqlalchemy import select

            if kind == "member_perm":
                from core.orm.tables import MemberPerm

                return select(MemberPerm.perm).where(
                    MemberPerm.group_id == values[0], MemberPerm.qq == values[1]
                )
            if kind == "group_perm":
                from core.orm.tables import GroupPerm

                return select(GroupPerm.perm).where(GroupPerm.group_id == values[0])
            if kind == "bot_admins":
                from core.orm.tables import MemberPerm

                return select(MemberPerm.qq).where(
                    MemberPerm.perm == Permission.BotAdmin
                )
        return (kind, *values)

    def _warn_database_fallback(self, group_id: str | int) -> None:
        normalized_group_id = _key(group_id)
        if normalized_group_id in self._database_warning_groups:
            return
        self._database_warning_groups.add(normalized_group_id)
        reason = self._database_failure_reason or "数据库读取失败"
        logger.warning(
            f"权限数据库不可用，群 {normalized_group_id} 回退到默认权限等级 "
            f"{int(GroupPermission.ActiveGroup)}；原因：{reason}"
        )

    def _record_database_failure(
        self, group_id: str | int, error: BaseException
    ) -> None:
        self._database_unavailable = True
        if self._database_failure_reason is None:
            self._database_failure_reason = f"{type(error).__name__}: {error}"
        self._warn_database_fallback(group_id)

    async def _fetch_one(self, statement: object) -> object | None:
        fetch_one = getattr(self._get_database(), "fetch_one")
        result = fetch_one(statement)
        if inspect.isawaitable(result):
            result = await result
        return result

    async def _fetch_all(self, statement: object) -> object:
        database = self._get_database()
        fetch_all = getattr(database, "fetch_all", None)
        if fetch_all is None:
            return ()
        result = fetch_all(statement)
        if inspect.isawaitable(result):
            result = await result
        return result

    async def _database_member_level(
        self, group_id: str | int, user_id: str | int
    ) -> int | None:
        if self._database_unavailable:
            self._warn_database_fallback(group_id)
            return None
        try:
            result = await self._fetch_one(
                self._statement(
                    "member_perm", _database_key(group_id), _database_key(user_id)
                )
            )
        except Exception as error:
            if not _is_database_unavailable(error):
                raise
            self._record_database_failure(group_id, error)
            return None
        return _level(result)

    async def _database_group_level(self, group_id: str | int) -> int | None:
        if self._database_unavailable:
            self._warn_database_fallback(group_id)
            return GroupPermission.ActiveGroup
        try:
            result = await self._fetch_one(
                self._statement("group_perm", _database_key(group_id))
            )
        except Exception as error:
            if not _is_database_unavailable(error):
                raise
            self._record_database_failure(group_id, error)
            # This is the old core/control.py behavior for a group without a
            # GroupPerm row: an unavailable database has the same permission
            # semantics as that missing row, so commands remain usable.
            return GroupPermission.ActiveGroup
        return _level(result)

    async def _database_bot_admin_ids(self) -> set[str]:
        if self._database_unavailable:
            self._warn_database_fallback(0)
            return self._bot_admins_from_database or set()
        if self._bot_admins_from_database is None:
            try:
                rows = await self._fetch_all(self._statement("bot_admins"))
            except Exception as error:
                if not _is_database_unavailable(error):
                    raise
                self._bot_admins_from_database = set()
                self._record_database_failure(0, error)
                return self._bot_admins_from_database
            self._bot_admins_from_database = {
                _key(value) for row in rows if (value := _scalar(row)) is not None
            }
        return self._bot_admins_from_database

    @staticmethod
    def _is_native_superuser(context: MessageContext, user_id: str) -> bool:
        """复用 Entari filter.superusers 使用的 basic.superusers 配置。"""

        if not getattr(EntariConfig, "_inited", False):
            return False
        basic = getattr(EntariConfig.instance, "basic", None)
        configured = getattr(basic, "superusers", {})
        if not isinstance(configured, dict):
            return False
        return user_id in {str(value) for value in configured.get(context.platform, ())}

    async def get_user_perm(self, context: MessageContext) -> int:
        """获取上下文发送者的有效成员权限数值。"""

        user_id = _key(context.user_id)
        if self._is_native_superuser(context, user_id):
            return Permission.Master
        global_level: int | None = None
        if self._database is not None or self._legacy_database:
            global_level = await self._database_member_level(0, user_id)
        if global_level is not None:
            return global_level

        group_id = context.channel_id if context.chat_type == "group" else None
        global_registry_level = self.registry.user_level(None, user_id)
        if global_registry_level is not None:
            return global_registry_level
        explicit_level = self.registry.user_level(group_id, user_id)
        if context.chat_type == "group" and self._database is not None:
            explicit_level = await self._database_member_level(group_id, user_id)
        elif context.chat_type == "group" and self._legacy_database:
            explicit_level = await self._database_member_level(group_id, user_id)
        if explicit_level is not None:
            return explicit_level

        if self.registry.master_id == user_id:
            return Permission.Master
        if user_id in self.registry.bot_admin_ids:
            return Permission.BotAdmin
        if self._database is not None or self._legacy_database:
            if user_id in await self._database_bot_admin_ids():
                return Permission.BotAdmin

        if context.chat_type == "group":
            role = (context.member_role or "member").lower()
            return _ROLE_LEVELS.get(role, Permission.User)
        return Permission.User

    async def get_group_perm(self, context: MessageContext) -> int:
        """获取上下文所属群等级；私聊没有群约束，返回正常群默认值。"""

        if context.chat_type != "group":
            return GroupPermission.ActiveGroup
        group_id = context.channel_id
        if self._database is not None or self._legacy_database:
            # 数据库可用时保持记录优先的原有行为；数据库不可用时，读取路径
            # 返回旧实现“无群记录”的 ActiveGroup 默认值，命令继续正常执行。
            database_level = await self._database_group_level(group_id)
            if database_level is not None:
                return database_level
        registry_level = self.registry.group_level(group_id)
        return GroupPermission.ActiveGroup if registry_level is None else registry_level

    async def require_perm(self, context: MessageContext, level: int) -> bool:
        """返回发送者是否达到指定成员权限；不足时返回 False，不抛事件异常。"""

        return await self.get_user_perm(context) >= int(level)

    async def require_group_perm(self, context: MessageContext, level: int) -> bool:
        """返回上下文群等级是否达到阈值；私聊按旧宿主语义跳过群限制。"""

        if context.chat_type != "group":
            return True
        return await self.get_group_perm(context) >= int(level)


async def get_user_perm(
    context: MessageContext, checker: PermissionChecker | None = None
) -> int:
    """使用指定或默认检查器获取成员权限。"""

    return await (checker or PermissionChecker()).get_user_perm(context)


async def get_group_perm(
    context: MessageContext, checker: PermissionChecker | None = None
) -> int:
    """使用指定或默认检查器获取群等级。"""

    return await (checker or PermissionChecker()).get_group_perm(context)


async def require_perm(
    context: MessageContext,
    level: int,
    checker: PermissionChecker | None = None,
) -> bool:
    """Tenko 的 awaitable 成员权限检查入口。"""

    return await (checker or PermissionChecker()).require_perm(context, level)


async def require_group_perm(
    context: MessageContext,
    level: int,
    checker: PermissionChecker | None = None,
) -> bool:
    """Tenko 的 awaitable 群等级检查入口。"""

    return await (checker or PermissionChecker()).require_group_perm(context, level)
