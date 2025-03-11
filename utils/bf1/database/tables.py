from sqlalchemy import (
    Column,
    Integer,
    BIGINT,
    String,
    DateTime,
    ForeignKey,
    JSON,
    Boolean,
)

from core.orm import orm


# bf1账号表
class Bf1Account(orm.Base):
    """bf1账号信息"""

    __tablename__ = "bf1_account"

    id = Column(Integer, primary_key=True)
    # 固定
    persona_id = Column(BIGINT)
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
    group_name = Column(String, unique=True)
    bind_ids = Column(JSON)
    # bind_ids格式: [
    #       {
    #           "guid": "guid",
    #           "gameId": "gameId",
    #           "serverId": "serverId",
    #           "account": "account",
    #       }
    #   ]


class Bf1GroupBind(orm.Base):
    """bf1群组绑定信息"""

    __tablename__ = "bf1_group_bind"
    id = Column(Integer, primary_key=True)
    group_id = Column(Integer, ForeignKey("bf1_group.id"), nullable=False)
    qq_group = Column(BIGINT, nullable=False)


# 服务器信息
class Bf1Server(orm.Base):
    """服务器信息"""

    __tablename__ = "bf1_server"
    id = Column(Integer, primary_key=True)
    # 服务器名称(变化)
    serverName = Column(String)
    # 服务器serverId(唯一标识)
    serverId = Column(BIGINT, unique=True)
    # 服务器guid(唯一标识)
    persistedGameId = Column(String)
    # gameid(变化)
    gameId = Column(BIGINT, nullable=False)
    createdDate = Column(DateTime, nullable=False)
    expirationDate = Column(DateTime, nullable=False)
    updatedDate = Column(DateTime, nullable=False)
    record_time = Column(DateTime, nullable=False)


# 服务器人数变化记录表
class Bf1ServerPlayerCount(orm.Base):
    """服务器人数信息变化记录表"""

    __tablename__ = "bf1_server_player_count"
    id = Column(Integer, primary_key=True)
    serverId = Column(BIGINT, ForeignKey("bf1_server.serverId"), nullable=False)
    playerCurrent = Column(Integer, nullable=False)
    playerMax = Column(Integer, nullable=False)
    playerQueue = Column(Integer, nullable=False)
    playerSpectator = Column(Integer, nullable=False)
    time = Column(DateTime, nullable=False)
    # 收藏
    serverBookmarkCount = Column(BIGINT, default=False)


#   Bf1Vip
class Bf1ServerVip(orm.Base):
    """VIP表"""

    __tablename__ = "bf1_server_vip"
    id = Column(Integer, primary_key=True)
    serverId = Column(BIGINT, ForeignKey("bf1_server.serverId"), nullable=False)
    personaId = Column(BIGINT, ForeignKey("bf1_account.persona_id"), nullable=False)
    displayName = Column(String, nullable=False)
    expire_time = Column(DateTime, default=None)
    time = Column(DateTime)


#   Ban
class Bf1ServerBan(orm.Base):
    """Ban表"""

    __tablename__ = "bf1_server_ban"
    id = Column(Integer, primary_key=True)
    serverId = Column(BIGINT, ForeignKey("bf1_server.serverId"), nullable=False)
    personaId = Column(BIGINT, ForeignKey("bf1_account.persona_id"), nullable=False)
    displayName = Column(String, nullable=False)
    expire_time = Column(DateTime, default=None)
    time = Column(DateTime)


#   Admin
class Bf1ServerAdmin(orm.Base):
    """管理员表"""

    __tablename__ = "bf1_server_admin"
    id = Column(Integer, primary_key=True)
    serverId = Column(BIGINT, ForeignKey("bf1_server.serverId"), nullable=False)
    personaId = Column(BIGINT, ForeignKey("bf1_account.persona_id"), nullable=False)
    displayName = Column(String, nullable=False)
    time = Column(DateTime)


#   Owner
class Bf1ServerOwner(orm.Base):
    """服主表"""

    __tablename__ = "bf1_server_owner"
    id = Column(Integer, primary_key=True)
    serverId = Column(BIGINT, ForeignKey("bf1_server.serverId"), nullable=False)
    personaId = Column(BIGINT, ForeignKey("bf1_account.persona_id"), nullable=False)
    displayName = Column(String, nullable=False)
    time = Column(DateTime)


# 服管日志
class Bf1ManagerLog(orm.Base):
    """服务器信息"""

    __tablename__ = "bf1_manager_log"
    id = Column(Integer, primary_key=True)
    # 操作者的qq
    operator_qq = Column(BIGINT)
    # 服务器信息
    serverId = Column(BIGINT)
    persistedGameId = Column(String)
    gameId = Column(BIGINT, nullable=False)
    # 固定
    persona_id = Column(BIGINT)
    # 变化
    display_name = Column(String)
    # 操作
    action = Column(String)
    # 信息
    info = Column(String)
    # 时间
    time = Column(DateTime)


# 对局缓存
class Bf1MatchCache(orm.Base):
    """记录对局id、服务器名、地图名、模式名、对局时间、队伍名、队伍胜负情况、玩家id、击杀、死亡、kd、命中、爆头、游玩时长"""

    __tablename__ = "bf1_match_cache"
    id = Column(Integer, primary_key=True)
    match_id = Column(String)

    server_name = Column(String, nullable=False)
    map_name = Column(String, nullable=False)
    mode_name = Column(String, nullable=False)

    time = Column(DateTime, nullable=False)

    team_name = Column(String, nullable=False)
    team_win = Column(Integer, nullable=False)

    persona_id = Column(BIGINT, nullable=True)
    display_name = Column(String(collation="NOCASE"), nullable=False)

    kills = Column(Integer, nullable=False)
    deaths = Column(Integer, nullable=False)
    kd = Column(Integer, nullable=False)
    kpm = Column(Integer, nullable=False)

    score = Column(Integer, nullable=False)
    spm = Column(Integer, nullable=False)

    accuracy = Column(String, nullable=False)
    headshots = Column(String, nullable=False)
    time_played = Column(Integer, nullable=False)


class Bf1MatchIdCache(orm.Base):
    """记录无效对局id"""

    __tablename__ = "bf1_match_id_cache"
    id = Column(Integer, primary_key=True)
    match_id = Column(String, nullable=False)


# 权限
class Bf1PermGroupBind(orm.Base):
    """
    一个群只能绑定一个权限组
    """

    __tablename__ = "bf1_perm_group_bind"
    id = Column(Integer, primary_key=True)
    qq_group_id = Column(BIGINT, nullable=False, unique=True)
    bf1_group_name = Column(String, nullable=False)


class Bf1PermMemberInfo(orm.Base):
    __tablename__ = "bf1_perm_member_info"
    id = Column(Integer, primary_key=True)
    qq_id = Column(BIGINT, nullable=False)
    bf1_group_name = Column(String, nullable=False)
    # 0:管理员 1:服主
    perm = Column(BIGINT, nullable=False)


class Bf1ServerManagerVip(orm.Base):
    """VIP表,用于记录服管vip信息"""

    __tablename__ = "bf1_server_manager_vip"
    id = Column(Integer, primary_key=True)
    serverId = Column(BIGINT, ForeignKey("bf1_server.serverId"), nullable=False)
    personaId = Column(BIGINT, ForeignKey("bf1_account.persona_id"), nullable=False)
    displayName = Column(String, nullable=False)
    expire_time = Column(DateTime, default=None)
    valid = Column(Boolean, default=True)
    time = Column(DateTime)
