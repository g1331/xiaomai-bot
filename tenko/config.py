from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - only exercised on Python 3.10
    import tomli as tomllib


def _section(data: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    value = data.get(name, {})
    if not isinstance(value, Mapping):
        raise ValueError(f"配置节 [{name}] 必须是 TOML table")
    return value


def _string(section: Mapping[str, Any], key: str, default: str) -> str:
    value = section.get(key, default)
    if not isinstance(value, str):
        raise ValueError(f"配置项 {key!r} 必须是字符串")
    return value


def _optional_string(
    section: Mapping[str, Any], key: str, default: str | None
) -> str | None:
    value = section.get(key, default)
    if value is not None and not isinstance(value, str):
        raise ValueError(f"配置项 {key!r} 必须是字符串或 null")
    return value


def _integer(section: Mapping[str, Any], key: str, default: int) -> int:
    value = section.get(key, default)
    if type(value) is not int:  # bool 是 int 的子类，但不是这里接受的类型。
        raise ValueError(f"配置项 {key!r} 必须是整数")
    return value


def _number(section: Mapping[str, Any], key: str, default: float) -> float:
    value = section.get(key, default)
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise ValueError(f"配置项 {key!r} 必须是数字")
    return float(value)


def _boolean(section: Mapping[str, Any], key: str, default: bool) -> bool:
    value = section.get(key, default)
    if type(value) is not bool:
        raise ValueError(f"配置项 {key!r} 必须是布尔值")
    return value


def _string_sequence(
    section: Mapping[str, Any], key: str, default: tuple[str, ...]
) -> tuple[str, ...]:
    value = section.get(key, default)
    if not isinstance(value, list | tuple):
        raise ValueError(f"配置项 {key!r} 必须是字符串列表")
    normalized: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item:
            raise ValueError(f"配置项 {key!r} 的每项必须是非空字符串")
        normalized.append(item)
    return tuple(normalized)


def _identifier_sequence(
    section: Mapping[str, Any], key: str, default: tuple[str, ...]
) -> tuple[str, ...]:
    value = section.get(key, default)
    if not isinstance(value, list | tuple):
        raise ValueError(f"配置项 {key!r} 必须是字符串或整数列表")
    normalized: list[str] = []
    for item in value:
        if not isinstance(item, str | int) or isinstance(item, bool):
            raise ValueError(f"配置项 {key!r} 的每项必须是字符串或整数")
        item = str(item)
        if not item:
            raise ValueError(f"配置项 {key!r} 的每项不能为空")
        normalized.append(item)
    return tuple(normalized)


def _identifier_mapping(
    section: Mapping[str, Any],
    key: str,
    default: Mapping[str, tuple[str, ...]],
) -> dict[str, tuple[str, ...]]:
    value = section.get(key, default)
    if not isinstance(value, Mapping):
        raise ValueError(f"配置项 {key!r} 必须是平台到 ID 列表的 TOML table")

    normalized: dict[str, tuple[str, ...]] = {}
    for platform, identifiers in value.items():
        if not isinstance(platform, str) or not platform:
            raise ValueError(f"配置项 {key!r} 的平台名称必须是非空字符串")
        normalized[platform] = _identifier_sequence({key: identifiers}, key, ())
    return normalized


def _path(*parts: str) -> str:
    clean_parts = [part.strip("/") for part in parts if part.strip("/")]
    return "/" + "/".join(clean_parts)


def _capability_overrides(
    section: Mapping[str, Any], key: str = "capability_overrides"
) -> Mapping[str, Mapping[str, bool]]:
    value = section.get(key, {})
    if not isinstance(value, Mapping):
        raise ValueError(f"配置项 {key!r} 必须是 TOML table")

    normalized: dict[str, dict[str, bool]] = {}
    for account_id, account_value in value.items():
        if not isinstance(account_value, Mapping):
            raise ValueError(
                f"账号 {account_id!r} 的 capability_overrides 必须是 TOML table"
            )
        account_key = str(account_id)
        if not account_key:
            raise ValueError("capability_overrides 的账号 ID 不能为空")
        normalized[account_key] = {}
        for capability, enabled in account_value.items():
            if not isinstance(capability, str) or not capability:
                raise ValueError("capability 名称必须是非空字符串")
            if type(enabled) is not bool:
                raise ValueError(
                    f"账号 {account_key} 的 capability {capability!r} 必须是布尔值"
                )
            normalized[account_key][capability] = enabled
    return normalized


@dataclass(frozen=True, slots=True)
class OneBotConfig:
    """NapCat 反向 WebSocket 与内部 Satori 服务的配置。"""

    listen_host: str = "127.0.0.1"
    listen_port: int = 8080
    reverse_ws_prefix: str = "/"
    reverse_ws_path: str = "onebot/v11"
    reverse_ws_endpoint: str = "ws"
    access_token: str | None = None
    api_timeout: int = 60
    satori_host: str | None = None
    satori_path: str = "satori"
    satori_token: str | None = "tenko-satori-local"
    capability_overrides: Mapping[str, Mapping[str, bool]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.listen_host:
            raise ValueError("listen_host 不能为空")
        if not 1 <= self.listen_port <= 65535:
            raise ValueError("listen_port 必须在 1 到 65535 之间")
        if not self.reverse_ws_path or not self.reverse_ws_endpoint:
            raise ValueError("reverse WebSocket path 和 endpoint 不能为空")
        if self.api_timeout <= 0:
            raise ValueError("api_timeout 必须大于 0")
        if not self.satori_path:
            raise ValueError("satori_path 不能为空")

        normalized_overrides = _capability_overrides(
            {"capability_overrides": self.capability_overrides}
        )
        object.__setattr__(self, "capability_overrides", normalized_overrides)

        if self.access_token == "":
            object.__setattr__(self, "access_token", None)
        if self.satori_token == "":
            object.__setattr__(self, "satori_token", None)

    @property
    def reverse_ws_path_value(self) -> str:
        return _path(
            self.reverse_ws_prefix,
            self.reverse_ws_path,
            self.reverse_ws_endpoint,
        )

    @property
    def reverse_ws_url(self) -> str:
        host = self.listen_host
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        return f"ws://{host}:{self.listen_port}{self.reverse_ws_path_value}"

    @property
    def satori_client_host(self) -> str:
        host: str
        if self.satori_host:
            host = self.satori_host
        elif self.listen_host == "0.0.0.0":
            host = "127.0.0.1"
        elif self.listen_host == "::":
            host = "::1"
        else:
            host = self.listen_host

        # satori-python-client builds its URL from this value and therefore
        # needs IPv6 literals in URL form rather than socket-address form.
        if ":" in host and not host.startswith("["):
            return f"[{host}]"
        return host

    @property
    def listen_probe_host(self) -> str:
        """返回本进程探测监听 socket 时应使用的地址。"""

        if self.listen_host == "0.0.0.0":
            return "127.0.0.1"
        if self.listen_host == "::":
            return "::1"
        return self.listen_host

    @classmethod
    def from_mapping(cls, section: Mapping[str, Any]) -> OneBotConfig:
        defaults = cls()
        return cls(
            listen_host=_string(section, "listen_host", defaults.listen_host),
            listen_port=_integer(section, "listen_port", defaults.listen_port),
            reverse_ws_prefix=_string(
                section, "reverse_ws_prefix", defaults.reverse_ws_prefix
            ),
            reverse_ws_path=_string(
                section, "reverse_ws_path", defaults.reverse_ws_path
            ),
            reverse_ws_endpoint=_string(
                section, "reverse_ws_endpoint", defaults.reverse_ws_endpoint
            ),
            access_token=_optional_string(
                section, "access_token", defaults.access_token
            ),
            api_timeout=_integer(section, "api_timeout", defaults.api_timeout),
            satori_host=_optional_string(section, "satori_host", defaults.satori_host),
            satori_path=_string(section, "satori_path", defaults.satori_path),
            satori_token=_optional_string(
                section, "satori_token", defaults.satori_token
            ),
            capability_overrides=_capability_overrides(section),
        )


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    """运行时行为配置。"""

    send_replies: bool = False
    reply_text: str = "Tenko 已收到消息。"
    log_level: str = "INFO"
    command_prefix: str = "/"
    superusers: Mapping[str, tuple[str, ...]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.reply_text:
            raise ValueError("reply_text 不能为空")
        if not self.log_level:
            raise ValueError("log_level 不能为空")
        if not self.command_prefix:
            raise ValueError("command_prefix 不能为空")
        object.__setattr__(
            self,
            "superusers",
            _identifier_mapping({"superusers": self.superusers}, "superusers", {}),
        )

    @classmethod
    def from_mapping(
        cls,
        section: Mapping[str, Any],
        *,
        superusers: Mapping[str, tuple[str, ...]] | None = None,
    ) -> RuntimeConfig:
        defaults = cls()
        return cls(
            send_replies=_boolean(section, "send_replies", defaults.send_replies),
            reply_text=_string(section, "reply_text", defaults.reply_text),
            log_level=_string(section, "log_level", defaults.log_level),
            command_prefix=_string(section, "command_prefix", defaults.command_prefix),
            superusers=(
                _identifier_mapping(section, "superusers", defaults.superusers)
                if superusers is None
                else superusers
            ),
        )


@dataclass(frozen=True, slots=True)
class EntariConfig:
    """Entari 原生 basic.superusers 的唯一权威配置来源。"""

    superusers: Mapping[str, tuple[str, ...]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "superusers",
            _identifier_mapping({"superusers": self.superusers}, "superusers", {}),
        )

    @classmethod
    def from_mapping(
        cls,
        section: Mapping[str, Any],
        *,
        legacy_runtime_section: Mapping[str, Any] | None = None,
    ) -> EntariConfig:
        if "superusers" in section:
            users = _identifier_mapping(section, "superusers", {})
        elif (
            legacy_runtime_section is not None
            and "superusers" in legacy_runtime_section
        ):
            # 仅为旧 `[runtime].superusers` 配置提供迁移读取；解析后的有效值
            # 仍只保存到本对象，避免运行时继续维护两份名单。
            users = _identifier_mapping(legacy_runtime_section, "superusers", {})
        else:
            users = {}
        return cls(users)


def _flatten_identifiers(mapping: Mapping[str, tuple[str, ...]]) -> tuple[str, ...]:
    """将平台映射按配置顺序展开，并去除重复 ID。"""

    flattened: list[str] = []
    seen: set[str] = set()
    for identifiers in mapping.values():
        for identifier in identifiers:
            if identifier not in seen:
                flattened.append(identifier)
                seen.add(identifier)
    return tuple(flattened)


@dataclass(frozen=True, slots=True)
class DebugConfig:
    """开发调试模式配置。"""

    enabled: bool = False
    masters: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "masters",
            _identifier_sequence({"masters": self.masters}, "masters", self.masters),
        )

    @classmethod
    def from_mapping(
        cls,
        section: Mapping[str, Any],
        *,
        inherited_masters: tuple[str, ...] = (),
    ) -> DebugConfig:
        defaults = cls()
        return cls(
            enabled=_boolean(section, "enabled", defaults.enabled),
            masters=_identifier_sequence(section, "masters", inherited_masters),
        )


@dataclass(frozen=True, slots=True)
class UpgradeConfig:
    """宿主升级策略配置。

    升级配置独立于旧 Graia 配置。默认策略只检查，不下载或切换制品；这样
    ``TenkoConfig()`` 在没有额外配置时也不会产生写入或重启副作用。
    """

    enabled: bool = True
    source: str = "git_tag"
    repository: str = "."
    github_repository: str = ""
    manifest_url: str = ""
    github_token: str | None = None
    asset_name: str | None = None
    tag_prefix: str = "v"
    channel: str = "stable"
    policy: str = "check"
    current_version: str | None = None
    config_version: str = "1.0.0"
    install_root: str = ".tenko/upgrades"
    config_path: str = "config/tenko.toml"
    data_dir: str = "data"
    health_command: tuple[str, ...] = ()
    launch_command: tuple[str, ...] = ()
    health_timeout: int = 30
    check_interval_hours: int = 24
    superuser_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.source:
            raise ValueError("upgrade source 不能为空")
        if self.channel.lower() not in {
            "stable",
            "release",
            "prerelease",
            "pre-release",
            "preview",
            "beta",
        }:
            raise ValueError("upgrade channel 必须是 stable 或 prerelease")
        if self.policy.lower() not in {
            "check",
            "check-only",
            "manual",
            "download",
            "auto-download",
            "install",
            "auto-install",
        }:
            raise ValueError("upgrade policy 必须是 check、download 或 install")
        if not self.repository:
            raise ValueError("upgrade repository 不能为空")
        if not self.tag_prefix:
            raise ValueError("upgrade tag_prefix 不能为空")
        if not self.config_version:
            raise ValueError("upgrade config_version 不能为空")
        if not self.install_root or not self.config_path or not self.data_dir:
            raise ValueError("upgrade 路径配置不能为空")
        if self.health_timeout <= 0:
            raise ValueError("upgrade health_timeout 必须大于 0")
        if self.check_interval_hours <= 0:
            raise ValueError("upgrade check_interval_hours 必须大于 0")

        for name in ("github_token", "asset_name", "current_version"):
            value = getattr(self, name)
            if value == "":
                object.__setattr__(self, name, None)

        object.__setattr__(self, "health_command", tuple(self.health_command))
        object.__setattr__(self, "launch_command", tuple(self.launch_command))
        object.__setattr__(self, "superuser_ids", tuple(self.superuser_ids))

    @classmethod
    def from_mapping(
        cls,
        section: Mapping[str, Any],
        *,
        inherited_superuser_ids: tuple[str, ...] = (),
    ) -> UpgradeConfig:
        defaults = cls()
        return cls(
            enabled=_boolean(section, "enabled", defaults.enabled),
            source=_string(section, "source", defaults.source),
            repository=_string(section, "repository", defaults.repository),
            github_repository=_string(
                section, "github_repository", defaults.github_repository
            ),
            manifest_url=_string(section, "manifest_url", defaults.manifest_url),
            github_token=_optional_string(
                section, "github_token", defaults.github_token
            ),
            asset_name=_optional_string(section, "asset_name", defaults.asset_name),
            tag_prefix=_string(section, "tag_prefix", defaults.tag_prefix),
            channel=_string(section, "channel", defaults.channel),
            policy=_string(section, "policy", defaults.policy),
            current_version=_optional_string(
                section, "current_version", defaults.current_version
            ),
            config_version=_string(section, "config_version", defaults.config_version),
            install_root=_string(section, "install_root", defaults.install_root),
            config_path=_string(section, "config_path", defaults.config_path),
            data_dir=_string(section, "data_dir", defaults.data_dir),
            health_command=_string_sequence(
                section, "health_command", defaults.health_command
            ),
            launch_command=_string_sequence(
                section, "launch_command", defaults.launch_command
            ),
            health_timeout=_integer(section, "health_timeout", defaults.health_timeout),
            check_interval_hours=_integer(
                section, "check_interval_hours", defaults.check_interval_hours
            ),
            superuser_ids=_identifier_sequence(
                section, "superuser_ids", inherited_superuser_ids
            ),
        )


@dataclass(frozen=True, slots=True)
class AccountsConfig:
    """账号路由状态持久化配置。"""

    state_path: str = ".tenko/accounts.json"

    def __post_init__(self) -> None:
        if not self.state_path:
            raise ValueError("accounts state_path 不能为空")

    @classmethod
    def from_mapping(cls, section: Mapping[str, Any]) -> AccountsConfig:
        defaults = cls()
        return cls(state_path=_string(section, "state_path", defaults.state_path))


@dataclass(frozen=True, slots=True)
class FeaturesConfig:
    """群级插件开关配置。"""

    state_path: str = ".tenko/features.json"
    default_enabled: bool = True

    def __post_init__(self) -> None:
        if not self.state_path:
            raise ValueError("features state_path 不能为空")

    @classmethod
    def from_mapping(cls, section: Mapping[str, Any]) -> FeaturesConfig:
        defaults = cls()
        return cls(
            state_path=_string(section, "state_path", defaults.state_path),
            default_enabled=_boolean(
                section, "default_enabled", defaults.default_enabled
            ),
        )


@dataclass(frozen=True, slots=True)
class RateLimitConfig:
    """统一命令限流配置。"""

    enabled: bool = True
    state_path: str = ".tenko/ratelimit.json"
    window_seconds: float = 15.0
    max_weight: int = 24
    default_weight: int = 1
    cooldown_seconds: float = 5.0
    blacklist_seconds: float = 300.0
    override_permission: int = 32

    def __post_init__(self) -> None:
        if not self.state_path:
            raise ValueError("ratelimit state_path 不能为空")
        if self.window_seconds <= 0:
            raise ValueError("ratelimit window_seconds 必须大于 0")
        if self.max_weight <= 0 or self.default_weight <= 0:
            raise ValueError("ratelimit weight 必须大于 0")
        if self.cooldown_seconds < 0 or self.blacklist_seconds < 0:
            raise ValueError("ratelimit 冷却时间不能为负数")
        if self.override_permission < 0:
            raise ValueError("ratelimit override_permission 不能为负数")

    @classmethod
    def from_mapping(cls, section: Mapping[str, Any]) -> RateLimitConfig:
        defaults = cls()
        return cls(
            enabled=_boolean(section, "enabled", defaults.enabled),
            state_path=_string(section, "state_path", defaults.state_path),
            window_seconds=_number(section, "window_seconds", defaults.window_seconds),
            max_weight=_integer(section, "max_weight", defaults.max_weight),
            default_weight=_integer(section, "default_weight", defaults.default_weight),
            cooldown_seconds=_number(
                section, "cooldown_seconds", defaults.cooldown_seconds
            ),
            blacklist_seconds=_number(
                section, "blacklist_seconds", defaults.blacklist_seconds
            ),
            override_permission=_integer(
                section, "override_permission", defaults.override_permission
            ),
        )


@dataclass(frozen=True, slots=True)
class ExceptionConfig:
    """异常取证的环形消息缓冲和本地落盘目录。"""

    message_buffer_size: int = 10
    evidence_dir: str = ".tenko/exceptions"

    def __post_init__(self) -> None:
        if type(self.message_buffer_size) is not int or self.message_buffer_size <= 0:
            raise ValueError("exception message_buffer_size 必须是正整数")
        if not self.evidence_dir:
            raise ValueError("exception evidence_dir 不能为空")

    @classmethod
    def from_mapping(cls, section: Mapping[str, Any]) -> ExceptionConfig:
        defaults = cls()
        return cls(
            message_buffer_size=_integer(
                section, "message_buffer_size", defaults.message_buffer_size
            ),
            evidence_dir=_string(section, "evidence_dir", defaults.evidence_dir),
        )


# 允许调用方使用更自然的单数名称，同时配置字段保持 `[features]` / `[ratelimit]`。
FeatureConfig = FeaturesConfig
RatelimitConfig = RateLimitConfig


@dataclass(frozen=True, slots=True)
class TenkoConfig:
    onebot: OneBotConfig = OneBotConfig()
    runtime: RuntimeConfig = RuntimeConfig()
    entari: EntariConfig = EntariConfig()
    upgrade: UpgradeConfig = UpgradeConfig()
    debug: DebugConfig = DebugConfig()
    accounts: AccountsConfig = AccountsConfig()
    features: FeaturesConfig = FeaturesConfig()
    ratelimit: RateLimitConfig = RateLimitConfig()
    exception: ExceptionConfig = ExceptionConfig()

    def __post_init__(self) -> None:
        # 代码构造方式的旧兼容：直接传 RuntimeConfig(superusers=...) 时也
        # 使用同一份有效名单；从 TOML 读取时的 canonical `[entari]` 优先级
        # 已在 from_mapping 中确定。
        if not self.entari.superusers and self.runtime.superusers:
            object.__setattr__(self, "entari", EntariConfig(self.runtime.superusers))

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> TenkoConfig:
        runtime_section = _section(data, "runtime")
        entari = EntariConfig.from_mapping(
            _section(data, "entari"),
            legacy_runtime_section=runtime_section,
        )
        superuser_ids = _flatten_identifiers(entari.superusers)
        return cls(
            onebot=OneBotConfig.from_mapping(_section(data, "onebot")),
            runtime=RuntimeConfig.from_mapping(
                runtime_section, superusers=entari.superusers
            ),
            entari=entari,
            debug=DebugConfig.from_mapping(
                _section(data, "debug"), inherited_masters=superuser_ids
            ),
            upgrade=UpgradeConfig.from_mapping(
                _section(data, "upgrade"), inherited_superuser_ids=superuser_ids
            ),
            accounts=AccountsConfig.from_mapping(_section(data, "accounts")),
            features=FeaturesConfig.from_mapping(_section(data, "features")),
            ratelimit=RateLimitConfig.from_mapping(_section(data, "ratelimit")),
            exception=ExceptionConfig.from_mapping(_section(data, "exception")),
        )

    @classmethod
    def load(cls, path: Path) -> TenkoConfig:
        if not path.exists():
            return cls()
        with path.open("rb") as file:
            data = tomllib.load(file)
        return cls.from_mapping(data)
