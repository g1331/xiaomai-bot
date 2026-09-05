from __future__ import annotations

import asyncio

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from loguru import logger

from ..context import MessageContext
from .perm import Permission, PermissionChecker

_FEATURE_MANAGER_NAMES = frozenset({"feature_manager", "功能开关"})

if TYPE_CHECKING:
    from ..db.repositories import FeatureStateRepository


def _key(value: object, label: str) -> str:
    if value is None:
        raise ValueError(f"{label}不能为空")
    normalized = str(value)
    if not normalized:
        raise ValueError(f"{label}不能为空")
    return normalized


class FeatureService:
    """维护插件开关和插件维护状态。

    该服务只拥有 Tenko 新宿主的功能状态，不调用 Entari 插件生命周期 API，
    普通插件使用群级开关；需要宿主级开关的插件可以使用可选的
    ``global_enabled`` 字段。同步事件入口读取内存快照，异步生命周期负责从
    repository 加载和刷新快照。
    """

    def __init__(
        self,
        repository: FeatureStateRepository | None = None,
        *,
        default_enabled: bool = True,
    ) -> None:
        if type(default_enabled) is not bool:
            raise TypeError("default_enabled 必须是布尔值")
        self._repository = repository
        self.default_enabled = default_enabled
        self._plugins: dict[str, dict[str, Any]] = {}
        self._ready = repository is None
        self._persist_lock = asyncio.Lock()

    def configure(
        self,
        repository: FeatureStateRepository | None = None,
        *,
        default_enabled: bool | None = None,
    ) -> None:
        """配置 repository 和默认值；实际数据库读取由异步初始化完成。"""

        if default_enabled is not None and type(default_enabled) is not bool:
            raise TypeError("default_enabled 必须是布尔值")
        self._repository = repository
        if default_enabled is not None:
            self.default_enabled = default_enabled
        self._plugins = {}
        self._ready = repository is None
        self._persist_lock = asyncio.Lock()

    @property
    def ready(self) -> bool:
        """返回数据库快照是否可安全用于命令判定。"""

        return self._ready

    def mark_unavailable(self) -> None:
        """将数据库读写失败转换为功能关闭的保守状态。"""

        self._plugins = {}
        self._ready = False

    async def initialize(
        self, repository: FeatureStateRepository | None = None
    ) -> None:
        """从 repository 加载状态；没有显式状态的插件使用配置默认值。"""

        if repository is not None:
            self._repository = repository
        if self._repository is None:
            self._plugins = {}
            self._ready = True
            return

        try:
            rows = await self._repository.list_states()
        except Exception:
            self.mark_unavailable()
            raise

        plugins: dict[str, dict[str, Any]] = {}
        for row in rows:
            state = plugins.setdefault(
                row.plugin_name,
                {"maintenance": False, "groups": {}},
            )
            if row.group_id is None:
                state["maintenance"] = row.maintenance
                if row.enabled is not None:
                    state["global_enabled"] = row.enabled
            elif row.enabled is not None:
                state["groups"][row.group_id] = row.enabled
        self._plugins = plugins
        self._ready = True

    def _state_records(self) -> tuple[Any, ...]:
        from ..db.repositories import FeatureStateRecord

        records: list[FeatureStateRecord] = []
        for plugin_name, state in self._plugins.items():
            if "global_enabled" in state or state["maintenance"]:
                records.append(
                    FeatureStateRecord(
                        plugin_name=plugin_name,
                        group_id=None,
                        enabled=state.get("global_enabled"),
                        maintenance=state["maintenance"],
                    )
                )
            records.extend(
                FeatureStateRecord(
                    plugin_name=plugin_name,
                    group_id=group_id,
                    enabled=enabled,
                    maintenance=False,
                )
                for group_id, enabled in state["groups"].items()
            )
        return tuple(records)

    async def persist_state(self) -> None:
        """将当前快照原子替换到功能状态表。"""

        if self._repository is None:
            if not self._ready:
                from ..db.errors import DatabaseUnavailableError

                raise DatabaseUnavailableError("功能状态数据库不可用")
            return
        if not self._ready:
            from ..db.errors import DatabaseUnavailableError

            raise DatabaseUnavailableError("功能状态数据库尚未就绪")
        try:
            async with self._persist_lock:
                await self._repository.replace_states(self._state_records())
        except Exception:
            self.mark_unavailable()
            raise

    def _plugin_state(self, plugin: object) -> dict[str, Any]:
        plugin_name = _key(plugin, "插件名")
        return self._plugins.setdefault(
            plugin_name,
            {"maintenance": False, "groups": {}},
        )

    @staticmethod
    def _group_id(group_id: str | int | None) -> str | None:
        return None if group_id is None else _key(group_id, "群 ID")

    def is_enabled(self, plugin: str, group_id: str | int | None = None) -> bool:
        """返回插件在指定群是否可执行；未显式设置时使用默认开启值。"""

        state = self._plugins.get(_key(plugin, "插件名"))
        if not self._ready:
            return False
        if state is None:
            return self.default_enabled
        if state["maintenance"]:
            return False
        global_enabled = state.get("global_enabled")
        if global_enabled is not None:
            return global_enabled
        normalized_group = self._group_id(group_id)
        if normalized_group is not None:
            enabled = state["groups"].get(normalized_group)
            if enabled is not None:
                return enabled
        return self.default_enabled

    def set_enabled(self, plugin: str, group_id: str | int, enabled: bool) -> bool:
        """更新指定群的插件开关；异步调用方随后应刷新 repository。"""

        if type(enabled) is not bool:
            raise TypeError("enabled 必须是布尔值")
        state = self._plugin_state(plugin)
        state["groups"][_key(group_id, "群 ID")] = enabled
        return enabled

    def enable(self, plugin: str, group_id: str | int) -> bool:
        return self.set_enabled(plugin, group_id, True)

    def disable(self, plugin: str, group_id: str | int) -> bool:
        return self.set_enabled(plugin, group_id, False)

    def set_global_enabled(self, plugin: str, enabled: bool) -> bool:
        """更新宿主级插件开关；异步调用方随后应刷新 repository。"""

        if type(enabled) is not bool:
            raise TypeError("enabled 必须是布尔值")
        self._plugin_state(plugin)["global_enabled"] = enabled
        return enabled

    def reset_global(self, plugin: str) -> None:
        """清除全局覆盖，恢复群级策略与默认值。"""

        self._plugin_state(plugin).pop("global_enabled", None)

    def set_maintenance(self, plugin: str, maintenance: bool) -> bool:
        """设置全局维护状态；维护中等价于所有群关闭。"""

        if type(maintenance) is not bool:
            raise TypeError("maintenance 必须是布尔值")
        self._plugin_state(plugin)["maintenance"] = maintenance
        return maintenance

    def is_maintenance(self, plugin: str) -> bool:
        if not self._ready:
            return True
        state = self._plugins.get(_key(plugin, "插件名"))
        return bool(state and state["maintenance"])

    def reset_group(self, plugin: str, group_id: str | int) -> None:
        """删除指定群的显式值，使其恢复默认策略。"""

        state = self._plugins.get(_key(plugin, "插件名"))
        if state is None:
            return
        state["groups"].pop(_key(group_id, "群 ID"), None)

    @property
    def state(self) -> Mapping[str, Mapping[str, Any]]:
        """返回用于查询/测试的只读快照。"""

        snapshot = {
            plugin: {
                "maintenance": value["maintenance"],
                "groups": dict(value["groups"]),
            }
            for plugin, value in self._plugins.items()
        }
        for plugin, value in self._plugins.items():
            if "global_enabled" in value:
                snapshot[plugin]["global_enabled"] = value["global_enabled"]
        return snapshot


