from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from arclet.entari.command import Query
from satori import (
    Channel,
    ChannelType,
    EventType,
    Guild,
    Image,
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


def make_resources(loaded_plugin):
    return loaded_plugin.SystemResources(
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


def make_process(loaded_plugin):
    return loaded_plugin.ProcessInfo(
        start_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        uptime_seconds=3661,
        rss=64 * 1024**2,
    )


def patch_status_data(loaded_plugin, monkeypatch) -> None:
    resources = make_resources(loaded_plugin)
    process = make_process(loaded_plugin)
    monkeypatch.setattr(loaded_plugin, "collect_system_resources", lambda: resources)
    monkeypatch.setattr(loaded_plugin, "collect_process_info", lambda: process)
    monkeypatch.setattr(
        loaded_plugin,
        "get_version_details",
        lambda: ("版本信息：v9.9.9", "Git分支：test", "最新提交：abc123 (tester)"),
    )


@pytest.mark.parametrize("loaded_plugin", ["status"], indirect=True)
def test_status_declares_render_service_for_entari_injection(loaded_plugin) -> None:
    parameter = next(
        parameter
        for parameter in loaded_plugin.status.params
        if parameter.name == "render_service"
    )

    assert parameter.annotation is loaded_plugin.RenderService
    assert any(
        getattr(provider, "origin", None) is loaded_plugin.RenderService
        for provider in parameter.providers
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("loaded_plugin", ["status"], indirect=True)
async def test_status_command_reports_legacy_group_fields_without_context_details(
    loaded_plugin, monkeypatch
) -> None:
    loaded_plugin.permission_checker = PermissionChecker(registry=PermissionRegistry())
    monkeypatch.setattr(loaded_plugin, "message_metrics", MessageMetrics())
    patch_status_data(loaded_plugin, monkeypatch)

    result = await loaded_plugin.status.callable_target(
        make_session("20001", "member"),
        Query("text.value", False),
        render_service=loaded_plugin.RenderService(),
    )

    output = str(result)
    assert output.startswith("开机时间：2026年")
    assert "运行时长：0天1小时1分1秒" in output
    assert "接收消息：0条 (实时:0条/m)" in output
    assert "发送消息：0条 (实时:0条/m)" in output
    assert "内存使用：2048MB (25%)" in output
    assert "CPU占比：12.5%" in output
    assert "磁盘占比：30.0%" in output
    assert "在线bot数量：0/0" in output
    assert "活动群组数量：0" in output
    assert "当前群禁言：0/0" in output
    assert "项目地址：https://github.com/g1331/xiaomai-bot" in output
    assert "Tenko 状态" not in output
    assert "10001" not in output
    assert "20001" not in output
    assert "账号:" not in output
    assert "用户:" not in output
    assert "会话:" not in output
    assert "已注册插件:" not in output
    assert "在线账号:" not in output
    assert "账号×群禁言:" not in output
    assert "RSS" not in output
    assert "网络 IO" not in output
    assert loaded_plugin.status_command.parse("/-bot -t").matched
    assert loaded_plugin.status_command.parse("/状态 -t").matched


@pytest.mark.asyncio
@pytest.mark.parametrize("loaded_plugin", ["status"], indirect=True)
async def test_status_command_sends_rendered_image_when_available(
    loaded_plugin, monkeypatch
) -> None:
    loaded_plugin.permission_checker = PermissionChecker(registry=PermissionRegistry())
    patch_status_data(loaded_plugin, monkeypatch)
    renderer = AsyncMock(return_value=b"jpeg-bytes")
    monkeypatch.setattr(loaded_plugin, "render_or_none", renderer)
    render_service = loaded_plugin.RenderService()

    result = await loaded_plugin.status.callable_target(
        make_session("20001", "member"),
        Query("text.value", False),
        render_service=render_service,
    )

    renderer.assert_awaited_once()
    assert renderer.await_args.args[:3] == (
        render_service,
        "render_template",
        "status.html",
    )
    assert renderer.await_args.args[3]["content"].startswith("开机时间：2026年")
    assert isinstance(result[0], Image)


@pytest.mark.asyncio
@pytest.mark.parametrize("loaded_plugin", ["status"], indirect=True)
async def test_status_command_falls_back_to_text_when_rendering_fails(
    loaded_plugin, monkeypatch
) -> None:
    loaded_plugin.permission_checker = PermissionChecker(registry=PermissionRegistry())
    patch_status_data(loaded_plugin, monkeypatch)
    renderer = AsyncMock(return_value=None)
    monkeypatch.setattr(loaded_plugin, "render_or_none", renderer)
    render_service = loaded_plugin.RenderService()

    result = await loaded_plugin.status.callable_target(
        make_session("20001", "member"),
        Query("text.value", False),
        render_service=render_service,
    )

    renderer.assert_awaited_once_with(
        render_service,
        "render_template",
        "status.html",
        renderer.await_args.args[3],
    )
    assert str(result).startswith("开机时间：2026年")


@pytest.mark.asyncio
@pytest.mark.parametrize("loaded_plugin", ["status"], indirect=True)
async def test_status_permission_filter_blocks_global_blacklisted_user(
    loaded_plugin,
) -> None:
    registry = PermissionRegistry()
    registry.set_user_level(None, "20001", Permission.GlobalBlack)
    loaded_plugin.permission_checker = PermissionChecker(registry=registry)

    result = await loaded_plugin.status.callable_target(
        make_session("20001", "member"),
        Query("text.value", False),
        render_service=loaded_plugin.RenderService(),
    )

    assert str(result) == "权限不足"


@pytest.mark.asyncio
@pytest.mark.parametrize("loaded_plugin", ["status"], indirect=True)
async def test_master_private_status_appends_only_operational_diagnostic(
    loaded_plugin, monkeypatch
) -> None:
    protocol = PrivateMessageProtocol()
    loaded_plugin.permission_checker = PermissionChecker(
        registry=PermissionRegistry(master_id="90001")
    )
    patch_status_data(loaded_plugin, monkeypatch)

    result = await loaded_plugin.status.callable_target(
        make_private_session("90001", protocol),
        Query("text.value", False),
        render_service=loaded_plugin.RenderService(),
    )

    output = str(result)
    assert "版本信息：v9.9.9" in output
    assert "进程 RSS：64.0MB" in output
    assert "网络 IO：↑ 4.0MB；↓ 5.0MB" in output
    assert "进程: 启动" not in output
    assert "在线账号:" not in output
    assert "账号×群禁言:" not in output
    assert "账号:" not in output
    assert "用户:" not in output
    assert "会话:" not in output
    assert "已注册插件:" not in output
    assert protocol.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("loaded_plugin", ["status"], indirect=True)
async def test_master_group_status_never_pushes_private_diagnostic(
    loaded_plugin, monkeypatch
) -> None:
    protocol = PrivateMessageProtocol()
    loaded_plugin.permission_checker = PermissionChecker(
        registry=PermissionRegistry(master_id="90001")
    )
    patch_status_data(loaded_plugin, monkeypatch)

    result = await loaded_plugin.status.callable_target(
        make_session("90001", "member", protocol),
        Query("text.value", False),
        render_service=loaded_plugin.RenderService(),
    )

    output = str(result)
    assert "当前群禁言：" in output
    assert "详情" not in output
    assert "在线账号:" not in output
    assert "账号×群禁言:" not in output
    assert "进程 RSS：" not in output
    assert "网络 IO：" not in output
    assert protocol.calls == []


@pytest.mark.parametrize("loaded_plugin", ["status"], indirect=True)
def test_group_and_private_status_share_the_same_legacy_base(
    loaded_plugin,
) -> None:
    registry = AccountRegistry()
    first = SimpleNamespace(self_id="10001")
    second = SimpleNamespace(self_id="10002")
    registry.register(first, groups=["40001"])
    registry.register(second, available=False, groups=["40002"])
    registry.set_muted(first, "40001", True)
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
    private_context = replace(
        context,
        chat_type="private",
        channel_id="private:20001",
    )
    resources = make_resources(loaded_plugin)
    process = make_process(loaded_plugin)
    metrics = MessageMetrics()
    version_details = ("版本信息：v9.9.9", "Git分支：test")

    group_output = loaded_plugin.build_status(
        context,
        7,
        registry=registry,
        metrics=metrics,
        resources=resources,
        process=process,
        version_details=version_details,
    )
    private_output = loaded_plugin.build_status(
        private_context,
        7,
        registry=registry,
        metrics=metrics,
        resources=resources,
        process=process,
        version_details=version_details,
    )

    assert group_output == f"{private_output}\n当前群禁言：1/1"
    assert "当前群禁言：" not in private_output
    for forbidden_value in ("10001", "10002", "20001", "40002"):
        assert forbidden_value not in group_output
    for forbidden_field in (
        "账号:",
        "用户:",
        "会话:",
        "已注册插件:",
        "在线账号:",
        "账号×群禁言:",
        "RSS",
        "网络 IO",
    ):
        assert forbidden_field not in group_output


@pytest.mark.parametrize("loaded_plugin", ["status"], indirect=True)
def test_build_status_reports_legacy_resources_and_current_group_mute(
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
        version_details=("版本信息：v9.9.9", "构建类型：dev"),
    )

    assert "开机时间：2026年" in output
    assert "运行时长：0天1小时1分1秒" in output
    assert "接收消息：1条 (实时:1条/m)" in output
    assert "发送消息：1条 (实时:1条/m)" in output
    assert "内存使用：2048MB (25%)" in output
    assert "CPU占比：12.5%" in output
    assert "磁盘占比：30.0%" in output
    assert "在线bot数量：1/2" in output
    assert "活动群组数量：1" in output
    assert "版本信息：v9.9.9" in output
    assert "构建类型：dev" in output
    assert "当前群禁言：1/2" in output
    assert "RSS" not in output
    assert "网络 IO" not in output
    assert "在线账号:" not in output
    assert "账号×群禁言:" not in output


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

    assert "开机时间：" in output
    assert "内存使用：" not in output
    assert "CPU占比：" not in output
    assert "磁盘占比：" not in output
    assert "RSS" not in output
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


@pytest.mark.parametrize("loaded_plugin", ["status"], indirect=True)
def test_get_version_details_includes_git_and_build_metadata(
    loaded_plugin, monkeypatch
) -> None:
    monkeypatch.setattr(loaded_plugin, "_project_version", lambda: "9.9.9")
    monkeypatch.setattr(
        loaded_plugin,
        "_git_output",
        lambda *arguments: {
            ("branch", "--show-current"): "release/test",
            ("log", "-1", "--format=%h%x1f%an%x1f%s"): (
                "abc123\x1fTenko Test\x1ffix(status): align output"
            ),
        }[arguments],
    )
    monkeypatch.setenv("B2V_BUILD_NUMBER", "42")
    monkeypatch.setenv("B2V_BUILD_DATE", "2026-08-30")
    monkeypatch.setenv("B2V_BUILD_TYPE", "release")

    assert loaded_plugin.get_version_details() == (
        "版本信息：v9.9.9",
        "Git分支：release/test",
        "最新提交：abc123 (Tenko Test)",
        "提交信息：fix(status): align output",
        "构建编号：42",
        "构建日期：2026-08-30",
        "构建类型：release",
    )
