from pathlib import Path

from creart import create
from graia.ariadne.event.mirai import BotMuteEvent
from graia.ariadne.message.chain import MessageChain
from graia.ariadne.model import Group, Member
from graia.ariadne.util.saya import listen
from graia.saya import Channel, Saya

from core.config import GlobalConfig
from core.models import (
    saya_model,
    response_model
)

module_controller = saya_model.get_module_controller()
account_controller = response_model.get_acc_controller()
global_config = create(GlobalConfig)
saya = Saya.current()
channel = Channel.current()
channel.name("自我保护")
channel.description("bot被禁言时会退出该群")
channel.author("13")
channel.metadata = module_controller.get_metadata_from_path(Path(__file__))


@listen(BotMuteEvent)
async def main(group: Group, member: Member):
    target_app, target_group = await account_controller.get_app_from_total_groups(global_config.test_group)
    if not (target_app and target_group):
        return
    await target_app.quit_group(group)
    await target_app.send_message(target_group, MessageChain(
        f"注意:\n"
        f"bot在{group.name}({group.id})被{member.name}({member.id})禁言\n"
        f"已自动退出该群!"
    ))
