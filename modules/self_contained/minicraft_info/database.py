import asyncio
import copy
from urllib.parse import urlparse

import websockets
from loguru import logger
from sqlalchemy import delete, select

from core.orm import orm

from .models import McGroupBind, McServer
from .utils import detect_server_type


async def validate_websocket_url_format(websocket_url: str) -> tuple[bool, str]:
    """验证 WebSocket URL 格式"""
    if not websocket_url:
        return True, ""  # 空 URL 是允许的

    try:
        # 验证 URL 格式
        parsed = urlparse(websocket_url)
        if parsed.scheme not in ["ws", "wss"]:
            return False, "WebSocket URL 必须以 ws:// 或 wss:// 开头"

        if not parsed.hostname:
            return False, "WebSocket URL 格式无效，缺少主机名"

        return True, "WebSocket URL 格式验证通过"

    except Exception as e:
        return False, f"WebSocket URL 格式验证失败: {str(e)}"


async def test_websocket_connection(websocket_url: str) -> tuple[bool, str]:
    """
    测试 WebSocket 连接（不使用认证header）

    Args:
        websocket_url (str): WebSocket服务器的URL。

    Returns:
        tuple[bool, str]:
            - 第一个值为布尔值，表示连接是否成功。
            - 第二个值为字符串，包含状态消息。

    Note:
        连接测试的超时时间为5秒。如果连接成功，返回 (True, "WebSocket 连接测试成功")。
        如果连接失败，返回 (False, 错误消息)，错误消息可能包括：
            - "WebSocket 连接超时"
            - "WebSocket URL 格式无效"
            - "WebSocket 握手失败（可能需要认证header）"
            - "WebSocket 连接被拒绝"
            - 其他异常的描述信息。
    """
    try:

        async def test_connection():
            async with websockets.connect(
                websocket_url,
                ping_interval=None,
                ping_timeout=None,
                close_timeout=1,
            ):
                pass  # 连接成功即可

        await asyncio.wait_for(test_connection(), timeout=5.0)
        return True, "WebSocket 连接测试成功"

    except asyncio.TimeoutError:
        return False, "WebSocket 连接超时"
    except websockets.exceptions.InvalidURI:
        return False, "WebSocket URL 格式无效"
    except websockets.exceptions.InvalidHandshake:
        return False, "WebSocket 握手失败（可能需要认证header）"
    except ConnectionRefusedError:
        return False, "WebSocket 连接被拒绝"
    except Exception as e:
        return False, f"WebSocket 连接测试失败: {str(e)}"


async def add_mc_server(
    server_address: str, server_name: str, websocket_url: str | None = None
) -> tuple[bool, str]:
    """添加MC服务器"""
    try:
        # 检查服务器是否已存在
        async with orm.async_session() as session:
            result = await session.execute(
                select(McServer).where(McServer.server_address == server_address)
            )
            if result.scalar_one_or_none():
                return False, f"服务器地址 {server_address} 已存在"

        # 验证 WebSocket URL 格式（如果提供）
        warning_message = ""
        if websocket_url:
            # 首先验证格式
            is_valid, format_message = await validate_websocket_url_format(
                websocket_url
            )
            if not is_valid:
                return False, f"WebSocket URL 格式验证失败: {format_message}"

            # 然后测试连接（失败时只警告，不阻止添加）
            connection_ok, connection_message = await test_websocket_connection(
                websocket_url
            )
            if not connection_ok:
                warning_message = f"\n⚠️ 警告: {connection_message}。服务器已添加，但可能需要配置认证header才能正常连接。"
                logger.warning(f"WebSocket 连接测试失败: {connection_message}")
            else:
                logger.info(f"WebSocket 连接测试成功: {connection_message}")

        # 检测服务器类型
        server_type = await detect_server_type(server_address)

        # 创建服务器记录
        server = McServer(
            server_name=server_name,
            server_address=server_address,
            server_type=server_type,
            websocket_url=websocket_url,
            websocket_headers={"x-self-name": server_name} if websocket_url else None,
        )

        async with orm.async_session() as session:
            session.add(server)
            await session.commit()
            await session.refresh(server)

        success_message = f"成功添加服务器 {server_name} ({server_type}版)"
        if websocket_url:
            success_message += "，WebSocket URL 已配置"

        # 添加警告信息（如果有）
        success_message += warning_message

        return True, success_message

    except Exception as e:
        logger.exception(f"添加服务器失败: {e}")
        return False, f"添加服务器失败: {str(e)}"


