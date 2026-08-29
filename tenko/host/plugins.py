from __future__ import annotations

import hashlib
import inspect
import json
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from importlib import invalidate_caches
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import MappingProxyType, ModuleType
from typing import Any

from ..context import MessageContext

_DEFAULT_PLUGIN_DIR = Path(__file__).resolve().parent.parent / "plugins"
_DEFAULT_LEGACY_STATE = Path("core/models/saya_model/modules_data.json")
_MISSING = object()


class PluginInterfaceError(TypeError):
    """插件没有实现 Tenko 要求的 `register(app, ctx)` 函数。"""


@dataclass(frozen=True, slots=True)
class PluginInfo:
    """一个可发现插件的路径和元数据快照。"""

    name: str
    path: Path
    is_package: bool
    metadata: Mapping[str, Any]
    qualified_name: str

    @property
    def default_switch(self) -> bool:
        value = self.metadata.get("default_switch", True)
        if type(value) is not bool:
            raise ValueError(f"插件 {self.name} 的 default_switch 必须是布尔值")
        return value

    @property
    def source_path(self) -> Path:
        return self.path / "__init__.py" if self.is_package else self.path

    @property
    def lookup_names(self) -> tuple[str, ...]:
        """返回新插件名和旧 modules_data key 的兼容查找名。"""

        names = [self.name, self.qualified_name, self.path.stem]
        metadata_name = self.metadata.get("module")
        if isinstance(metadata_name, str) and metadata_name:
            names.append(metadata_name)
        return tuple(dict.fromkeys(names))


@dataclass(slots=True)
class _LoadedPlugin:
    info: PluginInfo
    module: ModuleType
    app: Any
    context: Any


