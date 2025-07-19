from pathlib import Path

from graia.ariadne import Ariadne
from graia.ariadne.event.lifecycle import ApplicationLaunched
from graia.ariadne.event.message import GroupMessage
from graia.ariadne.message import Source
from graia.ariadne.message.chain import MessageChain
from graia.ariadne.message.element import At, Image, Plain
from graia.ariadne.message.parser.twilight import (
    ArgResult,
    ArgumentMatch,
    FullMatch,
    ParamMatch,
    RegexResult,
    SpacePolicy,
    Twilight,
    WildcardMatch,
)
from graia.ariadne.model import Group, Member
from graia.ariadne.util.saya import decorate, dispatch, listen
from graia.saya import Channel
from graia.saya.builtins.broadcast.schema import ListenerSchema
from loguru import logger

from core.control import Distribute, FrequencyLimitation, Function, Permission
from core.models import saya_model
from utils.type import parse_match_type

# 导入数据库模型以确保表被创建
# 导入数据库操作函数
from .database import (
    add_mc_server,
    bind_server_to_group,
    get_group_bound_servers,
    get_mc_server_by_id,
    get_server_bound_groups,
    list_mc_servers,
    remove_mc_server,
    remove_server_header,
    toggle_chat_sync,
    unbind_server_from_group,
    update_mc_server,
)

# 导入工具函数
from .utils import get_minecraft_server_info

# 导入 WebSocket 管理器
from .websocket import ws_manager

module_controller = saya_model.get_module_controller()
channel = Channel.current()
channel.meta["name"] = "MiniCraftInfo"
channel.meta["description"] = "MC服务器查询、管理和聊天互通功能"
channel.meta["author"] = "13"
channel.metadata = module_controller.get_metadata_from_path(Path(__file__))


async def resolve_server_from_input(
    group_id: int, user_input: str
) -> tuple[str | None, str | None]:
    """
    根据用户输入解析服务器地址

    Args:
        group_id: 群组ID
        user_input: 用户输入（序号或服务器地址）

    Returns:
        tuple[str | None, str | None]: (server_address, error_message)
        - 成功时：(服务器地址, None)
        - 失败时：(None, 错误信息)
    """
    try:
        # 获取当前群组绑定的服务器列表
        bound_servers = await get_group_bound_servers(group_id)

        if not bound_servers:
            return None, "当前群组没有绑定任何服务器"

        # 检查是否为数字（序号）
        # 处理正数和负数的情况
        try:
            index = int(user_input)

            # 检查序号是否在有效范围内
            if 1 <= index <= len(bound_servers):
                server_address = bound_servers[index - 1][0].server_address
                return server_address, None
            else:
                return None, f"序号无效，请输入 1-{len(bound_servers)} 之间的数字"
        except ValueError:
            # 不是数字，继续处理为服务器地址
            pass

        # 不是数字，当作服务器地址处理
        # 检查是否为绑定服务器中的地址
        for server, _ in bound_servers:
            if server.server_address == user_input:
                return user_input, None

        # 不在绑定列表中，但可能是有效的服务器地址，直接返回
        # 让调用方去验证服务器是否可访问
        if "." in user_input and ":" in user_input:
            return user_input, None
        elif "." in user_input:
            # 如果只有域名没有端口，添加默认端口
            return f"{user_input}:25565", None
        else:
            return (
                None,
                f"无效的服务器地址或序号。请输入：\n• 序号（1-{len(bound_servers)}）\n• 服务器地址（如：mc.hypixel.net 或 mc.hypixel.net:25565）",
            )

    except Exception as e:
        logger.error(f"解析服务器输入时出错: {e}")
        return None, f"解析输入时出错: {str(e)}"


