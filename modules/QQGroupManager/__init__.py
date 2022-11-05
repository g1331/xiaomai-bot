import json
import httpx
import asyncio

import yaml
from loguru import logger
from graia.ariadne.app import Ariadne
from graia.ariadne.event import MiraiEvent
from graia.ariadne.event.message import GroupMessage
from graia.ariadne.event.mirai import BotInvitedJoinGroupRequestEvent, MemberJoinRequestEvent
from graia.ariadne.message.chain import MessageChain
from graia.ariadne.message.element import At, Source
from graia.ariadne.message.parser.twilight import Twilight, FullMatch, UnionMatch, SpacePolicy, ElementMatch
from graia.ariadne.model import Group, Member, MemberInfo
from graia.ariadne.util.interrupt import FunctionWaiter
from graia.saya import Channel
from graia.saya.builtins.broadcast.schema import ListenerSchema

from modules.DuoQHandle import DuoQ
from modules.PermManager import Perm
from modules.Switch import Switch
from modules.bf1战绩 import getPid_byName, get_player_stat_data, record

channel = Channel.current()
channel.name("群管功能")
channel.description("TODO:入群审核、欢迎、战地id查验、禁言、解禁、设置群精华、加退群判断、好友申请判断、邀请加群判断、退群删除群配置、加群建立文件夹")
channel.author("13")

true = True
false = False
null = ''

# 读取账号信息
with open('./config/config.yaml', 'r', encoding="utf-8") as bot_file:
    bot_data = yaml.load(bot_file, Loader=yaml.Loader)
    master = bot_data["botinfo"]["Master"]
    test_group = bot_data["botinfo"]["testgroup"]
    admins = bot_data["botinfo"]["Admin"]


@channel.use(ListenerSchema(listening_events=[BotInvitedJoinGroupRequestEvent]))
async def invited_event(app: Ariadne, event: BotInvitedJoinGroupRequestEvent):
    """
    :param app:
    :param event: 被邀请加入群的事件
    :return:
    """
    try:
        if (event.supplicant == master) or (event.supplicant in admins):
            await event.accept()
            await app.send_message(await app.get_friend(event.supplicant), MessageChain(
                f"已自动同意您的邀请~"
            ))
    except:
        pass
    group = await app.get_group(test_group)
    if group is None:
        member = await app.get_friend(master)
        bot_message = await app.send_message(member, MessageChain(
            f"成员{event.nickname}({event.supplicant})邀请bot加入群:\n{event.group_name}({event.source_group})\n"
            f'是否同意该申请，请在1小时内回复“y”或“n”'
        ))
    else:
        bot_message = await app.send_message(group, MessageChain(
            f"成员{event.nickname}({event.supplicant})邀请bot加入群:\n{event.group_name}({event.source_group})\n"
            f'是否同意该申请，请在1小时内回复“y”或“n”'
        ))

    async def waiter(waiter_member: Member, waiter_message: MessageChain, waiter_group: Group,
                     event_waiter: GroupMessage):
        if Perm.get(waiter_member, group) >= 32 and group.id == waiter_group.id \
                and eval(event_waiter.json())['message_chain'][1]['type'] == "Quote" and \
                eval(event_waiter.json())['message_chain'][1]['id'] == bot_message.id:
            saying = waiter_message.display
            if saying == 'y':
                return True, waiter_member.id
            elif saying == 'n':
                return False, waiter_member.id
            elif saying.startswith("n"):
                saying.replace("n", "")
                return False, waiter_member.id
            else:
                pass

    try:
        result, admin = await FunctionWaiter(waiter, [GroupMessage]).wait(timeout=3600)
    except asyncio.exceptions.TimeoutError:
        await app.send_message(group, MessageChain(
            f'由于超时未审核，处理 {event.nickname}({event.supplicant}) 的入群邀请已失效'),
                               )
        return

    if result:
        await event.accept()  # 同意入群
        await app.send_message(group, MessageChain(
            f'已同意 {event.nickname}({event.supplicant}) 的入群邀请'),
                               )
    else:
        await event.reject(f'bot拒绝了你的入群邀请')  # 拒绝
        await app.send_message(group, MessageChain(
            f'已拒绝 {event.nickname}({event.supplicant}) 的入群邀请'),
                               )


