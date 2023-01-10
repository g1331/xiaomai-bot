import jieba
import datetime

from graia.ariadne.util.saya import listen
from graia.saya import Saya, Channel
from graia.ariadne.message.element import Plain
from graia.ariadne.message.chain import MessageChain
from graia.ariadne.event.message import Group, Member, GroupMessage

from core.orm import orm
from core.orm.tables import ChatRecord

# 关闭 jieba 的 Debug log
jieba.setLogLevel(jieba.logging.INFO)

saya = Saya.current()
channel = Channel.current()

channel.name("ChatRecorder")
channel.author("SAGIRI-kawaii")
channel.description("一个记录聊天记录的插件，可配合词云等插件使用")


@listen(GroupMessage)
async def chat_record(message: MessageChain, group: Group, member: Member):
    content = "".join(plain.text for plain in message.get(Plain)).strip()
    seg_result = jieba.lcut(content) if content else ""
    await orm.add(
        ChatRecord,
        {
            "time": datetime.datetime.now(),
            "group_id": group.id,
            "member_id": member.id,
            "persistent_string": message.as_persistent_string(),
            "seg": "|".join(seg_result) if seg_result else "",
        },
    )