# 应用启动时初始化 WebSocket 连接
@listen(ApplicationLaunched)
async def init_websocket_connections(app: Ariadne):
    """初始化 WebSocket 连接"""
    try:
        logger.info("开始初始化 WebSocket 连接...")

        # 获取所有服务器
        all_servers = await list_mc_servers()
        logger.info(f"找到 {len(all_servers)} 个已配置的服务器")

        # 筛选需要建立连接的服务器
        servers_to_connect = []
        for server in all_servers:
            if not server.websocket_url:
                logger.debug(
                    f"服务器 {server.server_name} 没有配置 WebSocket URL，跳过"
                )
                continue

            if not server.is_active:
                logger.debug(f"服务器 {server.server_name} 已禁用，跳过")
                continue

            # 检查是否有启用聊天同步的群组绑定
            from .database import get_server_bound_groups

            bound_groups = await get_server_bound_groups(
                server.id, sync_enabled_only=True
            )

            if bound_groups:
                servers_to_connect.append(server)
                logger.info(
                    f"服务器 {server.server_name} 有 {len(bound_groups)} 个群组启用了聊天同步"
                )
            else:
                logger.debug(
                    f"服务器 {server.server_name} 没有启用聊天同步的群组绑定，跳过"
                )

        logger.info(f"需要建立连接的服务器数量: {len(servers_to_connect)}")

        # 为筛选出的服务器建立连接
        successful_connections = 0
        failed_connections = 0

        for server in servers_to_connect:
            logger.info(f"尝试连接服务器 {server.server_name} (ID: {server.id})")
            logger.info(f"WebSocket URL: {server.websocket_url}")

            try:
                await ws_manager.add_connection(server)
                if server.id in ws_manager.connections:
                    successful_connections += 1
                    logger.success(f"✅ 服务器 {server.server_name} 连接成功")
                else:
                    failed_connections += 1
                    logger.error(f"❌ 服务器 {server.server_name} 连接失败")
            except Exception as e:
                failed_connections += 1
                logger.error(f"❌ 服务器 {server.server_name} 连接异常: {e}")

        logger.info(
            f"WebSocket 连接初始化完成: 成功 {successful_connections} 个，失败 {failed_connections} 个"
        )

    except Exception as e:
        logger.error(f"初始化 WebSocket 连接失败: {e}")
        logger.exception("详细错误信息:")


# QQ 群消息监听，转发到 MC 服务器
@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Function.require(channel.module, notice=False),
)
async def forward_qq_to_mc(group: Group, member: Member, message: MessageChain):
    """将 QQ 群消息转发到 MC 服务器"""
    try:
        # 获取当前群绑定的启用聊天同步的服务器
        bound_servers = await get_group_bound_servers(group.id)
        sync_enabled_servers = [
            (server, bind)
            for server, bind in bound_servers
            if bind.chat_sync_enabled and server.websocket_url
        ]

        if not sync_enabled_servers:
            return  # 没有启用聊天同步的服务器

        # 过滤掉命令消息（以 / 开头的消息）
        message_text = message.display.strip()
        if message_text.startswith("/"):
            return  # 不转发命令消息

        # 构造转发消息
        group_name = group.name or f"群{group.id}"
        member_name = member.name or f"用户{member.id}"

        # 处理不同类型的消息元素
        formatted_parts = []
        for element in message:
            if isinstance(element, Plain):
                formatted_parts.append(element.text)
            elif isinstance(element, Image):
                formatted_parts.append("[图片]")
            elif isinstance(element, At):
                formatted_parts.append(f"@{element.target}")
            else:
                formatted_parts.append("[不支持的消息类型]")

        formatted_message_content = "".join(formatted_parts).strip()
        if not formatted_message_content:
            return  # 空消息不转发

        # 构造最终的转发消息
        mc_message = f"[QQ-{group_name}] {member_name}: {formatted_message_content}"

        # 向所有启用聊天同步的服务器发送消息
        for server, bind in sync_enabled_servers:
            success = await ws_manager.send_to_server(server.id, mc_message)
            if success:
                logger.debug(
                    f"已向服务器 {server.server_name} 转发QQ消息: {mc_message}"
                )
            else:
                logger.warning(f"向服务器 {server.server_name} 转发QQ消息失败")

    except Exception as e:
        logger.error(f"转发QQ消息到MC服务器时出错: {e}")


# 管理员命令：添加服务器
@listen(GroupMessage)
@dispatch(
    Twilight(
        [
            FullMatch("/mcadmin add").space(SpacePolicy.FORCE),
            ParamMatch(optional=False) @ "server_address",
            ParamMatch(optional=False) @ "server_name",
            ParamMatch(optional=True) @ "websocket_url",
        ]
    )
)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level, if_noticed=True),
    Permission.user_require(Permission.Master, if_noticed=True),
)
async def mcadmin_add_server(
    app: Ariadne,
    group: Group,
    source: Source,
    server_address: RegexResult,
    server_name: RegexResult,
    websocket_url: RegexResult,
):
    address = server_address.result.display
    name = server_name.result.display
    ws_url = websocket_url.result.display if websocket_url.matched else None

    success, message = await add_mc_server(address, name, ws_url)
    await app.send_message(group, MessageChain(message), quote=source)