global player_name, player_pid


# 入群审核
@channel.use(ListenerSchema(listening_events=[MemberJoinRequestEvent], ))
async def join_handle(app: Ariadne, event: MemberJoinRequestEvent):
    """
    :param app: 实例
    :param event: 有人申请加群
    :return:
    """
    global player_name, player_pid
    group = await app.get_group(event.source_group)
    result = Switch.get('入群审核', group)
    if not result:
        return False
    i = 0
    player_data = None
    while i <= 3:
        try:
            player_data = await getPid_byName(event.message[event.message.find("答案：") + 3:])
            break
        except:
            i += 1
            continue
    player_info = None
    if player_data is None:
        player_info = '(查询失败)'
    elif player_data['personas'] == {}:
        player_info = '(无效id)'
    else:
        player_pid = player_data['personas']['persona'][0]['personaId']
        i = 0
        while i <= 3:
            try:
                player_stat_data = (await get_player_stat_data(str(player_pid)))["result"]
                if int(player_stat_data["basicStats"]["timePlayed"]) > 0:
                    bfban_url = 'https://api.gametools.network/bfban/checkban?personaids=' + str(player_pid)
                    async with httpx.AsyncClient() as client:
                        response = await client.get(bfban_url, timeout=5)
                    bf_html = response.text
                    bf_stat = eval(bf_html)
                    if bf_stat["personaids"][str(player_pid)]["hacker"]:
                        player_info = "(注意:此id已经被bfban实锤!)"
                        break
                    else:
                        player_info = "(有效id)"
                        break
                else:
                    player_info = f'(无效id-时长不足:{player_stat_data["basicStats"]["timePlayed"]})'
                    break
            except Exception as e:
                logger.error(e)
                i += 1
    if not player_info:
        player_info = "(查询信息失败)"
    if '\u4e00' <= event.message[event.message.find("答案：") + 3:] <= '\u9fa5':
        player_info = ""
    if not ((player_info in ["(有效id)", "(注意:此id已经被bfban实锤!)", "(无效id)", ""]) or player_info.startswith("(无效id-时长不足:")):
        logger.warning(player_info)
        player_info = "(查询信息失败)"
    if player_info != "(有效id)":
        bot_message = await app.send_message(group, MessageChain(
            f'收到{event.nickname}({event.supplicant})入群申请\n'
            f'{event.message}{player_info}\n' if event.message else f'无申请信息\n',
            f'请在10分钟内回复"y"来同意或"n"来拒绝\n拒绝可回复送 n+拒绝理由'
        ))
    else:
        player_pid = player_data['personas']['persona'][0]['personaId']
        player_name = player_data['personas']['persona'][0]['displayName']
        bind_result = record.check_bind(event.supplicant)
        if bind_result:
            player_pid_bind = record.get_bind_pid(event.supplicant)
            player_name_bind = record.get_bind_name(event.supplicant)
            if player_pid_bind != player_pid:
                bot_message = await app.send_message(group, MessageChain(
                    f'收到{event.nickname}({event.supplicant})入群申请\n'
                    f'{event.message}\n注意:他的入群id有效,但是和其绑定id不一致!绑定id:{player_name_bind}\n',
                    f'请在5分钟内回复"y"来同意或"n"来拒绝\n拒绝可回复 n+拒绝理)'
                ))
            else:
                if Switch.get('自动过审', group):
                    await event.accept()
                    await app.send_message(group, MessageChain(
                        f'收到{event.nickname}({event.supplicant})入群申请\n'
                        f'{event.message}{player_info}\n'
                        f'有效id已经自动审核通过!'
                    ))
                    # 创建配置文件
                    record.config_bind(event.supplicant)
                    # 写入绑定信息
                    with open(f"./data/battlefield/binds/players/{event.supplicant}/bind.json", 'r',
                              encoding='utf-8') as file_temp1:
                        data_temp = file_temp1.read()
                        if data_temp is None:
                            pass
                        else:
                            with open(f"./data/battlefield/binds/players/{event.supplicant}/bind.json", 'w',
                                      encoding='utf-8') as file_temp2:
                                json.dump(player_data, file_temp2, indent=4)
                            # 调用战地查询计数器，绑定记录增加
                            record.bind_counter(event.supplicant,
                                                f"{player_data['personas']['persona'][0]['pidId']}-{player_data['personas']['persona'][0]['displayName']}-入群自动绑定")
                    await asyncio.sleep(1)
                    await app.send_message(group, MessageChain(
                        At(event.supplicant), f"欢迎加入{event.group_name}\n",
                        f"已自动将你的名片修改并绑定为:{player_name}!\n"
                        f"发送-help或-帮助可以查看bot的功能"
                    ))
                    member = await app.get_member(event.source_group, event.supplicant)
                    await app.modify_member_info(member, MemberInfo(name=player_name))
                    return True
                else:
                    bot_message = await app.send_message(group, MessageChain(
                        f'收到{event.nickname}({event.supplicant})入群申请\n'
                        f'{event.message}{player_info}\n' if event.message else f'无申请信息\n',
                        f'请在5分钟内回复"y"来同意或"n"来拒绝\n拒绝可回复 n+拒绝理由'
                    ))
        else:
            if Switch.get('自动过审', group):
                await event.accept()
                await app.send_message(group, MessageChain(
                    f'收到{event.nickname}({event.supplicant})入群申请\n'
                    f'{event.message}{player_info}\n'
                    f'有效id已经自动审核通过!'
                ))
                # 创建配置文件
                record.config_bind(event.supplicant)
                # 写入绑定信息
                with open(f"./data/battlefield/binds/players/{event.supplicant}/bind.json", 'r',
                          encoding='utf-8') as file_temp1:
                    data_temp = file_temp1.read()
                    if data_temp is None:
                        pass
                    else:
                        with open(f"./data/battlefield/binds/players/{event.supplicant}/bind.json", 'w',
                                  encoding='utf-8') as file_temp2:
                            json.dump(player_data, file_temp2, indent=4)
                        # 调用战地查询计数器，绑定记录增加
                        record.bind_counter(event.supplicant,
                                            f"{player_data['personas']['persona'][0]['pidId']}-{player_data['personas']['persona'][0]['displayName']}-入群自动绑定")
                await asyncio.sleep(1)
                await app.send_message(group, MessageChain(
                    At(event.supplicant), f"欢迎加入{event.group_name}\n",
                    f"已自动将你的名片修改并绑定为:{player_name}!\n"
                    f"发送-help或-帮助可以查看bot的功能"
                ))
                member = await app.get_member(event.source_group, event.supplicant)
                await app.modify_member_info(member, MemberInfo(name=player_name))
                return True
            else:
                bot_message = await app.send_message(group, MessageChain(
                    f'收到{event.nickname}({event.supplicant})入群申请\n'
                    f'{event.message}{player_info}\n' if event.message else f'无申请信息\n',
                    f'请在10分钟内回复"y"来同意或"n"来拒绝\n拒绝可回复 n+拒绝理由'
                ))

    async def waiter(waiter_member: Member, waiter_message: MessageChain, waiter_group: Group,
                     event_waiter: GroupMessage):
        try:
            await app.get_member(waiter_group, event.supplicant)
            if_join = True
        except:
            if_join = False
        if if_join is False:
            if Perm.get(waiter_member, group) >= 32 and group.id == waiter_group.id \
                    and eval(event_waiter.json())['message_chain'][1]['type'] == "Quote" and \
                    eval(event_waiter.json())['message_chain'][1]['id'] == bot_message.id:
                saying = waiter_message.display.replace(f"@{app.account}", '').replace(" ", '')
                if saying == 'y':
                    return True, waiter_member.id, None
                elif saying == 'n':
                    return False, waiter_member.id, None
                elif saying.startswith("n") and saying != "n":
                    return False, waiter_member.id, saying.replace("n", "").replace("n ", "")
        else:
            return [None] * 3

    try:
        result, admin, reason = await FunctionWaiter(waiter, [GroupMessage]).wait(timeout=600)
    except asyncio.exceptions.TimeoutError:
        await app.send_message(group, MessageChain(
            f'注意:由于超时未审核，处理 {event.nickname}({event.supplicant}) 的入群请求已失效'), )
        return

    if result:
        await event.accept()  # 同意入群
        await asyncio.sleep(2)
        try:
            member = await app.get_member(event.source_group, event.supplicant)
            await app.modify_member_info(member, MemberInfo(name=player_name))
        except:
            pass
        await app.send_message(group, MessageChain(
            f'已同意 {event.nickname}({event.supplicant}) 的入群请求'), )
    elif result is False:
        await event.reject(f'{reason}' if reason else f'管理员拒绝了你的入群申请')  # 拒绝好友请求
        await app.send_message(group, MessageChain(
            f'已拒绝 {event.nickname}({event.supplicant}) 的入群请求'
        ))
    elif result is None:
        pass
    else:
        pass


