from sqlalchemy import Column, Integer, BIGINT, String, DateTime, ForeignKey, ARRAY
from sqlalchemy.orm import relationship

from core.orm import AsyncORM

bf1_orm = AsyncORM("data/battlefield/BF1data.db")


# bf1账号表
class Bf1Account(bf1_orm.Base):
    """bf1账号信息"""

    __tablename__ = "bf1_account"

    id = Column(Integer, primary_key=True)
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

    player_bind = relationship("Bf1PlayerBind", back_populates="bf1_account")

    @property
    def pid(self):
        return self.persona_id

    @pid.setter
    def pid(self, value):
        self.persona_id = value

    @property
    def uid(self):
        return self.user_id

    @uid.setter
    def uid(self, value):
        self.user_id = value


# 用户绑定表
class Bf1PlayerBind(bf1_orm.Base):
    """bf1账号绑定信息"""

    __tablename__ = "bf1_player_bind"

    id = Column(Integer, primary_key=True)
    qq = Column(BIGINT, primary_key=True, unique=True)
    persona_id = Column(BIGINT, ForeignKey("bf1_account.persona_id"), nullable=False)
    bf1_account = relationship("Bf1Account", back_populates="player_bind")

    @property
    def pid(self):
        return self.persona_id

    @pid.setter
    def pid(self, value):
        self.persona_id = value


# 群组信息
class Bf1Group(bf1_orm.Base):
    """bf1群组信息"""

    __tablename__ = "bf1_group"
    id = Column(Integer, primary_key=True)
    group_name = Column(String, primary_key=True)
    bind_guids = Column(ARRAY(String))
    bind_manager_account_pids = Column(ARRAY(BIGINT))
    bind_qq_groups = relationship("Bf1GroupBind", back_populates="bf1_group")


class Bf1GroupBind(bf1_orm.Base):
    """bf1群组与QQ群绑定关系表"""
    __tablename__ = "bf1_group_bind"
    id = Column(Integer, primary_key=True)
    qq_group_id = Column(BIGINT, primary_key=True)
    bf1_group_id = Column(Integer, ForeignKey("bf1_group.id"), nullable=False)
    bf1_group = relationship("Bf1Group", back_populates="bind_qq_groups")


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

    @property
    def guid(self):
        return self.persistedGameId

    @guid.setter
    def guid(self, value):
        self.persistedGameId = value
