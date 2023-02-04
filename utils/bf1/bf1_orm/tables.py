from sqlalchemy import Column, Integer, BIGINT, String, DateTime

from core.orm import AsyncORM

bf1_orm = AsyncORM("data/battlefield/BF1data.db")


# bf1账号表
class bf1_account(bf1_orm.Base):
    """bf1账号信息"""

    __tablename__ = "bf1_account"

    id = Column(Integer, primary_key=True)
    personaId = Column(BIGINT, nullable=False, primary_key=True)
    userId = Column(BIGINT, nullable=False)
    name = Column(String)
    displayName = Column(String)
    remid = Column(String)
    sid = Column(String)
    session = Column(String)

    @property
    def pid(self):
        return self.personaId

    @pid.setter
    def pid(self, value):
        self.personaId = value

    @property
    def uid(self):
        return self.userId

    @uid.setter
    def uid(self, value):
        self.userId = value


# 用户绑定表
class bf1_player_bind(bf1_orm.Base):
    """bf1账号绑定信息"""

    __tablename__ = "bf1_player_bind"
    id = Column(Integer, primary_key=True)
    personaId = Column(BIGINT, nullable=False)
    qq = Column(BIGINT, primary_key=True)


# 群组绑定表
class bf1_group_bind(bf1_orm.Base):
    """bf1群组绑定信息"""

    __tablename__ = "bf1_group_bind"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False, primary_key=True)
    serverId = Column(BIGINT)


# 服务器信息表
class bf1_server(bf1_orm.Base):
    """服务器固定信息"""

    __tablename__ = "bf1_server"
    id = Column(Integer, primary_key=True)
    serverId = Column(BIGINT, nullable=False, primary_key=True)
    persistedGameId = Column(String, nullable=False, primary_key=True)
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