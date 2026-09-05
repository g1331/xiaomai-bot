"""有界日志读取；仅允许官方日志目录中的普通日志文件。"""

from __future__ import annotations

import gzip
import re
import threading
import zipfile
from collections import deque
from pathlib import Path
from collections.abc import Callable


class LogReader:
    def __init__(self, secrets: Callable[[], tuple[str, ...]]) -> None:
        self.secrets = secrets
        self.records: deque[dict] = deque(maxlen=1000)
        self.sequence = 0
        self.lock = threading.Lock()

    def redact(self, text: str) -> str:
        for value in sorted(self.secrets(), key=len, reverse=True):
            if value:
                text = text.replace(value, "[REDACTED]")
        text = re.sub(r"(?i)(bearer\s+)\S+", r"\1[REDACTED]", text)
        return re.sub(
            r"""(?i)((?:access_token|admin_token|satori_token|token|password)["']?\s*[:=]\s*["']?)[^\s,"'&}]+""",
            r"\1[REDACTED]",
            text,
        )

    def sink(self, message) -> None:
        record = message.record
        if record.get("name") == "uvicorn.access" and "/webui" in record["message"]:
            return
        text = self.redact(record["message"])[:4000]
        with self.lock:
            self.sequence += 1
            self.records.append(
                {
                    "id": self.sequence,
                    "time": record["time"].isoformat(),
                    "level": record["level"].name,
                    "message": text,
                }
            )

    def live(self, after: int, query: str, level: str) -> dict:
        with self.lock:
            rows = list(self.records)
            cursor = self.sequence
        return {
            "records": [
                row
                for row in rows
                if row["id"] > after
                and query.casefold() in row["message"].casefold()
                and (not level or row["level"] == level)
            ],
            "cursor": cursor,
            "reset": after > cursor,
            "truncated": bool(rows and after and after < rows[0]["id"] - 1),
        }

    @staticmethod
    def files(directory: Path | None) -> list[str]:
        if directory is None or not directory.is_dir():
            return []
        return sorted(
            (
                p.name
                for p in directory.iterdir()
                if not p.is_symlink()
                and p.is_file()
                and (
                    p.name.endswith(".log")
                    or p.name.endswith(".log.gz")
                    or p.name.endswith(".log.zip")
                )
            ),
            reverse=True,
        )

    def history(self, directory: Path | None, name: str, query: str) -> dict:
        if directory is None or name not in self.files(directory):
            raise ValueError("日志文件不存在或不可读取")
        path = directory / name
        # ponytail: 每个文件最多扫描 8 MiB；日志规模增长后改为索引检索。
        maximum = 8 * 1024 * 1024
        if name.endswith(".gz"):
            with gzip.open(path, "rb") as stream:
                data = stream.read(maximum + 1)
        elif name.endswith(".zip"):
            with zipfile.ZipFile(path) as archive:
                names = archive.namelist()
                if len(names) != 1:
                    raise ValueError("压缩日志必须只包含一个文件")
                with archive.open(names[0]) as stream:
                    data = stream.read(maximum + 1)
        else:
            with path.open("rb") as stream:
                data = stream.read(maximum + 1)
        lines = self.redact(
            data[:maximum].decode("utf-8", errors="replace")
        ).splitlines()
        matches = [line[:4000] for line in lines if query.casefold() in line.casefold()]
        return {
            "lines": matches[-500:],
            "truncated": len(data) > maximum or len(matches) > 500,
            "matched": len(matches),
            "scan_limit_bytes": maximum,
        }
