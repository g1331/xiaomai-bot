from sqlalchemy import select

from utils.bf1.bf1_orm.tables import bf1_orm, bf1_player_bind


class bf1_db:

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

    @staticmethod
    async def get_pid_by_qq(qq):
        if bind := await bf1_orm.fetch_one(select(bf1_player_bind.personaId).where(bf1_player_bind.qq == qq)):
            return bind[0]
        else:
            return None

    @staticmethod
    async def get_qq_by_pid(pid):
        if bind := await bf1_orm.fetch_all(select(bf1_player_bind.qq).where(bf1_player_bind.personaId == pid)):
            return bind
        else:
            return None

    @staticmethod
    async def bind_player_qq(qq, pid):
        await bf1_orm.insert_or_update(
            table=bf1_player_bind,
            data={
                "personaId": pid,
                "qq": qq
            },
            condition=[
                bf1_player_bind.qq == qq
            ]
        )

    # TODO:
    #  服务器相关
    #  读:
    #  根据serverid/guid获取对应信息如gameid、
    #  写:
    #  从getFullServerDetails获取并写入服务器信息

    # TODO:
    #   bf群组相关
    #   读:
    #   根据qq来获取对应绑定的群组和guids
    #   根据对应guid获取服务器信息
    #   写:
    #   绑定qq群和群组名