async def remove_mc_server(server_id: int) -> tuple[bool, str]:
    """删除MC服务器"""
    try:
        async with orm.async_session() as session:
            # 检查服务器是否存在
            result = await session.execute(
                select(McServer).where(McServer.id == server_id)
            )
            server = result.scalar_one_or_none()
            if not server:
                return False, f"服务器ID {server_id} 不存在"

            server_name = server.server_name

            # 删除相关绑定
            await session.execute(
                delete(McGroupBind).where(McGroupBind.server_id == server_id)
            )

            # 删除服务器
            await session.execute(delete(McServer).where(McServer.id == server_id))

            await session.commit()

        return True, f"成功删除服务器 {server_name} 及其所有绑定关系"

    except Exception as e:
        logger.exception(f"删除服务器失败: {e}")
        return False, f"删除服务器失败: {str(e)}"


async def update_mc_server(
    server_id: int,
    new_name: str | None = None,
    new_address: str | None = None,
    new_websocket_url: str | None = None,
) -> tuple[bool, str, bool]:
    """
    更新MC服务器配置
    返回: (是否成功, 消息, 是否需要重连WebSocket)
    """
    try:
        async with orm.async_session() as session:
            # 检查服务器是否存在
            result = await session.execute(
                select(McServer).where(McServer.id == server_id)
            )
            server = result.scalar_one_or_none()
            if not server:
                return False, f"服务器ID {server_id} 不存在", False

            old_name = server.server_name
            old_address = server.server_address
            old_websocket_url = server.websocket_url

            changes = []
            websocket_changed = False

            # 更新服务器名称
            if new_name and new_name != server.server_name:
                server.server_name = new_name
                changes.append(f"名称: {old_name} → {new_name}")

                # 如果有 WebSocket 配置，更新 header 中的名称
                if server.websocket_headers:
                    server.websocket_headers["x-self-name"] = new_name

            # 更新服务器地址
            if new_address and new_address != server.server_address:
                # 检查新地址是否已被其他服务器使用
                existing_result = await session.execute(
                    select(McServer).where(
                        McServer.server_address == new_address, McServer.id != server_id
                    )
                )
                if existing_result.scalar_one_or_none():
                    return False, f"服务器地址 {new_address} 已被其他服务器使用", False

                # 重新检测服务器类型
                server_type = await detect_server_type(new_address)
                server.server_address = new_address
                server.server_type = server_type
                changes.append(f"地址: {old_address} → {new_address} ({server_type}版)")

            # 更新 WebSocket URL
            if new_websocket_url is not None:  # 允许设置为空字符串来移除 WebSocket
                if new_websocket_url != server.websocket_url:
                    # 验证新的 WebSocket URL 格式（如果不为空）
                    if new_websocket_url:
                        is_valid, format_message = await validate_websocket_url_format(
                            new_websocket_url
                        )
                        if not is_valid:
                            return (
                                False,
                                f"WebSocket URL 格式验证失败: {format_message}",
                                False,
                            )

                        # 测试连接（失败时只警告）
                        (
                            connection_ok,
                            connection_message,
                        ) = await test_websocket_connection(new_websocket_url)
                        if not connection_ok:
                            logger.warning(
                                f"新 WebSocket URL 连接测试失败: {connection_message}"
                            )
                        else:
                            logger.info(
                                f"新 WebSocket URL 连接测试成功: {connection_message}"
                            )

                    server.websocket_url = (
                        new_websocket_url if new_websocket_url else None
                    )

                    # 更新 WebSocket headers
                    if new_websocket_url:
                        server.websocket_headers = {"x-self-name": server.server_name}
                    else:
                        server.websocket_headers = None

                    old_url_display = old_websocket_url or "无"
                    new_url_display = new_websocket_url or "无"
                    changes.append(
                        f"WebSocket URL: {old_url_display} → {new_url_display}"
                    )
                    websocket_changed = True

            if not changes:
                return False, "没有检测到任何更改", False

            # 在提交前获取服务器名称，避免会话关闭后访问属性导致的错误
            server_name = server.server_name

            # 保存更改
            await session.commit()

            change_summary = "、".join(changes)
            return (
                True,
                f"成功更新服务器 {server_name}: {change_summary}",
                websocket_changed,
            )

    except Exception as e:
        logger.exception(f"更新服务器失败: {e}")
        return False, f"更新服务器失败: {str(e)}", False


