import time
from typing import Union

import psutil
from creart import create
from graia.ariadne.app import Ariadne
from graia.ariadne.event.message import GroupMessage, FriendMessage
from graia.ariadne.message.chain import MessageChain
from graia.ariadne.message.element import Source
from graia.ariadne.message.parser.twilight import Twilight, UnionMatch, SpacePolicy
from graia.ariadne.model import Group, Friend
from graia.saya import Channel, Saya
from graia.saya.builtins.broadcast.schema import ListenerSchema

from core.bot import Umaru
from core.config import GlobalConfig
from core.control import Permission

saya = Saya.current()
channel = Channel.current()
channel.name("Status")
channel.description("bot的运行状态")
channel.author("13")

config = create(GlobalConfig)
core = create(Umaru)


# 接发消息、cpu内存占用、bot数量
@channel.use(ListenerSchema(listening_events=[GroupMessage, FriendMessage],
                            decorators=[
                                Permission.user_require(Permission.User),
                            ],
                            inline_dispatchers=[
                                Twilight(
                                    [
                                        "action" @ UnionMatch("-bot", "-status", optional=False).space(
                                            SpacePolicy.PRESERVE),
                                    ]
                                    # 示例:-bot
                                )
                            ]))
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
    await app.send_message(src_place, MessageChain(
        f"开机时间：{core.launch_time}\n"
        f"运行时长：{work_time}\n"
        f"接收消息：{receive_counter}条(%.1f/m)\n" % ((receive_counter / (int(time.time()) - time_start)) * 60),
        f"发送消息：{send_counter + 1}条(%.1f/m)\n" % ((send_counter + 1) / (int(time.time()) - time_start) * 60),
        '内存使用：%.2fMB\n' % (ysy / 1024 / 1024),
        '内存占比：%.0f%%\n' % zb,
        f'CPU占比：{zb2}\n',
        f'磁盘占比：{cp}\n',
        f"当前在线bot数:{len(Ariadne.service.connections)}\n",
        # f"当前接收使用群数:{len()}\n"
        f"反馈Q群:749094683\n",
        f"爱发电地址:https://afdian.net/a/ss1333\n"
        f"项目地址:https://github.com/g1331/xiaomai-bot"
    ), quote=source)


@channel.use(ListenerSchema(listening_events=[GroupMessage],
                            decorators=[
                                Permission.user_require(16),
                            ],
                            inline_dispatchers=[
                                Twilight.from_command("-help status")
                            ]
                            ))
async def manager_help(app: Ariadne, group: Group):
    await app.send_message(group, MessageChain(
        f'1.使用-bot查看bot运行状态'
    ))
