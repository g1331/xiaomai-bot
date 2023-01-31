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


# 绑定表
class bf1_player_bind(bf1_orm.Base):
    """bf1账号绑定信息"""

    __tablename__ = "bf1_player_bind"
    id = Column(Integer, primary_key=True)
    personaId = Column(BIGINT, nullable=False)
    qq = Column(BIGINT, primary_key=True)


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
    guid = Column(String, nullable=False, primary_key=True)
    gameId = Column(BIGINT, nullable=False)
    createdDate = Column(BIGINT, nullable=False)
    expirationDate = Column(BIGINT, nullable=False)
    updatedDate = Column(BIGINT, nullable=False)
    time = Column(DateTime, nullable=False)
    _persistedGameId = Column("persistedGameId", String, nullable=False)

    # 使用计算属性的方法,将persistedGameId的值绑定到guid上
    @property
    def persistedGameId(self):
        return self.guid

    @persistedGameId.setter
    def persistedGameId(self, value):
        self._persistedGameId = value

# TODO:
#  BF1账号相关
#  读：
#  根据pid获取玩家信息
#  根据pid获取session
#  写：
#  初始化写入玩家信息
#  根据pid写入remid和sid
#  根据pid写入session

# TODO:
#  绑定相关
#  读:
#  根据qq获取绑定的pid
#  根据pid获取绑定的qq
#  写:
#  写入绑定信息 qq-pid

# TODO:
#  服务器相关
#  读:
#  根据serverid/guid获取对应信息如gameid、
#  写:
#  从getFullServerDetails获取并写入服务器信息