# 管理员命令：删除服务器
@listen(GroupMessage)
@dispatch(
    Twilight(
        [
            FullMatch("/mcadmin remove").space(SpacePolicy.FORCE),
            ParamMatch(optional=False) @ "server_id",
        ]
    )
)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level, if_noticed=True),
    Permission.user_require(Permission.Master, if_noticed=True),
)
async def mcadmin_remove_server(
    app: Ariadne, group: Group, source: Source, server_id: RegexResult
):
    try:
        sid = int(server_id.result.display)
        success, message = await remove_mc_server(sid)
        await app.send_message(group, MessageChain(message), quote=source)
    except ValueError:
        await app.send_message(group, MessageChain("服务器ID必须是数字"), quote=source)


# 管理员命令：列出所有服务器
@listen(GroupMessage)
@dispatch(Twilight([FullMatch("/mcadmin list")]))
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level, if_noticed=True),
    Permission.user_require(Permission.Master, if_noticed=True),
)
async def mcadmin_list_servers(app: Ariadne, group: Group, source: Source):
    servers = await list_mc_servers()
    if not servers:
        await app.send_message(group, MessageChain("暂无已添加的服务器"), quote=source)
        return

    message_parts = ["已添加的服务器列表：\n"]
    for server in servers:
        status = "✅" if server.is_active else "❌"
        ws_status = "🔗" if server.websocket_url else "❌"
        message_parts.append(
            f"{status} ID:{server.id} | {server.server_name}\n"
            f"   地址: {server.server_address}\n"
            f"   类型: {server.server_type}版 | WebSocket: {ws_status}\n"
        )

    await app.send_message(group, MessageChain("".join(message_parts)), quote=source)


# 管理员命令：更新服务器配置
@channel.use(
    ListenerSchema(
        listening_events=[GroupMessage],
        inline_dispatchers=[
            Twilight(
                [
                    FullMatch("/mcadmin update").space(SpacePolicy.FORCE),
                    ParamMatch(optional=False) @ "server_id",
                    ArgumentMatch("--name", "-n", optional=True) @ "name",
                    ArgumentMatch("--address", "-a", optional=True) @ "address",
                    ArgumentMatch("--websocket", "-w", optional=True) @ "websocket",
                    ArgumentMatch("--help", "-h", action="store_true", optional=True)
                    @ "help",
                ]
            )
        ],
        decorators=[
            Distribute.require(),
            Function.require(channel.module),
            FrequencyLimitation.require(channel.module),
            Permission.group_require(channel.metadata.level, if_noticed=True),
            Permission.user_require(Permission.Master, if_noticed=True),
        ],
    )
)
async def mcadmin_update_server(
    app: Ariadne,
    group: Group,
    source: Source,
    server_id: RegexResult,
    name: ArgResult,
    address: ArgResult,
    websocket: ArgResult,
    help: ArgResult,
):
    try:
        sid = int(server_id.result.display)

        # 显示帮助信息
        if help.matched:
            help_message = (
                "更新服务器配置命令帮助:\n\n"
                "用法: /mcadmin update <服务器ID> [选项]\n\n"
                "选项:\n"
                "  --name, -n <新名称>        更新服务器名称\n"
                "  --address, -a <新地址>     更新服务器地址\n"
                "  --websocket, -w <新URL>    更新WebSocket URL\n"
                "  --help, -h                 显示此帮助信息\n\n"
                "示例:\n"
                "  /mcadmin update 1 --name 新服务器名称\n"
                "  /mcadmin update 1 --address mc.example.com:25565\n"
                "  /mcadmin update 1 --websocket ws://localhost:8080\n"
                "  /mcadmin update 1 -n 新名称 -w ws://localhost:8080\n\n"
                "注意: 所有参数都是可选的，可以同时指定多个参数进行批量更新"
            )
            await app.send_message(group, MessageChain(help_message), quote=source)
            return

        # 解析参数 - 使用 parse_match_type 正确处理 MessageChain 对象
        new_name = parse_match_type(name, str, None)
        new_address = parse_match_type(address, str, None)
        new_websocket_url = parse_match_type(websocket, str, None)

        # 检查是否至少指定了一个更新参数
        if not any([new_name, new_address, new_websocket_url]):
            await app.send_message(
                group,
                MessageChain(
                    "请指定要更新的字段:\n"
                    "使用 --name/-n 更新服务器名称\n"
                    "使用 --address/-a 更新服务器地址\n"
                    "使用 --websocket/-w 更新WebSocket URL\n"
                    "使用 --help/-h 查看详细帮助\n\n"
                    "示例: /mcadmin update 1 --name 新服务器 --websocket ws://localhost:8080"
                ),
                quote=source,
            )
            return

        success, message, websocket_changed = await update_mc_server(
            sid, new_name, new_address, new_websocket_url
        )

        # 如果 WebSocket 配置发生变化，需要重新连接
        if success and websocket_changed:
            try:
                # 断开旧连接
                if sid in ws_manager.connections:
                    await ws_manager.remove_connection(sid)

                # 如果新配置有 WebSocket URL 且有启用聊天同步的群组，建立新连接
                if new_websocket_url:
                    from .database import get_server_bound_groups

                    bound_groups = await get_server_bound_groups(
                        sid, sync_enabled_only=True
                    )
                    if bound_groups:
                        # 获取更新后的服务器信息
                        servers = await list_mc_servers()
                        updated_server = None
                        for server in servers:
                            if server.id == sid:
                                updated_server = server
                                break

                        if updated_server:
                            await ws_manager.add_connection(updated_server)
                            message += "，WebSocket 连接已重新建立"

            except Exception as e:
                logger.error(f"重新建立 WebSocket 连接时出错: {e}")
                message += f"，但 WebSocket 重连失败: {str(e)}"

        await app.send_message(group, MessageChain(message), quote=source)

    except ValueError:
        await app.send_message(group, MessageChain("服务器ID必须是数字"), quote=source)
    except Exception as e:
        logger.error(f"更新服务器时出错: {e}")
        await app.send_message(
            group, MessageChain(f"更新服务器失败: {str(e)}"), quote=source
        )


