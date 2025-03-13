from pathlib import Path

from graia.ariadne import Ariadne
from graia.ariadne.event.message import GroupMessage
from graia.ariadne.message import Source
from graia.ariadne.message.chain import MessageChain
from graia.ariadne.message.element import Image
from graia.ariadne.message.parser.twilight import (
    Twilight,
    ParamMatch,
    RegexResult,
    UnionMatch,
    SpacePolicy,
)
from graia.ariadne.model import Group
from graia.ariadne.util.saya import listen, decorate, dispatch
from graia.saya import Channel
from loguru import logger
from mcstatus import JavaServer

from core.control import Permission, Function, FrequencyLimitation, Distribute
from core.models import saya_model

module_controller = saya_model.get_module_controller()
channel = Channel.current()
channel.meta["name"] = "MiniCraftInfo"
channel.meta["description"] = "获取Minecraft服务器信息"
channel.meta["author"] = "13"
channel.metadata = module_controller.get_metadata_from_path(Path(__file__))


@listen(GroupMessage)
@dispatch(
    Twilight(
        [
            UnionMatch("/mcs").space(SpacePolicy.FORCE),
            ParamMatch(optional=False) @ "server_host",
        ]
    )
)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level, if_noticed=True),
    Permission.user_require(Permission.User, if_noticed=True),
)
async def server_info_handle(
    app: Ariadne, group: Group, source: Source, server_host: RegexResult
):
    server_host = server_host.result.display
    result = await get_minecraft_server_info(server_host)
    if isinstance(result, str):
        return await app.send_message(group, MessageChain(result), quote=source)
    img_base64 = result["favicon"]
    return await app.send_message(
        group,
        MessageChain(
            [
                f"服务器地址: {server_host}\n",
                Image(base64=img_base64[img_base64.find(",") + 1 :])
                if img_base64
                else "",
                f"描述:\n{result['description']}\n",
                f"游戏版本:{result['version']}\n",
                f"协议版本:{result['protocol']}\n",
                f"在线人数:{result['online_players']}/{result['max_players']}\n",
                f"ping:{result['ping']}ms",
            ]
        ),
        quote=source,
    )


@listen(GroupMessage)
@dispatch(
    Twilight(
        [
            UnionMatch("/mcpl").space(SpacePolicy.FORCE),
            ParamMatch(optional=False) @ "server_host",
        ]
    )
)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level, if_noticed=True),
    Permission.user_require(Permission.User, if_noticed=True),
)
async def server_player_handle(
    app: Ariadne, group: Group, source: Source, server_host: RegexResult
):
    server_host = server_host.result.display
    result = await get_minecraft_server_info(server_host)
    if isinstance(result, str):
        return await app.send_message(group, MessageChain(result), quote=source)

    if len(result["players"]) == 0:
        return await app.send_message(
            group, MessageChain("服务器没有在线玩家"), quote=source
        )

    # 最多显示15个玩家
    # 先排序
    result["players"].sort()
    if len(result["players"]) > 15:
        players_str = (
            "玩家列表:\n"
            + "\n".join([f"{player}" for player in result["players"][:15]])
            + "\n超长只显示前15个玩家"
        )
    else:
        players_str = "玩家列表:\n" + "\n".join(
            [f"{player}" for player in result["players"]]
        )

    img_base64 = result["favicon"]
    return await app.send_message(
        group,
        MessageChain(
            [
                f"服务器地址: {server_host}\n",
                Image(base64=img_base64[img_base64.find(",") + 1 :])
                if img_base64
                else "",
                f"在线人数:{result['online_players']}/{result['max_players']}\n",
                f"{players_str}",
            ]
        ),
        quote=source,
    )


async def get_minecraft_server_info(server_host: str) -> dict | str:
    """
    获取Minecraft服务器信息
    :param server_host: 服务器地址
    :return: 成功返回服务器信息-dict, 失败返回错误信息-str
    """
    try:
        server = await JavaServer.async_lookup(server_host)
        status = await server.async_status()
    except ConnectionRefusedError as e:
        logger.error(f"[MC查询]无法连接到服务器 {server_host}, {e}")
        return f"未能连接到服务器「{server_host}」"
    except TimeoutError as e:
        logger.error(f"[MC查询]连接服务器 {server_host} 超时, {e}")
        return f"连接服务器 {server_host} 超时"
    except ConnectionResetError as e:
        logger.error(f"[MC查询]连接服务器 {server_host} 被重置, {e}")
        return f"连接服务器 {server_host} 被重置"
    except OSError as e:
        logger.error(f"[MC查询]连接服务器 {server_host} 出现错误, {e}")
        return f"连接服务器 {server_host} 出现错误"

    try:
        query_result = await JavaServer.async_query(server)
        players = query_result.players.names
    except Exception as e:
        logger.error(f"[MC查询]查询服务器 {server_host} 出现错误, {e}")
        players = []

    return {
        "server_host": server_host,
        "description": "".join(
            [item for item in status.motd.parsed if isinstance(item, str)]
        ),
        "version": status.version.name,
        "protocol": status.version.protocol,
        "online_players": status.players.online,
        "max_players": status.players.max,
        "ping": round(status.latency, 2),
        "players": [item.name for item in status.players.sample]
        if status.players.sample
        else players,
        "favicon": status.icon,
    }