async def list_mc_servers() -> list[McServer]:
    """获取所有MC服务器列表"""
    try:
        async with orm.async_session() as session:
            result = await session.execute(select(McServer).order_by(McServer.id))
            servers = result.scalars().all()

            # 确保所有关联数据都被加载，避免延迟加载问题
            for server in servers:
                # 访问 websocket_headers 属性以确保数据被加载
                _ = server.websocket_headers

            return servers
    except Exception as e:
        logger.exception(f"获取服务器列表失败: {e}")
        return []


async def get_mc_server_by_id(server_id: int) -> McServer | None:
    """根据ID获取单个MC服务器的最新信息"""
    try:
        async with orm.async_session() as session:
            result = await session.execute(
                select(McServer).where(McServer.id == server_id)
            )
            server = result.scalar_one_or_none()
            if server:
                # 确保 websocket_headers 数据被加载
                _ = server.websocket_headers
            return server
    except Exception as e:
        logger.exception(f"获取服务器信息失败: {e}")
        return None


async def bind_server_to_group(server_id: int, group_id: int) -> tuple[bool, str]:
    """绑定服务器到群组"""
    try:
        async with orm.async_session() as session:
            # 检查服务器是否存在
            server = await session.get(McServer, server_id)
            if not server:
                return False, f"服务器ID {server_id} 不存在"

            # 在 session 上下文内获取服务器名称，避免延迟加载问题
            server_name = server.server_name

            # 检查是否已经绑定
            bind_result = await session.execute(
                select(McGroupBind).where(
                    McGroupBind.server_id == server_id, McGroupBind.group_id == group_id
                )
            )
            if bind_result.scalar_one_or_none():
                return False, f"群 {group_id} 已经绑定了服务器 {server_name}"

            # 创建绑定
            bind = McGroupBind(group_id=group_id, server_id=server_id)
            session.add(bind)
            await session.commit()

            return True, f"成功将服务器 {server_name} 绑定到群 {group_id}"

    except Exception as e:
        logger.exception(f"绑定服务器失败: {e}")
        return False, f"绑定服务器失败: {str(e)}"


async def unbind_server_from_group(server_id: int, group_id: int) -> tuple[bool, str]:
    """从群组解绑服务器"""
    try:
        async with orm.async_session() as session:
            # 检查绑定是否存在
            bind_result = await session.execute(
                select(McGroupBind).where(
                    McGroupBind.server_id == server_id, McGroupBind.group_id == group_id
                )
            )
            bind = bind_result.scalar_one_or_none()
            if not bind:
                return False, f"群 {group_id} 没有绑定服务器ID {server_id}"

            # 获取服务器名称（在 session 上下文内）
            server_result = await session.execute(
                select(McServer).where(McServer.id == server_id)
            )
            server = server_result.scalar_one_or_none()
            server_name = server.server_name if server else f"ID:{server_id}"

            # 删除绑定
            await session.execute(
                delete(McGroupBind).where(
                    McGroupBind.server_id == server_id, McGroupBind.group_id == group_id
                )
            )
            await session.commit()

            return True, f"成功从群 {group_id} 解绑服务器 {server_name}"

    except Exception as e:
        logger.exception(f"解绑服务器失败: {e}")
        return False, f"解绑服务器失败: {str(e)}"


