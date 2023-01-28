import asyncio
from pathlib import Path
from typing import Union

from arclet.alconna import Alconna, CommandMeta
from arclet.alconna.graia import AlconnaDispatcher
from creart import create
from graia.ariadne.app import Ariadne
from graia.ariadne.event.message import GroupMessage, FriendMessage
from graia.ariadne.message.chain import MessageChain
from graia.ariadne.message.element import Image, Source
from graia.ariadne.message.parser.twilight import Twilight, UnionMatch, FullMatch, RegexMatch, RegexResult
from graia.ariadne.model import Group, Friend, Member
from graia.ariadne.util.saya import listen, dispatch, decorate
from graia.broadcast.interrupt import InterruptControl
from graia.saya import Channel, Saya

from core.bot import Umaru
from core.config import GlobalConfig
from core.control import (
    Permission,
    Function,
    FrequencyLimitation,
    Distribute
)
from core.models import saya_model
from utils.UI import *
from utils.waiter import ConfirmWaiter

config = create(GlobalConfig)
core = create(Umaru)
module_controller = saya_model.get_module_controller()

saya = Saya.current()
channel = Channel.current()
channel.name("SayaManager")
channel.description("负责插件管理(必须插件)")
channel.author("13")
channel.metadata = module_controller.get_metadata_from_path(Path(__file__))

inc = InterruptControl(saya.broadcast)


#   插件列表
#   已加载插件
#   未加载插件
@listen(GroupMessage, FriendMessage)
@decorate(
    Distribute.require(),
    Permission.user_require(Permission.GroupAdmin, if_noticed=True),
    Permission.group_require(channel.metadata.level, if_noticed=True),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
)
@dispatch(AlconnaDispatcher(Alconna(
    "插件列表",
    meta=CommandMeta(
        "查询已/未加载的插件",
        usage="",
        example="插件列表",
    ),
)))
async def get_modules_list(app: Ariadne, ori_place: Union[Group, Friend], src: Source):
    # 菜单信息
    usage = [ColumnListItem(
        content=use_item,
    ) for use_item in channel.metadata.usage]
    example = [ColumnListItem(
        content=example_item,
    ) for example_item in channel.metadata.example]
    menu_column = Column(elements=[
        ColumnTitle(title="插件列表"),
        ColumnTitle(title="用法"),
        ColumnList(
            rows=usage
        ),
        ColumnTitle(title="示例"),
        ColumnList(
            rows=example
        ),
    ])
    # 已加载插件
    loaded_columns = [ColumnTitle(title="已加载插件")]
    for i, channel_temp in enumerate(saya.channels):
        loaded_columns.append(ColumnList(rows=[
            ColumnListItem(
                # 副标题
                subtitle=f"{i + 1}.{module_controller.get_metadata_from_module_name(channel_temp).display_name or saya.channels[channel_temp].meta['name'] or channel_temp.split('.')[-1]}",
                # 内容
                content=channel_temp,
                # 开关指示
                right_element=ColumnListItemSwitch(
                    switch=module_controller.if_module_available(channel_temp))
            )
        ]))
    loaded_columns = [Column(elements=loaded_columns[i: i + 20]) for i in range(0, len(loaded_columns), 20)]
    # 未加载插件
    unloaded_columns = [ColumnTitle(title="未加载插件")]
    for i, channel_temp in enumerate(module_controller.get_not_installed_channels()):
        unloaded_columns.append(ColumnList(rows=[
            ColumnListItem(
                # 副标题
                subtitle=f"{i + 1 + len(saya.channels.keys())}.{module_controller.get_metadata_from_module_name(channel_temp).display_name or channel_temp.split('.')[-1]}",
                # 内容
                content=channel_temp,
            )
        ]))
    unloaded_columns = [Column(elements=unloaded_columns[i: i + 20]) for i in range(0, len(unloaded_columns), 20)]
    return await app.send_message(ori_place, MessageChain(
        Image(data_bytes=await OneMockUI.gen(
            GenForm(columns=[menu_column] + loaded_columns + unloaded_columns, color_type=get_color_type_follow_time())
        ))
    ), quote=src)