def _read_metadata(path: Path) -> Mapping[str, Any]:
    metadata_path = (
        path / "metadata.json" if path.is_dir() else path.with_name("metadata.json")
    )
    if not metadata_path.is_file():
        return MappingProxyType({})
    try:
        data = json.loads(metadata_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"插件元数据不是有效 JSON: {metadata_path}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"插件元数据必须是 JSON object: {metadata_path}")
    return MappingProxyType(data)


class PluginRuntime:
    """发现、开关过滤和装载 Tenko 插件。

    这里的边界是“文件系统插件模块 ↔ Tenko 宿主注册入口”：运行时只负责
    找到模块、导入模块并调用一次 `register(app, ctx)`，不复制 Saya 的
    channel、事件分发或依赖注入机制。`unregister` 是插件可选的清理入口，
    模块本身仍然是插件作者的实现对象。

    `legacy_state_path` 只读兼容旧 `modules_data.json` 的 `available`、群组
    `switch` 和 `default_switch` 语义；`set_enabled` 的覆盖保存在内存中，
    不会写回旧文件。
    """

    def __init__(
        self,
        plugin_dir: str | Path | None = None,
        *,
        app: Any = None,
        context: Any = None,
        legacy_state_path: str | Path | None = _DEFAULT_LEGACY_STATE,
        namespace: str = "tenko.plugins",
    ) -> None:
        self.plugin_dir = Path(plugin_dir or _DEFAULT_PLUGIN_DIR)
        self.app = app
        self.context = context
        self.namespace = namespace
        self._discovered: dict[str, PluginInfo] = {}
        self._loaded: dict[str, _LoadedPlugin] = {}
        self._switch_overrides: dict[tuple[str, str | None], bool] = {}
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
        """扫描插件目录的直接子项并按名称返回发现结果。"""

        if not self.plugin_dir.exists():
            self._discovered = {}
            return ()
        if not self.plugin_dir.is_dir():
            raise NotADirectoryError(f"插件目录不是目录: {self.plugin_dir}")

        discovered: dict[str, PluginInfo] = {}
        candidates = sorted(self.plugin_dir.iterdir(), key=lambda item: item.name)
        for path in candidates:
            if path.name.startswith("_"):
                continue
            if path.is_file() and path.suffix == ".py":
                is_package = False
            elif path.is_dir() and (path / "__init__.py").is_file():
                is_package = True
            else:
                continue
            name = path.stem if path.is_file() else path.name
            if name in discovered:
                raise ValueError(f"插件名称重复: {name}")
            discovered[name] = PluginInfo(
                name=name,
                path=path,
                is_package=is_package,
                metadata=_read_metadata(path),
                qualified_name=f"{self.namespace}.{name}",
            )
        self._discovered = discovered
        return tuple(discovered.values())

    def _info(self, plugin: str | PluginInfo) -> PluginInfo:
        if isinstance(plugin, PluginInfo):
            return plugin
        if not self._discovered:
            self.discover()
        try:
            return self._discovered[plugin]
        except KeyError as exc:
            raise KeyError(f"未发现插件: {plugin}") from exc

    @staticmethod
    def _group_id(
        context: MessageContext | str | int | None,
        group_id: str | int | None,
    ) -> str | None:
        if group_id is not None:
            return str(group_id)
        if isinstance(context, MessageContext):
            return context.channel_id if context.chat_type == "group" else None
        if context is None:
            return None
        return str(context)

    def _legacy_module_state(self, info: PluginInfo) -> Mapping[str, Any]:
        modules = self._legacy_state.get("modules", {})
        for name in info.lookup_names:
            value = modules.get(name)
            if isinstance(value, dict):
                return value
        return {}

    @staticmethod
    def _legacy_group_switch(
        state: Mapping[str, Any], group_id: str | None
    ) -> bool | None:
        if group_id is None:
            return None
        groups = state.get("groups", state)
        if not isinstance(groups, dict):
            return None
        group_state = groups.get(group_id)
        if not isinstance(group_state, dict):
            return None
        value = group_state.get("switch")
        if value is None:
            return None
        if type(value) is not bool:
            raise ValueError("旧插件状态中的 switch 必须是布尔值")
        return value

    def is_enabled(
        self,
        plugin: str | PluginInfo,
        context: MessageContext | str | int | None = None,
        *,
        group_id: str | int | None = None,
    ) -> bool:
        """判断插件在全局或指定群上下文中是否启用。"""

        info = self._info(plugin)
        normalized_group = self._group_id(context, group_id)
        state = self._legacy_module_state(info)
        global_override = self._switch_overrides.get((info.name, None))
        available = state.get("available", True)
        if type(available) is not bool:
            raise ValueError("旧插件状态中的 available 必须是布尔值")
        group_override = self._switch_overrides.get((info.name, normalized_group))
        if group_override is not None:
            return global_override is not False and group_override
        if global_override is not None:
            return global_override
        if not available:
            return False
        legacy_global_switch = state.get("switch")
        if legacy_global_switch is not None:
            if type(legacy_global_switch) is not bool:
                raise ValueError("旧插件状态中的 switch 必须是布尔值")
            enabled = legacy_global_switch
        else:
            enabled = info.default_switch
        if normalized_group is None:
            return enabled
        group_switch = self._legacy_group_switch(state, normalized_group)
        return enabled if group_switch is None else group_switch

    def set_enabled(
        self,
        plugin: str | PluginInfo,
        enabled: bool,
        *,
        group_id: str | int | None = None,
    ) -> None:
        """设置内存中的全局或群级开关，不写入旧状态文件。"""

        if type(enabled) is not bool:
            raise TypeError("enabled 必须是布尔值")
        info = self._info(plugin)
        normalized_group = None if group_id is None else str(group_id)
        self._switch_overrides[(info.name, normalized_group)] = enabled

    @property
    def loaded_plugins(self) -> Mapping[str, ModuleType]:
        """返回已加载模块的只读映射。"""

        return MappingProxyType(
            {name: loaded.module for name, loaded in self._loaded.items()}
        )

    def is_loaded(self, plugin: str | PluginInfo) -> bool:
        return self._info(plugin).name in self._loaded

    @staticmethod
    def _module_name(info: PluginInfo) -> str:
        digest = hashlib.sha256(str(info.path.resolve()).encode()).hexdigest()[:16]
        return f"_tenko_plugin_{digest}_{info.name}"

    @staticmethod
    def _reject_awaitable(result: object, operation: str) -> None:
        if inspect.isawaitable(result):
            if inspect.iscoroutine(result):
                result.close()
            raise TypeError(
                f"插件 {operation} 必须是同步函数；异步注册请在宿主层显式调度"
            )

    def _import(self, info: PluginInfo) -> tuple[str, ModuleType]:
        invalidate_caches()
        module_name = self._module_name(info)
        source_path = info.source_path
        spec = spec_from_file_location(
            module_name,
            source_path,
            submodule_search_locations=[str(info.path)] if info.is_package else None,
        )
        if spec is None:
            raise ImportError(f"无法创建插件模块 spec: {source_path}")
        module = module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            source = source_path.read_bytes()
            code = compile(source, str(source_path), "exec")
            exec(code, module.__dict__)
        except Exception:
            self._remove_module(module_name)
            raise
        return module_name, module

    @staticmethod
    def _remove_module(module_name: str) -> None:
        for name in tuple(sys.modules):
            if name == module_name or name.startswith(f"{module_name}."):
                sys.modules.pop(name, None)

    def load(
        self,
        plugin: str | PluginInfo,
        *,
        app: Any = _MISSING,
        context: Any = _MISSING,
        group_id: str | int | None = None,
    ) -> ModuleType | None:
        """加载启用的插件；被开关过滤时返回 `None`。"""

        info = self._info(plugin)
        routing_context = context if isinstance(context, MessageContext) else None
        if not self.is_enabled(info, routing_context, group_id=group_id):
            return None
        if info.name in self._loaded:
            return self._loaded[info.name].module

        loaded_app = self.app if app is _MISSING else app
        loaded_context = self.context if context is _MISSING else context
        module_name, module = self._import(info)
        register = getattr(module, "register", None)
        if not callable(register):
            self._remove_module(module_name)
            raise PluginInterfaceError(f"插件 {info.name} 必须提供 register(app, ctx)")
        try:
            result = register(loaded_app, loaded_context)
            self._reject_awaitable(result, "register")
        except Exception:
            self._remove_module(module_name)
            raise
        self._loaded[info.name] = _LoadedPlugin(
            info=info,
            module=module,
            app=loaded_app,
            context=loaded_context,
        )
        return module

    def load_all(self) -> Mapping[str, ModuleType]:
        """发现并加载所有全局启用插件，返回成功加载的模块。"""

        for info in self.discover():
            self.load(info)
        return self.loaded_plugins

    def unload(self, plugin: str | PluginInfo) -> bool:
        """卸载插件并清理其导入模块；未加载时返回 False。"""

        info = self._info(plugin)
        loaded = self._loaded.pop(info.name, None)
        if loaded is None:
            return False
        module_name = self._module_name(loaded.info)
        try:
            unregister = getattr(loaded.module, "unregister", None)
            if unregister is not None:
                if not callable(unregister):
                    raise PluginInterfaceError(
                        f"插件 {info.name} 的 unregister 必须是函数"
                    )
                result = unregister(loaded.app, loaded.context)
                self._reject_awaitable(result, "unregister")
        finally:
            self._remove_module(module_name)
        return True

    def reload(
        self,
        plugin: str | PluginInfo,
        *,
        app: Any = _MISSING,
        context: Any = _MISSING,
        group_id: str | int | None = None,
    ) -> ModuleType | None:
        """卸载后重新读取源文件并加载插件。"""

        info = self._info(plugin)
        self.unload(info)
        return self.load(
            info,
            app=app,
            context=context,
            group_id=group_id,
        )
