"""数据库边界使用的异常类型。"""


class DatabaseError(RuntimeError):
    """数据库操作失败。"""


class DatabaseUnavailableError(DatabaseError):
    """数据库插件、会话工厂或数据库连接当前不可用。"""


class DatabaseIdentifierError(ValueError):
    """Satori ID 无法转换为旧 schema 使用的整数 ID。"""


class InvalidPermissionError(ValueError):
    """成员权限值不在旧 schema 的允许值域内。"""


class InvalidGroupPermissionError(ValueError):
    """群等级不在旧 schema 的允许值域内。"""


class InvalidGroupSettingError(ValueError):
    """群设置值不在旧 schema 的允许值域内。"""
