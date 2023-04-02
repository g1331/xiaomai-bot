import json
import os
from pathlib import Path
from threading import Thread

from graia.amnesia.message import MessageChain
from graia.ariadne.app import Ariadne
from graia.ariadne.event.lifecycle import ApplicationLaunched
from graia.ariadne.event.message import GroupMessage
from graia.ariadne.message.element import Source
from graia.ariadne.message.parser.twilight import Twilight, UnionMatch, SpacePolicy, FullMatch, ParamMatch, \
    RegexResult
from graia.ariadne.model import Group
from graia.ariadne.util.saya import listen, dispatch, decorate
from graia.saya import Channel
from graia.saya.builtins.broadcast.schema import ListenerSchema

from core.control import Distribute, Function, FrequencyLimitation
from modules.self_contained.bf1_warm_server.route import bots, commands, infos, run_flask_app
from modules.self_contained.bf1_warm_server.utils import get_session, get_bots, Control, get_group_list, add_group, \
    remove_group, get_perm_list, add_perm, remove_perm
from modules.self_contained.bf1_warm_server.warm import warm, warm_dict, join_server, leave_server
from utils.bf1.default_account import BF1DA

channel = Channel.current()
bind_file_path = str(Path(__file__).parent / "bind.json")


@listen(GroupMessage)
@dispatch(
    Twilight(
        [
            UnionMatch("-nfh").space(SpacePolicy.PRESERVE),
        ]
    )
)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Control.group_require(),
)
async def helper(app: Ariadne, group: Group, source: Source):
    return await app.send_message(group, MessageChain(
        f"指令列表:\n"
        f"查询机器人状态:\n"
        f"-nfb\n"
        f"连接掉线bot:\n"
        f"-connect\n"
        f"查询服务器状态:\n"
        f"-info [群组名]\n"
        f"开启一个暖服计划:\n"
        f"-warm [群组名]\n"
        f"停止一个暖服计划:\n"
        f"-stop [群组名]\n"
        f"列出所有暖服计划:\n"
        f"-warmlist\n"
        f"手动加入服务器:\n"
        f"-join [群组名] [数量]\n"
        f"手动退出服务器:\n"
        f"-leave [群组名] [数量]\n"
        f"绑定群组:\n"
        f"-bind [群组名] [gameid]\n"
        f"解绑群组:\n"
        f"-unbind [群组名]\n"
        f"列出绑定群组:\n"
        f"-bdlist\n"
        f"授权群:\n"
        f"-addgroup [群号]\n"
        f"取消授权群:\n"
        f"-removegroup [群号]\n"
        f"列出授权群:\n"
        f"-grouplist\n"
        f"授权用户:\n"
        f"-addperm [qq号]\n"
        f"取消授权用户:\n"
        f"-removeperm [qq号]\n"
        f"列出授权用户:\n"
        f"-permlist\n"
    ), quote=source)


@listen(GroupMessage)
@dispatch(
    Twilight(
        [
            UnionMatch("-nfb").space(SpacePolicy.PRESERVE),
        ]
    )
)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Control.group_require(),
)
async def get_bot_list(app: Ariadne, group: Group, source: Source):
    # None是主页,Loading是正在加载,Playing是游戏中,Offline是离线
    menu_list = []
    loading_list = []
    playing_list = []
    offline_list = []
    unknown_list = []
    for bot_info in infos:
        if infos[bot_info].state == "None":
            menu_list.append(bot_info)
        elif infos[bot_info].state == "Loading":
            loading_list.append(bot_info)
        elif infos[bot_info].state == "Playing":
            playing_list.append(bot_info)
        elif infos[bot_info].state == "Offline":
            offline_list.append(bot_info)
        else:
            unknown_list.append(bot_info)
    return await app.send_message(group, MessageChain(
        f"机器人状态:\n"
        f"在线:{len(menu_list)}\n"
        f"加载中:{len(loading_list)}\n"
        f"游戏中:{len(playing_list)}\n"
        f"离线:{len(offline_list)}\n"
        f"未知:{len(unknown_list)}\n"
        f"总共:{len(bots)}"
    ), quote=source)