@channel.use(ListenerSchema(listening_events=[GroupMessage],
                            decorators=[Perm.require(32),
                                        DuoQ.require()],
                            inline_dispatchers=[
                                Twilight(
                                    [
                                        FullMatch("-help 入群审核")
                                    ]
                                )
                            ]))
async def join_handle_help(app: Ariadne, group: Group, message: MessageChain):
    await app.send_message(group, MessageChain(
        f"1.添加bot为群管理,bot将审核入群信息自动查验bf1id的有效性"
    ), quote=message[Source][0])


@channel.use(ListenerSchema(listening_events=[GroupMessage],
                            decorators=[Perm.require(32),
                                        DuoQ.require()],
                            inline_dispatchers=[
                                Twilight(
                                    [
                                        FullMatch("-help 自动过审")
                                    ]
                                )
                            ]))
async def join_handle_help(app: Ariadne, group: Group, message: MessageChain):
    await app.send_message(group, MessageChain(
        f"1.此功能打开后,如果橘子id有效将自动通过审核(请先开启入群审核)"
    ), quote=message[Source][0])


@channel.use(ListenerSchema(listening_events=[GroupMessage],
                            decorators=[Perm.require(32),
                                        Switch.require("群管"),
                                        DuoQ.require(),
                                        ],
                            inline_dispatchers=[
                                Twilight(
                                    [
                                        "at" @ ElementMatch(At, optional=True).space(SpacePolicy.PRESERVE),
                                        "command" @ UnionMatch("加精", "设精")
                                    ],
                                )
                            ]))
