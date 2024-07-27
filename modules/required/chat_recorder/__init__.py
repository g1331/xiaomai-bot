import jieba
import datetime

from pathlib import Path

from graia.ariadne.util.saya import listen, decorate
from graia.saya import Saya, Channel
from graia.ariadne.message.element import Plain
from graia.ariadne.message.chain import MessageChain
from graia.ariadne.event.message import Group, Member, GroupMessage

from core.control import Distribute
from core.models import saya_model
from core.orm import orm
from core.orm.tables import ChatRecord

# 关闭 jieba 的 Debug log
jieba.setLogLevel(jieba.logging.INFO)
module_controller = saya_model.get_module_controller()
saya = Saya.current()
channel = Channel.current()
channel.meta["name"] = ("ChatRecorder")
channel.meta["author"] = ("SAGIRI-kawaii")
channel.meta["description"] = ("一个记录聊天记录的插件，可配合词云等插件使用")
channel.metadata = module_controller.get_metadata_from_path(Path(__file__))


@listen(GroupMessage)
@decorate(Distribute.require())
async def chat_record(message: MessageChain, group: Group, member: Member):
    content = "".join(plain.text for plain in message.get(Plain)).strip()
    seg_result = jieba.lcut(content) if content else ""
    await orm.add(
        table=ChatRecord,
        data={
            "time": datetime.datetime.now(),
            "group_id": group.id,
            "member_id": member.id,
            "persistent_string": message.as_persistent_string(),
            "seg": "|".join(seg_result) if seg_result else "",
        }
    )