@listen(GroupMessage)
@dispatch(
    Twilight(
        [
            UnionMatch("-warm").space(SpacePolicy.FORCE),
            ParamMatch(optional=False).space(SpacePolicy.PRESERVE) @ "group_name",
        ]
    )
)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Control.group_require(),
)
async def warm_server_handle(app: Ariadne, group: Group, source: Source, group_name: RegexResult):
    group_name = group_name.result.display.strip()
    with open(bind_file_path, "r", encoding="utf-8") as f:
        bind = json.load(f)
    if group_name not in bind:
        return await app.send_message(group, MessageChain(
            f"未找到绑定群组:{group_name}"
        ), quote=source)
    game_id = bind[group_name]
    server_info = await ((await BF1DA.get_api_instance()).getFullServerDetails(game_id))
    if isinstance(server_info, str):
        return await app.send_message(
            group,
            MessageChain(f"查询出错!{server_info}"),
            quote=source
        )
    await app.send_message(group, MessageChain(f"下发指令ing"), quote=source)
    await warm(app, group, source, game_id, group_name)


@listen(GroupMessage)
@dispatch(
    Twilight(
        [
            UnionMatch("-warmlist").space(SpacePolicy.PRESERVE)
        ]
    )
)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Control.group_require(),
)
async def warm_list_handle(app: Ariadne, group: Group, source: Source):
    result = []
    if not warm_dict:
        return await app.send_message(group, MessageChain(
            f"当前无暖服计划"
        ), quote=source)
    for group_name in warm_dict:
        result.append(f"{group_name}\n{warm_dict[group_name]}" + "=" * 10)
    result = "\n".join(result)
    return await app.send_message(group, MessageChain(
        f"当前暖服计划:\n{result}"
    ), quote=source)


@listen(GroupMessage)
@dispatch(
    Twilight(
        [
            UnionMatch("-info").space(SpacePolicy.PRESERVE),
            ParamMatch(optional=False).space(SpacePolicy.PRESERVE) @ "group_name",
        ]
    )
)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Control.group_require(),
)
async def get_info_handle(app: Ariadne, group: Group, source: Source, group_name: RegexResult):
    group_name = group_name.result.display.strip()
    with open(bind_file_path, "r", encoding="utf-8") as f:
        bind = json.load(f)
    if group_name not in bind:
        return await app.send_message(group, MessageChain(
            f"未找到绑定群组:{group_name}"
        ), quote=source)
    game_id = bind[group_name]
    server_info = await ((await BF1DA.get_api_instance()).getFullServerDetails(game_id))
    if isinstance(server_info, str):
        return await app.send_message(
            group,
            MessageChain(f"查询出错!{server_info}"),
            quote=source
        )
    server_name = server_info["result"]["serverInfo"]["name"][:20]
    mapNamePretty = server_info["result"]["serverInfo"]["mapNamePretty"]
    mapModePretty = server_info["result"]["serverInfo"]["mapModePretty"]
    max_player = server_info["result"]["serverInfo"]["slots"]["Soldier"]["max"]
    current_player = server_info["result"]["serverInfo"]["slots"]["Soldier"]["current"]
    bot_in = 0
    for bot in infos:
        if infos[bot].gameId == game_id:
            bot_in += 1
    return await app.send_message(group, MessageChain(
        f"群组[{group_name}]\n"
        f"服务器:{server_name}\n"
        f"当前人数:{current_player}/{max_player}\n"
        f"地图:{mapNamePretty}-{mapModePretty}\n"
        f"当前机量:{bot_in}"
    ), quote=source)


@listen(GroupMessage)
@dispatch(
    Twilight(
        [
            UnionMatch("-stop").space(SpacePolicy.FORCE),
            ParamMatch(optional=False).space(SpacePolicy.PRESERVE) @ "group_name",
        ]
    )
)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Control.group_require(),
)
async def stop_warm_handle(app: Ariadne, group: Group, source: Source, group_name: RegexResult):
    group_name = group_name.result.display.strip()
    with open(bind_file_path, "r", encoding="utf-8") as f:
        bind = json.load(f)
    if group_name not in bind:
        return await app.send_message(group, MessageChain(
            f"未找到绑定群组:{group_name}"
        ), quote=source)
    game_id = bind[group_name]
    if group_name not in warm_dict:
        return await app.send_message(group, MessageChain(
            f"未找到群组:{group_name}的暖服计划"
        ), quote=source)
    del warm_dict[group_name]
    server_info = await ((await BF1DA.get_api_instance()).getFullServerDetails(game_id))
    if isinstance(server_info, str):
        return await app.send_message(
            group,
            MessageChain(f"查询出错!{server_info}"),
            quote=source
        )
    server_name = server_info["result"]["serverInfo"]["name"][:20]
    mapNamePretty = server_info["result"]["serverInfo"]["mapNamePretty"]
    mapModePretty = server_info["result"]["serverInfo"]["mapModePretty"]
    max_player = server_info["result"]["serverInfo"]["slots"]["Soldier"]["max"]
    current_player = server_info["result"]["serverInfo"]["slots"]["Soldier"]["current"]
    bot_in = 0
    for bot in infos:
        if infos[bot].gameId == game_id:
            bot_in += 1
    await app.send_message(group, MessageChain(
        f"群组[{group_name}]暖服被中止!\n"
        f"服务器:{server_name}\n"
        f"当前人数:{current_player}/{max_player}\n"
        f"地图:{mapNamePretty}-{mapModePretty}\n"
        f"当前机量:{bot_in}\n"
        f"正在退出所有机器人..."
    ), quote=source)
    await leave_server(game_id)
    await leave_server(game_id)
    del warm_dict[group_name]
    return await app.send_message(group, MessageChain(
        f"执行成功!"
    ), quote=source)


