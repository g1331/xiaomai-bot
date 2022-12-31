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
from graia.ariadne.message.parser.twilight import Twilight, UnionMatch, SpacePolicy, FullMatch
from graia.ariadne.model import Group, Friend
from graia.ariadne.util.saya import listen, dispatch, decorate
from graia.saya import Channel, Saya
from loguru import logger

from core.bot import Umaru
from core.config import GlobalConfig
from core.control import Permission, Function
from core.saya_modules import ModulesController
from modules.test_modules.test1.test_depend import test_depend

saya = Saya.current()
channel = Channel.current()
channel.name(channel.module)
channel.description("bot的运行状态")
channel.author("13")
channel.metadata = ModulesController.get_metadata_from_file(Path(__file__))

config = create(GlobalConfig)
core = create(Umaru)


# 接收事件
@listen(GroupMessage, FriendMessage)
# 依赖注入
@decorate(Permission.user_require(Permission.User))
# 消息链处理器
@dispatch(Twilight(["action" @ FullMatch("-bot").space(SpacePolicy.PRESERVE)]))
async def bot(app: Ariadne, src_place: Union[Group, Friend], source: Source):
    # 运行时长
    time_start = int(time.mktime(core.launch_time.timetuple()))
    m, s = divmod(int(time.time()) - time_start, 60)
    h, m = divmod(m, 60)
    d, h = divmod(h, 24)
    work_time = "%d天%d小时%d分%d秒" % (d, h, m, s)

    # 内存占用
    mem = psutil.virtual_memory()
    # 系统总计内存(单位字节)
    # zj = float(mem.total)
    # 系统已经使用内存(单位字节)
    ysy = float(mem.used)
    # 系统空闲内存(单位字节)
    # kx = float(mem.free)
    # 内存占比
    zb = float(mem.percent)
    # cpu占用
    zb2 = str(psutil.cpu_percent(interval=None, percpu=False)) + "%"
    # 磁盘
    cp = str(psutil.disk_usage('/').percent) + "%"
    receive_counter = core.received_count
    send_counter = core.sent_count
    launch_time = datetime.fromtimestamp(core.launch_time.timestamp()).strftime('%Y年%m月%d日%H时%M分%S秒')
    active_groups = []
    for account, group_list in core.total_groups.items():
        active_groups = [group.id for group in group_list]
    await app.send_message(src_place, MessageChain(
        f"开机时间：{launch_time}\n"
        f"运行时长：{work_time}\n"
        f"接收消息：{receive_counter}条(%.1f/m)\n" % ((receive_counter / (int(time.time()) - time_start)) * 60),
        f"发送消息：{send_counter + 1}条(%.1f/m)\n" % ((send_counter + 1) / (int(time.time()) - time_start) * 60),
        '内存使用：%.2fMB\n' % (ysy / 1024 / 1024),
        '内存占比：%.0f%%\n' % zb,
        f'CPU占比：{zb2}\n',
        f'磁盘占比：{cp}\n',
        f"在线bot数量:{len(Ariadne.service.connections)}\n",
        f"活动群组数量:{len(active_groups)}\n"
        f"反馈Q群:749094683\n",
        f"爱发电地址:https://afdian.net/a/ss1333\n"
        f"项目地址:https://github.com/g1331/xiaomai-bot"
    ), quote=source)


# 接收事件
@listen(GroupMessage, FriendMessage)
# 依赖注入
@decorate(test_depend.user_require())
# 消息链处理器
@dispatch(Twilight(["action" @ UnionMatch("-test", optional=False).space(SpacePolicy.PRESERVE)]))
async def fun():
    logger.success("执行成功")


@listen(GroupMessage, FriendMessage)
@decorate(
    Permission.user_require(Permission.Admin),
    Permission.group_require(channel.metadata.level),
    Function.require(channel.module)
)
@dispatch(Twilight([FullMatch("-test")]))
async def fun_test(app: Ariadne, ori_place: Union[Group, Friend], src: Source):
    try:
        logger.info(channel.module)
        logger.info(channel.meta)
        # for item in channel.content[:1]:
        #     logger.info(item.content)
        #     logger.info(item.metaclass)
        #     logger.info(type(item.metaclass))
        #     logger.info(type(item.metaclass))

        # 这个会返回当前模块文件的路径
        logger.info(Path(__file__))
        # 因为是从main运行的，所以会返回main.py的目录
        logger.info(Path.cwd())
        # 传入了由框架saya解析的模块地址名(channel.module),注意它并不是文件路径,如:modules.test_modules.test1
        logger.info(Path(channel.module))
        print(channel.metadata)
        return app.send_message(ori_place, MessageChain("成功"), quote=src)
    except Exception as e:
        return app.send_message(ori_place, MessageChain(f"失败:{e}"), quote=src)
