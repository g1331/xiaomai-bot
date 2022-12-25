import yaml
from graia.ariadne.app import Ariadne
from graia.ariadne.event.message import GroupMessage
from graia.ariadne.message.chain import MessageChain
from graia.ariadne.message.element import Source
from graia.ariadne.message.parser.twilight import Twilight, FullMatch, ParamMatch, UnionMatch, RegexResult, \
    SpacePolicy
from graia.ariadne.model import Group, Member
from graia.broadcast import ExecutionStop
from graia.broadcast.builtin.decorators import Depend
from graia.saya import Channel, Saya
from graia.saya.builtins.broadcast.schema import ListenerSchema
from loguru import logger

from modules.self_contained.DuoQHandle import DuoQ
from modules.PermManager import Perm
from util.internal_utils import MessageChainUtils

saya = Saya.current()
channel = Channel.current()
channel.name("开关模块")
channel.description("用于检查与控制非必需插件的使用与否")
channel.author("13")


class Switch(object):
    """
    1.检查当前群是否启用插件-depend
    2.获取群配置-switch.yaml文件
    3.根据模块名判断是否开启
    """

    @classmethod
    def get(cls, name: str, group: Group) -> bool:
        """
        根据传入的功能名字获取群号是否在其中
        :return: bool
        """
        # 读取vip群
        with open('./config/config.yaml', 'r', encoding="utf-8") as bot_file:
            config_data = yaml.load(bot_file, Loader=yaml.Loader)
            if group.id in config_data["vipgroup"]:
                return True
        with open('./config/Switch.yaml', 'r', encoding="utf-8") as file:
            temp = yaml.load(file, Loader=yaml.Loader)
            if name not in temp["funlist_off"]:
                if name in temp[group.id] and name in temp["funlist_on"]:
                    return True
                else:
                    return False
            else:
                return False

    @classmethod
    def require(cls, module_name: str):
        """
        指定需要的插件名
        :param module_name: 功能名
        :return: Depend
        """

        async def wrapper(group: Group):
            # 通过get来获取插件使用的状态
            try:
                result = cls.get(module_name, group)
            except:
                raise ExecutionStop
            if result:
                return Depend(wrapper)
            else:
                raise ExecutionStop

        return Depend(wrapper)


# 控制单个群开启功能
@channel.use(ListenerSchema(listening_events=[GroupMessage],
                            decorators=[
                                Perm.require(32),
                                DuoQ.require()
                            ],
                            inline_dispatchers=[
                                Twilight(
                                    [
                                        FullMatch('-').space(SpacePolicy.NOSPACE),
                                        "switch_type" @ UnionMatch("开启", "关闭").space(SpacePolicy.FORCE),
                                        "fun_name" @ ParamMatch(),
                                        # 当不传入群id时，读取当前群的id
                                        "group_id" @ ParamMatch(optional=True),
                                    ]
                                    # 示例: -开启 test 123
                                )
                            ]))
async def switch_on_off(app: Ariadne, group: Group, sender: Member, message: MessageChain, group_id: RegexResult,
                        switch_type: RegexResult, fun_name: RegexResult):
    if group_id.matched:
        group_id = int(str(group_id.result))
        # 如果不是当前群，判假
        if int(str(group_id)) != group.id and Perm.get(sender, group) < 128:
            await app.send_message(group, MessageChain(
                f"你没有此操作权限"
            ), quote=message[Source][0])
            return False
    else:
        group_id = group.id

    # 判断群号是否有效
    if await app.get_group(group_id) is None:
        await app.send_message(group, MessageChain(
            f"没有找到群【{group_id}】"
        ), quote=message[Source][0])
        return False

    file_path = f'./config/Switch.yaml'
    with open(file_path, 'r', encoding="utf-8") as file_temp:
        switch_data = yaml.load(file_temp, yaml.Loader)
        # 判断是否有群开关配置
        if group_id not in switch_data:
            switch_data[group_id] = []
        # 判断功能名是否存在
        if str(fun_name.result) not in switch_data["funlist_on"]:
            await app.send_message(group, MessageChain(
                f"未找到功能【{fun_name.result}】"
            ), quote=message[Source][0])
            return False
        # 判断是打开还是关闭操作
        if str(switch_type.result) == "开启":
            # 判断功能是否已经开启
            if str(fun_name.result) in switch_data[group_id]:
                await app.send_message(group, MessageChain(
                    f"功能【{fun_name.result}】已开启，请勿重复开启"
                ), quote=message[Source][0])
                return False
            else:
                switch_data[group_id].append(str(fun_name.result))
                with open(file_path, 'w', encoding="utf-8") as file_temp2:
                    yaml.dump(switch_data, file_temp2, allow_unicode=True)
                    await app.send_message(group, MessageChain(
                        f"已开启【{fun_name.result}】功能"
                    ), quote=message[Source][0])
                    return True
        else:
            # 判断功能是否已经关闭
            if str(fun_name.result) not in switch_data[group_id]:
                await app.send_message(group, MessageChain(
                    f"功能【{fun_name.result}】已关闭，请勿重复关闭"
                ), quote=message[Source][0])
                return False
            else:
                switch_data[group_id].remove(str(fun_name.result))
                with open(file_path, 'w', encoding="utf-8") as file_temp2:
                    yaml.dump(switch_data, file_temp2, allow_unicode=True)
                    await app.send_message(group, MessageChain(
                        f"已关闭【{fun_name.result}】功能"
                    ), quote=message[Source][0])
                    return True


