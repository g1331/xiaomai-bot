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
from sqlalchemy.orm import Mapped
from core.orm import orm


# bf1账号表
class Bf1Account(orm.Base):
    """bf1账号信息"""

    __tablename__ = "bf1_account"

    id: Mapped[int] = Column(Integer, primary_key=True)
    # 固定
    persona_id: Mapped[int] = Column(BIGINT)
    # 一般固定
    user_id: Mapped[int] = Column(BIGINT)
    # 变化
    name: Mapped[str | None] = Column(String)
    # 变化
    display_name: Mapped[str | None] = Column(String)

    remid: Mapped[str | None] = Column(String)
    sid: Mapped[str | None] = Column(String)
    session: Mapped[str | None] = Column(String)


# 用户绑定表
class Bf1PlayerBind(orm.Base):
    """bf1账号绑定信息"""

    __tablename__ = "bf1_player_bind"

    qq: Mapped[int] = Column(BIGINT, primary_key=True, unique=True)
    persona_id: Mapped[int] = Column(
        BIGINT, ForeignKey("bf1_account.persona_id"), nullable=False
    )


# 群组信息
class Bf1Group(orm.Base):
    """bf1群组信息"""

    __tablename__ = "bf1_group"

    id: Mapped[int] = Column(Integer, primary_key=True)
    group_name: Mapped[str] = Column(String, unique=True)
    bind_ids: Mapped[list[dict[str, str]]] = Column(JSON)
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

    id: Mapped[int] = Column(Integer, primary_key=True)
    group_id: Mapped[int] = Column(Integer, ForeignKey("bf1_group.id"), nullable=False)
    qq_group: Mapped[int] = Column(BIGINT, nullable=False)


# 服务器信息
class Bf1Server(orm.Base):
    """服务器信息"""

    __tablename__ = "bf1_server"

    id: Mapped[int] = Column(Integer, primary_key=True)
    # 服务器名称(变化)
    serverName: Mapped[str | None] = Column(String)
    # 服务器serverId(唯一标识)
    serverId: Mapped[int] = Column(BIGINT, unique=True)
    # 服务器guid(唯一标识)
    persistedGameId: Mapped[str | None] = Column(String)
    # gameid(变化)
    gameId: Mapped[int] = Column(BIGINT, nullable=False)
    createdDate: Mapped[DateTime] = Column(DateTime, nullable=False)
    expirationDate: Mapped[DateTime] = Column(DateTime, nullable=False)
    updatedDate: Mapped[DateTime] = Column(DateTime, nullable=False)
    record_time: Mapped[DateTime] = Column(DateTime, nullable=False)


# 服务器人数变化记录表
class Bf1ServerPlayerCount(orm.Base):
    """服务器人数信息变化记录表"""

    __tablename__ = "bf1_server_player_count"

    id: Mapped[int] = Column(Integer, primary_key=True)
    serverId: Mapped[int] = Column(
        BIGINT, ForeignKey("bf1_server.serverId"), nullable=False
    )
    playerCurrent: Mapped[int] = Column(Integer, nullable=False)
    playerMax: Mapped[int] = Column(Integer, nullable=False)
    playerQueue: Mapped[int] = Column(Integer, nullable=False)
    playerSpectator: Mapped[int] = Column(Integer, nullable=False)
    time: Mapped[DateTime] = Column(DateTime, nullable=False)
    # 收藏
    serverBookmarkCount: Mapped[int] = Column(BIGINT, default=False)


# VIP表
class Bf1ServerVip(orm.Base):
    """VIP表"""

    __tablename__ = "bf1_server_vip"

    id: Mapped[int] = Column(Integer, primary_key=True)
    serverId: Mapped[int] = Column(
        BIGINT, ForeignKey("bf1_server.serverId"), nullable=False
    )
    personaId: Mapped[int] = Column(
        BIGINT, ForeignKey("bf1_account.persona_id"), nullable=False
    )
    displayName: Mapped[str] = Column(String, nullable=False)
    expire_time: Mapped[DateTime | None] = Column(DateTime, default=None)
    time: Mapped[DateTime] = Column(DateTime)


# Ban表
class Bf1ServerBan(orm.Base):
    """Ban表"""

    __tablename__ = "bf1_server_ban"

    id: Mapped[int] = Column(Integer, primary_key=True)
    serverId: Mapped[int] = Column(
        BIGINT, ForeignKey("bf1_server.serverId"), nullable=False
    )
    personaId: Mapped[int] = Column(
        BIGINT, ForeignKey("bf1_account.persona_id"), nullable=False
    )
    displayName: Mapped[str] = Column(String, nullable=False)
    expire_time: Mapped[DateTime | None] = Column(DateTime, default=None)
    time: Mapped[DateTime] = Column(DateTime)


# 管理员表
class Bf1ServerAdmin(orm.Base):
    """管理员表"""

    __tablename__ = "bf1_server_admin"

    id: Mapped[int] = Column(Integer, primary_key=True)
    serverId: Mapped[int] = Column(
        BIGINT, ForeignKey("bf1_server.serverId"), nullable=False
    )
    personaId: Mapped[int] = Column(
        BIGINT, ForeignKey("bf1_account.persona_id"), nullable=False
    )
    displayName: Mapped[str] = Column(String, nullable=False)
    time: Mapped[DateTime] = Column(DateTime)


