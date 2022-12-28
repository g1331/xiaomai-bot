import yaml
from graia.ariadne.app import Ariadne
from graia.ariadne.event.message import GroupMessage
from graia.ariadne.message.chain import MessageChain
from graia.ariadne.message.element import Source
from graia.ariadne.message.parser.twilight import Twilight, FullMatch, ParamMatch, SpacePolicy, RegexResult
from graia.ariadne.model import Group
from graia.saya import Channel
from graia.saya.builtins.broadcast import ListenerSchema

from core.control import (
    Permission,
    Distribute
)

channel = Channel.current()
channel.name("多q适配")
channel.description("当群里有多个bot的时候,避免冲突响应")
channel.author("13")

bot_list = []
temp_dict = {}
temp_list = []


@channel.use(ListenerSchema(listening_events=[GroupMessage],
                            decorators=[
                                Permission.user_require(Permission.Admin),
                                Distribute.require()

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