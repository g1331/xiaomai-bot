import asyncio
from datetime import datetime, timedelta

from graia.ariadne import Ariadne
from graia.ariadne.event.message import GroupMessage
from graia.ariadne.message import Source
from graia.ariadne.message.chain import MessageChain
from graia.ariadne.message.element import Image
from graia.ariadne.message.parser.twilight import UnionMatch, Twilight
from graia.ariadne.model import Group, Member
from graia.ariadne.util.saya import dispatch, decorate, listen
from graia.broadcast.interrupt import InterruptControl
from graia.saya import Channel, Saya
from graia.scheduler import timers
from graia.scheduler.saya import SchedulerSchema

from core.control import Permission, FrequencyLimitation, Function, Distribute
from core.models import saya_model, response_model
from utils.self_upgrade import *
from utils.waiter import ConfirmWaiter

module_controller = saya_model.get_module_controller()
account_controller = response_model.get_acc_controller()
channel = Channel.current()
saya = Saya.current()
channel.name("AutoUpgrade")
channel.author("十三")
channel.description("自动更新")
channel.metadata = module_controller.get_metadata_from_path(Path(__file__))

upgrade_dict = {}
noticed_list = []

inc = InterruptControl(saya.broadcast)


@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level, if_noticed=True),
    Permission.user_require(Permission.Master, if_noticed=True),
)
@dispatch(
    Twilight([
        UnionMatch("-upgrade"),
        # 示例: -upgrade
    ])
)
async def upgrade_handle(app: Ariadne, group: Group, member: Member, source: Source):
    global upgrade_dict
    await auto_upgrade_handle()
    upgrade_info = [f"SHA:{sha}\n {upgrade_dict[sha]}" for sha in upgrade_dict]
    logger.debug(f"【Upgrade】更新信息\n{upgrade_info}")
    if not upgrade_info:
        return await app.send_message(
            group, MessageChain("当前Github仓库还没有更新信息!"), quote=source
        )
    await app.send_message(
        group,
        MessageChain(
            f"【Upgrade】获取到更新信息如下:\n",
            "\n".join(upgrade_info[:3]),
            f"\n你确定要更新吗?(y/n)"
        ),
        quote=source
    )
    try:
        if not await asyncio.wait_for(
                inc.wait(ConfirmWaiter(group, member)), 30
        ):
            return await app.send_message(group, MessageChain("未预期回复,操作退出"), quote=source)
        logger.opt(colors=True).info("<cyan>【Upgrade】正在更新</cyan>")
        try:
            await asyncio.to_thread(perform_update)
            upgrade_dict = {}
            logger.success("【Upgrade】更新完成,将在重新启动后生效")
            await app.send_message(group, MessageChain(f"【Upgrade】更新完成!\n 将在重新启动后生效"), quote=source)
        except Exception as e:
            logger.error(e)
            return await app.send_message(group, MessageChain(f"【Upgrade】更新失败!\n 请手动更新!{e}"), quote=source)
    except asyncio.TimeoutError:
        return await app.send_group_message(group, MessageChain("回复等待超时,进程退出"), quote=source)


@channel.use(SchedulerSchema(timers.every_custom_hours(24)))
async def auto_upgrade():
    await auto_upgrade_handle()


async def auto_upgrade_handle():
    global upgrade_dict, noticed_list
    if not has_git:
        return
    target_app, target_group = await account_controller.get_app_from_total_groups(config.test_group)
    logger.debug("【Upgrade】自动检测更新运行ing")
    try:
        if not (update := await check_update()):
            logger.opt(colors=True).success("<green>【Upgrade】当前版本已是最新</green>")
            upgrade_dict = {}
            return
    except ClientError:
        logger.opt(colors=True).error("<red>【Upgrade】无法连接到 GitHub</red>")
        return
    except RuntimeError:
        logger.warning("【Upgrade】未检测到 .git 文件夹，只有使用 git 时才检测更新！")
        return
    else:
        output = []
        for commit in update:
            sha = commit.get("sha", "")[:7]
            message = commit.get("commit", {}).get("message", "")
            message = message.replace("<", r"\<").splitlines()[0]
            output.append(f"<red>{sha}</red> <yellow>{message}</yellow>")
            if sha not in upgrade_dict:
                upgrade_dict[sha] = message
        history = "\n".join(["", *output, ""])
        logger.opt(colors=True).warning(f"<yellow>【Upgrade】发现新版本</yellow>\n{history}")
        if not config.auto_upgrade:
            return
        committer_name = f'{update[0].get("commit", {}).get("committer", {}).get("name")}'
        if update[0]:
            committer_avatar_url = f'{update[0].get("committer", {}).get("avatar_url")}'
        else:
            committer_avatar_url = ""
        utc_time_str = f'{update[0].get("commit", {}).get("committer", {}).get("date", "")}'
        committer_time = (
                datetime.fromisoformat(utc_time_str.replace("Z", "+00:00")) + timedelta(hours=8)).strftime(
            "%Y年%m月%d日 %H:%M:%S")
        sha = update[0].get("sha", "")[:7]
        message = update[0].get("commit", {}).get("message", "").replace("<", r"\<").splitlines()[0]
        url = f'{update[0].get("html_url")}'
        if target_app and target_group and sha not in noticed_list:
            await target_app.send_message(
                target_group,
                MessageChain(
                    f"【自动更新】发现新的提交!\n",
                    f"提交时间：{committer_time}\n",
                    f"提交信息：{message}\n",
                    Image(url=committer_avatar_url) if committer_avatar_url else "",
                    "\n" if committer_avatar_url else "",
                    f"提交者：{committer_name}\n",
                    f"sha：{sha}\n",
                    f"链接：{url}\n"
                    f"请Master在能登录服务器操作的情况下执行指令 ’-upgrade‘ 更新到最新版本",
                )
            )
            noticed_list.append(sha)