async def JiaJing(app: Ariadne, group: Group, event: MiraiEvent, src: Source):
    if eval(event.json())['message_chain'][1]['type'] == "Quote":
        quote_id = eval(event.json())['message_chain'][1]['id']
        bot_member = await app.get_member(group, app.account)
        if bot_member.permission.name == "Member":
            await app.send_message(group, MessageChain(
                f"bot权限不足!"
            ), quote=src)
            return
        try:
            await app.set_essence(quote_id)
        except Exception as e:
            logger.error(e)
            await app.send_message(group, MessageChain(
                f"出错力~!"
            ), quote=src)
            return
        await app.send_message(group, MessageChain(
            f"加精成功"
        ), quote=src)


@channel.use(ListenerSchema(listening_events=[GroupMessage],
                            decorators=[Perm.require(32),
                                        Switch.require("群管"),
                                        DuoQ.require(),
                                        ],
                            inline_dispatchers=[
                                Twilight(
                                    [
                                        "at" @ ElementMatch(At, optional=True).space(SpacePolicy.PRESERVE),
                                        FullMatch("禁言")
                                    ],
                                )
                            ]))
async def JinYan(app: Ariadne, group: Group, event: MiraiEvent, src: Source):
    if eval(event.json())['message_chain'][1]['type'] == "Quote":
        quote_id = eval(event.json())['message_chain'][1]['id']
        bot_member = await app.get_member(group, app.account)
        message_src = await app.get_message_from_id(quote_id)
        if bot_member.permission.name == "Member":
            await app.send_message(group, MessageChain(
                f"bot权限不足!"
            ), quote=src)
            return
        if (message_src.sender.permission.name == (
                "Administrator" or "Owner")) and bot_member.permission.name != "Owner":
            await app.send_message(group, MessageChain(
                f"bot权限不足!"
            ), quote=src)
            return
        if Perm.get(message_src.sender, group) >= 128:
            await app.send_message(group, MessageChain(
                f"我不能禁言bot管理员哦~"
            ), quote=src)
            return
        if Perm.get(message_src.sender, group) == 32:
            await app.send_message(group, MessageChain(
                f"我不能禁言管理员哦(被禁言对象需<32权)~"
            ), quote=src)
            return
        try:
            await app.mute_member(group, message_src.sender, 120)
        except Exception as e:
            logger.error(e)
            await app.send_message(group, MessageChain(
                f"禁言处理出错!"
            ), quote=src)
            return
        await app.send_message(group, MessageChain(
            f"已设置【{message_src.sender.name}】2分钟禁言"
        ), quote=src)


