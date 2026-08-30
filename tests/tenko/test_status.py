from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from arclet.entari.command import Query
from satori import (
    Channel,
    ChannelType,
    EventType,
    Guild,
    Login,
    MessageObject,
    Role,
    User,
)
from satori.model import Event, Member

from tenko.events import MessageMetrics
from tenko.context import MessageContext
from tenko.host.accounts import AccountRegistry
from tenko.host.perm import Permission, PermissionChecker, PermissionRegistry


def make_session(user_id: str, role: str, protocol=None):
    event = Event(
        type=EventType.MESSAGE_CREATED,
        timestamp=datetime.now(),
        login=Login(platform="onebot", user=User("10001")),
        channel=Channel("40001", ChannelType.TEXT),
        guild=Guild("40001", "Tenko"),
        member=Member(user=User(user_id), roles=[Role(role)]),
        user=User(user_id),
        message=MessageObject.from_elements("50001", []),
    )
    return SimpleNamespace(
        account=SimpleNamespace(protocol=protocol),
        event=SimpleNamespace(
            _origin=event,
            channel=event.channel,
            guild=event.guild,
            user=event.user,
        ),
    )


def make_private_session(user_id: str, protocol=None):
    event = Event(
        type=EventType.MESSAGE_CREATED,
        timestamp=datetime.now(),
        login=Login(platform="onebot", user=User("10001")),
        channel=Channel(f"private:{user_id}", ChannelType.DIRECT),
        guild=None,
        member=None,
        user=User(user_id),
        message=MessageObject.from_elements("50001", []),
    )
    return SimpleNamespace(
        account=SimpleNamespace(protocol=protocol),
        event=SimpleNamespace(
            _origin=event,
            channel=event.channel,
            guild=event.guild,
            user=event.user,
        ),
    )


class PrivateMessageProtocol:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def send_private_message(self, user_id, content):
        self.calls.append((str(user_id), str(content[0])))
        return []


@pytest.mark.asyncio
@pytest.mark.parametrize("loaded_plugin", ["status"], indirect=True)
async def test_status_command_reports_native_runtime_context(loaded_plugin) -> None:
    loaded_plugin.permission_checker = PermissionChecker(registry=PermissionRegistry())

    result = await loaded_plugin.status.callable_target(
        make_session("20001", "member"), Query("text.value", False)
    )

    assert "Tenko 状态" in str(result)
    assert "账号: 10001" in str(result)
    assert "当前群BOT在线:" in str(result)
    assert "在线账号:" not in str(result)
    assert "账号×群禁言:" not in str(result)
    assert "进程: 启动" not in str(result)
    assert loaded_plugin.status_command.parse("/-bot -t").matched
    assert loaded_plugin.status_command.parse("/状态 -t").matched


@pytest.mark.asyncio
@pytest.mark.parametrize("loaded_plugin", ["status"], indirect=True)
async def test_status_permission_filter_blocks_global_blacklisted_user(
    loaded_plugin,
) -> None:
    registry = PermissionRegistry()
    registry.set_user_level(None, "20001", Permission.GlobalBlack)
    loaded_plugin.permission_checker = PermissionChecker(registry=registry)

    result = await loaded_plugin.status.callable_target(
        make_session("20001", "member"), Query("text.value", False)
    )

    assert str(result) == "权限不足"


@pytest.mark.asyncio
@pytest.mark.parametrize("loaded_plugin", ["status"], indirect=True)
async def test_master_private_status_receives_full_diagnostic(loaded_plugin) -> None:
    loaded_plugin.permission_checker = PermissionChecker(
        registry=PermissionRegistry(master_id="90001")
    )

    result = await loaded_plugin.status.callable_target(
        make_private_session("90001"), Query("text.value", False)
    )

    output = str(result)
    assert "在线账号:" in output
    assert "账号×群禁言:" in output
    assert "进程: 启动" in output


@pytest.mark.asyncio
@pytest.mark.parametrize("loaded_plugin", ["status"], indirect=True)
async def test_master_group_status_keeps_group_summary_and_pushes_diagnostic(
    loaded_plugin,
) -> None:
    protocol = PrivateMessageProtocol()
    loaded_plugin.permission_checker = PermissionChecker(
        registry=PermissionRegistry(master_id="90001")
    )

    result = await loaded_plugin.status.callable_target(
        make_session("90001", "member", protocol), Query("text.value", False)
    )

    output = str(result)
    assert "当前群BOT在线:" in output
    assert "详情已发送给维护者" in output
    assert "在线账号:" not in output
    assert "账号×群禁言:" not in output
    assert protocol.calls and protocol.calls[0][0] == "90001"
    assert "在线账号:" in protocol.calls[0][1]
    assert "账号×群禁言:" in protocol.calls[0][1]