# 功能推送->打开所有群的某功能
@channel.use(ListenerSchema(listening_events=[GroupMessage],
                            decorators=[
                                Perm.require(256),
                                DuoQ.require()
                            ],
                            inline_dispatchers=[
                                Twilight(
                                    [
                                        "switch_type" @ UnionMatch("-推送功能").space(SpacePolicy.FORCE),
                                        "fun_name" @ ParamMatch(optional=False)
                                    ]
                                    # 示例: -推送功能 test
                                )
                            ]))
async def function_push():
    ...


# 调整插件的可用状态
@channel.use(ListenerSchema(listening_events=[GroupMessage],
                            decorators=[
                                Perm.require(128),
                                DuoQ.require()
                            ],
                            inline_dispatchers=[
                                Twilight(
                                    [
                                        "switch_type" @ UnionMatch("-插件开", "-插件关", "-插件删").space(SpacePolicy.FORCE),
                                        # 当不传入群id时，读取当前群的id
                                        "module_name" @ ParamMatch(),
                                    ]
                                    # 示例: -插件开/关 <module_name>
                                )
                            ]))
async def switch_module(app: Ariadne, group: Group, sender: Member, message: MessageChain, switch_type: RegexResult,
                        module_name: RegexResult):
    file_path = f'./config/Switch.yaml'
    with open(file_path, 'r', encoding="utf-8") as file_temp:
        switch_data = yaml.load(file_temp, yaml.Loader)
        funlist_on = switch_data["funlist_on"]
        funlist_off = switch_data["funlist_off"]
        if str(switch_type.result) == "-插件开":
            if str(module_name.result) in funlist_on:
                await app.send_message(group, MessageChain(
                    f"插件{module_name.result}已处于使用状态"
                ), quote=message[Source][0])
                return False
            else:
                switch_data["funlist_on"].append(str(module_name.result))
                for item in switch_data["funlist_off"]:
                    if item in switch_data["funlist_on"]:
                        switch_data["funlist_off"].remove(item)
                with open(file_path, 'w', encoding="utf-8") as file_temp2:
                    yaml.dump(switch_data, file_temp2, allow_unicode=True)
                    await app.send_message(group, MessageChain(
                        f"插件{module_name.result}开启成功"
                    ), quote=message[Source][0])
                    return True
        elif str(switch_type.result) == "-插件关":
            if str(module_name.result) not in funlist_on and str(module_name.result) in funlist_off:
                await app.send_message(group, MessageChain(
                    f"插件{module_name.result}已处于停用状态"
                ), quote=message[Source][0])
                return False
            else:
                switch_data["funlist_off"].append(str(module_name.result))
                for item in switch_data["funlist_on"]:
                    if item in switch_data["funlist_off"]:
                        switch_data["funlist_on"].remove(item)
                with open(file_path, 'w', encoding="utf-8") as file_temp2:
                    yaml.dump(switch_data, file_temp2, allow_unicode=True)
                    await app.send_message(group, MessageChain(
                        f"插件{module_name.result}关闭成功"
                    ), quote=message[Source][0])
                    return True
        elif str(switch_type.result) == "-插件删" and Perm.get(sender, group) == 256:
            try:
                switch_data["funlist_on"].remove(str(module_name.result))
                switch_data["funlist_off"].remove(str(module_name.result))
            except:
                with open(file_path, 'w', encoding="utf-8") as file_temp2:
                    yaml.dump(switch_data, file_temp2, allow_unicode=True)
                    await app.send_message(group, MessageChain(
                        f"插件{module_name.result}删除成功"
                    ), quote=message[Source][0])
                    return True
        elif str(switch_type.result) == "-插件删" and Perm.get(sender, group) != 256:
            await app.send_message(group, MessageChain(
                f'权限不足!所需权限级:{Perm.Master},你的权限级:{Perm.get(sender, group)}'
            ), quote=message[Source][0])
        else:
            await app.send_message(group, MessageChain(
                f'识别指令出错,示例:\n-插件开/关/删 <module_name>'
            ), quote=message[Source][0])


