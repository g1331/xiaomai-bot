import os
import yaml
from typing import Union
from graia.ariadne.app import Ariadne
from graia.ariadne.event.message import GroupMessage
from graia.ariadne.event.mirai import MemberJoinEvent, MemberLeaveEventQuit
from graia.ariadne.message.chain import MessageChain
from graia.ariadne.message.element import Source, At
from graia.ariadne.message.parser.twilight import Twilight, FullMatch, ParamMatch, RegexResult, SpacePolicy, \
    PRESERVE, UnionMatch
from graia.ariadne.model import Group, Member, Friend
from graia.broadcast import ExecutionStop
from graia.broadcast.builtin.decorators import Depend
from graia.saya import Channel
from graia.saya.builtins.broadcast.schema import ListenerSchema

# 获取属于这个模组的实例
from modules.DuoQHandle import DuoQ

channel = Channel.current()
channel.name("权限组模块")
channel.description("统一的模组型权限管理，可以对其他插件使用时进行权限判断，控制所有权限相关的内容,与插件开关区别")
channel.author("13")


# 该类用于depend等权限判断，含有修饰器来检查权限
class Perm(object):
    """
    用于处理权限相关
    """
    Master = 256
    Admin = 128
    GroupOwner = 64
    GroupAdmin = 32
    User = 16
    Black = 0
    GlobalBlack = -1

    DefaultGroup = 16
    AdminGroup = 32

    @classmethod
    def get(cls, sender: Member, group: Union[Group, Friend]) -> int:
        """
        根据传入的qq号与群号来判断该用户的权限等级
        :return: 如果一直返回16等级，说明文件没有初始化
        """
        # from os.path import dirname, abspath
        with open('./config/config.yaml', 'r', encoding="utf-8") as file:
            temp = yaml.load(file, Loader=yaml.Loader)
            if sender.id == temp["botinfo"]["Master"]:
                return Perm.Master
            elif sender.id in temp["botinfo"]["Admin"]:
                return Perm.Admin
                # return Perm.Admin
        # 优先判断权限组，如果没有权限组则使用qq群权限判断
        try:
            with open(f'./config/group/{group.id}/perm.yaml', 'r', encoding="utf-8") as file:
                fff = yaml.load(file, Loader=yaml.Loader)
                return fff[sender.id]
        except Exception as e:
            if sender.permission.name == "Owner":
                return Perm.GroupOwner
            elif sender.permission.name == "Administrator":
                return Perm.GroupAdmin
            elif sender.permission == "Member":
                return Perm.User
            return Perm.User

    @classmethod
    def require(cls, level: int = User):
        """
        指定level及以上的等级才能执行
        :param level: 设定权限等级
        :return:
        """

        async def wrapper(app: Ariadne, sender: Union[Member, Friend], group: Union[Group, Friend]):
            # 通过get来获取用户的权限等级
            user_level = cls.get(sender, group)
            if user_level >= level:
                return Depend(wrapper)
            elif user_level < level:
                if level != 16:
                    await app.send_message(group, MessageChain(
                        f"权限不足!需要的权限:{level},你的权限:{user_level}"
                    ))
                raise ExecutionStop
            else:
                raise ExecutionStop

        return Depend(wrapper)


# 创建权限组
@channel.use(ListenerSchema(listening_events=[GroupMessage],
                            decorators=[
                                Perm.require(128),
                                DuoQ.require()
                            ],
                            inline_dispatchers=[
                                Twilight(
                                    [
                                        FullMatch("-perm create group").space(PRESERVE),
                                        "group_id" @ ParamMatch(optional=True),
                                        "group_type" @ UnionMatch("默认", "管理")
                                    ]
                                    # 示例: -perm create group (group_id) <type>
                                )
                            ]))
