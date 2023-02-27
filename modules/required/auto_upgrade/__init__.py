from datetime import datetime, timedelta

from graia.ariadne.message.chain import MessageChain
from graia.ariadne.message.element import Image
from graia.saya import Channel
from graia.scheduler import timers
from graia.scheduler.saya import SchedulerSchema

from core.models import saya_model, response_model
from utils.self_upgrade import *

module_controller = saya_model.get_module_controller()
account_controller = response_model.get_acc_controller()
channel = Channel.current()
channel.name("AutoUpgrade")
channel.author("十三")
channel.description("自动更新")
channel.metadata = module_controller.get_metadata_from_path(Path(__file__))

init_noticed = False


@channel.use(SchedulerSchema(timers.every_custom_seconds(120)))
async def auto_upgrade_handle():
    if not has_git:
        return
    target_app, target_group = await account_controller.get_app_from_total_groups(config.test_group)
    logger.info("【自动更新】自动检测更新运行ing")
    try:
        if not (update := await check_update()):
            logger.opt(colors=True).success("<green>【自动更新】当前版本已是最新</green>")
            return
    except ClientError:
        logger.opt(colors=True).error("<red>【自动更新】无法连接到 GitHub</red>")
        return
    except RuntimeError:
        logger.warning("【自动更新】未检测到 .git 文件夹，只有使用 git 时才检测更新！")
        return
    else:
        output = []
        for commit in update:
            sha = commit.get("sha", "")[:7]
            message = commit.get("commit", {}).get("message", "")
            message = message.replace("<", r"\<").splitlines()[0]
            output.append(f"<red>{sha}</red> <yellow>{message}</yellow>")
        history = "\n".join(["", *output, ""])
        logger.opt(colors=True).warning(f"<yellow>【自动更新】发现新版本</yellow>\n{history}")
        if not config.auto_upgrade:
            return
        committer_name = f'{update[0].get("commit", {}).get("committer", {}).get("name")}'
        committer_avatar_url = f'{update[0].get("committer", {}).get("avatar_url")}'
        utc_time_str = f'{update[0].get("commit", {}).get("committer", {}).get("date", "")}'
        committer_time = (
                datetime.fromisoformat(utc_time_str.replace("Z", "+00:00")) + timedelta(hours=8)).strftime(
            "%Y年%m月%d日 %H:%M:%S")
        sha = update[0].get("sha", "")[:7]
        message = update[0].get("commit", {}).get("message", "").replace("<", r"\<").splitlines()[0]
        url = f'{update[0].get("html_url")}'
        await target_app.send_message(
            target_group,
            MessageChain(
                f"【自动更新】发现新的提交!\n",
                f"提交时间：{committer_time}\n",
                f"提交信息：{message}\n",
                Image(url=committer_avatar_url) + "\n" if committer_avatar_url else "",
                f"提交者：{committer_name}\n",
                f"sha：{sha}\n",
                f"链接：{url}\n",
            )
        )
        logger.opt(colors=True).info("<cyan>【自动更新】正在自动更新</cyan>")
        try:
            await asyncio.to_thread(perform_update)
            logger.success("【自动更新】更新完成,将在重新启动后生效")
            return await target_app.send_message(target_group, MessageChain(f"【自动更新】更新完成,将在重新启动后生效"))
        except Exception as e:
            logger.error(e)
            return await target_app.send_message(target_group, MessageChain(f"【自动更新】更新失败,请手动更新!{e}"))