@listen(GroupMessage)
@dispatch(
    Twilight(
        [
            UnionMatch("-join").space(SpacePolicy.FORCE),
            ParamMatch(optional=False).space(SpacePolicy.PRESERVE) @ "group_name",
            ParamMatch(optional=True).space(SpacePolicy.PRESERVE) @ "num",
        ]
    )
)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Control.group_require(),
)
async def join_server_handle(app: Ariadne, group: Group, source: Source, group_name: RegexResult, num: RegexResult):
    if not num.matched:
        return await app.send_message(group, MessageChain(
            f"请指定加入的bot数量!\n"
            f"例如: -join 群组名 10"
        ), quote=source)
    else:
        num = num.result.display.strip()
        if not num.isdigit():
            return await app.send_message(group, MessageChain(
                f"请指定正确的bot数量!\n"
                f"例如: -join 群组名 10"
            ), quote=source)
        num = int(num)
    group_name = group_name.result.display.strip()
    with open(bind_file_path, "r", encoding="utf-8") as f:
        bind = json.load(f)
    if group_name not in bind:
        return await app.send_message(group, MessageChain(
            f"未找到群组:{group_name}"
        ), quote=source)
    game_id = bind[group_name]
    server_info = await ((await BF1DA.get_api_instance()).getFullServerDetails(game_id))
    if isinstance(server_info, str):
        return await app.send_message(
            group,
            MessageChain(f"查询出错!{server_info}"),
            quote=source
        )
    if group_name in warm_dict:
        await app.send_message(group, MessageChain(
            f"注意,该群已经有暖服计划在执行,手动加入可能会影响暖服进程!"
        ), quote=source)
    join_num = await join_server(game_id, num)
    if join_num == 0:
        return await app.send_message(group, MessageChain(
            f"执行失败,请检查bot数量是否足够!"
        ), quote=source)
    return await app.send_message(group, MessageChain(
        f"执行成功!尝试加入{join_num}个bot"
    ), quote=source)


@listen(GroupMessage)
@dispatch(
    Twilight(
        [
            UnionMatch("-leave").space(SpacePolicy.FORCE),
            ParamMatch(optional=False).space(SpacePolicy.PRESERVE) @ "group_name",
            ParamMatch(optional=True).space(SpacePolicy.PRESERVE) @ "num",
        ]
    )
)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Control.group_require(),
)
async def leave_server_handle(app: Ariadne, group: Group, source: Source, group_name: RegexResult, num: RegexResult):
    if not num.matched:
        return await app.send_message(group, MessageChain(
            f"请指定退出的bot数量!\n"
            f"例如: -leave 群组名 10"
            f"退出全部bot请使用"
            f"-leave 群组名 all"
        ), quote=source)
    else:
        if num.result.display.strip() == "all":
            num = None
        else:
            num = num.result.display.strip()
            if not num.isdigit():
                return await app.send_message(group, MessageChain(
                    f"请指定正确的bot数量!\n"
                    f"例如: -leave 群组名 10"
                ), quote=source)
            num = int(num)
    group_name = group_name.result.display.strip()
    with open(bind_file_path, "r", encoding="utf-8") as f:
        bind = json.load(f)
    if group_name not in bind:
        return await app.send_message(group, MessageChain(
            f"未找到绑定群组:{group_name}"
        ), quote=source)
    game_id = bind[group_name]
    server_info = await ((await BF1DA.get_api_instance()).getFullServerDetails(game_id))
    if isinstance(server_info, str):
        return await app.send_message(
            group,
            MessageChain(f"查询出错!{server_info}"),
            quote=source
        )
    leave_num = await leave_server(game_id, num)
    return await app.send_message(group, MessageChain(
        f"执行完毕,预计退出{leave_num}个bot"
    ), quote=source)