async def crete_perm_group(app: Ariadne, group: Group, message: MessageChain,
                           group_id: RegexResult, group_type: RegexResult):
    """
    创建权限组配置文件
    :param app:
    :param group_type: 权限类型-默认/管理
    :param group_id: 是否匹配群id
    :param group: 群
    :param message: 传入消息
    :return:
    """
    if not group_id.matched:
        group_id = group.id
    else:
        group_id = int(str(group_id.result))

    # 判断群号是否有效
    if await app.get_group(group_id) is None:
        await app.send_message(group, MessageChain(
            f"没有找到群{group_id}"
        ), quote=message[Source][0])
        return False
    # 群目录判断
    path = f'./config/group/{group_id}'
    if not os.path.exists(path):
        os.makedirs(path)

    file_path = f'{path}/perm.yaml'
    if not os.path.isfile(file_path):
        if str(group_type.result) == "默认":
            open(file_path, mode="w", encoding="utf-8")
            await app.send_message(group, MessageChain(
                f"创建权限组配置成功,类型:{group_type.result}组"
            ), quote=message[Source][0])
        elif str(group_type.result) == "管理":
            try:
                dict_temp = {}
                member_list = await app.get_member_list(group_id)
                for item in member_list:
                    if str(item.permission) != "OWNER":
                        dict_temp[item.id] = 32
                    else:
                        dict_temp[item.id] = 64
                open(f"{path}/管理组.txt", mode="w", encoding="utf-8")
                with open(file_path, mode="w", encoding="utf-8") as file:
                    yaml.dump(dict_temp, file, allow_unicode=True)
                    await app.send_message(group, MessageChain(
                        f"创建权限组配置成功,类型:{group_type.result}组"
                    ), quote=message[Source][0])
                    return True
            except:
                await app.send_message(group, MessageChain(
                    f"未成功获取到群成员,创建配置失败"
                ), quote=message[Source][0])
    else:
        await app.send_message(group, MessageChain(
            f"<{group.name}><{group_id}>权限组已存在,请勿重复创建"
        ), quote=message[Source][0])
        return False


# 删除权限组文件
@channel.use(ListenerSchema(listening_events=[GroupMessage],
                            decorators=[
                                Perm.require(128),
                                DuoQ.require()
                            ],
                            inline_dispatchers=[
                                Twilight.from_command("-perm del group {group_id}")
                            ]))
async def del_perm_group(app: Ariadne, group: Group, message: MessageChain, group_id: RegexResult):
    group_id = int(str(group_id.result))
    path = f'./config/group/{group_id}'
    file_path = f'{path}/perm.yaml'
    admin_file_path = f"{path}/管理组.txt"
    if os.path.exists(file_path):
        try:
            os.remove(file_path)
            if os.path.exists(admin_file_path):
                os.remove(admin_file_path)
        except Exception as e:
            await app.send_message(group, MessageChain(
                f"删除权限组失败:{e}"
            ), quote=message[Source][0])
            return
        await app.send_message(group, MessageChain(
            f"为<{group.name}><{group_id}>删除权限组成功"
        ), quote=message[Source][0])
    else:
        await app.send_message(group, MessageChain(
            f"未找到该群权限组文件"
        ), quote=message[Source][0])


# 继承权限组文件
@channel.use(ListenerSchema(listening_events=[GroupMessage],
                            decorators=[
                                Perm.require(128),
                                DuoQ.require()
                            ],
                            inline_dispatchers=[
                                Twilight(
                                    [
                                        FullMatch("-perm").space(SpacePolicy.FORCE),
                                        FullMatch("succeed").space(SpacePolicy.FORCE),
                                        "groupNew_id" @ ParamMatch(optional=True).space(PRESERVE),
                                        FullMatch("from").space(SpacePolicy.FORCE),
                                        "groupOld_id" @ ParamMatch().space(SpacePolicy.PRESERVE),
                                        # 示例: -perm (gid) <action> <mid> <level:64,32,16,0>
                                    ]
                                )
                            ]))
async def succeed_perm_group(app: Ariadne, group: Group, sender: Member, message: MessageChain,
                             groupNew_id: RegexResult,
                             groupOld_id: RegexResult):
    ...


# 增删改权限组内容
@channel.use(ListenerSchema(listening_events=[GroupMessage],
                            decorators=[
                                Perm.require(64),
                                DuoQ.require()
                            ],
                            inline_dispatchers=[
                                Twilight(
                                    [
                                        FullMatch("-perm").space(SpacePolicy.FORCE),
                                        "group_id" @ ParamMatch(optional=True).space(PRESERVE),
                                        "action" @ UnionMatch("add", "+", "set").space(SpacePolicy.FORCE),
                                        FullMatch(" ", optional=True),
                                        "member_id" @ ParamMatch().space(SpacePolicy.FORCE),
                                        "level" @ UnionMatch("64", "32", "16", "0")
                                        # 示例: -perm (gid) <action> <mid> <level:64,32,16,0>
                                    ]
                                )
                            ]))