@channel.use(ListenerSchema(listening_events=[GroupMessage],
                            decorators=[Perm.require(32),
                                        Switch.require("群管"),
                                        DuoQ.require(),
                                        ],
                            inline_dispatchers=[
                                Twilight(
                                    [
                                        FullMatch("全体禁言")
                                    ],
                                )
                            ]))
async def JinYan(app: Ariadne, group: Group, src: Source, sender: Member):
    bot_member = await app.get_member(group, app.account)
    if bot_member.permission.name == "Member":
        await app.send_message(group, MessageChain(
            f"bot权限不足~"
        ), quote=src)
        return
    if sender.permission.name == "Member":
        await app.send_message(group, MessageChain(
            f"需要群管理/群主才能执行哦~"
        ), quote=src)
        return
    try:
        await app.mute_all(group)
    except Exception as e:
        logger.error(e)
        await app.send_message(group, MessageChain(
            f"禁言处理出错~"
        ), quote=src)
        return
    await app.send_message(group, MessageChain(
        f"开启全体禁言成功~"
    ), quote=src)


@channel.use(ListenerSchema(listening_events=[GroupMessage],
                            decorators=[Perm.require(32),
                                        Switch.require("群管"),
                                        DuoQ.require(),
                                        ],
                            inline_dispatchers=[
                                Twilight(
                                    [
                                        FullMatch("关闭全体禁言")
                                    ],
                                )
                            ]))
async def JinYan(app: Ariadne, group: Group, src: Source, sender: Member):
    bot_member = await app.get_member(group, app.account)
    if bot_member.permission.name == "Member":
        await app.send_message(group, MessageChain(
            f"bot权限不足~"
        ), quote=src)
        return
    if sender.permission.name == "Member":
        await app.send_message(group, MessageChain(
            f"需要群管理/群主才能执行哦~"
        ), quote=src)
        return
    try:
        await app.unmute_all(group)
    except Exception as e:
        logger.error(e)
        await app.send_message(group, MessageChain(
            f"处理出错~"
        ), quote=src)
        return
    await app.send_message(group, MessageChain(
        f"关闭全体禁言成功~"
    ), quote=src)


