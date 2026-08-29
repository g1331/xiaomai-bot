from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
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


def _boolean(section: Mapping[str, Any], key: str, default: bool) -> bool:
    value = section.get(key, default)
    if type(value) is not bool:
        raise ValueError(f"配置项 {key!r} 必须是布尔值")
    return value


def _path(*parts: str) -> str:
    clean_parts = [part.strip("/") for part in parts if part.strip("/")]
    return "/" + "/".join(clean_parts)


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
        )


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    """运行时行为配置。"""

    send_replies: bool = False
    reply_text: str = "Tenko 已收到消息。"
    log_level: str = "INFO"
    command_prefix: str = "/"

    def __post_init__(self) -> None:
        if not self.reply_text:
            raise ValueError("reply_text 不能为空")
        if not self.log_level:
            raise ValueError("log_level 不能为空")
        if not self.command_prefix:
            raise ValueError("command_prefix 不能为空")

    @classmethod
    def from_mapping(cls, section: Mapping[str, Any]) -> RuntimeConfig:
        defaults = cls()
        return cls(
            send_replies=_boolean(section, "send_replies", defaults.send_replies),
            reply_text=_string(section, "reply_text", defaults.reply_text),
            log_level=_string(section, "log_level", defaults.log_level),
            command_prefix=_string(section, "command_prefix", defaults.command_prefix),
        )


@dataclass(frozen=True, slots=True)
class TenkoConfig:
    onebot: OneBotConfig = OneBotConfig()
    runtime: RuntimeConfig = RuntimeConfig()

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> TenkoConfig:
        return cls(
            onebot=OneBotConfig.from_mapping(_section(data, "onebot")),
            runtime=RuntimeConfig.from_mapping(_section(data, "runtime")),
        )

    @classmethod
    def load(cls, path: Path) -> TenkoConfig:
        if not path.exists():
            return cls()
        with path.open("rb") as file:
            data = tomllib.load(file)
        return cls.from_mapping(data)
