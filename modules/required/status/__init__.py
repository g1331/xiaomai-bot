import time
from datetime import datetime
from pathlib import Path
from typing import Union

import psutil
from creart import create
from graia.ariadne.app import Ariadne
from graia.ariadne.event.message import GroupMessage, FriendMessage
from graia.ariadne.message.chain import MessageChain
from graia.ariadne.message.element import Source
from graia.ariadne.message.parser.twilight import Twilight, SpacePolicy, FullMatch
from graia.ariadne.model import Group, Friend
from graia.ariadne.util.saya import listen, dispatch, decorate
from graia.saya import Channel, Saya
from graia.scheduler import timers
from graia.scheduler.saya import SchedulerSchema

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

config = create(GlobalConfig)
core = create(Umaru)
module_controller = saya_model.get_module_controller()
account_controller = response_model.get_acc_controller()

saya = Saya.current()
channel = Channel.current()
channel.name("Status")
channel.description("查询BOT运行状态")
channel.author("13")
channel.metadata = module_controller.get_metadata_from_path(Path(__file__))

message_receive_before = 0
message_send_before = 0
Real_time_message_receive = 0
Real_time_message_send = 0


# 接收事件
@listen(GroupMessage, FriendMessage)
# 依赖注入
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level, if_noticed=True),
    Permission.user_require(Permission.User, if_noticed=True),
)
# 消息链处理器
@dispatch(Twilight([
    FullMatch("-bot").space(SpacePolicy.PRESERVE)
]))
async def bot(app: Ariadne, src_place: Union[Group, Friend], source: Source):
    global Real_time_message_receive, Real_time_message_send
    # 运行时长
    time_start = int(time.mktime(core.launch_time.timetuple()))
    m, s = divmod(int(time.time()) - time_start, 60)
    h, m = divmod(m, 60)
    d, h = divmod(h, 24)
    work_time = "%d天%d小时%d分%d秒" % (d, h, m, s)

    # 内存占用
    mem = psutil.virtual_memory()
    # 系统总计内存(单位字节)
    # 系统已经使用内存(单位字节)
    ysy = float(mem.used)
    # 系统空闲内存(单位字节)
    # 内存占比
    zb = float(mem.percent)
    # cpu占用
    zb2 = str(psutil.cpu_percent(interval=None, percpu=False)) + "%"
    # 磁盘
    cp = str(psutil.disk_usage('/').percent) + "%"
    launch_time = datetime.fromtimestamp(core.launch_time.timestamp()).strftime('%Y年%m月%d日%H时%M分%S秒')
    await app.send_message(src_place, MessageChain(
        f"开机时间：{launch_time}\n",
        f"运行时长：{work_time}\n",
        f"接收消息：{core.received_count}条(实时:%.1f/m)\n" % Real_time_message_receive,
        f"发送消息：{core.sent_count + 1}条(实时:%.1f/m)\n" % Real_time_message_send,
        f"内存使用：%.0fMB" % (ysy / 1024 / 1024),
        f"(%.0f%%)\n" % zb,
        f"CPU占比：{zb2}\n",
        f"磁盘占比：{cp}\n",
        f"在线bot数量:{len([app_item for app_item in core.apps if Ariadne.current(app_item.account).connection.status.available])}\n",
        f"活动群组数量:{len(account_controller.total_groups.keys())}\n",
        f"反馈Q群:749094683\n",
        f"爱发电地址:https://afdian.net/a/ss1333\n",
        f"项目地址:https://github.com/g1331/xiaomai-bot"
    ), quote=source)


# 自动刷新client
@channel.use(SchedulerSchema(timers.every_custom_minutes(1)))
async def message_counter():
    global message_receive_before, message_send_before, Real_time_message_receive, Real_time_message_send
    Real_time_message_receive = core.received_count - message_receive_before
    Real_time_message_send = core.sent_count - message_send_before
    message_receive_before = core.received_count
    message_send_before = core.sent_count
