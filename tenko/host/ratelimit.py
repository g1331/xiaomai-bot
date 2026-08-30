from __future__ import annotations

import json
import os
import tempfile
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path


_STATE_VERSION = 1


def _key(value: object, label: str) -> str:
    if value is None:
        raise ValueError(f"{label}不能为空")
    normalized = str(value)
    if not normalized:
        raise ValueError(f"{label}不能为空")
    return normalized


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    """一次限流判定结果。"""

    allowed: bool
    message: str | None = None
    retry_after: float = 0.0
    current_weight: int = 0


class RateLimitService:
    """按用户×群维护滚动窗口、冷却和临时黑名单。

    这是命令策略使用的纯宿主服务：不负责识别命令归属、不执行权限检查，
    也不依赖 SQLAlchemy。状态采用 JSON 文件保存，``clock`` 注入后可对窗口
    到期和重启恢复做确定性测试。
    """

    def __init__(
        self,
        state_path: str | Path | None = None,
        *,
        enabled: bool = True,
        window_seconds: float = 15.0,
        max_weight: int = 24,
        default_weight: int = 1,
        cooldown_seconds: float = 5.0,
        blacklist_seconds: float = 300.0,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if type(enabled) is not bool:
            raise TypeError("enabled 必须是布尔值")
        self._validate_positive(window_seconds, "window_seconds", allow_zero=False)
        self._validate_positive(cooldown_seconds, "cooldown_seconds", allow_zero=True)
        self._validate_positive(blacklist_seconds, "blacklist_seconds", allow_zero=True)
        if type(max_weight) is not int or max_weight <= 0:
            raise ValueError("max_weight 必须是正整数")
        if type(default_weight) is not int or default_weight <= 0:
            raise ValueError("default_weight 必须是正整数")
        self.state_path: Path | None = None
        self.enabled = enabled
        self.window_seconds = float(window_seconds)
        self.max_weight = max_weight
        self.default_weight = default_weight
        self.cooldown_seconds = float(cooldown_seconds)
        self.blacklist_seconds = float(blacklist_seconds)
        self.clock = clock
        self._events: dict[str, list[tuple[float, int]]] = {}
        self._cooldowns: dict[str, float] = {}
        self._blacklist: dict[str, float] = {}
        if state_path is not None:
            self.configure(state_path)

    @staticmethod
    def _validate_positive(value: object, label: str, *, allow_zero: bool) -> None:
        if not isinstance(value, int | float) or isinstance(value, bool):
            raise TypeError(f"{label} 必须是数字")
        if value < 0 or (value == 0 and not allow_zero):
            raise ValueError(f"{label} 必须是{'非负' if allow_zero else '正'}数")

    def configure(self, state_path: str | Path | None) -> None:
        self.state_path = None if state_path is None else Path(state_path)
        self._events = {}
        self._cooldowns = {}
        self._blacklist = {}
        self._load()

    @staticmethod
    def _decode_events(value: object, key: str) -> list[tuple[float, int]]:
        if not isinstance(value, list):
            raise ValueError(f"限流状态 {key!r} 的 events 必须是 JSON array")
        events: list[tuple[float, int]] = []
        for item in value:
            if not isinstance(item, Mapping):
                raise ValueError(f"限流状态 {key!r} 的事件必须是 JSON object")
            timestamp = item.get("at")
            weight = item.get("weight")
            if (
                not isinstance(timestamp, int | float)
                or isinstance(timestamp, bool)
                or type(weight) is not int
                or weight <= 0
            ):
                raise ValueError(f"限流状态 {key!r} 的事件字段非法")
            events.append((float(timestamp), weight))
        return events

    def _load(self) -> None:
        if self.state_path is None or not self.state_path.is_file():
            return
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"限流状态不是有效 JSON: {self.state_path}") from exc
        if not isinstance(data, Mapping):
            raise ValueError(f"限流状态必须是 JSON object: {self.state_path}")
        if data.get("version", _STATE_VERSION) != _STATE_VERSION:
            raise ValueError(f"不支持的限流状态版本: {data.get('version')}")
        events = data.get("events", {})
        cooldowns = data.get("cooldowns", {})
        blacklist = data.get("blacklist", {})
        if not isinstance(events, Mapping) or not isinstance(cooldowns, Mapping):
            raise ValueError(
                f"限流状态的 events/cooldowns 必须是 JSON object: {self.state_path}"
            )
        if not isinstance(blacklist, Mapping):
            raise ValueError(
                f"限流状态的 blacklist 必须是 JSON object: {self.state_path}"
            )
        self._events = {
            str(key): self._decode_events(value, str(key))
            for key, value in events.items()
        }
        self._cooldowns = self._decode_expiries(cooldowns, "cooldowns")
        self._blacklist = self._decode_expiries(blacklist, "blacklist")

    @staticmethod
    def _decode_expiries(
        value: Mapping[object, object], field: str
    ) -> dict[str, float]:
        decoded: dict[str, float] = {}
        for key, expiry in value.items():
            if not isinstance(expiry, int | float) or isinstance(expiry, bool):
                raise ValueError(f"限流状态的 {field} 到期时间必须是数字")
            decoded[str(key)] = float(expiry)
        return decoded

    def _persist(self) -> None:
        if self.state_path is None:
            return
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "version": _STATE_VERSION,
            "events": {
                key: [{"at": at, "weight": weight} for at, weight in events]
                for key, events in self._events.items()
            },
            "cooldowns": self._cooldowns,
            "blacklist": self._blacklist,
        }
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

    @staticmethod
    def _state_key(group_id: str | int, user_id: str | int) -> str:
        return f"{_key(group_id, '群 ID')}:{_key(user_id, '用户 ID')}"

    def _prune(self, key: str, now: float) -> bool:
        changed = False
        events = self._events.get(key, [])
        retained = [
            (timestamp, weight)
            for timestamp, weight in events
            if timestamp > now - self.window_seconds
        ]
        if retained:
            if retained != events:
                self._events[key] = retained
                changed = True
        elif key in self._events:
            del self._events[key]
            changed = True
        for mapping in (self._cooldowns, self._blacklist):
            expiry = mapping.get(key)
            if expiry is not None and expiry <= now:
                del mapping[key]
                changed = True
        return changed

    def is_blacklisted(
        self, group_id: str | int, user_id: str | int, *, now: float | None = None
    ) -> bool:
        key = self._state_key(group_id, user_id)
        current = self.clock() if now is None else float(now)
        changed = self._prune(key, current)
        if changed:
            self._persist()
        return key in self._blacklist and self._blacklist[key] > current

    def clear(self, group_id: str | int, user_id: str | int) -> None:
        """清除用户在群内的窗口、冷却和黑名单状态。"""

        key = self._state_key(group_id, user_id)
        self._events.pop(key, None)
        self._cooldowns.pop(key, None)
        self._blacklist.pop(key, None)
        self._persist()

    reset = clear

    def check(
        self,
        group_id: str | int,
        user_id: str | int,
        *,
        command: str | None = None,
        weight: int | None = None,
        override: bool = False,
        now: float | None = None,
    ) -> RateLimitDecision:
        """检查并记录一次命令调用。``override`` 用于管理员豁免。"""

        del command
        if type(override) is not bool:
            raise TypeError("override 必须是布尔值")
        actual_weight = self.default_weight if weight is None else weight
        if type(actual_weight) is not int or actual_weight <= 0:
            raise ValueError("weight 必须是正整数")
        if not self.enabled or override:
            return RateLimitDecision(True)

        key = self._state_key(group_id, user_id)
        current = self.clock() if now is None else float(now)
        changed = self._prune(key, current)
        blacklist_until = self._blacklist.get(key)
        if blacklist_until is not None and blacklist_until > current:
            if changed:
                self._persist()
            return RateLimitDecision(
                False,
                "检测到大量请求,加入黑名单5分钟!",
                blacklist_until - current,
                sum(item[1] for item in self._events.get(key, [])),
            )
        cooldown_until = self._cooldowns.get(key)
        if cooldown_until is not None and cooldown_until > current:
            if changed:
                self._persist()
            return RateLimitDecision(
                False,
                "超过频率调用限制!请稍后再试~",
                cooldown_until - current,
                sum(item[1] for item in self._events.get(key, [])),
            )

        current_weight = sum(item[1] for item in self._events.get(key, []))
        if current_weight + actual_weight >= self.max_weight:
            self._events.setdefault(key, []).append((current, actual_weight))
            if self.cooldown_seconds > 0:
                self._cooldowns[key] = current + self.cooldown_seconds
            if self.blacklist_seconds > 0:
                self._blacklist[key] = current + self.blacklist_seconds
            self._persist()
            retry_after = max(
                self._cooldowns.get(key, current) - current,
                self._blacklist.get(key, current) - current,
            )
            return RateLimitDecision(
                False,
                (
                    f"超过频率调用限制!({current_weight + actual_weight}/"
                    f"{self.max_weight})\n"
                    "休息一会儿吧~继续高频访问会被加入临时全局黑名单哦~"
                ),
                retry_after,
                current_weight + actual_weight,
            )

        self._events.setdefault(key, []).append((current, actual_weight))
        self._persist()
        return RateLimitDecision(True, current_weight=current_weight + actual_weight)


rate_limit_service = RateLimitService()


def configure_rate_limiter(
    state_path: str | Path | None,
    *,
    enabled: bool = True,
    window_seconds: float = 15.0,
    max_weight: int = 24,
    default_weight: int = 1,
    cooldown_seconds: float = 5.0,
    blacklist_seconds: float = 300.0,
) -> RateLimitService:
    """配置全局限流服务并返回同一实例。"""

    rate_limit_service.enabled = enabled
    rate_limit_service.window_seconds = float(window_seconds)
    rate_limit_service.max_weight = max_weight
    rate_limit_service.default_weight = default_weight
    rate_limit_service.cooldown_seconds = float(cooldown_seconds)
    rate_limit_service.blacklist_seconds = float(blacklist_seconds)
    rate_limit_service.configure(state_path)
    return rate_limit_service


__all__ = [
    "RateLimitDecision",
    "RateLimitService",
    "configure_rate_limiter",
    "rate_limit_service",
]
