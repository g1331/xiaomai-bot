import time
from collections import deque
from datetime import datetime
from pathlib import Path

import psutil
from creart import create
from graia.ariadne.app import Ariadne
from graia.ariadne.event.message import FriendMessage, GroupMessage
from graia.ariadne.message.chain import MessageChain
from graia.ariadne.message.element import Source
from graia.ariadne.message.parser.twilight import FullMatch, SpacePolicy, Twilight
from graia.ariadne.model import Friend, Group
from graia.ariadne.util.saya import decorate, dispatch, listen
from graia.saya import Channel, Saya
from graia.scheduler import timers
from graia.scheduler.saya import SchedulerSchema

from core.bot import Umaru
from core.config import GlobalConfig
from core.control import Distribute, FrequencyLimitation, Function, Permission
from core.models import response_model, saya_model
from utils.version_info import get_full_version_info

config = create(GlobalConfig)
core = create(Umaru)
module_controller = saya_model.get_module_controller()
account_controller = response_model.get_acc_controller()

saya = Saya.current()
channel = Channel.current()
channel.meta["name"] = "Status"
channel.meta["description"] = "查询BOT运行状态"
channel.meta["author"] = "13"
channel.metadata = module_controller.get_metadata_from_path(Path(__file__))


class MessageCount:
    """
    用于管理和检索消息计数统计信息的类。
    """

    def __init__(self):
        """
        初始化 MessageCount 实例。
        """
        self.receive_queue: deque[tuple[int, float]] = deque()
        self.send_queue: deque[tuple[int, float]] = deque()

    async def update_message_counts(self) -> None:
        """
        更新消息计数。

        参数:
        - core: 包含消息计数数据的对象。

        注意:
        - 为更新消息计数日志，应定期调用此方法。
        """
        self.receive_queue.append((core.received_count, time.time()))
        self.send_queue.append((core.sent_count, time.time()))

    def get_receive_count(self, time_limit: int | float = 60) -> int:
        """
        获取过去指定时间内接收到的消息数量。

        参数:
        - time_limit: Union[int, float], 指定的时间范围，单位为秒，默认为60秒。

        返回:
        - int: 过去指定时间内接收到的消息数量。
        """
        current_time = time.time()
        # 从队列前端移除超过60秒的条目
        while (
            self.receive_queue and current_time - self.receive_queue[0][1] > time_limit
        ):
            self.receive_queue.popleft()

        # 计算并返回过去一分钟内消息计数的差值
        return (
            self.receive_queue[-1][0] - self.receive_queue[0][0]
            if self.receive_queue
            else 0
        )

    def get_send_count(self, time_limit: int | float = 60) -> int:
        """
        获取过去指定时间内发送的消息数量。

        参数:
        - time_limit: Union[int, float], 指定的时间范围，单位为秒，默认为60秒。

        返回:
        - int: 过去指定时间内发送的消息数量。
        """
        current_time = time.time()
        # 从队列前端移除超过60秒的条目
        while self.send_queue and current_time - self.send_queue[0][1] > time_limit:
            self.send_queue.popleft()

        # 计算并返回过去一分钟内消息计数的差值
        return self.send_queue[-1][0] - self.send_queue[0][0] if self.send_queue else 0


message_count = MessageCount()


@channel.use(SchedulerSchema(timers.every_custom_seconds(3)))
async def message_counter():
    await message_count.update_message_counts()


# 接收事件
@listen(GroupMessage, FriendMessage)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level, if_noticed=True),
    Permission.user_require(Permission.User, if_noticed=True),
)
@dispatch(Twilight([FullMatch("-bot").space(SpacePolicy.PRESERVE)]))
async def status(app: Ariadne, src_place: Group | Friend, source: Source):
    # 获取版本信息
    version, git_info, b2v_info = get_full_version_info()

    # 运行时长
    time_start = int(time.mktime(core.launch_time.timetuple()))
    m, s = divmod(int(time.time()) - time_start, 60)
    h, m = divmod(m, 60)
    d, h = divmod(h, 24)
    work_time = f"{d}天{h}小时{m}分{s}秒"

    # 内存占用
    mem = psutil.virtual_memory()
    # 系统总计内存(单位字节)
    # 系统已经使用内存(单位字节)
    ysy = float(mem.used)
    # 系统空闲内存(单位字节)
    # 内存占比
    zb = float(mem.percent)
    # cpu占用
    zb2 = f"{str(psutil.cpu_percent(interval=None, percpu=False))}%"
    # 磁盘
    cp = str(psutil.disk_usage("/").percent) + "%"
    launch_time = datetime.fromtimestamp(core.launch_time.timestamp()).strftime(
        "%Y年%m月%d日%H时%M分%S秒"
    )
    real_time_received_message_count = message_count.get_receive_count()
    real_time_sent_message_count = message_count.get_send_count()

    # 版本信息块
    version_info = f"版本信息：v{version}\n"
    if git_info["commit_short"] != "未知":
        version_info += f"Git分支：{git_info['branch']}\n"
        version_info += (
            f"最新提交：{git_info['commit_short']} ({git_info['commit_author']})\n"
        )
        version_info += f"提交信息：{git_info['commit_message']}\n"

    # 构建信息块
    build_info = ""
    if b2v_info["build_number"] != "开发环境":
        build_info = f"构建编号：{b2v_info['build_number']}\n"
        if b2v_info["build_date"]:
            build_info += f"构建日期：{b2v_info['build_date']}\n"
        build_info += f"构建类型：{b2v_info['build_type']}\n"

    await app.send_message(
        src_place,
        MessageChain(
            f"开机时间：{launch_time}\n",
            f"运行时长：{work_time}\n",
            f"接收消息：{core.received_count}条 (实时:{real_time_received_message_count}条/m)\n"
            f"发送消息：{core.sent_count + 1}条 (实时:{real_time_sent_message_count}条/m)\n"
            f"内存使用：{ysy / 1024 / 1024:.0f}MB ({zb:.0f}%)\n",
            f"CPU占比：{zb2}\n",
            f"磁盘占比：{cp}\n",
            f"在线bot数量：{len([app_item for app_item in core.apps if Ariadne.current(app_item.account).connection.status.available])}/"
            f"{len(core.apps)}\n",
            f"活动群组数量：{len(account_controller.total_groups.keys())}\n",
            version_info,
            build_info,
            "项目地址：https://github.com/g1331/xiaomai-bot",
        ),
        quote=source,
    )
