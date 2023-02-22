import random
from pathlib import Path

from creart import create
from graia.ariadne.app import Ariadne
from graia.ariadne.event.message import GroupMessage
from graia.ariadne.message.chain import MessageChain
from graia.ariadne.message.element import Image, Source
from graia.ariadne.message.parser.twilight import (
    Twilight,
    RegexResult, UnionMatch, RegexMatch
)
from graia.ariadne.model import Group
from graia.ariadne.util.saya import listen, dispatch, decorate
from graia.saya import Channel, Saya

from core.bot import Umaru
from core.config import GlobalConfig
from core.control import (
    Permission,
    Function,
    FrequencyLimitation,
    Distribute
)
from core.models import (
    saya_model,
    response_model
)
from utils.UI import *
from utils.image import get_img_base64_str

config = create(GlobalConfig)
core = create(Umaru)

module_controller = saya_model.get_module_controller()
account_controller = response_model.get_acc_controller()

saya = Saya.current()
channel = Channel.current()
channel.name("Helper")
channel.description("生成帮助菜单信息(必须插件)")
channel.author("13")
channel.metadata = module_controller.get_metadata_from_path(Path(__file__))


@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level, if_noticed=True),
    Permission.user_require(Permission.User, if_noticed=True),
)
@dispatch(
    Twilight([
        UnionMatch("帮助", "-help", "-帮助"),
        # 示例: 帮助
    ])
)
async def helper(app: Ariadne, group: Group, source: Source):
    """生成帮助菜单
    三个部分:
    一、必须插件
    二、正常插件
    三、维护插件
    """
    required_module_list = module_controller.get_required_modules()
    normal_module_list = module_controller.get_available_modules()
    unavailable_module_list = module_controller.get_unavailable_modules()

    # 菜单信息
    usage = [ColumnListItem(
        content=use_item,
    ) for use_item in channel.metadata.usage]
    example = [ColumnListItem(
        content=example_item,
    ) for example_item in channel.metadata.example]
    dirs = [e for e in (Path("statics") / "Emoticons").iterdir()]

    # 必须插件
    required_columns = [
        ColumnTitle(title="小埋BOT帮助菜单"),
        ColumnUserInfo(
            name=f"どま うまる",
            avatar=get_img_base64_str(Path.read_bytes(random.choice(dirs))),
            description="如有疑问可加群749094683咨询"
        ),
        ColumnTitle(title="用法"),
        ColumnList(
            rows=usage
        ),
        ColumnTitle(title="示例"),
        ColumnList(
            rows=example
        ),
        ColumnTitle(title="内置插件")
    ]
    for i, channel_temp in enumerate(required_module_list):
        required_columns.append(ColumnList(rows=[
            ColumnListItem(
                # 副标题
                subtitle=f"{i + 1}.{module_controller.get_metadata_from_module_name(channel_temp).display_name or saya.channels[channel_temp].meta['name'] or channel_temp.split('.')[-1]}",
            )
        ]))
    required_columns = [Column(elements=required_columns[i: i + 20]) for i in range(0, len(required_columns), 20)]
    # 正常插件
    module_columns = [ColumnTitle(title="运行插件")]
    for i, channel_temp in enumerate(normal_module_list):
        module_columns.append(ColumnList(rows=[
            ColumnListItem(
                # 副标题
                subtitle=f"{i + 1 + len(required_module_list)}.{module_controller.get_metadata_from_module_name(channel_temp).display_name or saya.channels[channel_temp].meta['name'] or channel_temp.split('.')[-1]}",
                # 开关指示
                right_element=ColumnListItemSwitch(switch=module_controller.if_module_switch_on(channel_temp, group.id))
            )
        ]))
    # 维护插件
    module_columns.append(ColumnTitle(title="维护插件"))
    for i, channel_temp in enumerate(unavailable_module_list):
        module_columns.append(ColumnList(rows=[
            ColumnListItem(
                # 副标题
                subtitle=f"{i + len(saya.channels.keys())}.{module_controller.get_metadata_from_module_name(channel_temp).display_name or channel_temp.split('.')[-1]}",

            )
        ]))
    module_columns = [Column(elements=module_columns[i: i + 20]) for i in range(0, len(module_columns), 20)]
    return await app.send_message(group, MessageChain(
        Image(data_bytes=await OneMockUI.gen(
            GenForm(columns=required_columns + module_columns, color_type=get_color_type_follow_time())
        ))
    ), quote=source)


