from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

from arclet.alconna import command_manager
from arclet.entari.exceptions import RegisterNotInPluginError as PluginInterfaceError
from arclet.entari.plugin import (
    Plugin,
    PluginMetadata,
    disable_plugin,
    enable_plugin,
    get_plugin_commands,
    get_plugins,
    load_plugin,
    unload_plugin,
)

from ..context import MessageContext

_DEFAULT_PLUGIN_DIR = Path(__file__).resolve().parent.parent / "plugins"
_DEFAULT_LEGACY_STATE = Path("core/models/saya_model/modules_data.json")
_LEGACY_PLUGIN_NAMESPACES = (
    "modules.required",
    "modules.self_contained",
    "modules.third_party",
)

__all__ = [
    "Plugin",
    "PluginInfo",
    "PluginInterfaceError",
    "PluginMetadata",
    "PluginRuntime",
]


@dataclass(frozen=True, slots=True)
class PluginInfo:
    """插件目录项及其可传给 Entari 的导入名。"""

    name: str
    path: Path
    is_package: bool
    qualified_name: str

    @property
    def display_name(self) -> str:
        """返回已加载插件的元数据名称，未加载时回退到目录名。"""

        names = set(self.lookup_names)
        native_plugin = next(
            (plugin for plugin in get_plugins(subplugged=True) if plugin.id in names),
            None,
        )
        metadata_name = getattr(getattr(native_plugin, "metadata", None), "name", None)
        return str(metadata_name) if metadata_name else self.name

    @property
    def lookup_names(self) -> tuple[str, ...]:
        names = [self.name, self.qualified_name]
        names.extend(
            f"{namespace}.{self.name}" for namespace in _LEGACY_PLUGIN_NAMESPACES
        )
        return tuple(dict.fromkeys(names))