feature_service = FeatureService()


def configure_feature_service(
    repository: FeatureStateRepository | None = None,
    *,
    default_enabled: bool = True,
) -> FeatureService:
    """配置全局功能开关服务，返回供运行时注入的同一实例。"""

    feature_service.configure(repository, default_enabled=default_enabled)
    return feature_service


def _plugin_name(owner: object) -> str:
    return _key(getattr(owner, "name", owner), "插件名")


def _plugin_label(owner: object) -> str:
    return _key(
        getattr(owner, "display_name", getattr(owner, "name", owner)),
        "插件名",
    )


class CommandPolicy:
    """事件入口的统一命令策略。

    该策略只在能从已注册 Entari 命令解析出插件归属、且事件来自群聊时
    生效；普通消息和私聊保持事件层原有行为。功能开关先于限流，二者都
    在命令进入 Entari 原生命令分发前完成。
    """

    def __init__(
        self,
        feature_service: FeatureService,
        rate_limiter: Any | None = None,
        *,
        plugin_runtime: Any | None = None,
        permission_checker: PermissionChecker | None = None,
        command_prefix: str = "/",
        rate_limit_override_permission: int = Permission.GroupAdmin,
    ) -> None:
        self.feature_service = feature_service
        self.rate_limiter = rate_limiter
        self.plugin_runtime = plugin_runtime
        self.permission_checker = permission_checker or PermissionChecker()
        self.command_prefix = _key(command_prefix, "命令前缀")
        self.rate_limit_override_permission = int(rate_limit_override_permission)

    def _owner(self, text: str) -> object | None:
        runtime = self.plugin_runtime
        if runtime is None:
            return None
        return runtime.command_owner(text)

    def _disabled_notice(self, owner: object) -> str:
        label = _plugin_label(owner)
        return (
            f"{label}插件已关闭\n"
            f"请使用‘{self.command_prefix}开启 插件编号’来打开插件\n"
            "插件编号请使用‘帮助’获取"
        )

    @staticmethod
    def _maintenance_notice(owner: object) -> str:
        return f"{_plugin_label(owner)}插件正在维护~"

    async def check(self, account: object, event: object) -> str | None:
        del account
        try:
            context = MessageContext.from_event(event)  # type: ignore[arg-type]
        except ValueError:
            return None
        if context.chat_type != "group" or not context.text:
            return None
        owner = self._owner(context.text)
        if owner is None:
            return None
        if not self.feature_service.ready:
            return "功能状态暂不可用，请稍后再试"
        plugin_name = _plugin_name(owner)
        if (
            plugin_name not in _FEATURE_MANAGER_NAMES
            and self.feature_service.is_maintenance(plugin_name)
        ):
            logger.debug(
                "Ignore plugin command in maintenance mode: plugin={} group={} "
                "text={!r}",
                plugin_name,
                context.channel_id,
                context.text,
            )
            return self._maintenance_notice(owner)
        if (
            plugin_name not in _FEATURE_MANAGER_NAMES
            and not self.feature_service.is_enabled(plugin_name, context.channel_id)
        ):
            logger.debug(
                "Ignore disabled plugin command: plugin={} group={} text={!r}",
                plugin_name,
                context.channel_id,
                context.text,
            )
            return self._disabled_notice(owner)

        if self.rate_limiter is None:
            return None
        override = await self.permission_checker.require_perm(
            context, self.rate_limit_override_permission
        )
        check_and_persist = getattr(self.rate_limiter, "check_and_persist", None)
        if callable(check_and_persist):
            decision = await check_and_persist(
                context.channel_id,
                context.user_id,
                command=plugin_name,
                override=override,
            )
        else:
            decision = self.rate_limiter.check(
                context.channel_id,
                context.user_id,
                command=plugin_name,
                override=override,
            )
        if not decision.allowed:
            logger.debug(
                "Ignore rate-limited plugin command: plugin={} group={} user={}",
                plugin_name,
                context.channel_id,
                context.user_id,
            )
            return decision.message
        return None


__all__ = [
    "CommandPolicy",
    "FeatureService",
    "configure_feature_service",
    "feature_service",
]