# 获取功能详情
@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level, if_noticed=True),
    Permission.user_require(Permission.User, if_noticed=True),
)
@dispatch(
    Twilight([
        UnionMatch("帮助", "-help", "-帮助"),
        RegexMatch("[0-9]+$") @ "index"
        # 示例: 帮助 1
    ])
)
async def module_helper(app: Ariadne, group: Group, source: Source, index: RegexResult):
    """生成功能详情帮助
    """
    if not index.result.display.isdigit():
        return
    index = int(index.result.display) - 1
    required_module_list = module_controller.get_required_modules()
    normal_module_list = module_controller.get_available_modules()
    module_list = required_module_list + normal_module_list
    if not (0 <= index < len(module_list)):
        return await app.send_message(group, MessageChain("编号不在范围内~"), quote=source)
    module_metadata = module_controller.get_metadata_from_module_name(module_list[index])
    if module_metadata.usage:
        usage = [ColumnListItem(
            content=use_item,
        ) for use_item in module_metadata.usage]
    else:
        usage = [ColumnListItem(
            content="暂无",
        )]
    if module_metadata.example:
        example = [ColumnListItem(
            content=example_item,
        ) for example_item in module_metadata.example]
    else:
        example = [ColumnListItem(
            content="暂无",
        )]
    # display_name
    # module_name

    # 版本
    # 作者

    # 描述

    # 用法

    # 示例
    module_column = [Column(
        elements=[
            ColumnTitle(title="插件详情"),
            ColumnList(rows=[
                ColumnListItem(
                    subtitle=module_metadata.display_name or module_metadata.name or saya.channels[module_list[index]].meta['name'] or module_list[index].split('.')[-1],
                    content=module_list[index]
                ),
                ColumnListItem(
                    subtitle="版本",
                ),
                ColumnListItem(
                    content=module_metadata.version
                ),
                ColumnListItem(
                    subtitle="作者",
                    content=",".join(module_metadata.authors)
                )
            ]),
            ColumnTitle(title="描述"),
            ColumnList(rows=[ColumnListItem(
                content=module_metadata.description if module_metadata.description else "暂无",
            )]),
            ColumnTitle(title="用法"),
            ColumnList(
                rows=usage
            ),
            ColumnTitle(title="示例"),
            ColumnList(
                rows=example
            )
        ]
    )]

    return await app.send_message(group, MessageChain(
        Image(data_bytes=await OneMockUI.gen(
            GenForm(columns=module_column, color_type=get_color_type_follow_time())
        ))
    ), quote=source)


# 开关功能
@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level, if_noticed=True),
    Permission.user_require(Permission.GroupAdmin, if_noticed=True),
)
@dispatch(
    Twilight([
        UnionMatch("-开启", "-关闭") @ "operation",
        RegexMatch("[0-9]+") @ "index"
    ])
)
async def change_module_switch(
        app: Ariadne,
        group: Group,
        source: Source,
        operation: RegexResult,
        index: RegexResult
):
    """开关
    """
    operation = operation.result.display.replace("-", "")
    index = int(index.result.display) - 1
    required_module_list = module_controller.get_required_modules()
    normal_module_list = module_controller.get_available_modules()
    module_list = required_module_list + normal_module_list
    if not (0 <= index < len(module_list)):
        return await app.send_message(group, MessageChain("编号不在运行插件范围内~"), quote=source)
    target_module = module_list[index]
    module_meta = module_controller.get_metadata_from_module_name(target_module)
    target_name = module_meta.display_name or module_meta.name or target_module
    if target_module in required_module_list:
        return await app.send_message(group, MessageChain(f"无法操作必须插件<{target_name}>"), quote=source)
    if operation == "开启" and module_controller.if_module_switch_on(target_module, group):
        return await app.send_message(group, MessageChain(
            f"功能{target_name}已处于{operation}状态请不要重复{operation}!"
        ), quote=source)
    elif operation == "关闭" and not module_controller.if_module_switch_on(target_module, group):
        return await app.send_message(group, MessageChain(
            f"功能{target_name}已处于{operation}状态请不要重复{operation}!"
        ), quote=source)
    if operation == "开启":
        module_controller.turn_on_module(target_module, group)
        return await app.send_message(group, MessageChain(f"功能<{target_name}>已开启~"), quote=source)
    else:
        module_controller.turn_off_module(target_module, group)
        return await app.send_message(group, MessageChain(f"功能<{target_name}>已关闭~"), quote=source)
