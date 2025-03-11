from pathlib import Path

from creart import create
from graia.ariadne import Ariadne
from graia.ariadne.event.mirai import BotMuteEvent, NewFriendRequestEvent
from graia.ariadne.message.chain import MessageChain
from graia.ariadne.model import Group, Member
from graia.ariadne.util.saya import listen
from graia.saya import Channel, Saya

from core.config import GlobalConfig
from core.control import Permission
from core.models import saya_model, response_model

module_controller = saya_model.get_module_controller()
account_controller = response_model.get_acc_controller()
global_config = create(GlobalConfig)
saya = Saya.current()
channel = Channel.current()
channel.meta["name"] = "自我保护"
channel.meta["description"] = "bot被禁言时会退出该群"
channel.meta["author"] = "13"
channel.metadata = module_controller.get_metadata_from_path(Path(__file__))


@listen(BotMuteEvent)
async def auto_quit_group(app: Ariadne, group: Group, member: Member):
    await app.quit_group(group)
    target_app, target_group = await account_controller.get_app_from_total_groups(
        global_config.test_group
    )
    if target_app and target_group:
        await target_app.send_message(
            target_group,
            MessageChain(
                f"注意:\n"
                f"BOT在{group.name}({group.id})被{member.name}({member.id})禁言\n"
                f"已自动退出该群!"
            ),
        )
    else:
        await app.send_message(
            global_config.Master,
            MessageChain(
                f"注意:\n"
                f"BOT在{group.name}({group.id})被{member.name}({member.id})禁言\n"
                f"已自动退出该群!"
            ),
        )


@listen(NewFriendRequestEvent)
async def auto_agree_admin_friend_request(event: NewFriendRequestEvent):
    if (
        event.supplicant in await Permission.get_BotAdminsList()
    ) or event.supplicant == global_config.Master:
        await event.accept("已同意您的申请!")
        target_app, target_group = await account_controller.get_app_from_total_groups(
            global_config.test_group
        )
        if not (target_app and target_group):
            return
        return await target_app.send_message(
            target_group,
            MessageChain(
                f"成员{event.nickname}({event.supplicant})申请添加BOT好友\n"
                f"已自动同意该管理的申请"
            ),
        )
