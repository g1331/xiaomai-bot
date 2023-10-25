from graia.ariadne.event.lifecycle import ApplicationLaunched
from graia.ariadne.event.message import GroupMessage
from graia.ariadne.message.element import Image
from graia.ariadne.message.parser.twilight import Twilight, FullMatch
from graia.ariadne.message.parser.twilight import WildcardMatch, RegexResult, ArgResult, ArgumentMatch
from graia.saya import Channel
from graia.saya.builtins.broadcast.schema import ListenerSchema

from core.control import (
    Permission,
    Function,
    FrequencyLimitation,
    Distribute
)
from core.models import saya_model, response_model
from utils.text2img import md2img
from .manager import *

module_controller = saya_model.get_module_controller()
account_controller = response_model.get_acc_controller()

channel = Channel.current()
#channel.name("ChatGPT")
#channel.description("一个与ChatGPT对话的插件")
#channel.author("十三")
channel.metadata = module_controller.get_metadata_from_path(Path(__file__))

manager = ConversationManager()


@channel.use(
    ListenerSchema(
        listening_events=[GroupMessage],
        inline_dispatchers=[
            Twilight([
                FullMatch("-chat"),
                ArgumentMatch("-n", "-new", action="store_true", optional=True) @ "new_thread",
                ArgumentMatch("-t", "-text", action="store_true", optional=True) @ "text",
                ArgumentMatch("-w", "-web", action="store_true", optional=True) @ "web",
                ArgumentMatch("-p", "-preset", optional=True) @ "preset",
                ArgumentMatch("-m", "-mode", optional=True, type=str, choices=["gpt", "api"]) @ "mode",
                ArgumentMatch("--show-preset", action="store_true", optional=True) @ "show_preset",
                WildcardMatch().flags(re.DOTALL) @ "content",
            ])
        ],
        decorators=[
            Distribute.require(),
            Function.require(channel.module),
            FrequencyLimitation.require(channel.module, 5),
            Permission.group_require(channel.metadata.level, if_noticed=True),
            Permission.user_require(Permission.User),
        ],
    )
)
async def chat_gpt(
        app: Ariadne,
        group: Group,
        member: Member,
        source: Source,
        new_thread: ArgResult,
        text: ArgResult,
        web: ArgResult,
        preset: ArgResult,
        mode: ArgResult,
        content: RegexResult,
        show_preset: ArgResult,
):
    if mode.matched:
        if not await Permission.require_user_perm(group.id, member.id, Permission.BotAdmin):
            return await app.send_group_message(group, MessageChain("权限不足!"), quote=source)
        target_mode = mode.result
        await manager.change_mode(target_mode)
        return await app.send_group_message(group, MessageChain(f"已清空所有对话并切换模式为:{target_mode}模式"), quote=source)
    if show_preset.matched:
        return await app.send_group_message(
            group,
            MessageChain(Image(data_bytes=await md2img(
                "当前内置预设：\n\n" +
                "\n\n".join(
                    [f"{i} ({v['name']})：{v['description']}  (token cost:{len(ENCODER.encode(v['content']))})" for i, v
                     in preset_dict.items()]),
                use_proxy=True))),
            quote=source
        )
    if (get_gpt_mode() == "api") and (not gpt_api_available) and (not await Permission.require_user_perm(
            group.id, member.id, Permission.BotAdmin
    )):
        return await app.send_group_message(group, MessageChain("小埋忙不过来啦,请晚点再试试吧qwq~"), quote=source)
    if get_gpt_mode() == "gpt" and preset.matched:
        return await app.send_group_message(group, MessageChain("gpt模式下请直接对话进行预设~"), quote=source)
    if new_thread.matched:
        _ = await manager.new(group, member, (preset.result.display.strip() if preset.matched else ""))
        await app.send_group_message(group, MessageChain("已重置对话~"), quote=source)
    content = content.result.display.strip()
    if web.matched:
        content = await web_handle(content)
    response = await manager.send_message(group, member, content, app, source)
    if text.matched:
        await app.send_group_message(group, MessageChain(response), quote=source)
    else:
        await app.send_group_message(
            group, MessageChain(Image(data_bytes=await md2img(response, use_proxy=True))), quote=source
        )


@channel.use(ListenerSchema(listening_events=[ApplicationLaunched]))
async def init():
    await api_count_update()