# 管理员命令：绑定服务器到群组
@listen(GroupMessage)
@dispatch(
    Twilight(
        [
            FullMatch("/mcadmin bind").space(SpacePolicy.FORCE),
            ParamMatch(optional=False) @ "server_id",
            ParamMatch(optional=True) @ "group_id",
        ]
    )
)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level, if_noticed=True),
    Permission.user_require(Permission.Master, if_noticed=True),
)
async def mcadmin_bind_server(
    app: Ariadne,
    group: Group,
    source: Source,
    server_id: RegexResult,
    group_id: RegexResult,
):
    try:
        sid = int(server_id.result.display)
        # 如果没有指定群号，则绑定到当前群
        gid = int(group_id.result.display) if group_id.matched else group.id

        success, message = await bind_server_to_group(sid, gid)
        await app.send_message(group, MessageChain(message), quote=source)
    except ValueError:
        await app.send_message(
            group, MessageChain("服务器ID和群号必须是数字"), quote=source
        )


# 管理员命令：从群组解绑服务器
@listen(GroupMessage)
@dispatch(
    Twilight(
        [
            FullMatch("/mcadmin unbind").space(SpacePolicy.FORCE),
            ParamMatch(optional=False) @ "server_id",
            ParamMatch(optional=True) @ "group_id",
        ]
    )
)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level, if_noticed=True),
    Permission.user_require(Permission.Master, if_noticed=True),
)
async def mcadmin_unbind_server(
    app: Ariadne,
    group: Group,
    source: Source,
    server_id: RegexResult,
    group_id: RegexResult,
):
    try:
        sid = int(server_id.result.display)
        # 如果没有指定群号，则从当前群解绑
        gid = int(group_id.result.display) if group_id.matched else group.id

        success, message = await unbind_server_from_group(sid, gid)
        await app.send_message(group, MessageChain(message), quote=source)
    except ValueError:
        await app.send_message(
            group, MessageChain("服务器ID和群号必须是数字"), quote=source
        )