# 测试
@channel.use(ListenerSchema(listening_events=[GroupMessage],
                            decorators=[
                                Perm.require(128),
                                DuoQ.require()
                            ],
                            inline_dispatchers=[
                                Twilight(
                                    [
                                        FullMatch('-test switch').space(SpacePolicy.FORCE),
                                        "switch_type" @ ParamMatch(optional=False).space(SpacePolicy.FORCE),
                                        # 当不传入群id时，读取当前群的id
                                        "module_name" @ ParamMatch(optional=False),
                                    ]
                                    # 示例: -test 插件开/关 插件名字
                                )
                            ]))
async def fun_test(app: Ariadne, group: Group, message: MessageChain, switch_type: RegexResult,
                   module_name: RegexResult):
    await app.send_message(group, MessageChain(
        f"识别到指令:{switch_type.result} {module_name.result}"
    ), quote=message[Source][0])


# 帮助
@channel.use(ListenerSchema(listening_events=[GroupMessage],
                            decorators=[
                                Perm.require(16),
                                DuoQ.require()
                            ],
                            inline_dispatchers=[
                                Twilight.from_command("-help switch")
                            ]
                            ))
async def help_manager(app: Ariadne, group: Group):
    await app.send_message(group, MessageChain(
        f'全局指令格式:\n()表示可选项<>表示必填项\na/b表示可选参数a和b\n'
        f'1.开关功能:\n-<开启/关闭> <功能名> (群号)\n'
        f'2.查看功能列表:\n-<功能列表> (群号)\n'
        f'3.控制插件开关:\n-<插件开/关> <module_name>\n'
        f'4.测试参数:\n-test switch <参数1> <参数2>\n'
        f'5.插件重载:\n-插件重载 <插件名>\n'
        f'6.插件列表:\n-插件列表'
    ))


# 菜单
@channel.use(ListenerSchema(listening_events=[GroupMessage],
                            decorators=[
                                Perm.require(16),
                                DuoQ.require()
                            ],
                            inline_dispatchers=[
                                Twilight([
                                    "action" @ UnionMatch("-help", "-帮助").space(SpacePolicy.PRESERVE),
                                ])
                            ]
                            ))
