from sqlalchemy import Column, Integer, BIGINT, String, DateTime, ForeignKey, JSON, Boolean

from core.orm import orm


# bf1账号表
class Bf1Account(orm.Base):
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
class Bf1PlayerBind(orm.Base):
    """bf1账号绑定信息"""

    __tablename__ = "bf1_player_bind"

    qq = Column(BIGINT, primary_key=True, unique=True)
    persona_id = Column(BIGINT, ForeignKey("bf1_account.persona_id"), nullable=False)


# 群组信息
class Bf1Group(orm.Base):
    """bf1群组信息"""

    __tablename__ = "bf1_group"
    id = Column(Integer, primary_key=True)
    group_name = Column(String, primary_key=True)
    bind_guids = Column(JSON)
    bind_manager_account_pids = Column(JSON)


class Bf1GroupBind(orm.Base):
    """bf1群组与QQ群绑定关系表"""
    __tablename__ = "bf1_group_bind"
    id = Column(Integer, primary_key=True)
    qq_group_id = Column(BIGINT, primary_key=True)
    bf1_group_id = Column(Integer, ForeignKey("bf1_group.id"), nullable=False)


# 服务器信息
class Bf1Server(orm.Base):
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
class Bf1ManagerLog(orm.Base):
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


# 对局缓存
class Bf1MatchCache(orm.Base):
    """记录对局id、服务器名、地图名、模式名、对局时间、队伍名、队伍胜负情况、玩家id、击杀、死亡、kd、命中、爆头、游玩时长"""

    __tablename__ = "bf1_match_cache"
    id = Column(Integer, primary_key=True)
    match_id = Column(BIGINT, primary_key=False)

    server_name = Column(String, nullable=False)
    map_name = Column(String, nullable=False)
    mode_name = Column(String, nullable=False)

    time = Column(DateTime, nullable=False)

    team_name = Column(String, nullable=False)
    team_win = Column(Boolean, nullable=False)

    persona_id = Column(BIGINT, nullable=True)
    display_name = Column(String(collation='NOCASE'), nullable=False)

    kills = Column(Integer, nullable=False)
    deaths = Column(Integer, nullable=False)
    kd = Column(Integer, nullable=False)
    kpm = Column(Integer, nullable=False)

    score = Column(Integer, nullable=False)
    spm = Column(Integer, nullable=False)

    accuracy = Column(String, nullable=False)
    headshots = Column(String, nullable=False)
    time_played = Column(Integer, nullable=False)
