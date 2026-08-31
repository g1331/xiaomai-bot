"""可验证、可回滚的 Tenko 宿主升级器。

这个模块只负责宿主升级的控制平面：发现版本、获取并校验制品、准备独立
目录、写入原子状态指针以及生成外部重启接管记录。它不会在当前 Python
进程中导入新目录或替换 ``sys.modules``；正在运行的宿主必须由外部启动器
调用 :meth:`UpgradeManager.apply_handoff` 完成重启后的切换。

插件分发不是本模块的职责。需要支持新的制品源时，实现 ``VersionSource``
协议并注入 ``UpgradeManager`` 即可，不需要改动升级状态机。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import uuid
import zipfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from functools import total_ordering
from pathlib import Path, PurePosixPath
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urljoin, urlsplit
from urllib.request import Request, urlopen

from loguru import logger

from .perm import Permission, PermissionChecker, PermissionRegistry

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - 仅在 Python 3.10 中执行
    import tomli as tomllib


__all__ = [
    "ArtifactAcquisitionError",
    "ArtifactVerificationError",
    "AuditLogger",
    "CheckResult",
    "CompatibilityResult",
    "ConfigurationCompatibilityError",
    "ConfigCompatibilityChecker",
    "DefaultHealthChecker",
    "GitTagSource",
    "GitHubReleaseSource",
    "HealthCheckFailed",
    "HealthCheckResult",
    "HandoffResult",
    "InstallResult",
    "InvalidVersionError",
    "NoRollbackAvailable",
    "NoUpdateAvailable",
    "PrepareResult",
    "Release",
    "ReleasePointer",
    "RollbackResult",
    "SubprocessLauncher",
    "UpdateChannel",
    "UpdatePolicy",
    "UpdateRelation",
    "UpdateSourceError",
    "UpdaterError",
    "UpgradeConfigError",
    "UpgradeLayout",
    "UpgradeManager",
    "UrlManifestSource",
    "Version",
    "VersionSource",
    "compare_versions",
    "configure_updater",
    "get_upgrade_manager",
    "get_upgrade_permission_checker",
    "parse_version",
    "select_release",
]


class UpdaterError(RuntimeError):
    """升级流程的公共错误基类。"""


class InvalidVersionError(UpdaterError, ValueError):
    """版本字符串不符合严格的 SemVer 形状。"""


class UpdateSourceError(UpdaterError):
    """版本源不可用或返回了不符合契约的数据。"""


class ArtifactAcquisitionError(UpdaterError):
    """制品无法获取或无法解包。"""


class ArtifactVerificationError(UpdaterError):
    """制品的强校验失败。"""


class ConfigurationCompatibilityError(UpdaterError):
    """当前用户配置低于新版本声明的最低兼容版本。"""

    def __init__(self, result: CompatibilityResult):
        self.result = result
        super().__init__(result.reason)


class HealthCheckFailed(UpdaterError):
    """制品在切换前或切换后健康检查失败。"""


class UpgradeConfigError(UpdaterError, ValueError):
    """升级器配置无法构造。"""


class NoUpdateAvailable(UpdaterError):
    """当前通道没有高于本地版本的候选版本。"""


class NoRollbackAvailable(UpdaterError):
    """没有可以回滚到的上一版本。"""


class UpdateChannel(str, Enum):
    """版本通道。

    ``prerelease`` 通道同时允许正式版和预发布版；正式版通道显式排除
    SemVer 预发布版本，避免测试版本覆盖生产实例。
    """

    STABLE = "stable"
    PRERELEASE = "prerelease"
    PRE_RELEASE = "prerelease"

    @classmethod
    def parse(cls, value: str | UpdateChannel) -> UpdateChannel:
        if isinstance(value, cls):
            return value
        normalized = value.strip().lower().replace("_", "-")
        if normalized in {"stable", "release"}:
            return cls.STABLE
        if normalized in {"prerelease", "pre-release", "preview", "beta"}:
            return cls.PRERELEASE
        raise UpgradeConfigError("channel 必须是 stable 或 prerelease")


class UpdatePolicy(str, Enum):
    """自动化档位：只检查、自动下载、自动请求外部安装。"""

    CHECK_ONLY = "check"
    AUTO_DOWNLOAD = "download"
    AUTO_INSTALL = "install"
    MANUAL = "check"

    @classmethod
    def parse(cls, value: str | UpdatePolicy) -> UpdatePolicy:
        if isinstance(value, cls):
            return value
        normalized = value.strip().lower().replace("_", "-")
        aliases = {
            "check": cls.CHECK_ONLY,
            "check-only": cls.CHECK_ONLY,
            "manual": cls.CHECK_ONLY,
            "download": cls.AUTO_DOWNLOAD,
            "auto-download": cls.AUTO_DOWNLOAD,
            "install": cls.AUTO_INSTALL,
            "auto-install": cls.AUTO_INSTALL,
        }
        try:
            return aliases[normalized]
        except KeyError as exc:
            raise UpgradeConfigError(
                "policy 必须是 check、download 或 install"
            ) from exc


class UpdateRelation(str, Enum):
    SAME = "same"
    UPDATE_AVAILABLE = "update-available"
    CURRENT_AHEAD = "current-ahead"


_VERSION_PATTERN = re.compile(
    r"^(?:[vV])?"
    r"(?P<major>0|[1-9]\d*)\."
    r"(?P<minor>0|[1-9]\d*)\."
    r"(?P<patch>0|[1-9]\d*)"
    r"(?:-(?P<pre>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+(?P<build>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)
_HEX_SHA_PATTERN = re.compile(r"^[0-9a-fA-F]{40,64}$")
_SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")
_GIT_SCP_LIKE_PATTERN = re.compile(r"^(?:[^/@\s:]+@)?[^/@\s:]+:.+$")
_GIT_REMOTE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_URL_CREDENTIALS_PATTERN = re.compile(
    r"(?P<prefix>[A-Za-z][A-Za-z0-9+.-]*://)[^/@\s]+@"
)
_SCP_CREDENTIALS_PATTERN = re.compile(
    r"(?<![\w/@])[^/@\s:]+(?::[^/@\s]*)?@(?=[^/@\s:]+:)"
)
_FAILED_HANDOFF_RETENTION = 10


def _redact_text(value: object) -> str:
    """隐藏错误文本和地址中的凭据。"""

    text = str(value)
    text = _URL_CREDENTIALS_PATTERN.sub(r"\g<prefix>***@", text)
    return _SCP_CREDENTIALS_PATTERN.sub("***@", text)


@total_ordering
@dataclass(frozen=True, slots=True)
class Version:
    """SemVer 2.0.0 的可比较版本。

    构建元数据参与显示但不参与优先级比较，符合 SemVer 的 precedence 规则。
    """

    major: int
    minor: int
    patch: int
    prerelease: tuple[str, ...] = ()
    build: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("major", "minor", "patch"):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise InvalidVersionError(f"版本 {name} 必须是非负整数")
        for identifiers, name in (
            (self.prerelease, "prerelease"),
            (self.build, "build"),
        ):
            if not isinstance(identifiers, tuple) or any(
                not isinstance(item, str) or not item for item in identifiers
            ):
                raise InvalidVersionError(f"版本 {name} 标识符无效")
        for identifier in self.prerelease:
            if not re.fullmatch(r"[0-9A-Za-z-]+", identifier):
                raise InvalidVersionError("预发布标识符无效")
            if identifier.isdigit() and len(identifier) > 1 and identifier[0] == "0":
                raise InvalidVersionError("预发布数字标识符不能有前导零")
        for identifier in self.build:
            if not re.fullmatch(r"[0-9A-Za-z-]+", identifier):
                raise InvalidVersionError("构建标识符无效")

    @classmethod
    def parse(cls, value: str | Version) -> Version:
        if isinstance(value, cls):
            return value
        if not isinstance(value, str):
            raise InvalidVersionError(f"版本必须是字符串: {value!r}")
        match = _VERSION_PATTERN.fullmatch(value)
        if match is None:
            raise InvalidVersionError(f"非法版本号: {value!r}")
        return cls(
            int(match.group("major")),
            int(match.group("minor")),
            int(match.group("patch")),
            tuple(match.group("pre").split(".")) if match.group("pre") else (),
            tuple(match.group("build").split(".")) if match.group("build") else (),
        )

    @property
    def is_prerelease(self) -> bool:
        return bool(self.prerelease)

    def _precedence_equal(self, other: object) -> bool:
        return isinstance(other, Version) and (
            self.major,
            self.minor,
            self.patch,
            self.prerelease,
        ) == (other.major, other.minor, other.patch, other.prerelease)

    def __eq__(self, other: object) -> bool:
        return self._precedence_equal(other)

    def __hash__(self) -> int:
        return hash((self.major, self.minor, self.patch, self.prerelease))

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, Version):
            return NotImplemented
        left_base = (self.major, self.minor, self.patch)
        right_base = (other.major, other.minor, other.patch)
        if left_base != right_base:
            return left_base < right_base
        if not self.prerelease and not other.prerelease:
            return False
        if not self.prerelease:
            return False
        if not other.prerelease:
            return True
        for left, right in zip(self.prerelease, other.prerelease):
            if left == right:
                continue
            left_numeric = left.isdigit()
            right_numeric = right.isdigit()
            if left_numeric and right_numeric:
                return int(left) < int(right)
            if left_numeric != right_numeric:
                return left_numeric
            return left < right
        return len(self.prerelease) < len(other.prerelease)

    def __str__(self) -> str:
        value = f"{self.major}.{self.minor}.{self.patch}"
        if self.prerelease:
            value += f"-{'.'.join(self.prerelease)}"
        if self.build:
            value += f"+{'.'.join(self.build)}"
        return value


def parse_version(value: str | Version) -> Version:
    return Version.parse(value)


def compare_versions(current: str | Version, remote: str | Version) -> UpdateRelation:
    current_version = parse_version(current)
    remote_version = parse_version(remote)
    if remote_version == current_version:
        return UpdateRelation.SAME
    if remote_version > current_version:
        return UpdateRelation.UPDATE_AVAILABLE
    return UpdateRelation.CURRENT_AHEAD


@dataclass(frozen=True, slots=True)
class Release:
    """一个候选发布及其可验证制品信息。"""

    version: Version
    tag: str
    source: str = "unknown"
    commit_sha: str | None = None
    artifact_url: str | None = None
    artifact_sha256: str | None = None
    artifact_name: str | None = None
    prerelease: bool = False
    required_config_version: Version | None = None
    notes: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "version", parse_version(self.version))
        if not isinstance(self.tag, str) or not self.tag:
            raise ValueError("release tag 不能为空")
        if self.commit_sha is not None and (
            not isinstance(self.commit_sha, str)
            or not _HEX_SHA_PATTERN.fullmatch(self.commit_sha)
        ):
            raise ValueError("commit_sha 必须是完整 Git SHA")
        if self.artifact_sha256 is not None:
            if not isinstance(self.artifact_sha256, str):
                raise ValueError("artifact_sha256 必须是 SHA-256 十六进制摘要")
            digest = self.artifact_sha256.removeprefix("sha256:").lower()
            if not _SHA256_PATTERN.fullmatch(digest):
                raise ValueError("artifact_sha256 必须是 SHA-256 十六进制摘要")
            object.__setattr__(self, "artifact_sha256", digest)
        for value, name in (
            (self.artifact_url, "artifact_url"),
            (self.artifact_name, "artifact_name"),
        ):
            if value is not None and not isinstance(value, str):
                raise ValueError(f"{name} 必须是字符串")
        if self.required_config_version is not None:
            object.__setattr__(
                self,
                "required_config_version",
                parse_version(self.required_config_version),
            )
        object.__setattr__(
            self, "prerelease", self.prerelease or self.version.is_prerelease
        )
        object.__setattr__(self, "metadata", dict(self.metadata))

    @classmethod
    def from_mapping(
        cls,
        data: Mapping[str, Any],
        *,
        source: str = "manifest",
        default_tag: str | None = None,
    ) -> Release:
        try:
            version = data["version"]
        except KeyError as exc:
            raise UpdateSourceError("manifest release 缺少 version") from exc
        tag = data.get("tag", default_tag or str(version))
        if not isinstance(tag, str):
            raise UpdateSourceError("manifest release 的 tag 必须是字符串")
        sha = data.get("artifact_sha256", data.get("sha256"))
        commit_sha = data.get("commit_sha", data.get("commit"))
        required = data.get("required_config_version", data.get("min_config_version"))
        return cls(
            version=parse_version(version),
            tag=tag,
            source=source,
            commit_sha=commit_sha,
            artifact_url=data.get("artifact_url"),
            artifact_sha256=sha,
            artifact_name=data.get("artifact_name"),
            prerelease=bool(data.get("prerelease", False)),
            required_config_version=required,
            notes=str(data.get("notes", "")),
            metadata=data,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "version": str(self.version),
            "tag": self.tag,
            "source": self.source,
            "commit_sha": self.commit_sha,
            "artifact_url": self.artifact_url,
            "artifact_sha256": self.artifact_sha256,
            "artifact_name": self.artifact_name,
            "prerelease": self.prerelease,
            "required_config_version": (
                str(self.required_config_version)
                if self.required_config_version
                else None
            ),
            "notes": self.notes,
        }


def select_release(
    releases: Sequence[Release],
    current: str | Version,
    channel: str | UpdateChannel,
) -> Release | None:
    """在指定通道中选择高于当前版本的最高候选。"""

    current_version = parse_version(current)
    selected_channel = UpdateChannel.parse(channel)
    candidates = [
        release
        for release in releases
        if release.version > current_version
        and (selected_channel is UpdateChannel.PRERELEASE or not release.prerelease)
    ]
    if not candidates:
        return None
    # 相同版本的多个 tag 不是升级理由；用 tag 排序使结果稳定、可审计。
    return max(candidates, key=lambda release: (release.version, release.tag))


class VersionSource(Protocol):
    """可插拔版本源与制品获取协议。"""

    name: str

    async def discover(self, channel: UpdateChannel) -> Sequence[Release]:
        """发现候选发布。"""

    async def acquire(self, release: Release, destination: Path) -> Path:
        """把发布制品物化到 ``destination`` 下并返回应用根目录。"""


class HttpClient(Protocol):
    async def get_json(
        self, url: str, *, headers: Mapping[str, str] | None = None
    ) -> Any:
        """获取 JSON。"""

    async def download(
        self,
        url: str,
        destination: Path,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        """下载到指定文件。"""


class UrllibHttpClient:
    """标准库 HTTP 实现，网络调用放到线程避免阻塞 Entari 事件循环。"""

    def __init__(self, timeout: float = 30) -> None:
        if timeout <= 0:
            raise ValueError("HTTP timeout 必须大于 0")
        self.timeout = timeout

    @staticmethod
    def _headers(headers: Mapping[str, str] | None) -> dict[str, str]:
        result = {"User-Agent": "Tenko-Updater/1"}
        if headers:
            result.update(headers)
        return result

    def _get_json_sync(self, url: str, headers: Mapping[str, str] | None) -> Any:
        request = Request(url, headers=self._headers(headers))
        with urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    async def get_json(
        self, url: str, *, headers: Mapping[str, str] | None = None
    ) -> Any:
        try:
            return await asyncio.to_thread(self._get_json_sync, url, headers)
        except (
            HTTPError,
            URLError,
            TimeoutError,
            OSError,
            json.JSONDecodeError,
        ) as exc:
            raise UpdateSourceError(f"无法读取 {url}: {exc}") from exc

    def _download_sync(
        self,
        url: str,
        destination: Path,
        headers: Mapping[str, str] | None,
    ) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(
            f".{destination.name}.{uuid.uuid4().hex}.part"
        )
        request = Request(url, headers=self._headers(headers))
        try:
            with (
                urlopen(request, timeout=self.timeout) as response,
                temporary.open("wb") as output,
            ):
                shutil.copyfileobj(response, output)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)

    async def download(
        self,
        url: str,
        destination: Path,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        try:
            await asyncio.to_thread(self._download_sync, url, destination, headers)
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            raise ArtifactAcquisitionError(f"无法下载 {url}: {exc}") from exc


def _run_git(
    executable: str, arguments: Sequence[str], *, cwd: Path | None = None
) -> str:
    try:
        completed = subprocess.run(
            [executable, *arguments],
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise UpdateSourceError(f"找不到 Git 可执行文件: {executable}") from exc
    except OSError as exc:
        raise UpdateSourceError(f"无法运行 Git: {exc}") from exc
    except subprocess.CalledProcessError as exc:
        detail = _redact_text((exc.stderr or exc.stdout or "").strip())
        raise UpdateSourceError(f"Git 命令失败: {detail or exc.returncode}") from exc
    return completed.stdout.strip()


def _is_git_url(value: str) -> bool:
    try:
        parts = urlsplit(value)
    except ValueError:
        return False
    return bool(parts.scheme and ("://" in value or parts.scheme.lower() == "file"))


def _normalize_git_repository(
    repository: str | Path,
    stable_root: Path,
    *,
    git_executable: str = "git",
) -> str:
    """把 Git 配置值解析成固定的本地路径或远端 URL。"""

    configured = str(repository)
    repository_path = Path(configured).expanduser()
    if not repository_path.is_absolute():
        repository_path = stable_root / repository_path
    if repository_path.exists():
        return str(repository_path.resolve())
    if _is_git_url(configured) or _GIT_SCP_LIKE_PATTERN.fullmatch(configured):
        return configured
    if not _GIT_REMOTE_NAME_PATTERN.fullmatch(configured):
        return configured

    display_value = _redact_text(configured)
    try:
        resolved = _run_git(
            git_executable,
            ["remote", "get-url", configured],
            cwd=stable_root,
        )
    except UpdaterError as exc:
        reason = _redact_text(str(exc) or exc.__class__.__name__)
        raise UpgradeConfigError(
            f"无法解析 upgrade.repository={display_value!r}："
            f"在 Git 工作树 {stable_root} 中执行 "
            f"git remote get-url {display_value!r} 失败：{reason}。"
            "请检查该 remote，或将 upgrade.repository 改为完整 URL/本地路径。"
        ) from exc
    if not resolved:
        raise UpgradeConfigError(
            f"无法解析 upgrade.repository={display_value!r}："
            f"在 Git 工作树 {stable_root} 中执行 "
            f"git remote get-url {display_value!r} 未返回 URL。"
            "请检查该 remote，或将 upgrade.repository 改为完整 URL/本地路径。"
        )
    return resolved


class GitTagSource:
    """从 Git 远端 tag 发现版本，并以 commit SHA 校验浅克隆制品。"""

    name = "git_tag"

    def __init__(
        self,
        repository: str | Path,
        *,
        tag_prefix: str = "v",
        git_executable: str = "git",
    ) -> None:
        if not tag_prefix:
            raise ValueError("tag_prefix 不能为空")
        self.repository = str(repository)
        self.tag_prefix = tag_prefix
        self.git_executable = git_executable

    def _version_from_tag(self, tag: str) -> Version | None:
        if not tag.startswith(self.tag_prefix):
            return None
        try:
            return parse_version(tag[len(self.tag_prefix) :])
        except InvalidVersionError:
            # Git 仓库中可以存在非 SemVer 的历史 tag；它们不应阻断有效版本。
            return None

    async def discover(self, channel: UpdateChannel) -> Sequence[Release]:
        selected_channel = UpdateChannel.parse(channel)
        output = await asyncio.to_thread(
            _run_git,
            self.git_executable,
            ["ls-remote", "--tags", self.repository],
        )
        tag_shas: dict[str, str] = {}
        peeled_shas: dict[str, str] = {}
        for line in output.splitlines():
            parts = line.split(maxsplit=1)
            if len(parts) != 2:
                continue
            sha, ref = parts
            if not _HEX_SHA_PATTERN.fullmatch(sha):
                continue
            if ref.endswith("^{}"):
                peeled_shas[ref[:-3]] = sha
            elif ref.startswith("refs/tags/"):
                tag_shas[ref.removeprefix("refs/tags/")] = sha

        releases: list[Release] = []
        for tag, tag_sha in tag_shas.items():
            version = self._version_from_tag(tag)
            if version is None:
                continue
            if selected_channel is UpdateChannel.STABLE and version.is_prerelease:
                continue
            releases.append(
                Release(
                    version=version,
                    tag=tag,
                    source=self.name,
                    # Annotated tag 会报告 object SHA 和 peeled commit SHA；后者
                    # 是 clone + rev-parse 能够验证的值。
                    commit_sha=peeled_shas.get(f"refs/tags/{tag}", tag_sha),
                    prerelease=version.is_prerelease,
                )
            )
        return tuple(
            sorted(releases, key=lambda release: (release.version, release.tag))
        )

    async def acquire(self, release: Release, destination: Path) -> Path:
        if release.commit_sha is None:
            raise ArtifactVerificationError("Git 发布缺少 commit SHA，禁止安装")
        destination = destination.resolve()
        if destination.exists():
            raise ArtifactAcquisitionError(f"制品目录已存在: {destination}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            await asyncio.to_thread(
                _run_git,
                self.git_executable,
                [
                    "clone",
                    "--depth",
                    "1",
                    "--branch",
                    release.tag,
                    "--single-branch",
                    self.repository,
                    str(destination),
                ],
            )
            actual_sha = await asyncio.to_thread(
                _run_git,
                self.git_executable,
                ["rev-parse", "HEAD"],
                cwd=destination,
            )
            if actual_sha.lower() != release.commit_sha.lower():
                raise ArtifactVerificationError(
                    "Git 制品 commit SHA 校验失败: "
                    f"expected={release.commit_sha}, actual={actual_sha}"
                )
            return destination
        except UpdaterError:
            shutil.rmtree(destination, ignore_errors=True)
            raise
        except OSError as exc:
            shutil.rmtree(destination, ignore_errors=True)
            raise ArtifactAcquisitionError(f"无法准备 Git 制品: {exc}") from exc


class _ArchiveSource:
    def __init__(self, client: HttpClient | None = None) -> None:
        self.client = client or UrllibHttpClient()

    async def _acquire_archive(
        self,
        release: Release,
        destination: Path,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> Path:
        if not release.artifact_url:
            raise ArtifactAcquisitionError(
                f"{release.version} 没有可下载的 artifact_url"
            )
        if not release.artifact_sha256:
            raise ArtifactVerificationError(
                f"{release.version} 没有 SHA-256，禁止继续安装"
            )
        destination = destination.resolve()
        if destination.exists():
            raise ArtifactAcquisitionError(f"制品目录已存在: {destination}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        filename = Path(
            release.artifact_name or urlsplit(release.artifact_url).path or "artifact"
        ).name
        if not filename or filename in {".", ".."}:
            filename = "artifact"
        archive_path = destination.parent / f".{filename}.{uuid.uuid4().hex}.download"
        try:
            await self.client.download(
                release.artifact_url,
                archive_path,
                headers=headers,
            )
            actual_digest = await asyncio.to_thread(_sha256_file, archive_path)
            if actual_digest.lower() != release.artifact_sha256.lower():
                raise ArtifactVerificationError(
                    "release asset SHA-256 校验失败: "
                    f"expected={release.artifact_sha256}, actual={actual_digest}"
                )
            await asyncio.to_thread(_extract_archive, archive_path, destination)
            return destination
        except UpdaterError:
            shutil.rmtree(destination, ignore_errors=True)
            raise
        except (OSError, tarfile.TarError, zipfile.BadZipFile) as exc:
            shutil.rmtree(destination, ignore_errors=True)
            raise ArtifactAcquisitionError(f"无法解包 release asset: {exc}") from exc
        finally:
            archive_path.unlink(missing_ok=True)


class GitHubReleaseSource(_ArchiveSource):
    """读取 GitHub Releases API，并以资产 digest 校验下载文件。

    GitHub 官方 Releases API 的资产对象提供 ``browser_download_url`` 和
    ``digest``（``sha256:<64 hex>``）字段；这里不信任 tag 或文件名作为强校验。
    """

    name = "github_release"

    def __init__(
        self,
        repository: str,
        *,
        client: HttpClient | None = None,
        token: str | None = None,
        asset_name: str | None = None,
        tag_prefix: str = "v",
        api_base_url: str = "https://api.github.com",
    ) -> None:
        super().__init__(client)
        parts = repository.strip().strip("/").split("/")
        if len(parts) != 2 or not all(parts):
            raise ValueError("GitHub repository 必须是 owner/repository")
        if not tag_prefix:
            raise ValueError("tag_prefix 不能为空")
        self.repository = "/".join(parts)
        self.token = token or None
        self.asset_name = asset_name or None
        self.tag_prefix = tag_prefix
        self.api_base_url = api_base_url.rstrip("/")

    @property
    def releases_url(self) -> str:
        owner, repository = self.repository.split("/")
        return (
            f"{self.api_base_url}/repos/{quote(owner)}/{quote(repository)}"
            "/releases?per_page=100"
        )

    @property
    def headers(self) -> Mapping[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _parse_version(self, tag: str) -> Version | None:
        if not tag.startswith(self.tag_prefix):
            return None
        try:
            return parse_version(tag[len(self.tag_prefix) :])
        except InvalidVersionError:
            return None

    def _asset(self, value: Mapping[str, Any]) -> Mapping[str, Any] | None:
        assets = value.get("assets", [])
        if not isinstance(assets, list):
            raise UpdateSourceError("GitHub release 的 assets 必须是数组")
        if self.asset_name:
            return next(
                (
                    asset
                    for asset in assets
                    if isinstance(asset, Mapping)
                    and asset.get("name") == self.asset_name
                ),
                None,
            )
        candidates = [
            asset
            for asset in assets
            if isinstance(asset, Mapping) and asset.get("browser_download_url")
        ]
        # 当发布包含校验和或多个构建变体时，优先选择已经可验证的制品；否则
        # 保留第一个可下载制品，以便安装过程明确报告缺少 digest。
        return next((asset for asset in candidates if self._digest(asset)), None) or (
            candidates[0] if candidates else None
        )

    @staticmethod
    def _digest(asset: Mapping[str, Any] | None) -> str | None:
        if asset is None:
            return None
        value = asset.get("digest", asset.get("sha256"))
        if not isinstance(value, str):
            return None
        return value.removeprefix("sha256:")

    async def discover(self, channel: UpdateChannel) -> Sequence[Release]:
        selected_channel = UpdateChannel.parse(channel)
        payload = await self.client.get_json(self.releases_url, headers=self.headers)
        if not isinstance(payload, list):
            raise UpdateSourceError("GitHub Releases API 返回值不是数组")
        releases: list[Release] = []
        for item in payload:
            if not isinstance(item, Mapping) or item.get("draft", False):
                continue
            tag = item.get("tag_name")
            if not isinstance(tag, str):
                continue
            version = self._parse_version(tag)
            if version is None:
                continue
            is_prerelease = bool(item.get("prerelease", False)) or version.is_prerelease
            if selected_channel is UpdateChannel.STABLE and is_prerelease:
                continue
            asset = self._asset(item)
            commit = item.get("target_commitish")
            commit_sha = (
                commit
                if isinstance(commit, str) and _HEX_SHA_PATTERN.fullmatch(commit)
                else None
            )
            required = item.get(
                "required_config_version", item.get("min_config_version")
            )
            if required is not None and not isinstance(required, str):
                raise UpdateSourceError(f"GitHub release {tag} 的配置版本无效")
            releases.append(
                Release(
                    version=version,
                    tag=tag,
                    source=self.name,
                    commit_sha=commit_sha,
                    artifact_url=(
                        asset.get("browser_download_url") if asset is not None else None
                    ),
                    artifact_sha256=self._digest(asset),
                    artifact_name=(asset.get("name") if asset is not None else None),
                    prerelease=is_prerelease,
                    required_config_version=required,
                    notes=str(item.get("body", "") or ""),
                    metadata=item,
                )
            )
        return tuple(
            sorted(releases, key=lambda release: (release.version, release.tag))
        )

    async def acquire(self, release: Release, destination: Path) -> Path:
        return await self._acquire_archive(
            release,
            destination,
            headers=self.headers,
        )


class UrlManifestSource(_ArchiveSource):
    """从任意 URL 读取 JSON manifest 的扩展源。

    支持 ``[{...release...}]``、``{"releases": [...]}`` 和单个 release object；
    每个 release 必须提供 artifact URL 与 SHA-256，避免 manifest 只提供版本号
    却无法验证下载内容。
    """

    name = "manifest"

    def __init__(
        self,
        url: str,
        *,
        client: HttpClient | None = None,
        tag_prefix: str = "v",
    ) -> None:
        super().__init__(client)
        if not url:
            raise ValueError("manifest URL 不能为空")
        if not tag_prefix:
            raise ValueError("tag_prefix 不能为空")
        self.url = url
        self.tag_prefix = tag_prefix

    @staticmethod
    def _items(payload: Any) -> list[Mapping[str, Any]]:
        if isinstance(payload, list):
            values = payload
        elif isinstance(payload, Mapping) and isinstance(payload.get("releases"), list):
            values = payload["releases"]
        elif isinstance(payload, Mapping):
            values = [payload]
        else:
            raise UpdateSourceError("manifest 必须是 release 数组或 object")
        if not all(isinstance(item, Mapping) for item in values):
            raise UpdateSourceError("manifest releases 的每项必须是 object")
        return list(values)

    async def discover(self, channel: UpdateChannel) -> Sequence[Release]:
        selected_channel = UpdateChannel.parse(channel)
        payload = await self.client.get_json(self.url)
        releases: list[Release] = []
        for item in self._items(payload):
            version = parse_version(item.get("version"))
            release = Release.from_mapping(
                item,
                source=self.name,
                default_tag=f"{self.tag_prefix}{version}",
            )
            if (
                selected_channel is UpdateChannel.STABLE
                and release.version.is_prerelease
            ):
                continue
            if release.artifact_url:
                release = replace(
                    release, artifact_url=urljoin(self.url, release.artifact_url)
                )
            releases.append(release)
        return tuple(
            sorted(releases, key=lambda release: (release.version, release.tag))
        )

    async def acquire(self, release: Release, destination: Path) -> Path:
        return await self._acquire_archive(release, destination)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_archive_path(destination: Path, member_name: str) -> Path:
    pure = PurePosixPath(member_name)
    if pure.is_absolute() or ".." in pure.parts:
        raise ArtifactAcquisitionError(f"制品包含越界路径: {member_name!r}")
    relative = Path(*[part for part in pure.parts if part not in {"", "."}])
    target = (destination / relative).resolve()
    if not target.is_relative_to(destination.resolve()):
        raise ArtifactAcquisitionError(f"制品包含越界路径: {member_name!r}")
    return target


def _extract_zip(archive: Path, destination: Path) -> None:
    with zipfile.ZipFile(archive) as source:
        for member in source.infolist():
            target = _safe_archive_path(destination, member.filename)
            mode = member.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise ArtifactAcquisitionError("制品不允许包含符号链接")
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with source.open(member) as input_file, target.open("wb") as output:
                shutil.copyfileobj(input_file, output)


def _extract_tar(archive: Path, destination: Path) -> None:
    with tarfile.open(archive) as source:
        for member in source.getmembers():
            target = _safe_archive_path(destination, member.name)
            if member.issym() or member.islnk() or member.isdev():
                raise ArtifactAcquisitionError("制品不允许包含链接或设备文件")
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if not member.isfile():
                raise ArtifactAcquisitionError(
                    f"制品包含不支持的 tar 成员: {member.name}"
                )
            input_file = source.extractfile(member)
            if input_file is None:
                raise ArtifactAcquisitionError(f"无法读取 tar 成员: {member.name}")
            target.parent.mkdir(parents=True, exist_ok=True)
            with input_file, target.open("wb") as output:
                shutil.copyfileobj(input_file, output)


def _flatten_single_archive_root(destination: Path) -> None:
    children = list(destination.iterdir())
    if (
        len(children) != 1
        or not children[0].is_dir()
        or (destination / "tenko").exists()
    ):
        return
    source_root = children[0]
    for child in list(source_root.iterdir()):
        target = destination / child.name
        if target.exists():
            raise ArtifactAcquisitionError(f"制品根目录冲突: {target.name}")
        os.replace(child, target)
    source_root.rmdir()


def _extract_archive(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    try:
        if zipfile.is_zipfile(archive):
            _extract_zip(archive, destination)
        elif tarfile.is_tarfile(archive):
            _extract_tar(archive, destination)
        else:
            raise ArtifactAcquisitionError("只支持 zip 或 tar 制品")
        _flatten_single_archive_root(destination)
        if not any(destination.iterdir()):
            raise ArtifactAcquisitionError("制品为空")
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise


@dataclass(frozen=True, slots=True)
class CompatibilityResult:
    current_version: Version
    required_version: Version | None
    compatible: bool
    reason: str


class ConfigCompatibilityChecker:
    """比较用户配置版本和新制品声明的最低兼容版本。"""

    manifest_names = ("tenko/upgrade-manifest.json", "upgrade-manifest.json")

    @staticmethod
    def _required_from_manifest(candidate: Path) -> Version | None:
        for relative in ConfigCompatibilityChecker.manifest_names:
            path = candidate / relative
            if not path.is_file():
                continue
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ConfigurationCompatibilityError(
                    CompatibilityResult(
                        Version(0, 0, 0),
                        None,
                        False,
                        f"升级兼容性清单不可读取: {path}",
                    )
                ) from exc
            if not isinstance(value, Mapping):
                raise ConfigurationCompatibilityError(
                    CompatibilityResult(
                        Version(0, 0, 0),
                        None,
                        False,
                        f"升级兼容性清单必须是 object: {path}",
                    )
                )
            required = value.get(
                "min_config_version", value.get("required_config_version")
            )
            if required is None:
                return None
            try:
                return parse_version(required)
            except InvalidVersionError as exc:
                raise ConfigurationCompatibilityError(
                    CompatibilityResult(
                        Version(0, 0, 0),
                        None,
                        False,
                        f"升级兼容性清单中的版本非法: {required!r}",
                    )
                ) from exc
        return None

    def check(
        self,
        current_config_version: str | Version,
        required_config_version: str | Version | None,
    ) -> CompatibilityResult:
        current = parse_version(current_config_version)
        required = (
            parse_version(required_config_version)
            if required_config_version is not None
            else None
        )
        if required is None:
            return CompatibilityResult(
                current,
                None,
                True,
                "新版本未声明更高的最低配置版本",
            )
        if current < required:
            return CompatibilityResult(
                current,
                required,
                False,
                f"当前配置版本 {current} 低于新版本要求的最低配置版本 {required}",
            )
        return CompatibilityResult(
            current,
            required,
            True,
            f"当前配置版本 {current} 满足最低要求 {required}",
        )

    def check_candidate(
        self,
        candidate: Path,
        current_config_version: str | Version,
        release: Release,
    ) -> CompatibilityResult:
        required_versions = [
            version
            for version in (
                release.required_config_version,
                self._required_from_manifest(candidate),
            )
            if version is not None
        ]
        required = max(required_versions) if required_versions else None
        result = self.check(current_config_version, required)
        if not result.compatible:
            raise ConfigurationCompatibilityError(result)
        return result


@dataclass(frozen=True, slots=True)
class HealthCheckResult:
    ok: bool
    reason: str


class DefaultHealthChecker:
    """默认最小健康检查：进程存活（若有）加 Python 编译冒烟。

    实际部署可配置 ``health_command`` 做最小启动检查；命令以独立子进程运行，
    其工作目录和 ``PYTHONPATH`` 优先指向候选版本目录，因而不会导入当前进程中的
    旧模块。命令可使用 ``{python}``、``{release_root}``、``{config_path}`` 和
    ``{data_dir}`` 占位符。
    """

    def __init__(
        self,
        command: Sequence[str] = (),
        *,
        timeout: int = 30,
        python_executable: str = sys.executable,
        config_path: Path | None = None,
        data_dir: Path | None = None,
    ) -> None:
        if timeout <= 0:
            raise ValueError("health timeout 必须大于 0")
        self.command = tuple(command)
        self.timeout = timeout
        self.python_executable = python_executable
        self.config_path = config_path
        self.data_dir = data_dir

    def _command(self, candidate: Path) -> list[str]:
        values = {
            "{python}": self.python_executable,
            "{release_root}": str(candidate),
            "{config_path}": str(self.config_path) if self.config_path else "",
            "{data_dir}": str(self.data_dir) if self.data_dir else "",
        }
        return [
            next(
                (replacement for key, replacement in values.items() if item == key),
                item,
            )
            for item in self.command
        ]

    def _check_sync(self, candidate: Path) -> HealthCheckResult:
        package = candidate / "tenko"
        if not candidate.is_dir() or not (package / "__init__.py").is_file():
            return HealthCheckResult(False, "候选版本缺少 tenko 包入口")
        if self.command:
            try:
                completed = subprocess.run(
                    self._command(candidate),
                    cwd=candidate,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout,
                    env=_candidate_environment(candidate),
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                return HealthCheckResult(False, f"健康检查命令执行失败: {exc}")
            if completed.returncode != 0:
                output = (completed.stderr or completed.stdout or "").strip()
                return HealthCheckResult(
                    False,
                    f"健康检查命令返回 {completed.returncode}: {output[:500]}",
                )
            return HealthCheckResult(True, "配置的健康检查命令通过")
        try:
            completed = subprocess.run(
                [self.python_executable, "-m", "compileall", "-q", str(package)],
                cwd=candidate,
                check=False,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return HealthCheckResult(False, f"Python 编译冒烟失败: {exc}")
        if completed.returncode != 0:
            output = (completed.stderr or completed.stdout or "").strip()
            return HealthCheckResult(False, f"Python 编译冒烟失败: {output[:500]}")
        return HealthCheckResult(True, "tenko 包入口和 Python 编译冒烟通过")

    async def check(
        self,
        candidate: Path,
        *,
        phase: str,
        process: Any | None = None,
    ) -> HealthCheckResult:
        if process is not None:
            poll = getattr(process, "poll", None)
            if not callable(poll) or poll() is not None:
                return HealthCheckResult(False, f"{phase} 检查发现新进程已退出")
        result = await asyncio.to_thread(self._check_sync, candidate)
        if not result.ok:
            return HealthCheckResult(False, f"{phase}: {result.reason}")
        return result


class ProcessLauncher(Protocol):
    async def start(self, candidate: Path) -> Any:
        """启动候选版本并返回可查询 ``poll`` 的进程句柄。"""


class SubprocessLauncher:
    """配置化外部进程启动器，不使用 shell。"""

    def __init__(
        self,
        command: Sequence[str] = (),
        *,
        config_path: Path | None = None,
        data_dir: Path | None = None,
        upgrade_root: Path | None = None,
    ) -> None:
        self.command = tuple(command)
        self.config_path = config_path
        self.data_dir = data_dir
        self.upgrade_root = upgrade_root

    async def start(self, candidate: Path) -> subprocess.Popen[bytes] | None:
        if not self.command:
            return None
        replacements = {
            "{python}": sys.executable,
            "{release_root}": str(candidate),
            "{config_path}": str(self.config_path) if self.config_path else "",
            "{data_dir}": str(self.data_dir) if self.data_dir else "",
        }
        command = [
            next(
                (
                    replacement
                    for key, replacement in replacements.items()
                    if item == key
                ),
                item,
            )
            for item in self.command
        ]
        environment = os.environ.copy()
        if self.config_path:
            environment["TENKO_CONFIG_PATH"] = str(self.config_path)
        if self.data_dir:
            environment["TENKO_DATA_DIR"] = str(self.data_dir)
        if self.upgrade_root:
            environment["TENKO_UPGRADE_ROOT"] = str(self.upgrade_root)
        existing_pythonpath = environment.get("PYTHONPATH")
        environment["PYTHONPATH"] = os.pathsep.join(
            value for value in (str(candidate), existing_pythonpath) if value
        )
        try:
            return await asyncio.to_thread(
                subprocess.Popen,
                command,
                cwd=candidate,
                env=environment,
            )
        except OSError as exc:
            raise HealthCheckFailed(f"无法启动候选版本: {exc}") from exc


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=False, sort_keys=True)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@dataclass(frozen=True, slots=True)
class ReleasePointer:
    version: Version
    path: Path


@dataclass(frozen=True, slots=True)
class UpgradeLayout:
    """升级状态目录。

    ``active.json`` 是外部启动器唯一需要读取的指针。它通过临时文件加
    ``os.replace`` 更新，启动器不会读到半写入的 JSON，也不会在应用目录中
    同时混用新旧文件。
    """

    root: Path

    def __post_init__(self) -> None:
        object.__setattr__(self, "root", Path(self.root).expanduser().resolve())

    @property
    def versions_dir(self) -> Path:
        return self.root / "versions"

    @property
    def staging_dir(self) -> Path:
        return self.root / "staging"

    @property
    def active_file(self) -> Path:
        return self.root / "active.json"

    @property
    def previous_file(self) -> Path:
        return self.root / "previous.json"

    @property
    def pending_file(self) -> Path:
        return self.root / "pending.json"

    @property
    def handoff_file(self) -> Path:
        return self.root / "handoff.json"

    @property
    def failed_handoffs_dir(self) -> Path:
        return self.root / "failed-handoffs"

    @property
    def audit_file(self) -> Path:
        return self.root / "audit.jsonl"

    def ensure(self) -> None:
        self.versions_dir.mkdir(parents=True, exist_ok=True)
        self.staging_dir.mkdir(parents=True, exist_ok=True)

    def new_staging_dir(self) -> Path:
        self.ensure()
        return Path(tempfile.mkdtemp(prefix="stage-", dir=self.staging_dir))

    def new_version_path(self, version: Version, commit_sha: str | None = None) -> Path:
        suffix = commit_sha[:12] if commit_sha else uuid.uuid4().hex[:12]
        return self.versions_dir / f"{version}-{suffix}"

    def promote(
        self, staged: Path, version: Version, commit_sha: str | None = None
    ) -> Path:
        self.ensure()
        staged = staged.resolve()
        if not staged.is_dir() or not staged.is_relative_to(self.staging_dir.resolve()):
            raise UpgradeConfigError("只能提升升级状态目录下的 staging 制品")
        target = self.new_version_path(version, commit_sha)
        os.replace(staged, target)
        return target

    def _pointer(self, path: Path) -> ReleasePointer | None:
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            pointer_path = Path(data["path"]).expanduser().resolve()
            version = parse_version(data["version"])
        except (
            OSError,
            KeyError,
            TypeError,
            json.JSONDecodeError,
            InvalidVersionError,
        ) as exc:
            raise UpgradeConfigError(f"升级指针损坏: {path}") from exc
        self._validate_version_path(pointer_path)
        return ReleasePointer(version, pointer_path)

    def _validate_version_path(self, path: Path) -> Path:
        path = path.resolve()
        versions_root = self.versions_dir.resolve()
        try:
            relative = path.relative_to(versions_root)
        except ValueError as exc:
            raise UpgradeConfigError(
                f"升级指针必须指向 versions 下的版本目录: {path}"
            ) from exc
        if len(relative.parts) != 1 or not path.is_dir():
            raise UpgradeConfigError(f"升级版本目录无效: {path}")
        return path

    def read_active(self) -> ReleasePointer | None:
        return self._pointer(self.active_file)

    def read_previous(self) -> ReleasePointer | None:
        return self._pointer(self.previous_file)

    def write_pointer(
        self, target: Path, version: Version, *, previous: bool = False
    ) -> None:
        target = self._validate_version_path(target)
        _atomic_write_json(
            self.previous_file if previous else self.active_file,
            {"version": str(version), "path": str(target)},
        )

    def read_pending(self) -> Mapping[str, Any] | None:
        if not self.pending_file.is_file():
            return None
        try:
            data = json.loads(self.pending_file.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise UpgradeConfigError(
                f"pending 升级记录损坏: {self.pending_file}"
            ) from exc
        if not isinstance(data, Mapping):
            raise UpgradeConfigError("pending 升级记录必须是 object")
        try:
            parse_version(data["version"])
            candidate = Path(str(data["path"])).expanduser().resolve()
            self._validate_version_path(candidate)
        except (KeyError, TypeError, InvalidVersionError) as exc:
            raise UpgradeConfigError("pending 升级记录的版本或路径无效") from exc
        return data

    def write_pending(self, data: Mapping[str, Any]) -> None:
        _atomic_write_json(self.pending_file, data)

    def write_handoff(self, data: Mapping[str, Any]) -> None:
        _atomic_write_json(self.handoff_file, data)

    def read_handoff(self) -> Mapping[str, Any] | None:
        if not self.handoff_file.is_file():
            return None
        try:
            data = json.loads(self.handoff_file.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise UpgradeConfigError(f"handoff 记录损坏: {self.handoff_file}") from exc
        if not isinstance(data, Mapping):
            raise UpgradeConfigError("handoff 记录必须是 object")
        return data

    def clear_pending(self) -> None:
        self.pending_file.unlink(missing_ok=True)

    def clear_handoff(self) -> None:
        self.handoff_file.unlink(missing_ok=True)

    def isolate_handoff(self) -> Path | None:
        """隔离一次不可处理的 handoff，并保留有限数量的诊断副本。"""

        if not self.handoff_file.is_file():
            return None
        self.failed_handoffs_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        target = (
            self.failed_handoffs_dir / f"handoff-{timestamp}-{uuid.uuid4().hex}.json"
        )
        os.replace(self.handoff_file, target)
        files = [path for path in self.failed_handoffs_dir.iterdir() if path.is_file()]
        if len(files) > _FAILED_HANDOFF_RETENTION:
            files.sort(key=lambda path: path.stat().st_mtime_ns)
            for path in files[:-_FAILED_HANDOFF_RETENTION]:
                path.unlink(missing_ok=True)
        return target

    def clear_previous(self) -> None:
        self.previous_file.unlink(missing_ok=True)


class AuditLogger:
    """追加式 JSON Lines 审计记录。"""

    def __init__(
        self,
        path: str | Path,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.path = Path(path).expanduser().resolve()
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def record(
        self,
        action: str,
        *,
        current_version: str | Version | None = None,
        target_version: str | Version | None = None,
        result: str,
        **details: Any,
    ) -> Mapping[str, Any]:
        timestamp = self.clock()
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        payload: dict[str, Any] = {
            "timestamp": timestamp.astimezone(timezone.utc).isoformat(),
            "action": action,
            "current_version": (
                str(parse_version(current_version))
                if current_version is not None
                else None
            ),
            "target_version": (
                str(parse_version(target_version))
                if target_version is not None
                else None
            ),
            "result": result,
        }
        payload.update(details)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=False, sort_keys=True)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        logger.bind(upgrade_audit=payload).info("upgrade audit")
        return payload


@dataclass(frozen=True, slots=True)
class CheckResult:
    current_version: Version
    channel: UpdateChannel
    source: str
    status: str
    candidate: Release | None = None
    releases_seen: int = 0
    error: str | None = None

    @property
    def update_available(self) -> bool:
        return self.candidate is not None


@dataclass(frozen=True, slots=True)
class PrepareResult:
    release: Release
    path: Path
    compatibility: CompatibilityResult


@dataclass(frozen=True, slots=True)
class HandoffResult:
    action: str
    target_version: Version
    path: Path
    applied: bool = False


@dataclass(frozen=True, slots=True)
class InstallResult:
    success: bool
    target_version: Version
    active_path: Path | None
    rolled_back: bool
    reason: str


@dataclass(frozen=True, slots=True)
class RollbackResult:
    success: bool
    target_version: Version
    path: Path
    applied: bool
    reason: str


def read_project_version(project_root: str | Path) -> Version:
    path = Path(project_root) / "pyproject.toml"
    try:
        with path.open("rb") as file:
            data = tomllib.load(file)
        value = data["project"]["version"]
    except (OSError, KeyError, TypeError, tomllib.TOMLDecodeError) as exc:
        raise UpgradeConfigError(f"无法从 {path} 读取 project.version") from exc
    return parse_version(value)


class UpgradeManager:
    """协调升级的发现、准备、外部安装接管和回滚。"""

    def __init__(
        self,
        current_version: str | Version,
        source: VersionSource | None = None,
        *,
        sources: Sequence[VersionSource] = (),
        layout: UpgradeLayout | None = None,
        project_root: str | Path | None = None,
        config_path: str | Path | None = None,
        data_dir: str | Path | None = None,
        config_version: str | Version = "1.0.0",
        channel: str | UpdateChannel = UpdateChannel.STABLE,
        policy: str | UpdatePolicy = UpdatePolicy.CHECK_ONLY,
        enabled: bool = True,
        check_interval_hours: int = 24,
        compatibility_checker: ConfigCompatibilityChecker | None = None,
        health_checker: Any | None = None,
        launcher: ProcessLauncher | None = None,
        audit: AuditLogger | None = None,
    ) -> None:
        if source is not None and sources:
            raise ValueError("source 和 sources 只能指定一个")
        self.current_version = parse_version(current_version)
        self.sources = tuple(sources) if sources else ((source,) if source else ())
        self.layout = layout or UpgradeLayout(Path(".tenko/upgrades"))
        self.project_root = Path(project_root or Path.cwd()).expanduser().resolve()
        self.config_path = (
            self._resolve_path(config_path) if config_path is not None else None
        )
        self.data_dir = self._resolve_path(data_dir) if data_dir is not None else None
        self.config_version = parse_version(config_version)
        self.channel = UpdateChannel.parse(channel)
        self.policy = UpdatePolicy.parse(policy)
        self.enabled = bool(enabled)
        if check_interval_hours <= 0:
            raise ValueError("check_interval_hours 必须大于 0")
        self.check_interval_hours = check_interval_hours
        self.compatibility_checker = (
            compatibility_checker or ConfigCompatibilityChecker()
        )
        self.health_checker = health_checker or DefaultHealthChecker()
        self.launcher = launcher
        self.audit = audit or AuditLogger(self.layout.audit_file)
        self._operation_lock = asyncio.Lock()

    def _resolve_path(self, value: str | Path) -> Path:
        path = Path(value).expanduser()
        return path if path.is_absolute() else (self.project_root / path).resolve()

    @property
    def source_names(self) -> tuple[str, ...]:
        return tuple(
            getattr(source, "name", source.__class__.__name__)
            for source in self.sources
        )

    def _source_for(self, release: Release) -> VersionSource:
        for source in self.sources:
            if getattr(source, "name", None) == release.source:
                return source
        raise UpdateSourceError(f"找不到发布来源 {release.source!r}")

    async def _check_unlocked(self) -> CheckResult:
        if not self.enabled:
            result = CheckResult(
                self.current_version,
                self.channel,
                "+".join(self.source_names),
                "disabled",
            )
            self.audit.record(
                "check",
                current_version=self.current_version,
                result="disabled",
                channel=self.channel.value,
                sources=self.source_names,
            )
            return result
        if not self.sources:
            error = "未配置升级版本源"
            self.audit.record(
                "check",
                current_version=self.current_version,
                result="failed",
                error=error,
            )
            raise UpgradeConfigError(error)
        try:
            releases: list[Release] = []
            for source in self.sources:
                releases.extend(await source.discover(self.channel))
            candidate = select_release(releases, self.current_version, self.channel)
        except Exception as exc:
            if isinstance(exc, asyncio.CancelledError):
                raise
            error = str(exc) or exc.__class__.__name__
            self.audit.record(
                "check",
                current_version=self.current_version,
                result="failed",
                channel=self.channel.value,
                sources=self.source_names,
                error=error,
            )
            if isinstance(exc, UpdaterError):
                raise
            raise UpdateSourceError(error) from exc

        status = "available" if candidate else "current"
        self.audit.record(
            "check",
            current_version=self.current_version,
            target_version=candidate.version if candidate else None,
            result=status,
            channel=self.channel.value,
            sources=self.source_names,
            releases_seen=len(releases),
            target_tag=candidate.tag if candidate else None,
        )
        return CheckResult(
            self.current_version,
            self.channel,
            "+".join(self.source_names),
            status,
            candidate,
            len(releases),
        )

    async def check(self) -> CheckResult:
        async with self._operation_lock:
            return await self._check_unlocked()

    async def prepare(self, release: Release | None = None) -> PrepareResult:
        async with self._operation_lock:
            if release is None:
                checked = await self._check_unlocked()
                release = checked.candidate
            if release is None:
                raise NoUpdateAvailable("当前通道没有可安装的新版本")
            if release.version <= self.current_version:
                raise NoUpdateAvailable(
                    f"目标版本 {release.version} 不高于当前版本 {self.current_version}"
                )
            if self.channel is UpdateChannel.STABLE and release.version.is_prerelease:
                raise NoUpdateAvailable("stable 通道不允许安装预发布版本")
            if self.layout.read_pending() is not None:
                raise UpgradeConfigError("已有待安装版本，请先完成或清理现有 handoff")
            stage_root = self.layout.new_staging_dir()
            candidate_path = stage_root / "release"
            final_path: Path | None = None
            pending_written = False
            self.audit.record(
                "download",
                current_version=self.current_version,
                target_version=release.version,
                result="started",
                source=release.source,
                target_tag=release.tag,
            )
            try:
                source = self._source_for(release)
                acquired = await source.acquire(release, candidate_path)
                acquired = Path(acquired).resolve()
                if not acquired.is_dir() or not acquired.is_relative_to(
                    stage_root.resolve()
                ):
                    raise ArtifactAcquisitionError(
                        "版本源返回了 staging 目录之外的制品"
                    )
                compatibility = self.compatibility_checker.check_candidate(
                    acquired, self.config_version, release
                )
                health = await self.health_checker.check(
                    acquired,
                    phase="pre-switch",
                )
                if not _health_ok(health):
                    raise HealthCheckFailed(_health_reason(health))
                final_path = self.layout.promote(
                    acquired, release.version, release.commit_sha
                )
                pending = {
                    "version": str(release.version),
                    "path": str(final_path),
                    "release": release.as_dict(),
                    "prepared_at": datetime.now(timezone.utc).isoformat(),
                    "config_path": str(self.config_path) if self.config_path else None,
                    "data_dir": str(self.data_dir) if self.data_dir else None,
                    "compatibility": {
                        "current": str(compatibility.current_version),
                        "required": (
                            str(compatibility.required_version)
                            if compatibility.required_version
                            else None
                        ),
                    },
                }
                self.layout.write_pending(pending)
                pending_written = True
                self.audit.record(
                    "download",
                    current_version=self.current_version,
                    target_version=release.version,
                    result="success",
                    source=release.source,
                    target_path=str(final_path),
                    verification=(
                        "commit_sha" if release.commit_sha else "asset_sha256"
                    ),
                    compatibility=compatibility.reason,
                )
                return PrepareResult(release, final_path, compatibility)
            except Exception as exc:
                if isinstance(exc, asyncio.CancelledError):
                    raise
                self.audit.record(
                    "download",
                    current_version=self.current_version,
                    target_version=release.version,
                    result="failed",
                    source=release.source,
                    error=str(exc) or exc.__class__.__name__,
                )
                if final_path is not None and not pending_written:
                    shutil.rmtree(final_path, ignore_errors=True)
                shutil.rmtree(stage_root, ignore_errors=True)
                raise

    async def request_install(self) -> HandoffResult:
        async with self._operation_lock:
            pending = self.layout.read_pending()
            if pending is None:
                raise NoUpdateAvailable("没有已通过校验的待安装版本")
            version = parse_version(pending["version"])
            target = Path(str(pending["path"])).resolve()
            handoff = {
                "action": "activate",
                "version": str(version),
                "path": str(target),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "config_path": str(self.config_path) if self.config_path else None,
                "data_dir": str(self.data_dir) if self.data_dir else None,
            }
            self.layout.write_handoff(handoff)
            self.audit.record(
                "install",
                current_version=self.current_version,
                target_version=version,
                result="requested",
                handoff_path=str(self.layout.handoff_file),
                restart_required=True,
            )
            return HandoffResult("activate", version, target)

    async def rollback(self, *, defer: bool = True) -> RollbackResult:
        async with self._operation_lock:
            previous = self.layout.read_previous()
            if previous is None:
                self.audit.record(
                    "rollback",
                    current_version=self.current_version,
                    result="failed",
                    error="没有可回滚版本",
                )
                raise NoRollbackAvailable("没有可回滚的上一可用版本")
            current = self.layout.read_active()
            if current is None:
                self.audit.record(
                    "rollback",
                    current_version=self.current_version,
                    target_version=previous.version,
                    result="failed",
                    error="回滚前缺少 active 指针",
                )
                raise UpgradeConfigError("回滚前缺少 active 指针")
            if defer:
                self.layout.write_handoff(
                    {
                        "action": "rollback",
                        "version": str(previous.version),
                        "path": str(previous.path),
                        "from_version": str(current.version),
                        "from_path": str(current.path),
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    }
                )
                self.audit.record(
                    "rollback",
                    current_version=self.current_version,
                    target_version=previous.version,
                    result="requested",
                    handoff_path=str(self.layout.handoff_file),
                    restart_required=True,
                )
                return RollbackResult(
                    True,
                    previous.version,
                    previous.path,
                    False,
                    "已生成外部重启回滚记录",
                )
            return await self._apply_rollback_unlocked(start_process=True)

    def _snapshot_current(self) -> ReleasePointer:
        if not self.project_root.is_dir():
            raise UpgradeConfigError(f"当前项目目录不存在: {self.project_root}")
        self.layout.ensure()
        baseline = self.layout.new_version_path(
            self.current_version, f"baseline-{uuid.uuid4().hex[:12]}"
        )
        excluded = {
            ".git",
            ".venv",
            ".venv-entari",
            "__pycache__",
            ".pytest_cache",
            ".ruff_cache",
        }
        for path in (self.config_path, self.data_dir, self.layout.root):
            if path is None:
                continue
            try:
                relative = path.resolve().relative_to(self.project_root)
            except ValueError:
                continue
            if relative.parts:
                excluded.add(relative.parts[0])

        def ignore(_directory: str, names: list[str]) -> set[str]:
            return {name for name in names if name in excluded}

        try:
            shutil.copytree(self.project_root, baseline, ignore=ignore)
        except Exception:
            shutil.rmtree(baseline, ignore_errors=True)
            raise
        return ReleasePointer(self.current_version, baseline)

    async def _health(
        self, candidate: Path, *, phase: str, process: Any = None
    ) -> bool:
        result = await self.health_checker.check(
            candidate, phase=phase, process=process
        )
        return _health_ok(result)

    @staticmethod
    def _same_pointer(left: ReleasePointer, right: ReleasePointer) -> bool:
        return left.path == right.path and left.version == right.version

    @staticmethod
    def _pointer_data(pointer: ReleasePointer) -> dict[str, str]:
        return {
            "version": str(pointer.version),
            "path": str(pointer.path),
        }

    def _pointer_from_data(
        self, data: Mapping[str, Any], *, label: str
    ) -> ReleasePointer:
        try:
            version = parse_version(data["version"])
            path_value = data["path"]
            if not isinstance(path_value, str) or not path_value:
                raise TypeError("path 必须是非空字符串")
            path = Path(path_value).expanduser().resolve()
            self.layout._validate_version_path(path)
        except (KeyError, TypeError, InvalidVersionError, ValueError) as exc:
            raise UpgradeConfigError(f"{label} 的版本或路径无效") from exc
        return ReleasePointer(version, path)

    def _activation_recovery(self, pending: Mapping[str, Any]) -> ReleasePointer | None:
        value = pending.get("activation_recovery")
        if value is None:
            return None
        if not isinstance(value, Mapping):
            raise UpgradeConfigError("pending 激活恢复记录必须是 object")
        source = value.get("from")
        if source is None:
            source = {
                "version": value.get("from_version"),
                "path": value.get("from_path"),
            }
        if not isinstance(source, Mapping):
            raise UpgradeConfigError("pending 激活恢复记录缺少旧版本指针")
        return self._pointer_from_data(source, label="pending 激活恢复记录")

    def _record_matches_pointer(
        self, record: Mapping[str, Any], pointer: ReleasePointer, *, label: str
    ) -> bool:
        try:
            candidate = self._pointer_from_data(record, label=label)
        except UpgradeConfigError:
            return False
        return self._same_pointer(candidate, pointer)

    def _write_activation_recovery(
        self, pending: Mapping[str, Any], source: ReleasePointer
    ) -> None:
        updated = dict(pending)
        updated["activation_recovery"] = {
            "phase": "before-switch",
            "from": self._pointer_data(source),
        }
        self.layout.write_pending(updated)

    def _rollback_source(
        self,
        handoff: Mapping[str, Any] | None,
        current: ReleasePointer,
        target: ReleasePointer,
    ) -> ReleasePointer:
        if handoff is None:
            if current.path == target.path:
                raise UpgradeConfigError("回滚恢复记录缺少原 active 指针")
            return current

        has_from = "from_version" in handoff or "from_path" in handoff
        if not has_from:
            if current.path == target.path:
                raise UpgradeConfigError("回滚 handoff 缺少原 active 指针")
            return current
        source = self._pointer_from_data(
            {
                "version": handoff.get("from_version"),
                "path": handoff.get("from_path"),
            },
            label="回滚 handoff 的原 active 指针",
        )
        if source.path == target.path:
            raise UpgradeConfigError("回滚 handoff 的原 active 指针不能等于目标版本")
        if not (
            self._same_pointer(current, source) or self._same_pointer(current, target)
        ):
            raise UpgradeConfigError("回滚 handoff 与当前 active 指针不一致")
        return source

    def _rollback_handoff(
        self,
        handoff: Mapping[str, Any] | None,
        target: ReleasePointer,
        source: ReleasePointer,
    ) -> Mapping[str, Any]:
        data = dict(handoff or {})
        data.update(
            {
                "action": "rollback",
                "version": str(target.version),
                "path": str(target.path),
                "from_version": str(source.version),
                "from_path": str(source.path),
                "phase": "before-switch",
            }
        )
        self.layout.write_handoff(data)
        return data

    def _discard_live_handoff(self, *, isolate: bool) -> tuple[Path | None, str | None]:
        if not isolate:
            self.layout.clear_handoff()
            return None, None
        try:
            return self.layout.isolate_handoff(), None
        except OSError as exc:
            error = _redact_text(str(exc) or exc.__class__.__name__)
            try:
                self.layout.clear_handoff()
            except OSError as clear_exc:
                error = (
                    f"{error}; 清除 live handoff 也失败："
                    f"{_redact_text(str(clear_exc) or clear_exc.__class__.__name__)}"
                )
            return None, error

    def _failed_handoff_result(self, reason: str) -> InstallResult:
        active_path = None
        target_version = self.current_version
        try:
            active = self.layout.read_active()
        except UpgradeConfigError:
            active = None
        if active is not None:
            target_version = active.version
            active_path = active.path
        return InstallResult(
            False,
            target_version,
            active_path,
            False,
            _redact_text(reason),
        )

    def _quarantine_handoff(
        self,
        reason: str,
        *,
        action: object = None,
        clear_pending: bool = False,
    ) -> InstallResult:
        failed_path, quarantine_error = self._discard_live_handoff(isolate=True)
        pending_error = None
        if clear_pending:
            try:
                self.layout.clear_pending()
            except OSError as exc:
                pending_error = _redact_text(str(exc) or exc.__class__.__name__)
        safe_reason = _redact_text(reason)
        details: dict[str, Any] = {
            "handoff_action": _redact_text(action) if action is not None else None,
            "failed_handoff_path": str(failed_path) if failed_path else None,
        }
        if quarantine_error:
            details["quarantine_error"] = quarantine_error
        if pending_error:
            details["pending_cleanup_error"] = pending_error
        self.audit.record(
            "rollback" if action == "rollback" else "install",
            current_version=self.current_version,
            result="failed",
            error=safe_reason,
            **details,
        )
        return self._failed_handoff_result(safe_reason)

    async def activate_pending(self, *, start_process: bool = True) -> InstallResult:
        """由外部启动器在旧进程退出后调用，原子激活 pending 制品。"""

        async with self._operation_lock:
            pending = self.layout.read_pending()
            if pending is None:
                raise NoUpdateAvailable("没有待激活版本")
            target_version = parse_version(pending["version"])
            target_path = Path(str(pending["path"])).resolve()
            self.layout._validate_version_path(target_path)
            target = ReleasePointer(target_version, target_path)
            recovery = self._activation_recovery(pending)
            old = self.layout.read_active()
            previous_before = self.layout.read_previous()
            if old is None:
                old = self._snapshot_current()
                self.layout.write_pointer(old.path, old.version)
            already_active = self._same_pointer(old, target)
            if old.path == target.path and not already_active:
                raise UpgradeConfigError("active 指针与待安装版本路径冲突")
            if already_active:
                if recovery is None or recovery.path == target.path:
                    raise UpgradeConfigError(
                        "active 已指向待安装版本，但 pending 的旧版本恢复信息无效"
                    )
                source = recovery
            else:
                source = old
                # 先把恢复指针写入 pending，再替换 active。这样 active 已切换
                # 但整理尚未完成时，下一次启动仍能恢复到真正的旧版本。
                self._write_activation_recovery(pending, source)
            self.audit.record(
                "install",
                current_version=source.version,
                target_version=target_version,
                result="started",
                target_path=str(target_path),
            )
            process = None
            try:
                # active.json 的替换是唯一切换点；应用根目录从不被覆盖。
                if not already_active:
                    self.layout.write_pointer(target_path, target_version)
                if start_process and self.launcher is not None:
                    process = await self.launcher.start(target_path)
                if not await self._health(
                    target_path, phase="post-switch", process=process
                ):
                    raise HealthCheckFailed("切换后的健康检查未通过")
            except Exception as exc:
                _terminate_process(process)
                self.layout.write_pointer(source.path, source.version)
                if previous_before is None:
                    self.layout.clear_previous()
                else:
                    self.layout.write_pointer(
                        previous_before.path,
                        previous_before.version,
                        previous=True,
                    )
                self.layout.clear_pending()
                self.layout.clear_handoff()
                reason = str(exc) or exc.__class__.__name__
                self.audit.record(
                    "install",
                    current_version=source.version,
                    target_version=target_version,
                    result="failed",
                    error=reason,
                )
                self.audit.record(
                    "rollback",
                    current_version=target_version,
                    target_version=source.version,
                    result="success",
                    reason="post-switch health check failed",
                )
                return InstallResult(False, target_version, source.path, True, reason)

            self.layout.write_pointer(source.path, source.version, previous=True)
            self.layout.clear_pending()
            self.layout.clear_handoff()
            self.audit.record(
                "install",
                current_version=source.version,
                target_version=target_version,
                result="success",
                active_path=str(target_path),
                previous_path=str(source.path),
            )
            return InstallResult(True, target_version, target_path, False, "升级已激活")

    async def _apply_rollback_unlocked(
        self,
        *,
        handoff: Mapping[str, Any] | None = None,
        start_process: bool = True,
    ) -> RollbackResult:
        previous = self.layout.read_previous()
        current = self.layout.read_active()
        if previous is None:
            raise NoRollbackAvailable("没有可回滚的上一可用版本")
        if current is None:
            raise UpgradeConfigError("回滚前缺少 active 指针")
        source = self._rollback_source(handoff, current, previous)
        already_active = self._same_pointer(current, previous)
        if handoff is None:
            handoff = self._rollback_handoff(None, previous, source)
        else:
            handoff = self._rollback_handoff(handoff, previous, source)
        process = None
        try:
            if not already_active:
                self.layout.write_pointer(previous.path, previous.version)
            if start_process and self.launcher is not None:
                process = await self.launcher.start(previous.path)
            if not await self._health(previous.path, phase="rollback", process=process):
                raise HealthCheckFailed("回滚后的健康检查未通过")
        except Exception as exc:
            _terminate_process(process)
            self.layout.write_pointer(source.path, source.version)
            failed_handoff, quarantine_error = self._discard_live_handoff(isolate=True)
            reason = str(exc) or exc.__class__.__name__
            details: dict[str, Any] = {
                "error": _redact_text(reason),
                "failed_handoff_path": (
                    str(failed_handoff) if failed_handoff else None
                ),
            }
            if quarantine_error:
                details["quarantine_error"] = quarantine_error
            self.audit.record(
                "rollback",
                current_version=source.version,
                target_version=previous.version,
                result="failed",
                **details,
            )
            return RollbackResult(
                False,
                previous.version,
                previous.path,
                True,
                _redact_text(reason),
            )
        self.layout.write_pointer(source.path, source.version, previous=True)
        self.layout.clear_pending()
        self.layout.clear_handoff()
        self.audit.record(
            "rollback",
            current_version=source.version,
            target_version=previous.version,
            result="success",
            active_path=str(previous.path),
            previous_path=str(source.path),
        )
        return RollbackResult(
            True, previous.version, previous.path, True, "已回滚到上一版本"
        )

    async def apply_handoff(
        self, *, start_process: bool = True
    ) -> InstallResult | RollbackResult:
        """应用外部启动器写入的 activate/rollback 记录。"""

        try:
            handoff = self.layout.read_handoff()
        except UpgradeConfigError as exc:
            return self._quarantine_handoff(str(exc))
        if handoff is None:
            raise UpgradeConfigError("没有待处理的 handoff")
        action = handoff.get("action")
        if action == "activate":
            try:
                pending = self.layout.read_pending()
                if pending is None or not self._record_matches_pointer(
                    handoff,
                    self._pointer_from_data(pending, label="pending 升级记录"),
                    label="activate handoff",
                ):
                    raise UpgradeConfigError("activate handoff 与 pending 记录不一致")
            except UpgradeConfigError as exc:
                return self._quarantine_handoff(
                    str(exc), action=action, clear_pending=True
                )
            try:
                return await self.activate_pending(start_process=start_process)
            except UpdaterError as exc:
                return self._quarantine_handoff(
                    str(exc), action=action, clear_pending=True
                )
        if action == "rollback":
            try:
                previous = self.layout.read_previous()
                if previous is None or not self._record_matches_pointer(
                    handoff, previous, label="rollback handoff"
                ):
                    raise UpgradeConfigError("rollback handoff 与上一版本指针不一致")
            except UpgradeConfigError as exc:
                return self._quarantine_handoff(str(exc), action=action)
            try:
                async with self._operation_lock:
                    return await self._apply_rollback_unlocked(
                        handoff=handoff,
                        start_process=start_process,
                    )
            except UpdaterError as exc:
                return self._quarantine_handoff(str(exc), action=action)
        return self._quarantine_handoff(
            f"未知 handoff action: {_redact_text(action)!r}", action=action
        )

    async def run_policy(self) -> CheckResult | PrepareResult | HandoffResult:
        """执行配置化自动策略，供 Ready/周期任务调用。"""

        checked = await self.check()
        if not checked.candidate or self.policy is UpdatePolicy.CHECK_ONLY:
            return checked
        prepared = await self.prepare(checked.candidate)
        if self.policy is UpdatePolicy.AUTO_DOWNLOAD:
            return prepared
        return await self.request_install()

    @classmethod
    def from_config(
        cls,
        config: Any,
        *,
        project_root: str | Path | None = None,
    ) -> UpgradeManager:
        """从 ``tenko.config.UpgradeConfig`` 构造真实运行时实例。

        ``data_dir`` 仅供自定义健康/启动命令使用，是外部业务目录；它与
        Tenko 应用自身位于 ``.tenko/`` 下的持久化数据无关。
        """

        root = Path(project_root or Path.cwd()).expanduser().resolve()
        current = config.current_version or read_project_version(root)
        source_name = config.source.strip().lower().replace("-", "_")
        if source_name in {"git", "git_tag", "tag"}:
            source: VersionSource = GitTagSource(
                _normalize_git_repository(config.repository, root),
                tag_prefix=config.tag_prefix,
            )
        elif source_name in {"github", "github_release", "release"}:
            repository = config.github_repository or config.repository
            if repository in {"", "."}:
                raise UpgradeConfigError("github_release 需要 github_repository")
            source = GitHubReleaseSource(
                repository,
                token=config.github_token,
                asset_name=config.asset_name,
                tag_prefix=config.tag_prefix,
            )
        elif source_name in {"manifest", "url_manifest", "url"}:
            if not config.manifest_url:
                raise UpgradeConfigError("manifest 源需要 manifest_url")
            source = UrlManifestSource(
                config.manifest_url,
                tag_prefix=config.tag_prefix,
            )
        else:
            raise UpgradeConfigError(f"未知升级 source: {config.source!r}")

        configured_install_root = (
            os.environ.get("TENKO_UPGRADE_ROOT") or config.install_root
        )
        install_root = Path(configured_install_root).expanduser()
        if not install_root.is_absolute():
            install_root = root / install_root
        configured_config_path = (
            os.environ.get("TENKO_CONFIG_PATH") or config.config_path
        )
        config_path = Path(configured_config_path).expanduser()
        if not config_path.is_absolute():
            config_path = root / config_path
        configured_data_dir = os.environ.get("TENKO_DATA_DIR") or config.data_dir
        data_dir = Path(configured_data_dir).expanduser()
        if not data_dir.is_absolute():
            data_dir = root / data_dir
        layout = UpgradeLayout(install_root)
        health_checker = DefaultHealthChecker(
            config.health_command,
            timeout=config.health_timeout,
            config_path=config_path.resolve(),
            data_dir=data_dir.resolve(),
        )
        launcher = SubprocessLauncher(
            config.launch_command,
            config_path=config_path.resolve(),
            data_dir=data_dir.resolve(),
            upgrade_root=layout.root,
        )
        return cls(
            current,
            source,
            layout=layout,
            project_root=root,
            config_path=config_path,
            data_dir=data_dir,
            config_version=config.config_version,
            channel=config.channel,
            policy=config.policy,
            enabled=config.enabled,
            check_interval_hours=config.check_interval_hours,
            health_checker=health_checker,
            launcher=launcher,
        )


def _candidate_environment(candidate: Path) -> dict[str, str]:
    """让健康命令优先导入候选代码，而不是启动器所在的旧工作树。"""

    environment = os.environ.copy()
    existing_pythonpath = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = os.pathsep.join(
        value for value in (str(candidate), existing_pythonpath) if value
    )
    return environment


def _health_ok(value: HealthCheckResult | bool) -> bool:
    return value if isinstance(value, bool) else value.ok


def _health_reason(value: HealthCheckResult | bool) -> str:
    if isinstance(value, bool):
        return "健康检查返回 False"
    return value.reason


def _terminate_process(process: Any) -> None:
    if process is None:
        return
    poll = getattr(process, "poll", None)
    terminate = getattr(process, "terminate", None)
    if callable(poll) and callable(terminate) and poll() is None:
        terminate()


def _default_manager() -> UpgradeManager:
    try:
        version = read_project_version(Path.cwd())
    except UpgradeConfigError:
        version = Version(0, 0, 0)
    return UpgradeManager(
        version,
        layout=UpgradeLayout(Path(".tenko/upgrades")),
        enabled=False,
    )


_configured_manager = _default_manager()
_configured_permission_checker = PermissionChecker(registry=PermissionRegistry())


def configure_updater(
    manager: UpgradeManager,
    *,
    superuser_ids: Sequence[str | int] = (),
) -> None:
    """运行时在加载插件前注入管理器和升级命令的超级用户集合。"""

    global _configured_manager, _configured_permission_checker
    registry = PermissionRegistry()
    for user_id in superuser_ids:
        registry.set_user_level(None, user_id, Permission.Master)
    _configured_manager = manager
    _configured_permission_checker = PermissionChecker(registry=registry)


def get_upgrade_manager() -> UpgradeManager:
    return _configured_manager


def get_upgrade_permission_checker() -> PermissionChecker:
    return _configured_permission_checker