async def menu(app: Ariadne, group: Group, message: MessageChain):
    with open('./config/Switch.yaml', 'r', encoding="utf-8") as file:
        temp = yaml.load(file, Loader=yaml.Loader)
        funlist_on = temp["funlist_on"]
        if funlist_on is None or len(funlist_on) == 0:
            await app.send_message(group, MessageChain(
                f"注意:没有识别到装载的插件，可能正在维护"
            ), quote=message[Source][0])
        try:
            fun_on = temp[group.id]
        except:
            await app.send_message(group, MessageChain(
                f"注意:识别到第一次运行,当前开启0个功能\n可使用-开启 <功能名>来打开一个功能"
            ), quote=message[Source][0])
            group_id = group.id
            file_path = f'./config/Switch.yaml'
            with open(file_path, 'r', encoding="utf-8") as file_temp:
                switch_data = yaml.load(file_temp, yaml.Loader)
                # 判断是否有群开关配置
                if group_id not in switch_data:
                    switch_data[group_id] = []
                # 判断功能名是否存在
                # switch_data[group_id].append("test")
                with open(file_path, 'w', encoding="utf-8") as file_temp2:
                    yaml.dump(switch_data, file_temp2, allow_unicode=True)
            fun_on = []

    with open('./config/Switch.yaml', 'r', encoding="utf-8") as file:
        temp = yaml.load(file, Loader=yaml.Loader)
        funlist_on = temp["funlist_on"]
        funlist_off = temp["funlist_off"]
        funlist_always = temp["funlist_always"]
        if funlist_on is None or len(funlist_on) == 0:
            await app.send_message(group, MessageChain(
                f"注意:没有识别到装载的插件，可能正在维护"
            ), quote=message[Source][0])
        funlist_temp = []
        for fun_item in funlist_on:
            if fun_item in fun_on:
                funlist_temp.append(f'【√】{fun_item}\n')
            else:
                funlist_temp.append(f'【×】{fun_item}\n')
        funlist_temp = sorted(funlist_temp, key=len)
        for funlist_item in funlist_always:
            funlist_temp.append(f'【内置】{funlist_item}\n')
        if funlist_off is not None:
            for fun_item in funlist_off:
                funlist_temp.append(f'【维护ing】{fun_item}\n')
        if len(funlist_temp) != 0:
            funlist_temp[-1] = funlist_temp[-1].replace("\n", "")
        msg = '可用-help <功能名>查看帮助信息\n'
        for item in funlist_temp:
            msg += item

        await app.send_message(
            group,
            await MessageChainUtils.messagechain_to_img(
                MessageChain(
                    msg
                )
            ),
        )

        # image = await create_image(msg)
        # await app.send_message(
        #     group, MessageChain([Image(data_bytes=image)]), quote=message[Source][0]
        # )
        # await app.send_message(group, MessageChain(
        #     "可用-help <功能名>查看帮助信息\n",
        #     funlist_temp,
        #
        #     f'管理员可使用-开启/关闭+功能名进行开关\n全局指令格式:\n()表示可选项,<>表示必填项,a/b表示可选参数a和b\n'
        # ), quote=message[Source][0])


# 插件重载/列表/信息
@channel.use(ListenerSchema(listening_events=[GroupMessage],
                            decorators=[Perm.require(256),
                                        DuoQ.require()],
                            inline_dispatchers=[
                                Twilight(
                                    [
                                        "action" @ UnionMatch("-插件重载").space(SpacePolicy.FORCE),
                                        "module_name" @ ParamMatch(optional=False).space(SpacePolicy.PRESERVE)
                                    ],
                                    # 示例: -插件重载 test
                                )
                            ]))
async def module_reload(app: Ariadne, group: Group, module_name: RegexResult,
                        source: Source):
    module_name = f"modules.{module_name.result.display}"
    if module_name not in saya.channels:
        await app.send_message(group, MessageChain(
            f"未找到插件{module_name}"
        ), quote=source)
        return
    try:
        # logger.warning(saya.channels)
        # saya.channels.get()
        logger.warning(f"重载插件{module_name}执行ing")
        with saya.module_context():
            saya.reload_channel(saya.channels[module_name])
        await app.send_message(group, MessageChain(
            "执行成功!"
        ), quote=source)
        return
    except Exception as e:
        logger.error(f"重载插件{module_name}失败!")
        await app.send_message(group, MessageChain(
            f"执行失败!\n{e}"
        ), quote=source)
        return


@channel.use(ListenerSchema(listening_events=[GroupMessage],
                            decorators=[Perm.require(128),
                                        DuoQ.require()],
                            inline_dispatchers=[
                                Twilight(
                                    [
                                        "action" @ UnionMatch("-插件列表").space(SpacePolicy.PRESERVE)
                                    ],
                                )
                            ]))
async def module_list(app: Ariadne, group: Group):
    temp = saya.channels
    send = []
    for module in temp.keys():
        send.append(f"{module.replace('modules.', '')}\n")
    send = sorted(send, key=len)
    send[-1] = send[-1].replace("\n", '')
    msg = ''
    for item in send:
        msg += item
    await app.send_message(
        group,
        await MessageChainUtils.messagechain_to_img(
            MessageChain(
                msg
            )
        ),
    )
    # image = await create_image(msg)
    # await app.send_message(
    #     group, MessageChain([Image(data_bytes=image)]), quote=message[Source][0]
    # )
    # await app.send_message(group, MessageChain(
    #     send
    # ), quote=source)
