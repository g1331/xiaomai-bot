import yaml
from typing import Union
from graia.ariadne.app import Ariadne
from graia.ariadne.event.message import GroupMessage
from graia.ariadne.message.chain import MessageChain
from graia.ariadne.message.element import Source
from graia.ariadne.message.parser.twilight import Twilight, FullMatch, ParamMatch, SpacePolicy, RegexResult
from graia.ariadne.model import Group, Friend
from graia.broadcast import ExecutionStop
from graia.broadcast.builtin.decorators import Depend
from graia.saya.builtins.broadcast import ListenerSchema
from graia.saya import Channel

channel = Channel.current()
channel.name("多q适配")
channel.description("当群里有多个bot的时候,避免冲突响应")
channel.author("13")

bot_list = []
temp_dict = {}
temp_list = []


class DuoQ(object):

    @classmethod
    def require(cls):
        """
        只要是接收群消息的都要这个!
        :return: Depend
        """

        async def wrapper(group: Union[Group, Friend], app: Ariadne, source: Source):
            global temp_dict
            if type(group) == Friend:
                return Depend(wrapper)
            # 第一次要获取群列表，然后添加bot到groupid字典，编号
            # 然后对messageId取余，对应编号bot响应
            if group.id not in temp_dict:
                member_list = await app.get_member_list(group)
                temp_dict[group.id] = {}
                temp_dict[group.id][0] = app.account
                for item in member_list:
                    if item.id in Ariadne.service.connections:
                        temp_dict[group.id][len(temp_dict[group.id])] = item.id
            if temp_dict[group.id][source.id % len(temp_dict[group.id])] != app.account:
                raise ExecutionStop
            # 防止bot中途掉线/风控造成无响应
            if temp_dict[group.id][source.id % len(temp_dict[group.id])] not in Ariadne.service.connections:
                temp_dict.pop(group.id)
            return Depend(wrapper)

        return Depend(wrapper)


from modules.PermManager import Perm


@channel.use(ListenerSchema(listening_events=[GroupMessage],
                            decorators=[
                                Perm.require(128),
                                DuoQ.require()
                            ],
                            inline_dispatchers=[
                                Twilight(
                                    [
                                        FullMatch("-choose bot").space(SpacePolicy.FORCE),
                                        "bot_id" @ ParamMatch().space(SpacePolicy.PRESERVE),
                                    ],
                                )
                            ]))
async def check_bot(app: Ariadne, group: Group, message: MessageChain, bot_id: RegexResult):
    global temp_dict
    bot_id = int(bot_id.result.display)
    member_list = await app.get_member_list(group)
    member_list = [item.id for item in member_list]
    if app.account not in member_list:
        member_list.append(app.account)
    if bot_id not in member_list:
        await app.send_message(group, MessageChain(
            f"没有找到bot{bot_id}"
        ), quote=message[Source][0])
        return False
    else:
        await app.send_message(group, MessageChain(
            f"群{group.name}({group.id})默认bot由{temp_dict[group.id]}切换为{bot_id}"
        ), quote=message[Source][0])
        temp_dict[group.id] = bot_id
        return False


def if_blocked(account: int) -> bool:
    file_temp = open('./config/config.yaml', 'r', encoding="utf-8")
    data_temp = yaml.load(file_temp, Loader=yaml.Loader)
    bot_blocked_list = data_temp["botinfo"]["bot_blocked"]
    if account in bot_blocked_list:
        return True
    else:
        return False