@channel.use(ListenerSchema(listening_events=[GroupMessage],
                            decorators=[Perm.require(32),
                                        Switch.require("群管"),
                                        DuoQ.require(),
                                        ],
                            inline_dispatchers=[
                                Twilight(
                                    [
                                        "at" @ ElementMatch(At, optional=True).space(SpacePolicy.PRESERVE),
                                        FullMatch("解禁")
                                    ],
                                )
                            ]))
async def JieJin(app: Ariadne, group: Group, event: MiraiEvent, src: Source):
    if eval(event.json())['message_chain'][1]['type'] == "Quote":
        quote_id = eval(event.json())['message_chain'][1]['id']
        bot_member = await app.get_member(group, app.account)
        message_src = await app.get_message_from_id(quote_id)
        if bot_member.permission.name == "Member":
            await app.send_message(group, MessageChain(
                f"bot权限不足!"
            ), quote=src)
            return
        if message_src.sender.permission.name == "Administrator" and bot_member.permission.name != "Owner":
            await app.send_message(group, MessageChain(
                f"bot权限不足!"
            ), quote=src)
            return
        try:
            await app.unmute_member(group, message_src.sender)
        except Exception as e:
            logger.error(e)
            await app.send_message(group, MessageChain(
                f"解禁处理出错!"
            ), quote=src)
            return
        await app.send_message(group, MessageChain(
            f"已取消【{message_src.sender.name}】的禁言"
        ), quote=src)


@channel.use(ListenerSchema(listening_events=[GroupMessage],
                            decorators=[Perm.require(32),
                                        Switch.require("群管"),
                                        DuoQ.require(),
                                        ],
                            inline_dispatchers=[
                                Twilight(
                                    [
                                        "at" @ ElementMatch(At, optional=True).space(SpacePolicy.PRESERVE),
                                        FullMatch("撤回")
                                    ],
                                )
                            ]))
async def Recall(app: Ariadne, group: Group, event: MiraiEvent, src: Source):
    if eval(event.json())['message_chain'][1]['type'] == "Quote":
        quote_id = eval(event.json())['message_chain'][1]['id']
        bot_member = await app.get_member(group, app.account)
        message_src = await app.get_message_from_id(quote_id)
        if bot_member.permission.name == "Member" and message_src.sender.id != app.account:
            await app.send_message(group, MessageChain(
                f"bot权限不足!"
            ), quote=src)
            return
        if message_src.sender.permission.name == "Administrator" and bot_member.permission.name != "Owner" and message_src.sender.id != app.account:
            await app.send_message(group, MessageChain(
                f"bot权限不足!"
            ), quote=src)
            return
        try:
            await app.recall_message(quote_id)
        except Exception as e:
            logger.error(e)
            await app.send_message(group, MessageChain(
                f"撤回处理出错!"
            ), quote=src)
            return
        await app.send_message(group, MessageChain(
            f"撤回成功!"
        ), quote=src)


@channel.use(ListenerSchema(listening_events=[GroupMessage],
                            decorators=[Perm.require(32),
                                        # Switch.require("群管"),
                                        DuoQ.require()],
                            inline_dispatchers=[
                                Twilight(
                                    [
                                        FullMatch("-help 群管")
                                    ]
                                )
                            ]))
async def manager_help(app: Ariadne, group: Group, message: MessageChain):
    await app.send_message(group, MessageChain(
        f"1.回复消息 加精/设精 可将消息加入群精华\n"
        f"2.回复消息 禁言 可将回复对象禁言2min\n"
        f"3.发送消息 全体禁言 (仅群管理/群主)\n"
        f"4.发送消息 关闭全体禁言 (仅群管理/群主)\n"
        f"5.回复消息 解禁 可将回复对象解禁\n"
        f"6.回复消息 撤回 可将回复对象消息撤回"
    ), quote=message[Source][0])