@pytest.mark.parametrize("loaded_plugin", ["status"], indirect=True)
def test_build_status_reports_resources_metrics_and_account_mute_state(
    loaded_plugin,
) -> None:
    registry = AccountRegistry()
    first = SimpleNamespace(self_id="10001")
    second = SimpleNamespace(self_id="10002")
    registry.register(first, groups=["40001"])
    registry.register(second, available=False, groups=["40001"])
    registry.set_muted(first, "40001", True)
    metrics = MessageMetrics(buffer_size=10)
    context = MessageContext(
        account_id="10001",
        event_type="message-created",
        protocol_event_type="message.group.normal",
        chat_type="group",
        channel_id="40001",
        user_id="20001",
        message_id="50001",
        text="状态",
        image_urls=(),
    )
    metrics.record_received(context)
    metrics.record_sent(
        account_id="10001",
        platform="onebot",
        chat_type="group",
        channel_id="40001",
        text="状态结果",
    )

    output = loaded_plugin.build_status(
        context,
        7,
        registry=registry,
        metrics=metrics,
        resources=loaded_plugin.SystemResources(
            cpu_percent=12.5,
            memory_used=2 * 1024**3,
            memory_total=8 * 1024**3,
            memory_percent=25.0,
            disk_used=3 * 1024**3,
            disk_total=10 * 1024**3,
            disk_percent=30.0,
            net_sent=4 * 1024**2,
            net_received=5 * 1024**2,
        ),
        process=loaded_plugin.ProcessInfo(
            start_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
            uptime_seconds=3661,
            rss=64 * 1024**2,
        ),
        detailed=True,
    )

    assert "消息: 收 1 / 发 1" in output
    assert "系统: CPU 12.5%" in output
    assert "内存 2.0GB/8.0GB" in output
    assert "磁盘 3.0GB/10.0GB" in output
    assert "网络 IO" in output
    assert "在线账号: 10001" in output
    assert "活跃群: 1" in output
    assert "10001@40001=永久" in output
    assert "RSS 64.0MB" in output


@pytest.mark.parametrize("loaded_plugin", ["status"], indirect=True)
def test_status_skips_system_resource_section_when_psutil_is_missing(
    loaded_plugin, monkeypatch
) -> None:
    monkeypatch.setattr(loaded_plugin, "psutil", None)
    registry = AccountRegistry()
    context = MessageContext(
        account_id="10001",
        event_type="message-created",
        protocol_event_type=None,
        chat_type="private",
        channel_id="private:20001",
        user_id="20001",
        message_id="50001",
        text="状态",
        image_urls=(),
    )

    output = loaded_plugin.build_status(
        context, 1, registry=registry, metrics=MessageMetrics(), detailed=True
    )

    assert "进程: 启动" in output
    assert "系统:" not in output
    assert "网络 IO" not in output


@pytest.mark.parametrize("loaded_plugin", ["status"], indirect=True)
def test_collect_system_resources_reads_psutil_snapshot(
    loaded_plugin, monkeypatch
) -> None:
    fake_psutil = SimpleNamespace(
        cpu_percent=lambda: 12.5,
        virtual_memory=lambda: SimpleNamespace(
            used=2 * 1024**3, total=8 * 1024**3, percent=25.0
        ),
        disk_usage=lambda path: SimpleNamespace(
            used=3 * 1024**3, total=10 * 1024**3, percent=30.0
        ),
        net_io_counters=lambda: SimpleNamespace(
            bytes_sent=4 * 1024**2, bytes_recv=5 * 1024**2
        ),
    )
    monkeypatch.setattr(loaded_plugin, "psutil", fake_psutil)

    resources = loaded_plugin.collect_system_resources()

    assert resources == loaded_plugin.SystemResources(
        cpu_percent=12.5,
        memory_used=2 * 1024**3,
        memory_total=8 * 1024**3,
        memory_percent=25.0,
        disk_used=3 * 1024**3,
        disk_total=10 * 1024**3,
        disk_percent=30.0,
        net_sent=4 * 1024**2,
        net_received=5 * 1024**2,
    )