@listen(GroupMessage)
@dispatch(
    Twilight(
        [
            FullMatch("-connect")
        ]
    )
)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Control.group_require(),
)
async def connect_game(app: Ariadne, group: Group, source: Source):
    bot_list = []
    for bot_name in infos:
        if infos[bot_name].onlineState != 3:
            bot_list.append(bot_name)
            commands[bot_name] = "connect"
    if not bot_list:
        return await app.send_message(group, MessageChain(
            "当前没有离线机器人"
        ), quote=source)
    else:
        await app.send_message(group, MessageChain(
            f"指令已下达!\n预计连接{len(bot_list)}个机器人"
        ), quote=source)


@listen(GroupMessage)
@dispatch(
    Twilight(
        [
            FullMatch("-bind").space(SpacePolicy.FORCE),
            ParamMatch(optional=False).space(SpacePolicy.FORCE) @ "group_name",
            ParamMatch(optional=False).space(SpacePolicy.PRESERVE) @ "game_id",
        ]
    )
)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Control.group_require(),
)
async def bind_gn_gi(app: Ariadne, group: Group, source: Source, game_id: RegexResult, group_name: RegexResult):
    game_id = game_id.result.display.strip()
    group_name = group_name.result.display.strip()
    server_info = await ((await BF1DA.get_api_instance()).getFullServerDetails(game_id))
    if isinstance(server_info, str):
        return await app.send_message(
            group,
            MessageChain(f"查询出错!{server_info}"),
            quote=source
        )
    else:
        server_info = server_info["result"]
    if not os.path.exists(bind_file_path):
        with open(bind_file_path, "w") as f:
            json.dump({}, f, indent=4, ensure_ascii=False)
    with open(bind_file_path, "r") as f:
        bind_data = json.load(f)
        if bind_data:
            bind_data[group_name] = game_id
        else:
            bind_data = {group_name: game_id}
    with open(bind_file_path, "w") as f:
        json.dump(bind_data, f, indent=4, ensure_ascii=False)
    await app.send_message(
        group,
        MessageChain(f"成功将{group_name}绑定到{game_id}\n"
                     f"服名:{server_info['serverInfo']['name']}\n"),
        quote=source
    )


@listen(GroupMessage)
@dispatch(
    Twilight(
        [
            FullMatch("-unbind").space(SpacePolicy.FORCE),
            ParamMatch(optional=False).space(SpacePolicy.PRESERVE) @ "group_name"
        ]
    )
)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Control.group_require(),
)
async def unbind_gn_gi(app: Ariadne, group: Group, source: Source, group_name: RegexResult):
    group_name = group_name.result.display.strip()
    if not os.path.exists(bind_file_path):
        with open(bind_file_path, "w") as f:
            json.dump({}, f, indent=4, ensure_ascii=False)
    with open(bind_file_path, "r") as f:
        bind_data = json.load(f)
        if group_name not in bind_data:
            return await app.send_message(
                group,
                MessageChain(f"未找到绑定的群组[{group_name}]"),
                quote=source
            )
        else:
            del bind_data[group_name]
    with open(bind_file_path, "w") as f:
        json.dump(bind_data, f, indent=4, ensure_ascii=False)
    return await app.send_message(
        group,
        MessageChain(f"成功解绑[{group_name}]!"),
        quote=source
    )


@listen(GroupMessage)
@dispatch(
    Twilight(
        [
            FullMatch("-bdlist").space(SpacePolicy.PRESERVE)
        ]
    )
)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Control.group_require(),
)
async def bdlist(app: Ariadne, group: Group, source: Source):
    if not os.path.exists(bind_file_path):
        with open(bind_file_path, "w") as f:
            json.dump({}, f, indent=4, ensure_ascii=False)
    with open(bind_file_path, "r") as f:
        bind_data = json.load(f)
        if not bind_data:
            return await app.send_message(
                group,
                MessageChain(f"未找到绑定的群组!"),
                quote=source
            )
        else:
            result = []
            for group_name in bind_data:
                result.append(f"{group_name}:{bind_data[group_name]}")
        result = "\n".join(result)
        return await app.send_message(
            group,
            MessageChain(f"绑定列表:\n{result}"),
            quote=source
        )