#   加载插件
#   卸载插件
#   重载插件
@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Permission.user_require(Permission.Master, if_noticed=True),
    Permission.group_require(channel.metadata.level, if_noticed=True),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
)
@dispatch(
    Twilight([
        UnionMatch("加载", "卸载", "重载") @ "operation",
        FullMatch("插件"),
        RegexMatch("[0-9]+") @ "index"
    ])
)
async def change_module_status(
        app: Ariadne,
        group: Group,
        member: Member,
        source: Source,
        operation: RegexResult,
        index: RegexResult
):
    operation = operation.result.display
    index = int(index.result.display) if index.result.display.isdigit() else None
    if not index:
        return await app.send_message(group, MessageChain(f"请检查输入的编号!"), quote=source)
    if operation == "加载":
        operation_type = saya_model.ModuleOperationType.INSTALL
    else:
        operation_type = saya_model.ModuleOperationType.UNINSTALL if operation == "卸载" else saya_model.ModuleOperationType.RELOAD
    modules = sorted(module_controller.get_installed_channels() + module_controller.get_not_installed_channels())
    if index == 0 or index > len(modules):
        return await app.send_message(group, MessageChain(f"当前只有{len(modules)}个插件哦~\n(index:{index})"), quote=source)
    module = modules[index - 1]
    await app.send_message(group, MessageChain(f"你确定要{operation}插件`{module}`吗?(是/否)"), quote=source)
    try:
        if await asyncio.wait_for(inc.wait(ConfirmWaiter(group, member)), 30):
            if operation == "加载":
                module_controller.add_module(module)
            exceptions = module_controller.module_operation(module, operation_type)
            if exceptions:
                return await app.send_group_message(
                    group,
                    MessageChain("\n".join(f"模块<{m}>{operation}发生错误:{e}" for m, e in exceptions.items())),
                    quote=source
                )
            return await app.send_group_message(group, MessageChain(f"模块:{module}{operation}完成"), quote=source)
        else:
            return await app.send_message(group, MessageChain(f"未预期回复,操作退出"), quote=source)
    except asyncio.TimeoutError:
        return await app.send_group_message(group, MessageChain("回复等待超时,进程退出"), quote=source)


#   开启插件
#   关闭插件
@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Permission.user_require(Permission.BotAdmin, if_noticed=True),
    Permission.group_require(channel.metadata.level, if_noticed=True),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
)
@dispatch(
    Twilight([
        UnionMatch("开启", "关闭") @ "operation",
        FullMatch("插件"),
        RegexMatch("[0-9]+") @ "index"
    ])
)
async def switch_module(
        app: Ariadne,
        group: Group,
        member: Member,
        source: Source,
        operation: RegexResult,
        index: RegexResult
):
    operation = operation.result.display
    index = int(index.result.display)
    modules = module_controller.get_installed_channels() + module_controller.get_not_installed_channels()
    module = modules[index - 1]
    if index == 0 or index > len(modules):
        return await app.send_message(group, MessageChain(f"当前只有{len(modules)}(index:{index})个插件~"), quote=source)
    if operation == "开启" and module_controller.if_module_available(module):
        return await app.send_message(group, MessageChain(f"插件{module}已处于开启状态!"), quote=source)
    elif operation == "关闭" and (not module_controller.if_module_available(module)):
        if module in module_controller.get_required_modules():
            return await app.send_message(group, MessageChain(f"无法关闭必须插件!"), quote=source)
        return await app.send_message(group, MessageChain(f"插件{module}已处于关闭状态!"), quote=source)
    await app.send_message(group, MessageChain(f"你确定要{operation}插件`{module}`吗?(是/否)"), quote=source)
    try:
        if await asyncio.wait_for(inc.wait(ConfirmWaiter(group, member)), 30):
            exceptions = module_controller.enable_module(
                module) if operation == "开启" else module_controller.disable_module(module)
            if exceptions:
                return await app.send_group_message(
                    group,
                    MessageChain("\n".join(f"模块<{m}>{operation}发生错误:{e}" for m, e in exceptions.items())),
                    quote=source
                )
            return await app.send_group_message(group, MessageChain(f"模块:{module}{operation}完成"), quote=source)
        else:
            return await app.send_message(group, MessageChain(f"未预期回复,操作退出"), quote=source)
    except asyncio.TimeoutError:
        return await app.send_group_message(group, MessageChain("回复等待超时,进程退出"), quote=source)