async def zsg_perm_group(app: Ariadne, group: Group, sender: Member, message: MessageChain, group_id: RegexResult,
                         level: RegexResult, member_id: RegexResult):
    """
    对权限组进行增删改查
    :param message:
    :param sender:
    :param group:
    :param app:
    :param group_id:qq群
    :param level:权限级
    :param member_id:被添加人的id
    :return:
    """
    if group_id.matched:
        group_id = int(str(group_id.result))
    else:
        group_id = group.id
    try:
        member_id = int(str(member_id.result).replace("@", ""))
    except:
        await app.send_message(group, MessageChain(
            f"请检查输入的成员qq号"
        ), quote=message[Source][0])
        return False
    # 修改其他群组的权限判假
    if group_id != group.id and Perm.get(sender, group) < 128:
        await app.send_message(group, MessageChain(
            f"无权执行此操作,所需权限级<{Perm.Admin}>,你的权限级<{Perm.get(sender, group)}>"
        ), quote=message[Source][0])
        return False

    # 判断群号是否有效
    # if await app.get_group(group_id) is None:
    #     await app.send_message(group, MessageChain(
    #         f"没有找到群{group_id}"
    #     ), quote=message[Source][0])
    #     return False
    #
    if await app.get_member(group_id, member_id) is None:
        await app.send_message(group, MessageChain(
            f"没有找到群成员{member_id}"
        ), quote=message[Source][0])
        return False
    if (Perm.get(await app.get_member(group, member_id), group) >= 128) and (Perm.get(sender, group) < 128):
        await app.send_message(group, MessageChain(
            f"错误!无法将bot管理者降级!"
        ), quote=message[Source][0])
        return False

    # 进行增删改
    path = f'./config/group/{group_id}'
    file_path = f'{path}/perm.yaml'
    if not os.path.exists(file_path):
        await app.send_message(group, MessageChain(
            f"请先使用[-perm create group (group_id) <type>]创建权限组"
        ), quote=message[Source][0])
        return False
    with open(file_path, 'r', encoding="utf-8") as file1:
        file_before = yaml.load(file1, Loader=yaml.Loader)
        if file_before is None:
            file_before = {}
        file_before[int(str(member_id).replace("@", ""))] = int(str(level.result))
        with open(file_path, 'w', encoding="utf-8") as file2:
            yaml.dump(file_before, file2, allow_unicode=True)
            await app.send_message(group, MessageChain(
                f"群<{group.id}>设置成员<{str(member_id).replace('@', '')}>权限级<{level.result}>成功"
            ), quote=message[Source][0])
            return True


# 管理组-加群自动添加,默认和管理组-退群自动删除
@channel.use(ListenerSchema(listening_events=[MemberJoinEvent]))
async def auto_add_admin_perm(app: Ariadne, group: Group, member: Member):
    group_id = group.id
    member_id = member.id
    # 进行增删改
    path = f'./config/group/{group_id}'
    file_path = f'{path}/perm.yaml'
    file_path2 = f'{path}/管理组.txt'
    if os.path.exists(file_path) and not os.path.exists(file_path2):
        return
    with open(file_path, 'r', encoding="utf-8") as file1:
        file_before = yaml.load(file1, Loader=yaml.Loader)
        if file_before is None:
            file_before = {}
        file_before[int(str(member_id).replace("@", ""))] = 32
        with open(file_path, 'w', encoding="utf-8") as file2:
            yaml.dump(file_before, file2, allow_unicode=True)
            await app.send_message(group, MessageChain(
                At(member), f"已自动修改权限为32"
            ))
            return


@channel.use(ListenerSchema(listening_events=[MemberLeaveEventQuit]))
async def auto_del_perm(app: Ariadne, group: Group, member: Member):
    group_id = group.id
    member_id = member.id
    # 进行增删改
    path = f'./config/group/{group_id}'
    file_path = f'{path}/perm.yaml'
    if not os.path.exists(file_path):
        return False
    with open(file_path, 'r', encoding="utf-8") as file1:
        file_before = yaml.load(file1, Loader=yaml.Loader)
        if file_before is None:
            file_before = {}
        try:
            file_before.pop(int(str(member_id).replace("@", "")))
        except:
            return False
        with open(file_path, 'w', encoding="utf-8") as file2:
            yaml.dump(file_before, file2, allow_unicode=True)
            await app.send_message(group, MessageChain(
                f"成员{member.name}({member.id})退群,已自动删除其权限"
            ))
            return True


# 查询权限组-当权限>=128时 可以查询其他群的
@channel.use(ListenerSchema(listening_events=[GroupMessage],
                            decorators=[
                                Perm.require(32),
                                DuoQ.require()
                            ],
                            inline_dispatchers=[
                                Twilight(
                                    [
                                        FullMatch("-perm list").space(SpacePolicy.PRESERVE)
                                        # 示例: -perm list
                                    ]
                                )
                            ]))