@listen(GroupMessage)
@dispatch(
    Twilight(
        [
            FullMatch("-add group").space(SpacePolicy.PRESERVE),
            ParamMatch(optional=False).space(SpacePolicy.PRESERVE) @ "group_id"
        ]
    )
)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Control.group_require(),
    Control.user_require(),
)
async def add_qq_group(app: Ariadne, group: Group, source: Source, group_id: RegexResult):
    group_id = group_id.result.display.strip()
    group_list = get_group_list()
    if group_id in group_list:
        return await app.send_message(
            group,
            MessageChain(f"QQ群[{group_id}]已存在!"),
            quote=source
        )
    else:
        add_group(group_id)
        return await app.send_message(
            group,
            MessageChain(f"QQ群[{group_id}]已添加!"),
            quote=source
        )


@listen(GroupMessage)
@dispatch(
    Twilight(
        [
            FullMatch("-remove group").space(SpacePolicy.PRESERVE),
            ParamMatch(optional=False).space(SpacePolicy.PRESERVE) @ "group_id"
        ]
    )
)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Control.group_require(),
    Control.user_require(),
)
async def remove_qq_group(app: Ariadne, group: Group, source: Source, group_id: RegexResult):
    group_id = group_id.result.display.strip()
    group_list = get_group_list()
    if group_id not in group_list:
        return await app.send_message(
            group,
            MessageChain(f"QQ群[{group_id}]不存在!"),
            quote=source
        )
    else:
        remove_group(group_id)
        return await app.send_message(
            group,
            MessageChain(f"QQ群[{group_id}]已移除!"),
            quote=source
        )


@listen(GroupMessage)
@dispatch(
    Twilight(
        [
            FullMatch("-grouplist").space(SpacePolicy.PRESERVE)
        ]
    )
)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Control.group_require(),
)
async def get_grouplist(app: Ariadne, group: Group, source: Source):
    group_list = get_group_list()
    if not group_list:
        return await app.send_message(
            group,
            MessageChain(f"未找到绑定的QQ群!"),
            quote=source
        )
    else:
        for i in range(len(group_list)):
            group_list[i] = f"{i + 1}.{group_list[i]}"
        result = "\n".join(group_list)
        return await app.send_message(
            group,
            MessageChain(f"已授权的群列表:\n{result}"),
            quote=source
        )


@listen(GroupMessage)
@dispatch(
    Twilight(
        [
            FullMatch("-add perm").space(SpacePolicy.PRESERVE),
            ParamMatch(optional=False).space(SpacePolicy.PRESERVE) @ "member_id"
        ]
    )
)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Control.group_require(),
    Control.user_require(),
)
async def add_member_perm(app: Ariadne, group: Group, source: Source, member_id: RegexResult):
    member_id = member_id.result.display.strip()
    perm_list = get_perm_list()
    if member_id in perm_list:
        return await app.send_message(
            group,
            MessageChain(f"成员[{member_id}]已存在!"),
            quote=source
        )
    else:
        add_perm(member_id)
        return await app.send_message(
            group,
            MessageChain(f"成员[{member_id}]已添加!"),
            quote=source
        )


@listen(GroupMessage)
@dispatch(
    Twilight(
        [
            FullMatch("-remove perm").space(SpacePolicy.PRESERVE),
            ParamMatch(optional=False).space(SpacePolicy.PRESERVE) @ "member_id"
        ]
    )
)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Control.group_require(),
    Control.user_require(),
)
async def remove_member_perm(app: Ariadne, group: Group, source: Source, member_id: RegexResult):
    member_id = member_id.result.display.strip()
    perm_list = get_perm_list()
    if member_id not in perm_list:
        return await app.send_message(
            group,
            MessageChain(f"成员[{member_id}]不存在!"),
            quote=source
        )
    else:
        remove_perm(member_id)
        return await app.send_message(
            group,
            MessageChain(f"成员[{member_id}]已移除!"),
            quote=source
        )


@listen(GroupMessage)
@dispatch(
    Twilight(
        [
            FullMatch("-permlist").space(SpacePolicy.PRESERVE)
        ]
    )
)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Control.group_require(),
)
async def get_permlist(app: Ariadne, group: Group, source: Source):
    perm_list = get_perm_list()
    if not perm_list:
        return await app.send_message(
            group,
            MessageChain(f"未找到授权的成员!"),
            quote=source
        )
    else:
        for i in range(len(perm_list)):
            perm_list[i] = f"{i + 1}.{perm_list[i]}"
        result = "\n".join(perm_list)
        return await app.send_message(
            group,
            MessageChain(f"已授权的成员列表:\n{result}"),
            quote=source
        )


@channel.use(ListenerSchema(listening_events=[ApplicationLaunched]))
async def application_launched_listener():
    flask_thread = Thread(target=run_flask_app)
    flask_thread.start()
