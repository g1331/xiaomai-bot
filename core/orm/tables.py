from sqlalchemy import Column, Integer, String, Boolean, DateTime, BIGINT, Text
from sqlalchemy.orm import Mapped

from core.orm import orm


class MemberPerm(orm.Base):
    """
    -1为全局黑 对应群号为0
    0为单群黑
    16为群员
    32为管理
    64为群主
    128为Admin
    256为Master
    """

    __tablename__ = "MemberPerm"

    group_id: Mapped[int] = Column(Integer, primary_key=True)
    qq: Mapped[int] = Column(Integer, primary_key=True)
    perm: Mapped[int] = Column(
        Integer,
        nullable=False,
        info={"check": [-1, 0, 16, 32, 64, 128, 256]},
        default=16,
    )


class GroupPerm(orm.Base):
    """
    0为非活动群组
    1为正常活动群组
    2为vip群组
    3为测试群组
    """

    __tablename__ = "GroupPerm"

    group_id: Mapped[int] = Column(Integer, primary_key=True)
    group_name: Mapped[str] = Column(String(length=60), nullable=False)
    perm: Mapped[int] = Column(
        Integer, nullable=False, info={"check": [0, 1, 2, 3]}, default=1
    )
    active: Mapped[bool] = Column(Boolean, default=True)


class GroupSetting(orm.Base):
    """
    群设置
    """

    __tablename__ = "GroupSetting"

    group_id: Mapped[int] = Column(Integer, primary_key=True)
    frequency_limitation: Mapped[bool] = Column(Boolean, default=True)
    response_type: Mapped[str] = Column(
        String, info={"check": ["random", "deterministic"]}, default="random"
    )
    permission_type: Mapped[str] = Column(
        String, info={"check": ["default", "admin"]}, default="default"
    )


class ChatRecord(orm.Base):
    """聊天记录表"""

    __tablename__ = "chat_record"

    id: Mapped[int] = Column(Integer, primary_key=True)
    time: Mapped[DateTime] = Column(DateTime, nullable=False)
    group_id: Mapped[int] = Column(BIGINT, nullable=False)
    member_id: Mapped[int] = Column(BIGINT, nullable=False)
    persistent_string: Mapped[str] = Column(String(length=4000), nullable=False)
    seg: Mapped[str] = Column(String(length=4000), nullable=False)


class KeywordReply(orm.Base):
    """关键词回复"""

    __tablename__ = "keyword_reply"

    keyword: Mapped[str] = Column(String(length=200), primary_key=True)
    group: Mapped[int] = Column(BIGINT, default=-1)
    reply_type: Mapped[str] = Column(String(length=10), nullable=False)
    reply: Mapped[str] = Column(Text, nullable=False)
    reply_md5: Mapped[str] = Column(String(length=32), primary_key=True)
