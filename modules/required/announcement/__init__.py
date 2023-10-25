import asyncio
from pathlib import Path

from creart import create
from graia.ariadne.app import Ariadne
from graia.ariadne.event.message import GroupMessage
from graia.ariadne.message.chain import MessageChain
from graia.ariadne.message.element import Source, At
from graia.ariadne.message.parser.twilight import (
    Twilight,
    FullMatch,
    ParamMatch,
    RegexResult, SpacePolicy, ArgumentMatch, ArgResult
)
from graia.ariadne.model import Group, Member
from graia.ariadne.util.saya import listen, dispatch, decorate
from graia.broadcast.interrupt import InterruptControl
from graia.saya import Channel, Saya
from loguru import logger

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
from utils.string import generate_random_str
from utils.waiter import ConfirmWaiter

config = create(GlobalConfig)
core = create(Umaru)

module_controller = saya_model.get_module_controller()
account_controller = response_model.get_acc_controller()
saya = Saya.current()
channel = Channel.current()
#channel.name("Announcement")
#channel.description("推送公告到符合条件的群")
#channel.author("13")
channel.metadata = module_controller.get_metadata_from_path(Path(__file__))

inc = InterruptControl(saya.broadcast)


# 查询拥有多个BOT的群，以及BOT列表
@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level, if_noticed=True),
    Permission.user_require(Permission.BotAdmin, if_noticed=True),
)
@dispatch(
    Twilight([
        FullMatch("-公告"),
        ArgumentMatch("-t", "-time", optional=True, type=int, default=1) @ "time_interval",
        "function_name" @ ParamMatch(optional=False).space(SpacePolicy.FORCE),
        "content" @ ParamMatch(optional=False),
        # 示例: -公告 帮助菜单 你好
    ])
)
async def push_handle(
        app: Ariadne, group: Group, source: Source, member: Member, time_interval: ArgResult,
        function_name: RegexResult, content: RegexResult
):
    time_interval = time_interval.result
    if not (0 < time_interval < 10):
        return await app.send_message(group, MessageChain(f"间隔时间需要在0~10之间哦!匹配到的时间:{time_interval}"), quote=source)
    function_name = function_name.result.display
    content = content.result.display
    content = f"""
    ===BOT公告推送===
    {content}
    """
    # 获取打开了功能的群
    available_modules = module_controller.get_required_modules() + module_controller.get_available_modules()
    module_name = None
    for channel_temp in available_modules:
        temp_name = module_controller.get_metadata_from_module_name(channel_temp).display_name or \
                    saya.channels[channel_temp].meta[
                        'name'] or channel_temp.split('.')[-1]
        if temp_name == function_name:
            module_name = channel_temp
    if not module_name:
        return await app.send_message(group, MessageChain(f"没有在运行插件中找到 {function_name} 哦~"), quote=source)
    push_list = []
    for group_id in account_controller.account_dict:
        target_app, target_group = await account_controller.get_app_from_total_groups(group_id)
        if target_app and target_group and module_controller.if_module_switch_on(module_name, target_group):
            push_list.append([target_app, target_group])
    if not push_list:
        return await app.send_message(group, MessageChain(f"没有满足条件的群哦~"), quote=source)
    else:
        try:
            await app.send_message(
                group,
                MessageChain(
                    f"推送示例:\n“{content}\n    ({generate_random_str(20)})”\n预计在{len(push_list) * time_interval}分钟内推送到{len(push_list)}个群(间隔:{time_interval})确定要推送吗?(是/否)"),
                quote=source
            )
            if not await asyncio.wait_for(inc.wait(ConfirmWaiter(group, member)), 30):
                return await app.send_message(group, MessageChain(f"未预期回复,操作退出"), quote=source)
        except asyncio.TimeoutError:
            return await app.send_group_message(group, MessageChain("回复等待超时,进程退出"), quote=source)
        await app.send_message(
            group,
            MessageChain(f"开始推送!\n预计在{len(push_list)}分钟内推送到{len(push_list)}个群~"),
            quote=source
        )
        await pusher(push_list, content, time_interval)
        return await app.send_message(
            group,
            MessageChain([At(member), f"您的公告\n“{content}”\n已推送完毕!"]),
            quote=source
        )


async def pusher(push_list, content, time):
    for item in push_list:
        item: list[Ariadne, Group]
        target_app, target_group = item
        try:
            await target_app.send_message(
                target_group,
                MessageChain(content + f"\n    ({generate_random_str(20)})")
            )
        except Exception as e:
            logger.error(
                f"推送公告到群{target_group.id}时发送错误!{e}"
            )
        finally:
            await asyncio.sleep(time * 60)
