from __future__ import annotations

import bisect
import importlib.metadata
import inspect
import json
import math
import os
import tempfile
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from loguru import logger

from tenko.host.actions import action_service as default_action_service
from tenko.host.features import feature_service as default_feature_service
from tenko.host.perm import PermissionChecker
from tenko.plugins._common import master_id_for_account

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 回退路径
    import tomli as tomllib


STARTUP_NOTIFY_FEATURE = "startup_notify"
_HISTORY_VERSION = 1
_DEFAULT_HISTORY_PATH = Path(".tenko/startup_times.json")
_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _duration(value: object, label: str = "启动耗时") -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{label}必须是数字")
    normalized = float(value)
    if not math.isfinite(normalized) or normalized < 0:
        raise ValueError(f"{label}必须是有限的非负数字")
    return normalized


def _normalize_id(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


class StartupHistory:
    """读写版本化的启动耗时历史。"""

    def __init__(self, path: str | Path = _DEFAULT_HISTORY_PATH) -> None:
        self.path = Path(path)

    def load(self) -> tuple[float, ...]:
        if not self.path.is_file():
            return ()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"启动耗时历史不是有效 JSON: {self.path}") from exc
        if not isinstance(data, dict):
            raise ValueError(f"启动耗时历史必须是 JSON object: {self.path}")
        version = data.get("version", _HISTORY_VERSION)
        if type(version) is not int or version != _HISTORY_VERSION:
            raise ValueError(f"不支持的启动耗时历史版本: {version}")
        durations = data.get("durations", [])
        if not isinstance(durations, list):
            raise ValueError(f"启动耗时历史的 durations 必须是 JSON array: {self.path}")
        return tuple(_duration(value, "历史启动耗时") for value in durations)

    def record(
        self,
        duration: float,
        *,
        previous: Sequence[float] | None = None,
    ) -> tuple[float, ...]:
        current = _duration(duration)
        samples = (
            tuple(_duration(value, "历史启动耗时") for value in previous)
            if previous is not None
            else self.load()
        )
        updated = (*samples, current)
        self._persist(updated)
        return updated

    def _persist(self, durations: Sequence[float]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                json.dump(
                    {
                        "version": _HISTORY_VERSION,
                        "durations": list(durations),
                    },
                    temporary,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                temporary.write("\n")
                temporary.flush()
                os.fsync(temporary.fileno())
                temporary_path = temporary.name
            os.replace(temporary_path, self.path)
        finally:
            if temporary_path is not None and os.path.exists(temporary_path):
                os.unlink(temporary_path)


def calculate_beaten_percent(
    duration: float,
    history: Sequence[float],
) -> float | None:
    """按历史耗时计算当前启动速度超过的比例。

    历史耗时按从快到慢排序，使用相邻样本之间的线性插值；因此耗时越短，
    返回值越高。最短边界为 100%，最长边界为 0%。
    """

    current = _duration(duration)
    samples = tuple(sorted(_duration(value, "历史启动耗时") for value in history))
    if not samples:
        return None
    if len(samples) == 1:
        if current < samples[0]:
            return 100.0
        if current > samples[0]:
            return 0.0
        return 50.0
    if current <= samples[0]:
        return 100.0
    if current >= samples[-1]:
        return 0.0

    upper_index = bisect.bisect_right(samples, current)
    lower_index = upper_index - 1
    lower = samples[lower_index]
    upper = samples[upper_index]
    fraction = 0.0 if lower == upper else (current - lower) / (upper - lower)
    position = lower_index + fraction
    beaten = (len(samples) - 1 - position) / (len(samples) - 1) * 100
    return max(0.0, min(100.0, beaten))


def calculate_percentile(duration: float, history: Sequence[float]) -> float | None:
    """返回与 ``calculate_beaten_percent`` 相反方向的慢速百分位。"""

    beaten = calculate_beaten_percent(duration, history)
    return None if beaten is None else 100.0 - beaten


def _project_version() -> str:
    try:
        return importlib.metadata.version("tenko")
    except importlib.metadata.PackageNotFoundError:
        pass

    try:
        with (_PROJECT_ROOT / "pyproject.toml").open("rb") as project_file:
            project_data = tomllib.load(project_file)
        version = project_data["project"]["version"]
    except (
        OSError,
        KeyError,
        TypeError,
        tomllib.TOMLDecodeError,
    ):
        return "0.0.0"
    return str(version)


def _format_percent(value: float) -> str:
    return f"{value:.1f}".rstrip("0").rstrip(".")


def build_startup_notice(
    version: str,
    duration: float,
    history: Sequence[float],
) -> str:
    """组装启动通知文本。"""

    normalized_duration = _duration(duration)
    version_text = str(version).strip() or "0.0.0"
    if not version_text.lower().startswith("v"):
        version_text = f"v{version_text}"
    beaten = calculate_beaten_percent(normalized_duration, history)
    lines = [
        "🎉 Tenko 已启动！",
        f"版本：{version_text}",
        f"启动耗时：{normalized_duration:.2f} 秒",
    ]
    if beaten is None:
        lines.append("首次启动，暂无对比数据")
    else:
        lines.append(f"您的 bot 启动耗时已经打败了 {_format_percent(beaten)}% 的 bot！")
    return "\n".join(lines)


class StartupNotifier:
    """在框架 Ready 且至少一个账号在线后发送一次启动通知。"""

    def __init__(
        self,
        *,
        notify_group: str | int | None = None,
        history: StartupHistory | None = None,
        history_path: str | Path | None = None,
        action_service: Any | None = None,
        feature_service: Any | None = None,
        permission_checker: Any | None = None,
        started_at: float | None = None,
        clock: Callable[[], float] | None = None,
        version_provider: Callable[[], str] | None = None,
    ) -> None:
        self.notify_group_id = _normalize_id(notify_group)
        self.history = history or StartupHistory(history_path or _DEFAULT_HISTORY_PATH)
        self.action_service = (
            default_action_service if action_service is None else action_service
        )
        self.feature_service = (
            default_feature_service if feature_service is None else feature_service
        )
        self.permission_checker = (
            PermissionChecker() if permission_checker is None else permission_checker
        )
        self.started_at = (
            time.perf_counter()
            if started_at is None
            else _duration(started_at, "启动起点")
        )
        self.clock = clock or time.perf_counter
        self.version_provider = version_provider or _project_version
        self._online_account: object | None = None
        self._framework_ready = False
        self._attempted = False
        self._sending = False

    def configure_notify_group(self, group_id: str | int | None) -> None:
        """设置通知群；空值表示回退到 Master 私聊。"""

        self.notify_group_id = _normalize_id(group_id)

    async def mark_account_online(self, account: object) -> None:
        self._online_account = account
        await self._maybe_notify()

    async def mark_framework_ready(self) -> None:
        self._framework_ready = True
        await self._maybe_notify()

    async def _maybe_notify(self) -> None:
        if (
            not self._framework_ready
            or self._online_account is None
            or self._attempted
            or self._sending
        ):
            return
        self._sending = True
        self._attempted = True
        try:
            if not self.feature_service.is_enabled(STARTUP_NOTIFY_FEATURE):
                logger.info("Tenko startup notification is disabled")
                return

            duration = max(float(self.clock()) - self.started_at, 0.0)
            try:
                history = self.history.load()
            except Exception as error:
                history = ()
                logger.warning(
                    "Could not load startup duration history {}: {}",
                    self.history.path,
                    error,
                )
            notice = build_startup_notice(
                self.version_provider(),
                duration,
                history,
            )
            try:
                self.history.record(duration, previous=history)
            except Exception:
                logger.exception(
                    "Could not persist startup duration history {}",
                    self.history.path,
                )
            await self._send(notice)
        except Exception:
            # 通知属于启动后的附加动作；任何格式、配置或动作异常都不能让
            # Entari/Launart 的主生命周期失败。
            logger.exception("Tenko startup notification failed")
        finally:
            self._sending = False

    async def _send(self, notice: str) -> None:
        account = self._online_account
        if account is None:  # pragma: no cover - _maybe_notify 已建立此条件
            return
        if self.notify_group_id is not None:
            sender = getattr(self.action_service, "send_group_message", None)
            if not callable(sender):
                logger.warning("ActionService has no group notification API")
                return
            result = sender(
                account,
                self.notify_group_id,
                notice,
                context=None,
                permission_checker=self.permission_checker,
                system=True,
            )
            if inspect.isawaitable(result):
                await result
            logger.info(
                "Tenko startup notification sent to group {}",
                self.notify_group_id,
            )
            return

        master_id = master_id_for_account(account, self.permission_checker)
        if master_id is None:
            logger.warning("Tenko startup notification has no configured Master")
            return
        sender = getattr(self.action_service, "send_private_message", None)
        if not callable(sender):
            logger.warning("ActionService has no private notification API")
            return
        result = sender(account, master_id, notice)
        if inspect.isawaitable(result):
            await result
        logger.info(
            "Tenko startup notification sent to Master {}",
            master_id,
        )


__all__ = [
    "STARTUP_NOTIFY_FEATURE",
    "StartupHistory",
    "StartupNotifier",
    "build_startup_notice",
    "calculate_beaten_percent",
    "calculate_percentile",
]
