import time
import psutil
import asyncio
from graia.ariadne.app import Ariadne
from graia.ariadne.event.message import GroupMessage, MessageEvent, ActiveMessage
from graia.ariadne.message.chain import MessageChain
from graia.ariadne.message.element import Source
from graia.ariadne.message.parser.twilight import Twilight, UnionMatch, SpacePolicy
from graia.ariadne.model import Group
from graia.saya import Channel, Saya
from graia.saya.builtins.broadcast.schema import ListenerSchema


from modules.DuoQHandle import DuoQ
from modules.PermManager import Perm


saya = Saya.current()
channel = Channel.current()
channel.name("Status")
channel.description("bot的运行状态")
channel.author("13")

receive_counter = 0
send_counter = 0
group_list = []
app_list = []


@channel.use(ListenerSchema(listening_events=[GroupMessage]))
async def fun_group_counter(group: Group, app: Ariadne):
    global receive_counter, group_list, app_list
    if group.id not in group_list:
        group_list.append(group.id)
    if app.account not in app_list:
        app_list.append(app.account)


@channel.use(ListenerSchema(listening_events=[MessageEvent]))
async def fun_receive_counter():
    global receive_counter
    receive_counter += 1


@channel.use(ListenerSchema(listening_events=[ActiveMessage]))
async def fun_send_counter():
    global send_counter
    send_counter += 1


time_start = int(time.time())


# 接发消息、cpu内存占用、bot数量
@channel.use(ListenerSchema(listening_events=[GroupMessage],
                            decorators=[
                                Perm.require(),
                                DuoQ.require()
                            ],
                            inline_dispatchers=[
                                Twilight(
                                    [
                                        "action" @ UnionMatch("-bot", optional=False).space(
                                            SpacePolicy.PRESERVE),
                                    ]
                                    # 示例:-bot
                                )
                            ]))
async def bot(app: Ariadne, group: Group, source: Source):
    global app_list
    # 运行时长
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
    # 上传与下载网速
    sent_before = psutil.net_io_counters().bytes_sent  # 已发送的流量
    recv_before = psutil.net_io_counters().bytes_recv  # 已接收的流量
    await asyncio.sleep(1)
    sent_now = psutil.net_io_counters().bytes_sent
    recv_now = psutil.net_io_counters().bytes_recv
    sent = (sent_now - sent_before) / 1024  # 算出1秒后的差值
    recv = (recv_now - recv_before) / 1024

    await app.send_message(group, MessageChain(
        f"运行时长：{work_time}\n"
        f"接收消息：{receive_counter}条(%.1f/m)\n" % ((receive_counter / (int(time.time()) - time_start)) * 60),
        f"发送消息：{send_counter + 1}条(%.1f/m)\n" % ((send_counter + 1) / (int(time.time()) - time_start) * 60),
        '内存使用：%.2fMB\n' % (ysy / 1024 / 1024),
        # '总内存：%.2fMB\n' % (zj / 1024 / 1024),
        '内存占比：%.0f%%\n' % zb,
        f'CPU占比：{zb2}\n',
        f'磁盘占比：{cp}\n',
        "上传速度：{0}KB/s\n".format("%.2f" % sent),
        "下载速度：{0}KB/s\n".format("%.2f" % recv),
        f"当前响应bot数:{len(app_list)}\n",
        f"当前接收使用群数:{len(group_list)}",

    ), quote=source)
    app_list = []


@channel.use(ListenerSchema(listening_events=[GroupMessage],
                            decorators=[
                                Perm.require(16),
                                DuoQ.require()
                            ],
                            inline_dispatchers=[
                                Twilight.from_command("-help status")
                            ]
                            ))
async def help(app: Ariadne, group: Group, message: MessageChain):
    await app.send_message(group, MessageChain(
        f'1.使用-bot/-status查看bot运行状态'
    ))