class PluginRuntime:
    """把旧目录和状态格式适配到 Entari 原生插件机制。"""

    def __init__(
        self,
        plugin_dir: str | Path | None = None,
        *,
        legacy_state_path: str | Path | None = _DEFAULT_LEGACY_STATE,
        namespace: str = "tenko.plugins",
    ) -> None:
        self.plugin_dir = Path(plugin_dir or _DEFAULT_PLUGIN_DIR)
        self.namespace = namespace
        self._discovered: dict[str, PluginInfo] = {}
        self._legacy_state = self._load_legacy_state(legacy_state_path)

    @staticmethod
    def _load_legacy_state(path: str | Path | None) -> Mapping[str, Any]:
        if path is None:
            return MappingProxyType({})
        state_path = Path(path)
        if not state_path.is_file():
            return MappingProxyType({})
        try:
            data = json.loads(state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"旧插件状态不是有效 JSON: {state_path}") from exc
        if not isinstance(data, dict):
            raise ValueError(f"旧插件状态必须是 JSON object: {state_path}")
        modules = data.get("modules", {})
        if not isinstance(modules, dict):
            raise ValueError(f"旧插件状态的 modules 必须是 JSON object: {state_path}")
        return MappingProxyType({"modules": MappingProxyType(modules)})

    def discover(self) -> tuple[PluginInfo, ...]:
        """发现插件目录的直接子项，不导入插件。"""

        if not self.plugin_dir.exists():
            self._discovered = {}
            return ()
        if not self.plugin_dir.is_dir():
            raise NotADirectoryError(f"插件目录不是目录: {self.plugin_dir}")

        discovered: dict[str, PluginInfo] = {}
        for path in sorted(self.plugin_dir.iterdir(), key=lambda item: item.name):
            if path.name.startswith("_"):
                continue
            is_package = path.is_dir() and (path / "__init__.py").is_file()
            if not is_package and not (path.is_file() and path.suffix == ".py"):
                continue
            name = path.name if is_package else path.stem
            if name in discovered:
                raise ValueError(f"插件名称重复: {name}")
            qualified_name = f"{self.namespace}.{name}" if self.namespace else name
            discovered[name] = PluginInfo(name, path, is_package, qualified_name)
        self._discovered = discovered
        return tuple(discovered.values())

    def _info(self, plugin: str | PluginInfo) -> PluginInfo:
        if isinstance(plugin, PluginInfo):
            return plugin
        if not self._discovered:
            self.discover()
        if plugin in self._discovered:
            return self._discovered[plugin]
        for info in self._discovered.values():
            if plugin in info.lookup_names:
                return info
        raise KeyError(f"未发现插件: {plugin}")

    def _legacy_module_state(self, info: PluginInfo) -> Mapping[str, Any]:
        modules = self._legacy_state.get("modules", {})
        for name in info.lookup_names:
            value = modules.get(name)
            if isinstance(value, Mapping):
                return value
        return {}

    @staticmethod
    def _legacy_bool(value: Any, field: str) -> bool | None:
        if value is None:
            return None
        if type(value) is not bool:
            raise ValueError(f"旧插件状态中的 {field} 必须是布尔值")
        return value

    def _legacy_global_enabled(self, info: PluginInfo) -> bool | None:
        state = self._legacy_module_state(info)
        available = self._legacy_bool(state.get("available"), "available")
        if available is False:
            return False
        switch = self._legacy_bool(state.get("switch"), "switch")
        return switch if switch is not None else available

    @classmethod
    def _legacy_group_switch(
        cls, state: Mapping[str, Any], group_id: str | None
    ) -> bool | None:
        if group_id is None:
            return None
        groups = state.get("groups", state)
        if not isinstance(groups, Mapping):
            return None
        group_state = groups.get(group_id)
        if not isinstance(group_state, Mapping):
            return None
        return cls._legacy_bool(group_state.get("switch"), "switch")

    @staticmethod
    def _group_id(
        context: MessageContext | str | int | None,
        group_id: str | int | None,
    ) -> str | None:
        if group_id is not None:
            return str(group_id)
        if isinstance(context, MessageContext):
            return context.channel_id if context.chat_type == "group" else None
        return None if context is None else str(context)

    def is_enabled(
        self,
        plugin: str | PluginInfo,
        context: MessageContext | str | int | None = None,
        *,
        group_id: str | int | None = None,
    ) -> bool:
        """查询原生全局状态，并兼容旧状态中的群级开关。"""

        info = self._info(plugin)
        state = self._legacy_module_state(info)
        global_enabled = self._legacy_global_enabled(info)
        group_enabled = self._legacy_group_switch(
            state, self._group_id(context, group_id)
        )
        if global_enabled is False or group_enabled is False:
            return False
        native_plugin = self._native_plugin(info)
        if native_plugin is not None and not native_plugin.is_available:
            return False
        return (
            group_enabled if group_enabled is not None else global_enabled is not False
        )

    @staticmethod
    def _native_plugin(info: PluginInfo) -> Plugin | None:
        names = set(info.lookup_names)
        return next(
            (plugin for plugin in get_plugins(subplugged=True) if plugin.id in names),
            None,
        )

    @property
    def loaded_plugins(self) -> Mapping[str, Plugin]:
        if not self._discovered:
            self.discover()
        loaded = {
            info.name: plugin
            for info in self._discovered.values()
            if (plugin := self._native_plugin(info)) is not None
        }
        return MappingProxyType(loaded)

    def is_loaded(self, plugin: str | PluginInfo) -> bool:
        return self._native_plugin(self._info(plugin)) is not None

    @staticmethod
    def _command_matches(text: str, candidate: str) -> bool:
        return text == candidate or (
            text.startswith(candidate)
            and len(text) > len(candidate)
            and text[len(candidate)] in " \t"
        )

    @staticmethod
    def _shortcut_candidates(command: object) -> tuple[str, ...]:
        get_shortcuts = getattr(command, "get_shortcuts", None)
        if get_shortcuts is None:
            return ()
        candidates: list[str] = []
        for shortcut in get_shortcuts() or ():
            raw = str(shortcut).split(" ", 1)[0]
            if raw.startswith("[") and "]" in raw:
                prefix, alias = raw[1:].split("]", 1)
                if alias:
                    candidates.append(f"{prefix}{alias}")
            elif raw:
                candidates.append(raw)
        return tuple(candidates)

    def command_owner(self, text: str) -> PluginInfo | None:
        """按当前 Entari 注册命令返回其插件目录项。

        ``get_plugin_commands`` 是 Entari 保存的插件归属索引；命令 shortcut
        则从对应的原生 Alconna 对象读取，因此 ``/状态`` 这类别名也会落到
        正确插件。无法识别的消息返回 ``None``，不阻断 Entari 原生命令链。
        """

        if not isinstance(text, str) or not text:
            return None
        if not self._discovered:
            self.discover()
        native_commands = tuple(command_manager.get_commands())
        for native_plugin in get_plugins(subplugged=True):
            try:
                plugin_commands = tuple(get_plugin_commands(native_plugin) or ())
            except (PluginInterfaceError, TypeError, AttributeError):
                plugin_commands = ()
            command_names = {
                str(command_name) for _prefixes, command_name in plugin_commands
            }
            command_candidates: set[str] = set()
            for prefixes, command_name in plugin_commands:
                for prefix in prefixes or ():
                    command_candidates.add(f"{prefix}{command_name}")
            for native_command in native_commands:
                if getattr(native_command, "command", None) in command_names:
                    command_candidates.update(self._shortcut_candidates(native_command))
            if not any(
                self._command_matches(text, candidate)
                for candidate in command_candidates
            ):
                continue
            for info in self._discovered.values():
                if native_plugin.id in info.lookup_names:
                    return info
        return None

    async def _apply_legacy_state(self, info: PluginInfo, plugin: Plugin) -> None:
        enabled = self._legacy_global_enabled(info)
        if enabled is not None:
            await (enable_plugin if enabled else disable_plugin)(plugin.id)

    async def load(
        self,
        plugin: str | PluginInfo,
        *,
        config: dict[str, Any] | None = None,
    ) -> Plugin | None:
        """通过 Entari 加载插件，并应用旧状态中的全局开关。"""

        info = self._info(plugin)
        loaded = (
            load_plugin(info.qualified_name)
            if config is None
            else load_plugin(info.qualified_name, config)
        )
        if loaded is not None:
            await self._apply_legacy_state(info, loaded)
        return loaded

    async def load_all(
        self,
        configs: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> Mapping[str, Plugin]:
        """发现并加载插件，可为指定插件传入 Entari 配置。

        显式配置的插件先于其他插件加载，避免某个插件的依赖导入以默认
        配置抢先创建它，之后无法再替换已注册的 Entari 服务实例。
        """

        configs = {} if configs is None else configs
        infos = self.discover()
        configured_names = set(configs)
        for info in infos:
            if info.name not in configured_names:
                continue
            config = configs.get(info.name)
            await self.load(info, config=dict(config))
        for info in infos:
            if info.name in configured_names:
                continue
            await self.load(info)
        return self.loaded_plugins

    def unload(self, plugin: str | PluginInfo) -> bool:
        """通过 Entari 卸载插件。"""

        return unload_plugin(self._info(plugin).qualified_name)

    async def reload(
        self,
        plugin: str | PluginInfo,
        *,
        config: dict[str, Any] | None = None,
    ) -> Plugin | None:
        """按 Entari 的原生热重载方式卸载后重新加载。"""

        info = self._info(plugin)
        unload_plugin(info.qualified_name)
        return await self.load(info, config=config)

    async def enable(self, plugin: str | PluginInfo) -> bool:
        return await enable_plugin(self._info(plugin).qualified_name)

    async def disable(self, plugin: str | PluginInfo) -> bool:
        return await disable_plugin(self._info(plugin).qualified_name)

    async def set_enabled(self, plugin: str | PluginInfo, enabled: bool) -> bool:
        if type(enabled) is not bool:
            raise TypeError("enabled 必须是布尔值")
        return await (self.enable(plugin) if enabled else self.disable(plugin))
