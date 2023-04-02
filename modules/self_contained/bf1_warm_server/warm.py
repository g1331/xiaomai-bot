import asyncio
import time
from graia.amnesia.message import MessageChain
from graia.ariadne import Ariadne
from graia.ariadne.message import Source
from graia.ariadne.model import Group
from loguru import logger

from modules.self_contained.bf1_warm_server import infos, commands
from utils.bf1.default_account import BF1DA
from utils.bf1.gateway_api import api_instance

warm_dict = {
    # "group_name": "game_id"
}
warm_info = {

}
PlayerCount = {
    "Open": {
        24: 20,
        32: 26,
        40: 34,
        64: 57,
    },
    "Save": {
        24: 12,
        32: 16,
        40: 20,
        64: 32,
    },
    "Full": {
        24: 20,
        32: 28,
        40: 36,
        64: 60,
    },
}


async def leave_server(game_id, num=None) -> int:
    # 如果不指定num则全部退出
    if num is None:
        tasks = []
        for bot_name in infos:
            if infos[bot_name].gameId == game_id:
                tasks.append((api_instance.get_api_instance(
                    bot_name, session=infos[bot_name].sessionId)).leaveGame(game_id))
        await asyncio.gather(*tasks)
    else:
        tasks = []
        for bot_name in infos:
            if infos[bot_name].gameId == game_id:
                tasks.append((api_instance.get_api_instance(
                        bot_name, session=infos[bot_name].sessionId)).leaveGame(game_id))
                if len(tasks) >= num:
                    break
        await asyncio.gather(*tasks)
    return len(tasks)


async def join_server(game_id, num) -> int:
    counter = 0
    for bot_name in infos:
        if infos[bot_name].state == "None":
            commands[bot_name] = f"join {game_id}"
            counter += 1
            if counter >= num:
                break
    return counter