# 管理员命令：控制聊天互通开关
@listen(GroupMessage)
@dispatch(
    Twilight(
        [
            FullMatch("/mcadmin sync").space(SpacePolicy.FORCE),
            ParamMatch(optional=False) @ "server_id",
            ParamMatch(optional=False) @ "switch",
            ParamMatch(optional=True) @ "group_id",
        ]
    )
)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level, if_noticed=True),
    Permission.user_require(Permission.Master, if_noticed=True),
)
async def mcadmin_sync_chat(
    app: Ariadne,
    group: Group,
    source: Source,
    server_id: RegexResult,
    switch: RegexResult,
    group_id: RegexResult,
):
    try:
        sid = int(server_id.result.display)
        switch_value = switch.result.display.lower()

        if switch_value not in ["on", "off", "开启", "关闭"]:
            await app.send_message(
                group, MessageChain("开关参数必须是 on/off 或 开启/关闭"), quote=source
            )
            return

        enabled = switch_value in ["on", "开启"]
        # 如果没有指定群号，则操作当前群
        gid = int(group_id.result.display) if group_id.matched else group.id

        success, message = await toggle_chat_sync(sid, gid, enabled)

        # 如果成功开启聊天同步，尝试建立 WebSocket 连接
        if success and enabled:
            try:
                # 获取服务器信息
                servers = await list_mc_servers()
                target_server = None
                for server in servers:
                    if server.id == sid:
                        target_server = server
                        break

                if target_server and target_server.websocket_url:
                    # 检查连接是否已存在
                    if sid not in ws_manager.connections:
                        await ws_manager.add_connection(target_server)
                        logger.info(
                            f"为服务器 {target_server.server_name} 建立了 WebSocket 连接"
                        )
                    else:
                        logger.info(
                            f"服务器 {target_server.server_name} 的 WebSocket 连接已存在"
                        )
                elif target_server:
                    logger.warning(
                        f"服务器 {target_server.server_name} 没有配置 WebSocket URL"
                    )
                else:
                    logger.error(f"找不到服务器 ID {sid}")

            except Exception as e:
                logger.error(f"建立 WebSocket 连接时出错: {e}")

        # 如果关闭聊天同步，检查是否需要断开连接
        elif success and not enabled:
            try:
                # 检查该服务器是否还有其他群组启用了聊天同步
                from .database import get_server_bound_groups

                remaining_bindings = await get_server_bound_groups(
                    sid, sync_enabled_only=True
                )

                # 如果没有其他群组启用聊天同步，断开连接
                if not remaining_bindings and sid in ws_manager.connections:
                    await ws_manager.remove_connection(sid)
                    logger.info(f"已断开服务器 ID {sid} 的 WebSocket 连接")

            except Exception as e:
                logger.error(f"管理 WebSocket 连接时出错: {e}")

        await app.send_message(group, MessageChain(message), quote=source)

    except ValueError:
        await app.send_message(
            group, MessageChain("服务器ID和群号必须是数字"), quote=source
        )


# 管理员命令：查看 WebSocket 连接状态
@listen(GroupMessage)
@dispatch(Twilight([FullMatch("/mcadmin status")]))
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level, if_noticed=True),
    Permission.user_require(Permission.Master, if_noticed=True),
)
async def mcadmin_websocket_status(app: Ariadne, group: Group, source: Source):
    """查看 WebSocket 连接状态"""
    try:
        if not ws_manager.connections:
            await app.send_message(
                group, MessageChain("当前没有活跃的 WebSocket 连接"), quote=source
            )
            return

        message_parts = ["WebSocket 连接状态：\n"]
        for server_id, connection in ws_manager.connections.items():
            status = "🟢 已连接" if connection.is_connected else "🔴 已断开"

            # 获取服务器信息用于显示
            server = await get_mc_server_by_id(server_id)
            server_name = server.server_name if server else f"ID {server_id}"
            websocket_url = server.websocket_url if server else "未知"

            message_parts.append(
                f"服务器 ID {server_id} ({server_name}): {status}\n"
                f"  WebSocket URL: {websocket_url}\n"
                f"  重连次数: {connection.reconnect_attempts}\n"
            )

        await app.send_message(
            group, MessageChain("".join(message_parts)), quote=source
        )

    except Exception as e:
        logger.error(f"查看 WebSocket 状态时出错: {e}")
        await app.send_message(
            group, MessageChain(f"查看状态失败: {str(e)}"), quote=source
        )


