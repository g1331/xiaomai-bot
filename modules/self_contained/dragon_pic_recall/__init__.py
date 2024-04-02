from pathlib import Path

import aiohttp
from creart import create
from graia.ariadne.event.message import GroupMessage, MessageEvent
from graia.ariadne.message import Source
from graia.ariadne.message.element import Image
from graia.ariadne.model import Group
from graia.ariadne.util.saya import listen, decorate
from graia.saya import Channel
from loguru import logger

from core.config import GlobalConfig
from core.control import (
    Permission,
    Function,
    FrequencyLimitation,
    Distribute
)
from core.models import saya_model, response_model

module_controller = saya_model.get_module_controller()
account_controller = response_model.get_acc_controller()
config = create(GlobalConfig)
channel = Channel.current()
channel.name("龙图检测")
channel.description("识别到龙图就自动撤回")
channel.author("13")
channel.metadata = module_controller.get_metadata_from_path(Path(__file__))

api_url = config.functions.get("dragon_detect", {}).get("api_url", "")


@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level, if_noticed=True),
    Permission.user_require(Permission.User, if_noticed=True),
)
async def dragon_recall(group: Group, event: MessageEvent, source: Source):
    target_app, target_group = await account_controller.get_app_from_total_groups(group.id, ["Administrator", "Owner"])
    if not (target_app and target_group):
        return
    app = target_app
    group = target_group
    if not api_url:
        return
    if event.message_chain.has(Image):
        try:
            img_bytes = await event.message_chain.get(Image)[0].get_bytes()
            async with aiohttp.ClientSession() as session:
                async with session.post(api_url, data=img_bytes) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get("is_dragon", False):
                            await app.recall_message(message=source, target=group)
        except Exception as e:
            logger.error(f"[Function: {channel.module}] [Group: {group.id}] [Error: {e}] ")