async def get_group_bound_servers(group_id: int) -> list[tuple[McServer, McGroupBind]]:
    """获取群组绑定的服务器列表"""
    try:
        async with orm.async_session() as session:
            result = await session.execute(
                select(McServer, McGroupBind)
                .join(McGroupBind, McServer.id == McGroupBind.server_id)
                .where(McGroupBind.group_id == group_id)
                .order_by(McServer.id)
            )
            return result.all()
    except Exception as e:
        logger.exception(f"获取群组绑定服务器失败: {e}")
        return []


async def toggle_chat_sync(
    server_id: int, group_id: int, enabled: bool
) -> tuple[bool, str]:
    """切换聊天同步状态"""
    try:
        async with orm.async_session() as session:
            # 检查绑定是否存在
            bind_result = await session.execute(
                select(McGroupBind).where(
                    McGroupBind.server_id == server_id, McGroupBind.group_id == group_id
                )
            )
            bind = bind_result.scalar_one_or_none()
            if not bind:
                return False, f"群 {group_id} 没有绑定服务器ID {server_id}"

            # 获取服务器名称
            server_result = await session.execute(
                select(McServer).where(McServer.id == server_id)
            )
            server = server_result.scalar_one_or_none()
            server_name = server.server_name if server else f"ID:{server_id}"

            # 更新聊天同步状态
            bind.chat_sync_enabled = enabled
            await session.commit()

            status = "开启" if enabled else "关闭"
            return True, f"成功{status}群 {group_id} 与服务器 {server_name} 的聊天互通"

    except Exception as e:
        logger.exception(f"切换聊天同步状态失败: {e}")
        return False, f"切换聊天同步状态失败: {str(e)}"


async def get_server_bound_groups(
    server_id: int, sync_enabled_only: bool = False
) -> list[tuple[McGroupBind, McServer]]:
    """获取服务器绑定的群组列表"""
    try:
        async with orm.async_session() as session:
            query = (
                select(McGroupBind, McServer)
                .join(McServer, McGroupBind.server_id == McServer.id)
                .where(McGroupBind.server_id == server_id)
            )

            if sync_enabled_only:
                query = query.where(McGroupBind.chat_sync_enabled.is_(True))

            result = await session.execute(query.order_by(McGroupBind.group_id))
            return result.all()
    except Exception as e:
        logger.exception(f"获取服务器绑定群组失败: {e}")
        return []


async def get_all_sync_enabled_bindings() -> list[tuple[McServer, McGroupBind]]:
    """获取所有启用聊天同步的绑定关系"""
    try:
        async with orm.async_session() as session:
            result = await session.execute(
                select(McServer, McGroupBind)
                .join(McGroupBind, McServer.id == McGroupBind.server_id)
                .where(McGroupBind.chat_sync_enabled.is_(True))
                .where(McServer.is_active.is_(True))
                .where(McServer.websocket_url.isnot(None))
                .order_by(McServer.id)
            )
            return result.all()
    except Exception as e:
        logger.exception(f"获取启用聊天同步的绑定关系失败: {e}")
        return []