# 管理员命令：详细调试 WebSocket 连接状态
@listen(GroupMessage)
@dispatch(Twilight([FullMatch("/mcadmin debug")]))
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level, if_noticed=True),
    Permission.user_require(Permission.Master, if_noticed=True),
)
async def mcadmin_websocket_debug(app: Ariadne, group: Group, source: Source):
    """详细调试 WebSocket 连接状态"""
    try:
        if not ws_manager.connections:
            await app.send_message(
                group, MessageChain("当前没有活跃的 WebSocket 连接"), quote=source
            )
            return

        status_info = ws_manager.get_connection_status()
        message_parts = ["WebSocket 连接详细状态：\n\n"]

        for server_id, status in status_info.items():
            message_parts.append(
                f"🔧 服务器 ID {server_id} ({status['server_name']}):\n"
            )
            message_parts.append(
                f"  ├─ 连接状态: {'🟢 已连接' if status['is_connected'] else '🔴 已断开'}\n"
            )
            message_parts.append(f"  ├─ 重连次数: {status['reconnect_attempts']}\n")
            message_parts.append(f"  ├─ 重连延迟: {status['reconnect_delay']}秒\n")
            message_parts.append(
                f"  ├─ 重连中: {'是' if status['is_reconnecting'] else '否'}\n"
            )
            message_parts.append(
                f"  ├─ 监听任务: {'运行中' if status['has_listen_task'] else '已停止'}\n"
            )
            message_parts.append(
                f"  └─ WebSocket: {'已关闭' if status['websocket_closed'] else '已打开'}\n\n"
            )

        await app.send_message(
            group, MessageChain("".join(message_parts)), quote=source
        )

    except Exception as e:
        logger.error(f"调试 WebSocket 状态时出错: {e}")
        await app.send_message(group, MessageChain(f"调试失败: {str(e)}"), quote=source)


# 普通用户命令：查看当前群绑定的服务器列表
@listen(GroupMessage)
@dispatch(Twilight([FullMatch("/mclist")]))
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level, if_noticed=True),
    Permission.user_require(Permission.User, if_noticed=True),
)
async def mc_list_bound_servers(app: Ariadne, group: Group, source: Source):
    bound_servers = await get_group_bound_servers(group.id)
    if not bound_servers:
        await app.send_message(
            group, MessageChain("当前群组没有绑定任何服务器"), quote=source
        )
        return

    message_parts = ["当前群组绑定的服务器：\n"]
    for server, bind in bound_servers:
        status = "✅" if server.is_active else "❌"
        sync_status = "🔗" if bind.chat_sync_enabled else "❌"
        message_parts.append(
            f"{status} {server.server_name}\n"
            f"   地址: {server.server_address}\n"
            f"   类型: {server.server_type}版 | 聊天互通: {sync_status}\n"
        )

    await app.send_message(group, MessageChain("".join(message_parts)), quote=source)


# 原有命令：查询服务器信息（支持无参数查询绑定服务器）
@listen(GroupMessage)
@dispatch(
    Twilight(
        [
            FullMatch("/mcs").space(SpacePolicy.PRESERVE),
            ParamMatch(optional=True) @ "server_host",
        ]
    )
)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level, if_noticed=True),
    Permission.user_require(Permission.User, if_noticed=True),
)
async def server_info_handle(
    app: Ariadne, group: Group, source: Source, server_host: RegexResult
):
    # 如果没有指定服务器地址，查询当前群绑定的服务器
    if not server_host.matched:
        bound_servers = await get_group_bound_servers(group.id)
        if not bound_servers:
            await app.send_message(
                group,
                MessageChain(
                    "当前群组没有绑定任何服务器，请使用 /mcs <服务器地址> 查询指定服务器"
                ),
                quote=source,
            )
            return

        # 无参数时始终显示所有绑定服务器的详细信息列表
        message_parts = ["📋 当前群组绑定的服务器信息：\n\n"]

        for i, (server, bind) in enumerate(bound_servers, 1):
            try:
                # 查询服务器信息
                result = await get_minecraft_server_info(server.server_address)

                if isinstance(result, str):
                    # 查询失败
                    message_parts.append(f"🔴 服务器{i}：{server.server_name}\n")
                    message_parts.append(f"地址：{server.server_address}\n")
                    message_parts.append(f"状态：查询失败 - {result}\n\n")
                else:
                    # 查询成功
                    sync_status = "🔗" if bind.chat_sync_enabled else "❌"
                    message_parts.append(f"🟢 服务器{i}：{server.server_name}\n")
                    message_parts.append(f"地址：{server.server_address}\n")
                    message_parts.append(f"描述：{result['description']}\n")
                    message_parts.append(f"游戏版本：{result['version']}\n")
                    message_parts.append(
                        f"人数：{result['online_players']}/{result['max_players']}\n"
                    )
                    message_parts.append(f"PING：{result['ping']}ms\n")
                    message_parts.append(f"聊天互通：{sync_status}\n\n")

            except Exception as e:
                logger.error(f"查询服务器 {server.server_name} 信息时出错: {e}")
                message_parts.append(f"🔴 服务器{i}：{server.server_name}\n")
                message_parts.append(f"地址：{server.server_address}\n")
                message_parts.append("状态：查询出错\n\n")

        message_parts.append("💡 提示：使用 /mcs <序号> 或 /mcs <地址> 查询单个服务器")

        await app.send_message(
            group, MessageChain("".join(message_parts)), quote=source
        )
        return
    else:
        # 处理用户输入的参数
        server_address, error_message = await resolve_server_from_input(
            group.id, server_host.result.display.strip()
        )

        if error_message:
            await app.send_message(group, MessageChain(error_message), quote=source)
            return

    result = await get_minecraft_server_info(server_address)
    if isinstance(result, str):
        return await app.send_message(group, MessageChain(result), quote=source)

    img_base64 = result["favicon"]
    return await app.send_message(
        group,
        MessageChain(
            [
                f"服务器地址: {server_address}\n",
                Image(base64=img_base64[img_base64.find(",") + 1 :])
                if img_base64
                else "",
                f"描述:\n{result['description']}\n",
                f"游戏版本:{result['version']}\n",
                f"协议版本:{result['protocol']}\n",
                f"在线人数:{result['online_players']}/{result['max_players']}\n",
                f"ping:{result['ping']}ms",
            ]
        ),
        quote=source,
    )