async def perm_list(app: Ariadne, group: Group, message: MessageChain):
    # 进行增删改
    path = f'./config/group/{group.id}'
    file_path = f'{path}/perm.yaml'
    if not os.path.exists(file_path):
        await app.send_message(group, MessageChain(
            f"请先使用[-perm create group (group_id) <type>]创建权限组"
        ), quote=message[Source][0])
        return False
    else:
        with open(file_path, 'r', encoding="utf-8") as file1:
            data = yaml.load(file1, Loader=yaml.Loader)
            level_64 = []
            level_32 = []
            level_else = []
            for key_id in list(data.keys()):
                try:
                    member = await app.get_member(group, int(key_id))
                    if data[key_id] == 64:
                        level_64.append(f"{member.name}({key_id})\n")
                    elif data[key_id] == 32:
                        level_32.append(f"{member.name}({key_id})\n")
                    elif data[key_id] == 16:
                        data.pop(key_id)
                    else:
                        level_else.append(f"{data[key_id]}-{member.name}({key_id})\n")
                except Exception as e:
                    data.pop(key_id)
            with open(file_path, 'w', encoding="utf-8") as file2:
                yaml.dump(data, file2, allow_unicode=True)
        message_send = MessageChain(
            f"64:\n", level_64,
            f"32(共{len(level_32)}人):\n", level_32,
            f"其他:\n" if len(level_else) != 0 else '', level_else if len(level_else) != 0 else ''
        )
        await app.send_message(group, message_send, quote=message[Source][0])
        return True


# 增删bot管理
@channel.use(ListenerSchema(listening_events=[GroupMessage],
                            decorators=[
                                Perm.require(256),
                                DuoQ.require()
                            ],
                            inline_dispatchers=[
                                Twilight(
                                    [
                                        FullMatch("-perm botAdmin").space(SpacePolicy.FORCE),
                                        "action" @ UnionMatch("add", "del").space(SpacePolicy.FORCE),
                                        "member_id" @ ParamMatch().space(SpacePolicy.PRESERVE),
                                        # 示例: -perm botAdmin add
                                    ]
                                )
                            ]))
async def change_botAdmin(app: Ariadne, group: Group, message: MessageChain,
                          action: RegexResult, member_id: RegexResult):
    with open('./config/config.yaml', 'r', encoding="utf-8") as bot_file:
        bot_data = yaml.load(bot_file, Loader=yaml.Loader)
        member_id = int(str(member_id.result).replace("@", ""))
        if str(action.result) == "add":
            if member_id in bot_data["botinfo"]["Admin"]:
                await app.send_message(group, MessageChain(
                    f"{member_id}已经是bot管理员了"
                ), quote=message[Source][0])
                return False
            else:
                bot_data["botinfo"]["Admin"].append(member_id)
                with open('./config/config.yaml', 'w', encoding="utf-8") as bot_file2:
                    yaml.dump(bot_data, bot_file2, allow_unicode=True)
                    await app.send_message(group, MessageChain(
                        f"添加{member_id}为bot管理员成功"
                    ), quote=message[Source][0])
        else:
            if member_id in bot_data["botinfo"]["Admin"]:
                bot_data["botinfo"]["Admin"].remove(member_id)
                with open('./config/config.yaml', 'w', encoding="utf-8") as bot_file2:
                    yaml.dump(bot_data, bot_file2, allow_unicode=True)
                    await app.send_message(group, MessageChain(
                        f"删除{member_id}bot管理员成功"
                    ), quote=message[Source][0])
            else:
                await app.send_message(group, MessageChain(
                    f"{member_id}不是bot管理员"
                ), quote=message[Source][0])
                return False


# 测试权限消息
@channel.use(ListenerSchema(listening_events=[GroupMessage],
                            decorators=[
                                Perm.require(16),
                                DuoQ.require()
                            ],
                            inline_dispatchers=[
                                Twilight.from_command("-test perm")
                            ]
                            ))
async def check_perm(app: Ariadne, group: Group, sender: Member, message: MessageChain):
    await app.send_message(group, MessageChain(
        "这是一则测试内容\n"f"你的权限级:{Perm.get(sender, group)}\n"
        f"你的群权限:{sender.permission}"
    ), quote=message[Source][0])


# 帮助信息
@channel.use(ListenerSchema(listening_events=[GroupMessage],
                            decorators=[
                                Perm.require(16),
                                DuoQ.require()
                            ],
                            inline_dispatchers=[
                                Twilight.from_command("-help perm")
                            ]
                            ))
async def help_manager(app: Ariadne, group: Group, message: MessageChain):
    await app.send_message(group, MessageChain(
        f'()表示可选项,<>表示必填项,a/b表示可选参数a和b\n'
        f'1.创建权限组:\n-perm create group (群号) <默认/管理>\n'
        f'2.删除权限组:\n-perm del group <群号>\n'
        f'3.修改权限组-增删bot管理:\n-perm (群号) <set/add/+> <qq号> <64/32/16/0>\n注意:修改至0时，bot不会再响应该成员消息\n'
        f'4.测试权限组:\n-test perm\n'
        f'5.增删su管理权限:\n-perm botAdmin add/del <qq号>'
    ), quote=message[Source][0])