# 服主表
class Bf1ServerOwner(orm.Base):
    """服主表"""

    __tablename__ = "bf1_server_owner"

    id: Mapped[int] = Column(Integer, primary_key=True)
    serverId: Mapped[int] = Column(
        BIGINT, ForeignKey("bf1_server.serverId"), nullable=False
    )
    personaId: Mapped[int] = Column(
        BIGINT, ForeignKey("bf1_account.persona_id"), nullable=False
    )
    displayName: Mapped[str] = Column(String, nullable=False)
    time: Mapped[DateTime] = Column(DateTime)


# 服管日志
class Bf1ManagerLog(orm.Base):
    """服务器管理日志"""

    __tablename__ = "bf1_manager_log"

    id: Mapped[int] = Column(Integer, primary_key=True)
    # 操作者的qq
    operator_qq: Mapped[int] = Column(BIGINT)
    # 服务器信息
    serverId: Mapped[int] = Column(BIGINT)
    persistedGameId: Mapped[str | None] = Column(String)
    gameId: Mapped[int] = Column(BIGINT, nullable=False)
    # 固定
    persona_id: Mapped[int] = Column(BIGINT)
    # 变化
    display_name: Mapped[str | None] = Column(String)
    # 操作
    action: Mapped[str | None] = Column(String)
    # 信息
    info: Mapped[str | None] = Column(String)
    # 时间
    time: Mapped[DateTime] = Column(DateTime)


# 对局缓存
class Bf1MatchCache(orm.Base):
    """
    记录对局 id、服务器名、地图名、模式名、对局时间、
    队伍名、队伍胜负情况、玩家 id、击杀、死亡、kd、命中、爆头、游玩时长
    """

    __tablename__ = "bf1_match_cache"

    id: Mapped[int] = Column(Integer, primary_key=True)
    match_id: Mapped[str] = Column(String)
    server_name: Mapped[str] = Column(String, nullable=False)
    map_name: Mapped[str] = Column(String, nullable=False)
    mode_name: Mapped[str] = Column(String, nullable=False)
    time: Mapped[DateTime] = Column(DateTime, nullable=False)
    team_name: Mapped[str] = Column(String, nullable=False)
    team_win: Mapped[int] = Column(Integer, nullable=False)
    persona_id: Mapped[int | None] = Column(BIGINT, nullable=True)
    display_name: Mapped[str] = Column(String(collation="NOCASE"), nullable=False)
    kills: Mapped[int] = Column(Integer, nullable=False)
    deaths: Mapped[int] = Column(Integer, nullable=False)
    kd: Mapped[int] = Column(Integer, nullable=False)
    kpm: Mapped[int] = Column(Integer, nullable=False)
    score: Mapped[int] = Column(Integer, nullable=False)
    spm: Mapped[int] = Column(Integer, nullable=False)
    accuracy: Mapped[str] = Column(String, nullable=False)
    headshots: Mapped[str] = Column(String, nullable=False)
    time_played: Mapped[int] = Column(Integer, nullable=False)


class Bf1MatchIdCache(orm.Base):
    """记录无效对局 id"""

    __tablename__ = "bf1_match_id_cache"

    id: Mapped[int] = Column(Integer, primary_key=True)
    match_id: Mapped[str] = Column(String, nullable=False)


# 权限组绑定
class Bf1PermGroupBind(orm.Base):
    """
    一个群只能绑定一个权限组
    """

    __tablename__ = "bf1_perm_group_bind"

    id: Mapped[int] = Column(Integer, primary_key=True)
    qq_group_id: Mapped[int] = Column(BIGINT, nullable=False, unique=True)
    bf1_group_name: Mapped[str] = Column(String, nullable=False)


class Bf1PermMemberInfo(orm.Base):
    __tablename__ = "bf1_perm_member_info"

    id: Mapped[int] = Column(Integer, primary_key=True)
    qq_id: Mapped[int] = Column(BIGINT, nullable=False)
    bf1_group_name: Mapped[str] = Column(String, nullable=False)
    # 0: 管理员 1: 服主
    perm: Mapped[int] = Column(BIGINT, nullable=False)


class Bf1ServerManagerVip(orm.Base):
    """VIP 表，用于记录服管 VIP 信息"""

    __tablename__ = "bf1_server_manager_vip"

    id: Mapped[int] = Column(Integer, primary_key=True)
    serverId: Mapped[int] = Column(
        BIGINT, ForeignKey("bf1_server.serverId"), nullable=False
    )
    personaId: Mapped[int] = Column(
        BIGINT, ForeignKey("bf1_account.persona_id"), nullable=False
    )
    displayName: Mapped[str] = Column(String, nullable=False)
    expire_time: Mapped[DateTime | None] = Column(DateTime, default=None)
    valid: Mapped[bool] = Column(Boolean, default=True)
    time: Mapped[DateTime] = Column(DateTime)