# 原有命令：查询玩家列表（支持无参数查询绑定服务器）
@listen(GroupMessage)
@dispatch(
    Twilight(
        [
            FullMatch("/mcpl").space(SpacePolicy.PRESERVE),
            ParamMatch(optional=True) @ "server_host",
        ]
    )
)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level, if_noticed=True),
    Permission.user_require(Permission.User, if_noticed=True),
)
async def server_player_handle(
    app: Ariadne, group: Group, source: Source, server_host: RegexResult
):
    # 如果没有指定服务器地址，查询当前群绑定的服务器
    if not server_host.matched:
        bound_servers = await get_group_bound_servers(group.id)
        if not bound_servers:
            await app.send_message(
                group,
                MessageChain(
                    "当前群组没有绑定任何服务器，请使用 /mcpl <服务器地址> 查询指定服务器"
                ),
                quote=source,
            )
            return

        # 如果有多个绑定服务器，显示选择提示
        if len(bound_servers) > 1:
            message_parts = [
                "👥 当前群组绑定了多个服务器，请选择要查询玩家列表的服务器：\n\n"
            ]

            for i, (server, bind) in enumerate(bound_servers, 1):
                sync_status = "🔗" if bind.chat_sync_enabled else "❌"
                status = "✅" if server.is_active else "❌"
                message_parts.append(
                    f"{status} {i}. {server.server_name}\n"
                    f"   地址: {server.server_address}\n"
                    f"   聊天互通: {sync_status}\n\n"
                )

            message_parts.append("💡 使用方法：\n")
            message_parts.append("• 通过序号查询: /mcpl 1 或 /mcpl 2\n")
            message_parts.append("• 通过地址查询: /mcpl <服务器地址>")

            await app.send_message(
                group, MessageChain("".join(message_parts)), quote=source
            )
            return

        # 只有一个绑定服务器，直接查询
        server_address = bound_servers[0][0].server_address
    else:
        # 处理用户输入的参数
        server_address, error_message = await resolve_server_from_input(
            group.id, server_host.result.display.strip()
        )

        if error_message:
            await app.send_message(group, MessageChain(error_message), quote=source)
            return

    result = await get_minecraft_server_info(server_address)
    if isinstance(result, str):
        return await app.send_message(group, MessageChain(result), quote=source)

    if len(result["players"]) == 0:
        return await app.send_message(
            group, MessageChain("服务器没有在线玩家"), quote=source
        )

    # 最多显示15个玩家
    # 先排序
    result["players"].sort()
    if len(result["players"]) > 15:
        players_str = (
            "玩家列表:\n"
            + "\n".join([f"{player}" for player in result["players"][:15]])
            + "\n超长只显示前15个玩家"
        )
    else:
        players_str = "玩家列表:\n" + "\n".join(
            [f"{player}" for player in result["players"]]
        )

    img_base64 = result["favicon"]
    return await app.send_message(
        group,
        MessageChain(
            [
                f"服务器地址: {server_address}\n",
                Image(base64=img_base64[img_base64.find(",") + 1 :])
                if img_base64
                else "",
                f"在线人数:{result['online_players']}/{result['max_players']}\n",
                f"{players_str}",
            ]
        ),
        quote=source,
    )


