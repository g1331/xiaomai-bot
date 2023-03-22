from sqlalchemy import Column, Integer, BIGINT, String, DateTime, ForeignKey, JSON

from core.orm import AsyncORM

bf1_orm = AsyncORM("sqlite+aiosqlite:///data/battlefield/BF1data.db")


# bf1账号表
class Bf1Account(bf1_orm.Base):
    """bf1账号信息"""

    __tablename__ = "bf1_account"

    # 固定
    persona_id = Column(BIGINT, primary_key=True)
    # 一般固定
    user_id = Column(BIGINT)
    # 变化
    name = Column(String)
    # 变化
    display_name = Column(String)

    remid = Column(String)
    sid = Column(String)
    session = Column(String)


# 用户绑定表
class Bf1PlayerBind(bf1_orm.Base):
    """bf1账号绑定信息"""

    __tablename__ = "bf1_player_bind"

    qq = Column(BIGINT, primary_key=True, unique=True)
    persona_id = Column(BIGINT, ForeignKey("bf1_account.persona_id"), nullable=False)


# 群组信息
class Bf1Group(bf1_orm.Base):
    """bf1群组信息"""

    __tablename__ = "bf1_group"
    id = Column(Integer, primary_key=True)
    group_name = Column(String, primary_key=True)
    bind_guids = Column(JSON)
    bind_manager_account_pids = Column(JSON)


class Bf1GroupBind(bf1_orm.Base):
    """bf1群组与QQ群绑定关系表"""
    __tablename__ = "bf1_group_bind"
    id = Column(Integer, primary_key=True)
    qq_group_id = Column(BIGINT, primary_key=True)
    bf1_group_id = Column(Integer, ForeignKey("bf1_group.id"), nullable=False)


# 服务器信息
class Bf1Server(bf1_orm.Base):
    """服务器信息"""

    __tablename__ = "bf1_server"
    id = Column(Integer, primary_key=True)
    serverId = Column(BIGINT, primary_key=True)
    persistedGameId = Column(String, primary_key=True)
    gameId = Column(BIGINT, nullable=False)
    createdDate = Column(BIGINT, nullable=False)
    expirationDate = Column(BIGINT, nullable=False)
    updatedDate = Column(BIGINT, nullable=False)
    time = Column(DateTime, nullable=False)


# 服管日志
class Bf1ManagerLog(bf1_orm.Base):
    """服务器信息"""

    __tablename__ = "bf1_manager_log"
    id = Column(Integer, primary_key=True)
    serverId = Column(BIGINT, primary_key=True)
    persistedGameId = Column(String, primary_key=True)
    gameId = Column(BIGINT, nullable=False)
    # 固定
    persona_id = Column(BIGINT, primary_key=True)
    # 变化
    display_name = Column(String)
    time = Column(DateTime, nullable=False)