async def add_server_header(server_id: int, key: str, value: str) -> tuple[bool, str]:
    """添加或更新服务器的 WebSocket 请求头"""
    try:
        if not key or not key.strip():
            return False, "请求头名称不能为空"

        key = key.strip()

        async with orm.async_session() as session:
            result = await session.execute(
                select(McServer).where(McServer.id == server_id)
            )
            server = result.scalar_one_or_none()
            if not server:
                return False, f"服务器ID {server_id} 不存在"

            server_name = server.server_name
            # 创建字典的深拷贝，避免就地修改问题

            current_headers = (
                copy.deepcopy(server.websocket_headers)
                if server.websocket_headers
                else {}
            )

            # 添加调试日志
            logger.debug(f"更新前的请求头: {server.websocket_headers}")

            # 确保 x-self-name 始终存在（如果 headers 为空则初始化）
            if not current_headers:
                current_headers = {"x-self-name": server_name}
            elif "x-self-name" not in current_headers:
                current_headers["x-self-name"] = server_name

            old_value = current_headers.get(key)
            current_headers[key] = value

            logger.debug(f"更新后的请求头（提交前）: {current_headers}")

            # 使用 flag_modified 明确告诉 SQLAlchemy 字段已修改
            from sqlalchemy.orm.attributes import flag_modified

            server.websocket_headers = current_headers
            flag_modified(server, "websocket_headers")

            # 添加到会话中
            session.add(server)

            await session.commit()

            # 刷新对象以确保获取最新数据
            await session.refresh(server)

            # 添加调试日志
            logger.info(f"数据库更新后的请求头: {server.websocket_headers}")

            # 再次验证数据库中的数据
            verification_result = await session.execute(
                select(McServer).where(McServer.id == server_id)
            )
            verification_server = verification_result.scalar_one_or_none()
            if verification_server:
                logger.info(
                    f"验证查询的请求头: {verification_server.websocket_headers}"
                )
            else:
                logger.error("验证查询失败：找不到服务器")

            if old_value is None:
                return True, f"成功为服务器 {server_name} 添加请求头 {key}: {value}"
            else:
                return (
                    True,
                    f"成功更新服务器 {server_name} 的请求头 {key}: {old_value} → {value}",
                )

    except Exception as e:
        logger.exception(f"添加服务器请求头失败: {e}")
        return False, f"添加服务器请求头失败: {str(e)}"


async def remove_server_header(server_id: int, key: str) -> tuple[bool, str]:
    """移除服务器的 WebSocket 请求头"""
    try:
        # 验证参数
        if not key or not key.strip():
            return False, "请求头名称不能为空"

        key = key.strip()

        # 防止删除必需的 x-self-name 头
        if key.lower() == "x-self-name":
            return False, "不能删除 x-self-name 请求头，该头部是必需的"

        async with orm.async_session() as session:
            # 检查服务器是否存在
            result = await session.execute(
                select(McServer).where(McServer.id == server_id)
            )
            server = result.scalar_one_or_none()
            if not server:
                return False, f"服务器ID {server_id} 不存在"

            server_name = server.server_name

            # 创建字典的深拷贝，避免就地修改问题
            import copy

            current_headers = (
                copy.deepcopy(server.websocket_headers)
                if server.websocket_headers
                else {}
            )

            # 检查要删除的头部是否存在
            if key not in current_headers:
                return False, f"服务器 {server_name} 没有设置请求头 {key}"

            # 移除指定的头部
            old_value = current_headers.pop(key)

            # 确保 x-self-name 始终存在
            current_headers["x-self-name"] = server_name

            # 使用 flag_modified 明确告诉 SQLAlchemy 字段已修改
            from sqlalchemy.orm.attributes import flag_modified

            server.websocket_headers = current_headers
            flag_modified(server, "websocket_headers")

            # 更新数据库
            session.add(server)
            await session.commit()

            return (
                True,
                f"成功移除服务器 {server_name} 的请求头 {key} (原值: {old_value})",
            )

    except Exception as e:
        logger.exception(f"移除服务器请求头失败: {e}")
        return False, f"移除服务器请求头失败: {str(e)}"


async def get_server_headers(server_id: int) -> tuple[bool, str, dict]:
    """获取服务器的所有 WebSocket 请求头"""
    try:
        async with orm.async_session() as session:
            # 检查服务器是否存在
            result = await session.execute(
                select(McServer).where(McServer.id == server_id)
            )
            server = result.scalar_one_or_none()
            if not server:
                return False, f"服务器ID {server_id} 不存在", {}

            # 在 session 上下文内获取所需数据
            server_name = server.server_name
            headers = server.websocket_headers or {}

            return True, f"服务器 {server_name} 的请求头", headers

    except Exception as e:
        logger.exception(f"获取服务器请求头失败: {e}")
        return False, f"获取服务器请求头失败: {str(e)}", {}
