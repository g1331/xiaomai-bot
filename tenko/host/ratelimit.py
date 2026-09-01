from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..db.repositories import RateLimitRepository


_DATABASE_UNAVAILABLE_MESSAGE = "限流状态暂不可用，请稍后再试"


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
    状态通过可选 repository 恢复和保存；``clock`` 注入后可对窗口到期和
    重启恢复做确定性测试。
    """

    def __init__(
        self,
        repository: RateLimitRepository | None = None,
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
        self._repository = repository
        self.enabled = enabled
        self.window_seconds = float(window_seconds)
        self.max_weight = max_weight
        self.default_weight = default_weight
        self.cooldown_seconds = float(cooldown_seconds)
        self.blacklist_seconds = float(blacklist_seconds)
        self.clock = clock
        self._events: dict[tuple[str, str], list[tuple[float, int]]] = {}
        self._cooldowns: dict[tuple[str, str], float] = {}
        self._blacklist: dict[tuple[str, str], float] = {}
        self._ready = repository is None

    @staticmethod
    def _validate_positive(value: object, label: str, *, allow_zero: bool) -> None:
        if not isinstance(value, int | float) or isinstance(value, bool):
            raise TypeError(f"{label} 必须是数字")
        if value < 0 or (value == 0 and not allow_zero):
            raise ValueError(f"{label} 必须是{'非负' if allow_zero else '正'}数")

    def configure(self, repository: RateLimitRepository | None = None) -> None:
        """配置 repository；实际数据库读取由异步初始化完成。"""

        self._repository = repository
        self._events = {}
        self._cooldowns = {}
        self._blacklist = {}

        self._ready = repository is None

    @property
    def ready(self) -> bool:
        """返回限流数据库快照是否可安全使用。"""

        return self._ready

    def mark_unavailable(self) -> None:
        """将数据库失败转换为拦截所有受限命令的状态。"""

        self._ready = False

    async def initialize(self, repository: RateLimitRepository | None = None) -> None:
        """从 repository 恢复滚动窗口和到期状态。"""

        if repository is not None:
            self._repository = repository
        if self._repository is None:
            self._events = {}
            self._cooldowns = {}
            self._blacklist = {}
            self._ready = True
            return

        try:
            snapshot = await self._repository.load_state()
        except Exception:
            self.mark_unavailable()
            raise

        events: dict[tuple[str, str], list[tuple[float, int]]] = {}
        for row in snapshot.events:
            events.setdefault((row.group_id, row.user_id), []).append(
                (row.occurred_at, row.weight)
            )
        self._events = events
        self._cooldowns = {}
        self._blacklist = {}
        for row in snapshot.subjects:
            key = (row.group_id, row.user_id)
            if row.cooldown_until is not None:
                self._cooldowns[key] = row.cooldown_until
            if row.blacklist_until is not None:
                self._blacklist[key] = row.blacklist_until
        self._ready = True

    @staticmethod
    def _state_key(group_id: str | int, user_id: str | int) -> tuple[str, str]:
        return _key(group_id, "群 ID"), _key(user_id, "用户 ID")

    def _state_records(self) -> tuple[tuple[object, ...], tuple[object, ...]]:
        from ..db.repositories import RateLimitEventRecord, RateLimitSubjectRecord

        events = tuple(
            RateLimitEventRecord(
                group_id=group_id,
                user_id=user_id,
                occurred_at=occurred_at,
                weight=weight,
            )
            for (group_id, user_id), values in self._events.items()
            for occurred_at, weight in values
        )
        subjects = tuple(
            RateLimitSubjectRecord(
                group_id=group_id,
                user_id=user_id,
                cooldown_until=self._cooldowns.get((group_id, user_id)),
                blacklist_until=self._blacklist.get((group_id, user_id)),
            )
            for group_id, user_id in sorted(set(self._cooldowns) | set(self._blacklist))
        )
        return events, subjects

    async def persist_state(self) -> None:
        """将当前限流快照原子替换到状态表。"""

        if self._repository is None:
            if not self._ready:
                from ..db.errors import DatabaseUnavailableError

                raise DatabaseUnavailableError(_DATABASE_UNAVAILABLE_MESSAGE)
            return
        if not self._ready:
            from ..db.errors import DatabaseUnavailableError

            raise DatabaseUnavailableError(_DATABASE_UNAVAILABLE_MESSAGE)
        events, subjects = self._state_records()
        try:
            await self._repository.replace_state(events, subjects)
        except Exception:
            self.mark_unavailable()
            raise

    async def check_and_persist(self, *args, **kwargs) -> RateLimitDecision:
        """完成一次判定并确保限流状态写入数据库。"""

        if self._repository is not None and not self._ready:
            return RateLimitDecision(False, _DATABASE_UNAVAILABLE_MESSAGE)
        decision = self.check(*args, **kwargs)
        if self._repository is None:
            return decision
        try:
            await self.persist_state()
        except Exception:
            return RateLimitDecision(False, _DATABASE_UNAVAILABLE_MESSAGE)
        return decision

    def _prune(self, key: tuple[str, str], now: float) -> bool:
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
        if not self._ready:
            return True
        current = self.clock() if now is None else float(now)
        self._prune(key, current)
        return key in self._blacklist and self._blacklist[key] > current

    def clear(self, group_id: str | int, user_id: str | int) -> None:
        """清除用户在群内的窗口、冷却和黑名单状态。"""

        key = self._state_key(group_id, user_id)
        self._events.pop(key, None)
        self._cooldowns.pop(key, None)
        self._blacklist.pop(key, None)

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
        if not self._ready:
            return RateLimitDecision(False, _DATABASE_UNAVAILABLE_MESSAGE)
        if not self.enabled or override:
            return RateLimitDecision(True)

        key = self._state_key(group_id, user_id)
        current = self.clock() if now is None else float(now)
        self._prune(key, current)
        blacklist_until = self._blacklist.get(key)
        if blacklist_until is not None and blacklist_until > current:
            return RateLimitDecision(
                False,
                "检测到大量请求,加入黑名单5分钟!",
                blacklist_until - current,
                sum(item[1] for item in self._events.get(key, [])),
            )
        cooldown_until = self._cooldowns.get(key)
        if cooldown_until is not None and cooldown_until > current:
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
        return RateLimitDecision(True, current_weight=current_weight + actual_weight)


rate_limit_service = RateLimitService()


def configure_rate_limiter(
    repository: RateLimitRepository | None = None,
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
    rate_limit_service.configure(repository)
    return rate_limit_service


__all__ = [
    "RateLimitDecision",
    "RateLimitService",
    "configure_rate_limiter",
    "rate_limit_service",
]
