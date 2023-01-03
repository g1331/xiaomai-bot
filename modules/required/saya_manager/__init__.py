import asyncio
from pathlib import Path
from typing import Union

from arclet.alconna import Alconna, CommandMeta, Args
from arclet.alconna.graia import AlconnaDispatcher, assign, Query, Match
from arclet.alconna.tools import MarkdownTextFormatter, ArgParserTextFormatter
from creart import create
from graia.ariadne.app import Ariadne
from graia.ariadne.event.message import GroupMessage, FriendMessage
from graia.ariadne.message.chain import MessageChain
from graia.ariadne.message.element import Image, Source
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
module_controller = saya_model.get_module_data()

saya = Saya.current()
channel = Channel.current()
channel.name("SayaManager")
channel.description("负责插件管理(必须插件)")
channel.author("13")
channel.metadata = module_controller.get_metadata_from_file(Path(__file__))

inc = InterruptControl(saya.broadcast)


# TODO
#   插件列表
#   已加载插件
#   未加载插件
@listen(GroupMessage, FriendMessage)
@decorate(
    Permission.user_require(Permission.GroupAdmin, if_noticed=True),
    Permission.group_require(channel.metadata.level, if_noticed=True),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Distribute.require()
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
    form = GenForm(
        columns=[
            # 菜单信息
            Column(
                elements=[
                    ColumnTitle(title="插件列表"),
                    # ColumnImage(src=""),
                    ColumnList(
                        rows=[
                            ColumnListItem(
                                content="发送 '-插件 卸载/重载 {编号}' 来卸载/重载已加载插件",
                            ),
                            ColumnListItem(
                                content="发送 '-插件 加载 {编号}' 来加载未加载插件",
                            ),
                            ColumnListItem(
                                content="发送 '-插件 开启/关闭 {编号}' 来修改插件的可用状态",
                            )
                        ]
                    )
                ]
            ),
            # 已加载插件
            Column(
                elements=[
                    ColumnTitle(title="已加载插件"),
                    ColumnList(
                        rows=[
                            ColumnListItem(
                                # 副标题
                                subtitle=f"{i + 1}.{module_controller.get_metadata_from_file(channel_temp).display_name or saya.channels[channel_temp].meta['name'] or channel_temp.split('.')[-1]}",
                                # 内容
                                content=channel_temp,
                                # 开关指示
                                right_element=ColumnListItemSwitch(
                                    switch=module_controller.if_module_available(channel_temp))
                            ) for i, channel_temp in enumerate(saya.channels)
                        ]
                    )
                ]
            ),
            # 未加载插件
            Column(
                elements=[
                    ColumnTitle(title="未加载插件"),
                    ColumnList(
                        rows=[
                            ColumnListItem(
                                # 副标题
                                subtitle=f"{i + 1 + len(saya.channels.keys())}.{module_controller.get_metadata_from_file(channel_temp).display_name or channel_temp.split('.')[-1]}",
                                # 内容
                                content=channel_temp,
                            ) for i, channel_temp in enumerate(module_controller.get_not_installed_channels())
                        ]
                    )
                ]
            )
        ],
        color_type="dark"
    )
    return await app.send_message(ori_place, MessageChain(Image(data_bytes=await OneMockUI.gen(form))), quote=src)


#   加载插件
#   卸载插件
#   重载插件
operation_list = ["加载", "卸载", "重载"]
module_operation_order = Alconna(
    "-插件",
    Args['operation#执行的操作', operation_list],
    "index#插件编号", Args.num[int],
    meta=CommandMeta(
        "对插件的操作",
        usage="传入被操作插件的编号",
        example="-插件 operation index",
    ),
    formatter_type=ArgParserTextFormatter
)


@listen(GroupMessage)
@decorate(
    Permission.user_require(Permission.Master, if_noticed=True),
    Permission.group_require(channel.metadata.level, if_noticed=True),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Distribute.require()
)
@dispatch(AlconnaDispatcher(module_operation_order))
@assign("operation", or_not=True)
async def install_module(
        app: Ariadne,
        group: Group,
        member: Member,
        source: Source,
        operation: Match[str],
        index: Query[int] = Query("num")
):
    operation = operation.result
    if operation == "加载":
        operation_type = saya_model.ModuleOperationType.INSTALL
    else:
        operation_type = saya_model.ModuleOperationType.UNINSTALL if operation == "卸载" else saya_model.ModuleOperationType.RELOAD
    index = index.result
    modules = module_controller.get_installed_channels() + module_controller.get_not_installed_channels()
    module = modules[index - 1]
    if index == 0 or index > len(modules):
        return await app.send_message(group, MessageChain(f"当前只有{len(modules)}(index:{index})个插件~"), quote=source)
    await app.send_message(group, MessageChain(f"你确定要{operation}插件`{module}`吗?(是/否)"), quote=source)
    try:
        if await asyncio.wait_for(inc.wait(ConfirmWaiter(group, member)), 30):
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
operation_list = ["开启", "关闭"]
module_switch_order = Alconna(
    "-插件",
    Args['operation#执行的操作', operation_list],
    "index#插件编号", Args.num[int],
    meta=CommandMeta(
        "对插件的操作",
        usage="传入被操作插件的编号",
        example="-插件 operation index",
    ),
    formatter_type=ArgParserTextFormatter
)


@listen(GroupMessage)
@decorate(
    Permission.user_require(Permission.Master, if_noticed=True),
    Permission.group_require(channel.metadata.level, if_noticed=True),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Distribute.require()
)
@dispatch(AlconnaDispatcher(module_switch_order))
@assign("operation", or_not=True)
async def install_module(
        app: Ariadne,
        group: Group,
        member: Member,
        source: Source,
        operation: Match[str],
        index: Query[int] = Query("num")
):
    operation = operation.result
    index = index.result
    modules = module_controller.get_installed_channels() + module_controller.get_not_installed_channels()
    module = modules[index - 1]
    if index == 0 or index > len(modules):
        return await app.send_message(group, MessageChain(f"当前只有{len(modules)}(index:{index})个插件~"), quote=source)
    await app.send_message(group, MessageChain(f"你确定要{operation}插件`{module}`吗?(是/否)"), quote=source)
    try:
        if await asyncio.wait_for(inc.wait(ConfirmWaiter(group, member)), 30):
            exceptions = module_controller.enable_module(module) if operation == "开启" else module_controller.disable_module(module)
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