async def warm(app: Ariadne, group: Group, source: Source, game_id, group_name):
    global warm_dict, warm_info
    if group_name in warm_dict:
        return await app.send_message(group, MessageChain(
            f"群组{group_name}已经在暖服中,请勿重复操作!"
        ), quote=source)
    start_time = time.time()
    warm_dict[group_name] = game_id
    fail_counter = 0
    fail_info = None
    cost_time = 0
    while cost_time < 60 * 30:
        if fail_counter >= 60:
            await app.send_message(group, MessageChain(
                f"暖服失败!重试次数过多!\n"
                f"失败信息:{fail_info}\n"
                f"正在退出机器人..."
            ), quote=source)
            await leave_server(game_id)
            await leave_server(game_id)
            return
        cost_time = time.time() - start_time
        server_info = await ((await BF1DA.get_api_instance()).getFullServerDetails(game_id))
        if isinstance(server_info, str):
            fail_info = f"{server_info}"
            fail_counter += 1
            await asyncio.sleep(5)
            continue
        server_name = server_info["result"]["serverInfo"]["name"][:20]
        mapNamePretty = server_info["result"]["serverInfo"]["mapNamePretty"]
        mapModePretty = server_info["result"]["serverInfo"]["mapModePretty"]
        max_player = server_info["result"]["serverInfo"]["slots"]["Soldier"]["max"]
        current_player = server_info["result"]["serverInfo"]["slots"]["Soldier"]["current"]
        full_player = PlayerCount["Full"][max_player]
        bot_in = 0
        for bot in infos:
            if infos[bot].gameId == game_id:
                bot_in += 1
        real_player = current_player - bot_in
        # 秒转换为xx分xx秒
        if cost_time < 60:
            time_info = f"{round(cost_time, 2)}秒"
        else:
            time_info = f"{int(cost_time // 60)}分{round(cost_time % 60)}秒"
        info = f"服务器:{server_name}\n" \
               f"当前人数:{current_player}/{max_player}\n" \
               f"地图:{mapNamePretty}-{mapModePretty}\n" \
               f"当前机量:{bot_in}\n" \
               f"任务已耗时:{time_info}\n"
        warm_info[group_name] = info
        if group_name not in warm_dict:
            return
        # 1.如果current_player<full_player,就用最多full_player个机器人进服,使得current_player>=full_player
        # 2.如果current_player>=full_player,就看real_player是否大于full_player
        if current_player < full_player:
            need_in = full_player - current_player
            try_join = await join_server(game_id, need_in)
            if try_join == 0:
                # await app.send_message(group, MessageChain(
                #     f"暖服任务告警!\n"
                #     f"需要塞入机量:{need_in}\n"
                #     f"实际空闲机量:{try_join}\n"
                #     f"服务器:{server_name}\n"
                #     f"当前人数:{current_player}/{max_player}\n"
                #     f"当前机量:{bot_in}\n"
                #     f"任务已耗时:{time_info}"
                # ), quote=source)
                fail_counter += 1
                await asyncio.sleep(60)
                continue
            # await app.send_message(group, MessageChain(
            #     f"加塞执行!\n"
            #     f"服务器:{server_name}!\n"
            #     f"当前人数:{current_player}/{max_player}\n"
            #     f"地图:{mapNamePretty}-{mapModePretty}\n"
            #     f"服内机量:{bot_in}\n"
            #     f"尝试塞入机量:{try_join}\n"
            #     f"任务已耗时:{time_info}"
            # ), quote=source)
            await asyncio.sleep(60)
            continue
        elif current_player >= full_player:
            # 如果真实人数大于full_player,就退出所有机器人,返回暖服完成
            if real_player >= full_player:
                await leave_server(game_id)
                await leave_server(game_id)
                del warm_dict[group_name]
                bot_in = 0
                for bot in infos:
                    if infos[bot].gameId == game_id:
                        bot_in += 1
                return await app.send_message(group, MessageChain(
                    f"服务器:{server_name}已经暖服完成!\n"
                    f"当前人数:{current_player}/{max_player}\n"
                    f"服内机量:{bot_in}\n"
                    f"任务已耗时:{time_info}"
                ), quote=source)
            # 如果真实人数小于full_player,就计算需要多少机器人退服
            # current = real + bot > full
            else:
                need_leave = bot_in - (full_player - real_player)
                # await app.send_message(group, MessageChain(
                #     f"暖服ing\n"
                #     f"服务器:{server_name}\n"
                #     f"当前人数:{current_player}/{max_player}\n"
                #     f"地图:{mapNamePretty}-{mapModePretty}\n"
                #     f"服内机量:{bot_in}\n"
                #     f"尝试退服机量:{need_leave}\n"
                #     f"任务已耗时:{time_info}"
                # ), quote=source)
                # 计算需要多少机器人退服
                if need_leave <= 0:
                    logger.info(
                        f"暖服ing\n"
                        f"服务器:{server_name}\n"
                        f"当前人数:{current_player}/{max_player}\n"
                        f"地图:{mapNamePretty}-{mapModePretty}\n"
                        f"服内机量:{bot_in}\n"
                        f"尝试退服机量:{need_leave}\n"
                        f"任务已耗时:{time_info}"
                    )
                    await asyncio.sleep(30)
                    continue
                # 退服
                await leave_server(game_id, need_leave)
                await asyncio.sleep(60)
                continue

    server_name = None
    max_player = None
    current_player = None
    mapNamePretty = None
    mapModePretty = None
    try:
        server_info = await ((await BF1DA.get_api_instance()).getFullServerDetails(game_id))
        server_name = server_info["result"]["serverInfo"]["name"][:20]
        max_player = server_info["result"]["serverInfo"]["slots"]["Soldier"]["max"]
        current_player = server_info["result"]["serverInfo"]["slots"]["Soldier"]["current"]
        mapNamePretty = server_info["result"]["serverInfo"]["mapNamePretty"]
        mapModePretty = server_info["result"]["serverInfo"]["mapModePretty"]
    except Exception as e:
        logger.error(f"获取服务器信息失败!{e}")
    bot_in = 0
    for bot in infos:
        if infos[bot].gameId == game_id:
            bot_in += 1
    time_info = f"{int(cost_time // 60)}分{round(cost_time % 60)}秒"
    # 如果30分钟后还没完成,就退出所有机器人,返回暖服失败
    await app.send_message(group, MessageChain(
        f"暖服失败!任务耗时超过30min!\n"
        f"群组:{group_name}\n"
        f"服务器:{server_name}\n"
        f"当前人数:{current_player}/{max_player}\n"
        f"地图:{mapNamePretty}-{mapModePretty}\n"
        f"服内机量:{bot_in}\n"
        f"任务耗时:{time_info}\n"
        f"正在退出所有机器人..."
    ), quote=source)
    await leave_server(game_id)
    await leave_server(game_id)
    del warm_dict[group_name]
    return
