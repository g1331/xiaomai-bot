from sqlalchemy import Column, Integer, String, Boolean, DateTime, BIGINT, Text

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

    group_id = Column(Integer, primary_key=True)
    qq = Column(Integer, primary_key=True)
    perm = Column(
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

    group_id = Column(Integer, primary_key=True)
    group_name = Column(String(length=60), nullable=False)
    perm = Column(Integer, nullable=False, info={"check": [0, 1, 2, 3]}, default=1)
    active = Column(Boolean, default=True)


class GroupSetting(orm.Base):
    """
    群设置
    """

    __tablename__ = "GroupSetting"

    group_id = Column(Integer, primary_key=True)
    # 频率限制
    frequency_limitation = Column(Boolean, default=True)
    # 多账户响应类型
    response_type = Column(
        String, info={"check": ["random", "deterministic"]}, default="random"
    )
    # 权限组类型
    permission_type = Column(
        String, info={"check": ["default", "admin"]}, default="default"
    )


class ChatRecord(orm.Base):
    """聊天记录表"""

    __tablename__ = "chat_record"

    id = Column(Integer, primary_key=True)
    time = Column(DateTime, nullable=False)
    group_id = Column(BIGINT, nullable=False)
    member_id = Column(BIGINT, nullable=False)
    persistent_string = Column(String(length=4000), nullable=False)
    seg = Column(String(length=4000), nullable=False)


class KeywordReply(orm.Base):
    """关键词回复"""

    __tablename__ = "keyword_reply"

    keyword = Column(String(length=200), primary_key=True)
    group = Column(BIGINT, default=-1)
    reply_type = Column(String(length=10), nullable=False)
    reply = Column(Text, nullable=False)
    reply_md5 = Column(String(length=32), primary_key=True)
