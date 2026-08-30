"""Tenko 的数据库边界。

该包不在导入时创建引擎。运行时必须先加载官方
``entari-plugin-database``，再由 ``bootstrap`` 注册模型和数据库服务；这样
没有数据库依赖时，权限宿主仍可以保留明确的降级路径。
"""

from .errors import (
    DatabaseError,
    DatabaseIdentifierError,
    DatabaseUnavailableError,
    InvalidGroupPermissionError,
    InvalidGroupSettingError,
    InvalidPermissionError,
)
from .ids import to_database_id

__all__ = [
    "DatabaseError",
    "DatabaseIdentifierError",
    "DatabaseUnavailableError",
    "InvalidGroupPermissionError",
    "InvalidGroupSettingError",
    "InvalidPermissionError",
    "to_database_id",
]