# 管理员命令：添加 WebSocket 请求头
@listen(GroupMessage)
@dispatch(
    Twilight(
        [
            FullMatch("/mcadmin header add").space(SpacePolicy.FORCE),
            ParamMatch(optional=False) @ "server_id",
            ParamMatch(optional=False) @ "key",
            WildcardMatch(optional=False) @ "value",
        ]
    )
)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level, if_noticed=True),
)
async def mcadmin_header_add(
    app: Ariadne,
    group: Group,
    source: Source,
    server_id: RegexResult,
    key: RegexResult,
    value: RegexResult,
):
    from .database import add_server_header

    try:
        sid = int(server_id.result.display)
    except ValueError:
        await app.send_message(group, MessageChain("服务器ID必须是数字"), quote=source)
        return

    header_key = key.result.display.strip()
    header_value = value.result.display.strip()

    success, message = await add_server_header(sid, header_key, header_value)

    if success:
        # 如果服务器有 WebSocket 连接，需要重新连接以应用新的请求头
        try:
            if sid in ws_manager.connections:
                await ws_manager.remove_connection(sid)

                updated_server = await get_mc_server_by_id(sid)

                if updated_server and updated_server.websocket_url:
                    # 检查是否有启用聊天同步的群组
                    bound_groups = await get_server_bound_groups(
                        sid, sync_enabled_only=True
                    )
                    if bound_groups:
                        await ws_manager.add_connection(updated_server)
                        message += "，WebSocket 连接已重新建立"
        except Exception as e:
            logger.error(f"重新建立 WebSocket 连接时出错: {e}")
            message += f"，但 WebSocket 重连失败: {str(e)}"

    await app.send_message(group, MessageChain(message), quote=source)


# 管理员命令：移除 WebSocket 请求头
@listen(GroupMessage)
@dispatch(
    Twilight(
        [
            FullMatch("/mcadmin header remove").space(SpacePolicy.FORCE),
            ParamMatch(optional=False) @ "server_id",
            ParamMatch(optional=False) @ "key",
        ]
    )
)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level, if_noticed=True),
)
async def mcadmin_header_remove(
    app: Ariadne, group: Group, source: Source, server_id: RegexResult, key: RegexResult
):
    try:
        sid = int(server_id.result.display)
    except ValueError:
        await app.send_message(group, MessageChain("服务器ID必须是数字"), quote=source)
        return

    header_key = key.result.display.strip()

    success, message = await remove_server_header(sid, header_key)

    if success:
        # 如果服务器有 WebSocket 连接，需要重新连接以应用更新后的请求头
        try:
            if sid in ws_manager.connections:
                await ws_manager.remove_connection(sid)

                updated_server = await get_mc_server_by_id(sid)

                if updated_server and updated_server.websocket_url:
                    # 检查是否有启用聊天同步的群组
                    bound_groups = await get_server_bound_groups(
                        sid, sync_enabled_only=True
                    )
                    if bound_groups:
                        await ws_manager.add_connection(updated_server)
                        message += "，WebSocket 连接已重新建立"
        except Exception as e:
            logger.error(f"重新建立 WebSocket 连接时出错: {e}")
            message += f"，但 WebSocket 重连失败: {str(e)}"

    await app.send_message(group, MessageChain(message), quote=source)


# 管理员命令：列出 WebSocket 请求头
@listen(GroupMessage)
@dispatch(
    Twilight(
        [
            FullMatch("/mcadmin header list").space(SpacePolicy.FORCE),
            ParamMatch(optional=False) @ "server_id",
        ]
    )
)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level, if_noticed=True),
)
async def mcadmin_header_list(
    app: Ariadne, group: Group, source: Source, server_id: RegexResult
):
    from .database import get_server_headers

    try:
        sid = int(server_id.result.display)
    except ValueError:
        await app.send_message(group, MessageChain("服务器ID必须是数字"), quote=source)
        return

    success, message, headers = await get_server_headers(sid)

    if success:
        if headers:
            header_list = []
            for key, value in headers.items():
                # 对于敏感信息（如 Authorization），只显示部分内容
                if key.lower() in ["authorization", "auth", "token"]:
                    if len(value) > 10:
                        display_value = value[:6] + "..." + value[-4:]
                    else:
                        display_value = "***"
                else:
                    display_value = value
                header_list.append(f"  {key}: {display_value}")

            headers_text = "\n".join(header_list)
            full_message = f"{message}:\n{headers_text}"
        else:
            full_message = f"{message}: 无自定义请求头"
    else:
        full_message = message

    await app.send_message(group, MessageChain(full_message), quote=source)
