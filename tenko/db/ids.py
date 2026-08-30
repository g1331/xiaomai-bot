"""旧数据库整数 ID 与 Satori ID 之间的边界转换。"""

from __future__ import annotations

import re

from .errors import DatabaseIdentifierError

_ID_PATTERN = re.compile(r"^[0-9]+$")
_SQLITE_INTEGER_MAX = 2**63 - 1


def to_database_id(value: str | int, label: str) -> int:
    """将 QQ/群号等 Satori ID 转换为旧表使用的 ``INTEGER``。

    旧表中的 QQ 号和群号都是纯数字；不接受 Discord 风格或其他平台的
    非数字 ID，以免在 repository 边界静默产生错误的授权记录。
    """

    if isinstance(value, bool) or not isinstance(value, str | int):
        raise DatabaseIdentifierError(f"{label}必须是纯数字 ID，收到 {value!r}")
    normalized = str(value)
    if not _ID_PATTERN.fullmatch(normalized):
        raise DatabaseIdentifierError(f"{label}必须是纯数字 ID，收到 {value!r}")
    result = int(normalized)
    if result > _SQLITE_INTEGER_MAX:
        raise DatabaseIdentifierError(f"{label}超出 SQLite INTEGER 范围: {value!r}")
    return result
