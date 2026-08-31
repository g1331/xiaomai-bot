"""与旧 ``core/orm/tables.py`` 同构的 Tenko SQLAlchemy 模型。"""

from __future__ import annotations

try:
    from entari_plugin_database import BaseOrm, Mapped, mapped_column
except (AttributeError, ImportError, LookupError) as error:  # pragma: no cover
    from .errors import DatabaseUnavailableError

    raise DatabaseUnavailableError(
        "官方 entari-plugin-database 尚未加载，无法注册 Tenko 数据模型"
    ) from error

from sqlalchemy import Boolean, Integer, String

from .migration import LEGACY_SCHEMA_REVISION


class MemberPerm(BaseOrm):
    """成员权限；``group_id=0`` 表示全局权限记录。"""

    __tablename__ = "MemberPerm"
    __revision__ = LEGACY_SCHEMA_REVISION

    group_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    qq: Mapped[int] = mapped_column(Integer, primary_key=True)
    perm: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        info={"check": [-1, 0, 16, 32, 64, 128, 256]},
        default=16,
    )


class GroupPerm(BaseOrm):
    """群等级和启用状态。"""

    __tablename__ = "GroupPerm"
    __revision__ = LEGACY_SCHEMA_REVISION

    group_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_name: Mapped[str] = mapped_column(String(length=60), nullable=False)
    perm: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        info={"check": [0, 1, 2, 3]},
        default=1,
    )
    active: Mapped[bool] = mapped_column(Boolean, nullable=True, default=True)


class GroupSetting(BaseOrm):
    """群频控、响应账号和成员权限同步策略。"""

    __tablename__ = "GroupSetting"
    __revision__ = LEGACY_SCHEMA_REVISION

    group_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    frequency_limitation: Mapped[bool] = mapped_column(
        Boolean, nullable=True, default=True
    )
    response_type: Mapped[str] = mapped_column(
        String,
        nullable=True,
        info={"check": ["random", "deterministic"]},
        default="random",
    )
    permission_type: Mapped[str] = mapped_column(
        String,
        nullable=True,
        info={"check": ["default", "admin"]},
        default="default",
    )


MODEL_CLASSES = (
    MemberPerm,
    GroupPerm,
    GroupSetting,
)

__all__ = [
    "GroupPerm",
    "GroupSetting",
    "MODEL_CLASSES",
    "MemberPerm",
]
