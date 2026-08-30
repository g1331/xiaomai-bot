from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from loguru import logger

from ..context import MessageContext
from .perm import Permission, PermissionChecker

_STATE_VERSION = 1
_FEATURE_MANAGER_NAMES = frozenset({"feature_manager", "功能开关"})


def _key(value: object, label: str) -> str:
    if value is None:
        raise ValueError(f"{label}不能为空")
    normalized = str(value)
    if not normalized:
        raise ValueError(f"{label}不能为空")
    return normalized


class FeatureService:
    """维护群×插件开关和插件维护状态。

    该服务只拥有 Tenko 新宿主的功能状态，不调用 Entari 插件生命周期 API，
    也不读写旧的 ``modules_data.json``。JSON 文件是当前阶段的持久化边界，
    后续接入真实数据库时可以替换本服务而不改变事件入口协议。
    """

    def __init__(
        self,
        state_path: str | Path | None = None,
        *,
        default_enabled: bool = True,
    ) -> None:
        if type(default_enabled) is not bool:
            raise TypeError("default_enabled 必须是布尔值")
        self.state_path: Path | None = None
        self.default_enabled = default_enabled
        self._plugins: dict[str, dict[str, Any]] = {}
        if state_path is not None:
            self.configure(state_path, default_enabled=default_enabled)

    def configure(
        self,
        state_path: str | Path | None,
        *,
        default_enabled: bool | None = None,
    ) -> None:
        """切换持久化位置并重新加载状态。"""

        if default_enabled is not None and type(default_enabled) is not bool:
            raise TypeError("default_enabled 必须是布尔值")
        self.state_path = None if state_path is None else Path(state_path)
        if default_enabled is not None:
            self.default_enabled = default_enabled
        self._plugins = {}
        self._load()

    @staticmethod
    def _validate_plugin_state(plugin: str, value: object) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            raise ValueError(f"功能状态 {plugin!r} 必须是 JSON object")
        maintenance = value.get("maintenance", False)
        if type(maintenance) is not bool:
            raise ValueError(f"功能状态 {plugin!r} 的 maintenance 必须是布尔值")
        groups = value.get("groups", {})
        if not isinstance(groups, Mapping):
            raise ValueError(f"功能状态 {plugin!r} 的 groups 必须是 JSON object")
        normalized_groups: dict[str, bool] = {}
        for group_id, enabled in groups.items():
            if type(enabled) is not bool:
                raise ValueError(f"功能状态 {plugin!r} 的群开关必须是布尔值")
            normalized_groups[_key(group_id, "群 ID")] = enabled
        return {"maintenance": maintenance, "groups": normalized_groups}

    def _load(self) -> None:
        if self.state_path is None or not self.state_path.is_file():
            return
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"功能开关状态不是有效 JSON: {self.state_path}") from exc
        if not isinstance(data, Mapping):
            raise ValueError(f"功能开关状态必须是 JSON object: {self.state_path}")
        version = data.get("version", _STATE_VERSION)
        if version != _STATE_VERSION:
            raise ValueError(f"不支持的功能开关状态版本: {version}")
        plugins = data.get("plugins", {})
        if not isinstance(plugins, Mapping):
            raise ValueError(
                f"功能开关状态的 plugins 必须是 JSON object: {self.state_path}"
            )
        self._plugins = {
            _key(plugin, "插件名"): self._validate_plugin_state(str(plugin), value)
            for plugin, value in plugins.items()
        }

    def _persist(self) -> None:
        if self.state_path is None:
            return
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        data = {"version": _STATE_VERSION, "plugins": self._plugins}
        temporary_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=self.state_path.parent,
                prefix=f".{self.state_path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                json.dump(data, temporary, ensure_ascii=False, indent=2, sort_keys=True)
                temporary.write("\n")
                temporary.flush()
                os.fsync(temporary.fileno())
                temporary_path = temporary.name
            os.replace(temporary_path, self.state_path)
        finally:
            if temporary_path is not None and os.path.exists(temporary_path):
                os.unlink(temporary_path)

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
        if state is None:
            return self.default_enabled
        if state["maintenance"]:
            return False
        normalized_group = self._group_id(group_id)
        if normalized_group is not None:
            enabled = state["groups"].get(normalized_group)
            if enabled is not None:
                return enabled
        return self.default_enabled

    def set_enabled(self, plugin: str, group_id: str | int, enabled: bool) -> bool:
        """设置指定群的插件开关并立即持久化。"""

        if type(enabled) is not bool:
            raise TypeError("enabled 必须是布尔值")
        state = self._plugin_state(plugin)
        state["groups"][_key(group_id, "群 ID")] = enabled
        self._persist()
        return enabled

    def enable(self, plugin: str, group_id: str | int) -> bool:
        return self.set_enabled(plugin, group_id, True)

    def disable(self, plugin: str, group_id: str | int) -> bool:
        return self.set_enabled(plugin, group_id, False)

    def set_maintenance(self, plugin: str, maintenance: bool) -> bool:
        """设置全局维护状态；维护中等价于所有群关闭。"""

        if type(maintenance) is not bool:
            raise TypeError("maintenance 必须是布尔值")
        self._plugin_state(plugin)["maintenance"] = maintenance
        self._persist()
        return maintenance

    def is_maintenance(self, plugin: str) -> bool:
        state = self._plugins.get(_key(plugin, "插件名"))
        return bool(state and state["maintenance"])

    def reset_group(self, plugin: str, group_id: str | int) -> None:
        """删除指定群的显式值，使其恢复默认策略。"""

        state = self._plugins.get(_key(plugin, "插件名"))
        if state is None:
            return
        state["groups"].pop(_key(group_id, "群 ID"), None)
        self._persist()

    @property
    def state(self) -> Mapping[str, Mapping[str, Any]]:
        """返回用于查询/测试的只读快照。"""

        return {
            plugin: {
                "maintenance": value["maintenance"],
                "groups": dict(value["groups"]),
            }
            for plugin, value in self._plugins.items()
        }


feature_service = FeatureService()


def configure_feature_service(
    state_path: str | Path | None,
    *,
    default_enabled: bool = True,
) -> FeatureService:
    """配置全局功能开关服务，返回供运行时注入的同一实例。"""

    feature_service.configure(state_path, default_enabled=default_enabled)
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
        plugin_name = _plugin_name(owner)
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
