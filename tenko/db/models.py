"""与旧 ``core/orm/tables.py`` 同构的 Tenko SQLAlchemy 模型。"""

from __future__ import annotations

from datetime import datetime

try:
    from entari_plugin_database import BaseOrm, Mapped, mapped_column
except (AttributeError, ImportError, LookupError) as error:  # pragma: no cover
    from .errors import DatabaseUnavailableError

    raise DatabaseUnavailableError(
        "官方 entari-plugin-database 尚未加载，无法注册 Tenko 数据模型"
    ) from error

from sqlalchemy import BIGINT, Boolean, DateTime, Integer, String, Text

_SCHEMA_REVISION = "tenko-g1-legacy-schema-v1"


class MemberPerm(BaseOrm):
    """成员权限；``group_id=0`` 表示全局权限记录。"""

    __tablename__ = "MemberPerm"
    __revision__ = _SCHEMA_REVISION

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
    __revision__ = _SCHEMA_REVISION

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
    __revision__ = _SCHEMA_REVISION

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


class ChatRecord(BaseOrm):
    """聊天记录表；G1 只保留结构，不接入业务写入。"""

    __tablename__ = "chat_record"
    __revision__ = _SCHEMA_REVISION

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    group_id: Mapped[int] = mapped_column(BIGINT, nullable=False)
    member_id: Mapped[int] = mapped_column(BIGINT, nullable=False)
    persistent_string: Mapped[str] = mapped_column(String(length=4000), nullable=False)
    seg: Mapped[str] = mapped_column(String(length=4000), nullable=False)


class KeywordReply(BaseOrm):
    """关键词回复表；G1 只保留结构，不接入业务写入。"""

    __tablename__ = "keyword_reply"
    __revision__ = _SCHEMA_REVISION

    keyword: Mapped[str] = mapped_column(String(length=200), primary_key=True)
    group: Mapped[int] = mapped_column(BIGINT, nullable=True, default=-1)
    reply_type: Mapped[str] = mapped_column(String(length=10), nullable=False)
    reply: Mapped[str] = mapped_column(Text, nullable=False)
    reply_md5: Mapped[str] = mapped_column(String(length=32), primary_key=True)


MODEL_CLASSES = (
    MemberPerm,
    GroupPerm,
    GroupSetting,
    ChatRecord,
    KeywordReply,
)

__all__ = [
    "ChatRecord",
    "GroupPerm",
    "GroupSetting",
    "KeywordReply",
    "MODEL_CLASSES",
    "MemberPerm",
]
