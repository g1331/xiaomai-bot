from __future__ import annotations

import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from arclet.entari.command import Match, Query
from arclet.entari.event.base import GuildRequestEvent
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
from satori.element import At, Author, Quote
from satori.model import Event, Member

from tenko.host.actions import (
    ActionCapability,
    ActionCapabilityUnavailable,
    ActionExecutionError,
    ActionFailure,
    ActionPermissionDenied,
    ActionService,
)
from tenko.host.accounts import AccountRegistry
from tenko.host.perm import PermissionChecker, PermissionRegistry


def make_session(user_id: str, role: str, elements=None):
    event = Event(
        type=EventType.MESSAGE_CREATED,
        timestamp=datetime.now(),
        login=Login(platform="onebot", user=User("10001")),
        channel=Channel("40001", ChannelType.TEXT),
        guild=Guild("40001", "Tenko"),
        member=Member(user=User(user_id), roles=[Role(role)]),
        user=User(user_id),
        message=MessageObject.from_elements("50001", elements or []),
    )
    return SimpleNamespace(
        event=SimpleNamespace(
            _origin=event,
            channel=event.channel,
            guild=event.guild,
            user=event.user,
        )
    )


def make_private_session(user_id: str):
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
        event=SimpleNamespace(
            _origin=event,
            channel=event.channel,
            guild=event.guild,
            user=event.user,
        )
    )


def make_query(path: str, result):
    query = Query(path, result)
    query.available = True
    return query


@pytest.mark.asyncio
@pytest.mark.parametrize("loaded_plugin", ["group_manager"], indirect=True)
async def test_group_setting_trigger_is_read_only(loaded_plugin) -> None:
    loaded_plugin.permission_checker = PermissionChecker(registry=PermissionRegistry())
    loaded_plugin.read_group_settings = AsyncMock(
        return_value={
            "frequency_limitation": True,
            "response_type": "random",
            "permission_type": "admin",
            "permission": 2,
            "active": True,
        }
    )

    result = await loaded_plugin.group_setting.callable_target(
        make_session("20001", "admin"), Query("group.group_id", None)
    )

    assert "权限类型: admin" in str(result)
    loaded_plugin.read_group_settings.assert_awaited_once_with("40001")


@pytest.mark.asyncio
@pytest.mark.parametrize("loaded_plugin", ["group_manager"], indirect=True)
async def test_group_setting_permission_filter_blocks_normal_member(
    loaded_plugin,
) -> None:
    loaded_plugin.permission_checker = PermissionChecker(registry=PermissionRegistry())
    loaded_plugin.read_group_settings = AsyncMock()

    result = await loaded_plugin.group_setting.callable_target(
        make_session("20001", "member"), Query("group.group_id", None)
    )

    assert str(result) == "权限不足"
    loaded_plugin.read_group_settings.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("loaded_plugin", ["group_manager"], indirect=True)
async def test_group_setting_rejects_cross_group_target_in_group(
    loaded_plugin,
) -> None:
    loaded_plugin.permission_checker = PermissionChecker(
        registry=PermissionRegistry(master_id="20001")
    )
    loaded_plugin.read_group_settings = AsyncMock()

    result = await loaded_plugin.group_setting.callable_target(
        make_session("20001", "member"), make_query("group.group_id", 40002)
    )

    assert str(result) == "群内只能查询当前群"
    loaded_plugin.read_group_settings.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("loaded_plugin", ["group_manager"], indirect=True)
async def test_master_private_group_setting_can_query_requested_group(
    loaded_plugin,
) -> None:
    loaded_plugin.permission_checker = PermissionChecker(
        registry=PermissionRegistry(master_id="90001")
    )
    loaded_plugin.read_group_settings = AsyncMock(
        return_value={
            "frequency_limitation": True,
            "response_type": "random",
            "permission_type": "default",
            "permission": 1,
            "active": True,
        }
    )

    result = await loaded_plugin.group_setting.callable_target(
        make_private_session("90001"), make_query("group.group_id", 40002)
    )

    assert "群40002设置" in str(result)
    loaded_plugin.read_group_settings.assert_awaited_once_with("40002")


@pytest.mark.asyncio
@pytest.mark.parametrize("loaded_plugin", ["group_manager"], indirect=True)
async def test_non_master_private_group_setting_is_denied(loaded_plugin) -> None:
    loaded_plugin.permission_checker = PermissionChecker(registry=PermissionRegistry())
    loaded_plugin.read_group_settings = AsyncMock()

    result = await loaded_plugin.group_setting.callable_target(
        make_private_session("20001"), make_query("group.group_id", 40002)
    )

    assert str(result) == "权限不足"
    loaded_plugin.read_group_settings.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("loaded_plugin", ["group_manager"], indirect=True)
async def test_group_setting_reads_real_repositories(
    loaded_plugin, tenko_database
) -> None:
    del tenko_database
    from tenko.db.repositories import group_perm_repository, group_setting_repository

    await group_perm_repository.set("40001", 2, group_name="VIP 群", active=False)
    await group_setting_repository.set(
        "40001",
        frequency_limitation=False,
        response_type="deterministic",
        permission_type="admin",
    )

    settings = await loaded_plugin.read_group_settings("40001")

    assert settings == {
        "frequency_limitation": False,
        "response_type": "deterministic",
        "permission_type": "admin",
        "permission": 2,
        "active": False,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("loaded_plugin", ["group_manager"], indirect=True)
async def test_group_setting_falls_back_when_database_is_unavailable(
    loaded_plugin, tenko_database
) -> None:
    from tenko.db.repositories import configure_session_factory

    configure_session_factory(None)
    settings = await loaded_plugin.read_group_settings("40001")

    assert settings == {
        "frequency_limitation": True,
        "response_type": "random",
        "permission_type": "default",
        "permission": 1,
        "active": True,
    }


class FakeProtocol:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []

    async def guild_member_mute(self, *args):
        self.calls.append(("guild_member_mute", args, {}))

    async def channel_mute(self, *args):
        self.calls.append(("channel_mute", args, {}))

    async def message_delete(self, *args):
        self.calls.append(("message_delete", args, {}))

    async def guild_member_kick(self, *args, **kwargs):
        self.calls.append(("guild_member_kick", args, kwargs))


class InviteProtocol:
    def __init__(self, approval_error: BaseException | None = None) -> None:
        self.approvals: list[tuple[str, bool, str]] = []
        self.private_messages: list[tuple[str, str]] = []
        self.approval_error = approval_error

    async def guild_approve(self, request_id, approved, comment):
        if self.approval_error is not None:
            raise self.approval_error
        self.approvals.append((request_id, approved, comment))

    async def send_private_message(self, user_id, content):
        self.private_messages.append((str(user_id), str(content[0])))
        return [MessageObject("notice-1", str(content[0]))]


class FakeAccount:
    self_id = "10001"

    def __init__(self, protocol: FakeProtocol) -> None:
        self.protocol = protocol


class InviteAccount:
    self_id = "10001"
    platform = "onebot"

    def __init__(self, protocol: InviteProtocol) -> None:
        self.protocol = protocol


def make_invite_event(
    account, request_id: str = "request-1", inviter_id: str = "20001"
):
    origin = Event(
        type=EventType.GUILD_REQUEST,
        timestamp=datetime.now(),
        login=Login(platform="onebot", user=User(account.self_id)),
        channel=Channel("40001", ChannelType.TEXT),
        guild=Guild("40001", "审核群"),
        user=User(inviter_id),
        message=MessageObject(request_id, "邀请机器人"),
        _type="request.group.invite",
        _data={"group_id": "40001", "user_id": inviter_id, "sub_type": "invite"},
    )
    return GuildRequestEvent(account, origin)


async def clear_pending_invites(loaded_plugin) -> None:
    tasks = tuple(loaded_plugin.invite_expiry_tasks.values())
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    loaded_plugin.invite_expiry_tasks.clear()
    loaded_plugin.pending_invites.clear()


def install_action_service(loaded_plugin):
    protocol = FakeProtocol()
    account = FakeAccount(protocol)
    accounts = AccountRegistry()
    accounts.register(account, groups=["40001"])
    permissions = PermissionRegistry()
    checker = PermissionChecker(registry=permissions)
    loaded_plugin.permission_checker = checker
    loaded_plugin.account_registry = accounts
    loaded_plugin.action_service = ActionService(accounts, checker)
    return protocol


@pytest.mark.parametrize("loaded_plugin", ["group_manager"], indirect=True)
def test_action_error_message_never_exposes_platform_details(loaded_plugin) -> None:
    failure = ActionFailure(
        account_id="10001",
        capability=ActionCapability.MEMBER_MUTE,
        action="set_group_ban",
        status="failed",
        retcode=1200,
        message="ERR_NOT_GROUP_ADMIN",
        wording="ERR_NOT_GROUP_ADMIN",
        echo="echo-1",
    )
    errors = (
        (ActionPermissionDenied("internal permission detail"), "权限不足"),
        (
            ActionCapabilityUnavailable("账号 10001 不支持平台能力 member_mute"),
            "该账号暂不支持此操作（或已被临时限制），已通知开发者",
        ),
        (
            ActionExecutionError("平台动作失败: set_group_ban (1200)", failure=failure),
            "该账号在此群没有管理员权限",
        ),
        (
            ActionExecutionError("平台动作失败: opaque", failure=None),
            "平台操作失败，已通知开发者",
        ),
    )

    for error, expected in errors:
        result = loaded_plugin._action_error(error)
        assert result == expected
        assert all(
            field not in result
            for field in ("retcode", "echo", "wording", "ActionFailed", "traceback")
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("loaded_plugin", ["group_manager"], indirect=True)
async def test_group_action_error_reports_and_returns_safe_message(
    loaded_plugin, monkeypatch
) -> None:
    failure = ActionFailure(
        account_id="10001",
        capability=ActionCapability.MEMBER_MUTE,
        action="set_group_ban",
        status="failed",
        retcode=1200,
        message="ERR_NOT_GROUP_ADMIN",
        wording="ERR_NOT_GROUP_ADMIN",
    )
    error = ActionExecutionError("平台动作失败: set_group_ban (1200)", failure=failure)
    reporter = AsyncMock()
    monkeypatch.setattr(loaded_plugin, "report_action_error", reporter)
    loaded_plugin.permission_checker = PermissionChecker(registry=PermissionRegistry())
    loaded_plugin.action_service = SimpleNamespace(
        authorize=AsyncMock(return_value=True),
        mute_member=AsyncMock(side_effect=error),
    )
    session = make_session("20001", "admin")

    result = await loaded_plugin.mute.callable_target(
        session,
        Match(("20002", "5"), True),
        Match(None, False),
    )

    assert str(result) == "该账号在此群没有管理员权限"
    reporter.assert_awaited_once_with(error, session)


@pytest.mark.asyncio
@pytest.mark.parametrize("loaded_plugin", ["group_manager"], indirect=True)
async def test_management_commands_call_action_service(loaded_plugin) -> None:
    protocol = install_action_service(loaded_plugin)
    session = make_session("20001", "admin")

    mute_result = await loaded_plugin.mute.callable_target(
        session,
        Match((At("20002"), "5"), True),
        Match(None, False),
    )
    unmute_result = await loaded_plugin.unmute.callable_target(
        session,
        Match((At("20002"),), True),
    )
    whole_mute_result = await loaded_plugin.mute_all.callable_target(session)
    whole_unmute_result = await loaded_plugin.unmute_all.callable_target(session)
    kick_result = await loaded_plugin.kick.callable_target(
        session,
        Match(("20002",), True),
    )

    assert str(mute_result) == "已设置【20002】5分钟的禁言!"
    assert str(unmute_result) == "已解禁20002!"
    assert str(whole_mute_result) == "开启全体禁言成功!"
    assert str(whole_unmute_result) == "关闭全体禁言成功!"
    assert str(kick_result) == "已将20002踢出群聊!"
    assert protocol.calls == [
        ("guild_member_mute", ("40001", "20002", 300.0), {}),
        ("guild_member_mute", ("40001", "20002", 0.0), {}),
        ("channel_mute", ("40001", 60.0), {}),
        ("channel_mute", ("40001", 0.0), {}),
        ("guild_member_kick", ("40001", "20002"), {"permanent": False}),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("loaded_plugin", ["group_manager"], indirect=True)
async def test_recall_uses_the_satori_quote_message_id(loaded_plugin) -> None:
    protocol = install_action_service(loaded_plugin)
    session = make_session(
        "20001",
        "admin",
        [Quote("60001", content=[Author("20002")])],
    )

    result = await loaded_plugin.recall.callable_target(session)

    assert result is None
    assert protocol.calls == [("message_delete", ("40001", "60001"), {})]


@pytest.mark.asyncio
@pytest.mark.parametrize("loaded_plugin", ["group_manager"], indirect=True)
async def test_unmute_self_recovers_current_bot_mute_state(loaded_plugin) -> None:
    protocol = install_action_service(loaded_plugin)
    loaded_plugin.account_registry.set_muted("10001", "40001", True)

    result = await loaded_plugin.unmute_self.callable_target(
        make_session("20001", "admin")
    )

    assert str(result) == "已解除本BOT在当前群的禁言状态!"
    assert not loaded_plugin.account_registry.is_muted("10001", "40001")
    assert protocol.calls == [("guild_member_mute", ("40001", "10001", 0.0), {})]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("command_name", "arguments"),
    [
        ("mute", (Match(("20002", "5"), True), Match(None, False))),
        ("unmute", (Match(("20002",), True),)),
        ("mute_all", ()),
        ("unmute_all", ()),
        ("recall", ()),
        ("kick", (Match(("20002",), True),)),
    ],
)
@pytest.mark.parametrize("loaded_plugin", ["group_manager"], indirect=True)
async def test_every_management_command_blocks_members(
    loaded_plugin, command_name, arguments
) -> None:
    loaded_plugin.permission_checker = PermissionChecker(registry=PermissionRegistry())
    loaded_plugin.action_service = ActionService(
        AccountRegistry(), loaded_plugin.permission_checker
    )
    result = await getattr(loaded_plugin, command_name).callable_target(
        make_session("20001", "member"), *arguments
    )

    assert str(result) == "权限不足"


@pytest.mark.asyncio
@pytest.mark.parametrize("minutes", [0, 30 * 24 * 60 + 1])
@pytest.mark.parametrize("loaded_plugin", ["group_manager"], indirect=True)
async def test_mute_rejects_legacy_minute_boundaries(loaded_plugin, minutes) -> None:
    protocol = install_action_service(loaded_plugin)
    result = await loaded_plugin.mute.callable_target(
        make_session("20001", "admin"),
        Match((At("20002"), str(minutes)), True),
        Match(None, False),
    )

    assert str(result) == "时间非法!范围(分钟): `0 &lt; time &lt;= 43200`"
    assert protocol.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("loaded_plugin", ["group_manager"], indirect=True)
async def test_privileged_inviter_is_automatically_approved(loaded_plugin) -> None:
    protocol = InviteProtocol()
    account = InviteAccount(protocol)
    permissions = PermissionRegistry(bot_admin_ids=["20001"])
    loaded_plugin.permission_checker = PermissionChecker(registry=permissions)
    await clear_pending_invites(loaded_plugin)

    await loaded_plugin.invited_event.callable_target(
        make_invite_event(account, inviter_id="20001")
    )

    assert protocol.approvals == [("request-1", True, "已同意您的邀请~")]
    assert loaded_plugin.pending_invites == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("loaded_plugin", ["group_manager"], indirect=True)
async def test_unprivileged_inviter_is_recorded_for_command_review(
    loaded_plugin,
) -> None:
    protocol = InviteProtocol()
    account = InviteAccount(protocol)
    loaded_plugin.permission_checker = PermissionChecker(registry=PermissionRegistry())
    await clear_pending_invites(loaded_plugin)

    try:
        await loaded_plugin.invited_event.callable_target(make_invite_event(account))

        pending = loaded_plugin.pending_invites["request-1"]
        assert pending.group_id == "40001"
        assert pending.inviter_id == "20001"
        assert protocol.approvals == []
    finally:
        await clear_pending_invites(loaded_plugin)


@pytest.mark.asyncio
@pytest.mark.parametrize("loaded_plugin", ["group_manager"], indirect=True)
async def test_privileged_invite_is_kept_pending_when_auto_approval_fails(
    loaded_plugin,
) -> None:
    protocol = InviteProtocol(approval_error=RuntimeError("approval unavailable"))
    account = InviteAccount(protocol)
    loaded_plugin.permission_checker = PermissionChecker(
        registry=PermissionRegistry(bot_admin_ids=["20001"])
    )
    await clear_pending_invites(loaded_plugin)

    try:
        await loaded_plugin.invited_event.callable_target(
            make_invite_event(account, inviter_id="20001")
        )

        assert loaded_plugin.pending_invites["request-1"].inviter_id == "20001"
        assert protocol.approvals == []
    finally:
        await clear_pending_invites(loaded_plugin)


@pytest.mark.asyncio
@pytest.mark.parametrize("loaded_plugin", ["group_manager"], indirect=True)
async def test_group_admin_can_approve_pending_invite(loaded_plugin) -> None:
    protocol = InviteProtocol()
    account = InviteAccount(protocol)
    loaded_plugin.permission_checker = PermissionChecker(registry=PermissionRegistry())
    loaded_plugin.pending_invites["request-1"] = loaded_plugin.PendingInvite(
        request_id="request-1",
        account=account,
        group_id="40001",
        group_name="审核群",
        inviter_id="20001",
        inviter_name="邀请人",
        comment="",
        created_at=0,
    )

    result = await loaded_plugin.approve_invite.callable_target(
        make_session("20002", "admin"), Match("request-1", True)
    )

    assert str(result) == "已同意邀请 request-1"
    assert protocol.approvals == [("request-1", True, "已同意您的邀请~")]
    assert loaded_plugin.pending_invites == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("loaded_plugin", ["group_manager"], indirect=True)
async def test_group_admin_can_reject_pending_invite_with_reason(loaded_plugin) -> None:
    protocol = InviteProtocol()
    account = InviteAccount(protocol)
    loaded_plugin.permission_checker = PermissionChecker(registry=PermissionRegistry())
    loaded_plugin.pending_invites["request-1"] = loaded_plugin.PendingInvite(
        request_id="request-1",
        account=account,
        group_id="40001",
        group_name="审核群",
        inviter_id="20001",
        inviter_name="邀请人",
        comment="",
        created_at=0,
    )

    result = await loaded_plugin.reject_invite.callable_target(
        make_session("20002", "admin"),
        Match("request-1", True),
        Match(("非工作群",), True),
    )

    assert str(result) == "已拒绝邀请 request-1"
    assert protocol.approvals == [("request-1", False, "非工作群")]
    assert loaded_plugin.pending_invites == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("loaded_plugin", ["group_manager"], indirect=True)
async def test_normal_group_member_cannot_review_pending_invite(loaded_plugin) -> None:
    protocol = InviteProtocol()
    account = InviteAccount(protocol)
    loaded_plugin.permission_checker = PermissionChecker(registry=PermissionRegistry())
    loaded_plugin.pending_invites["request-1"] = loaded_plugin.PendingInvite(
        request_id="request-1",
        account=account,
        group_id="40001",
        group_name="审核群",
        inviter_id="20001",
        inviter_name="邀请人",
        comment="",
        created_at=0,
    )

    result = await loaded_plugin.approve_invite.callable_target(
        make_session("20002", "member"), Match("request-1", True)
    )

    assert str(result) == "权限不足"
    assert protocol.approvals == []
    loaded_plugin.pending_invites.clear()


@pytest.mark.asyncio
@pytest.mark.parametrize("loaded_plugin", ["group_manager"], indirect=True)
async def test_superuser_can_list_pending_invites(loaded_plugin) -> None:
    loaded_plugin.permission_checker = PermissionChecker(
        registry=PermissionRegistry(master_id="90001")
    )
    loaded_plugin.pending_invites["request-1"] = loaded_plugin.PendingInvite(
        request_id="request-1",
        account=InviteAccount(InviteProtocol()),
        group_id="40001",
        group_name="审核群",
        inviter_id="20001",
        inviter_name="邀请人",
        comment="",
        created_at=0,
    )

    result = await loaded_plugin.pending_invite_list.callable_target(
        make_private_session("90001")
    )

    assert "request-1" in str(result)
    assert "邀请人(20001)" in str(result)
    loaded_plugin.pending_invites.clear()


@pytest.mark.asyncio
@pytest.mark.parametrize("loaded_plugin", ["group_manager"], indirect=True)
async def test_superuser_can_reset_current_account_capability_state(
    loaded_plugin,
) -> None:
    accounts = AccountRegistry()
    account = FakeAccount(FakeProtocol())
    accounts.register(account, groups=["40001"])
    checker = PermissionChecker(registry=PermissionRegistry(master_id="90001"))
    service = ActionService(accounts, checker)
    service.set_capability("10001", "member_mute", False)
    service.set_capability("10001", "group_mute", True)
    loaded_plugin.permission_checker = checker
    loaded_plugin.action_service = service

    result = await loaded_plugin.reset_capability.callable_target(
        make_private_session("90001"), Query("account_id", None)
    )

    assert str(result) == "已重置账号 10001 的 2 项平台能力学习状态"
    assert service.capability_status("10001", "member_mute") is None
    assert service.capability_status("10001", "group_mute") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("loaded_plugin", ["group_manager"], indirect=True)
async def test_non_master_cannot_reset_capability_state(loaded_plugin) -> None:
    checker = PermissionChecker(registry=PermissionRegistry())
    service = ActionService(AccountRegistry(), checker)
    service.set_capability("10001", "member_mute", False)
    loaded_plugin.permission_checker = checker
    loaded_plugin.action_service = service

    result = await loaded_plugin.reset_capability.callable_target(
        make_private_session("20001"), Query("account_id", None)
    )

    assert str(result) == "权限不足"
    assert service.capability_status("10001", "member_mute") is False


@pytest.mark.asyncio
@pytest.mark.parametrize("loaded_plugin", ["group_manager"], indirect=True)
async def test_master_group_cannot_list_pending_invites(loaded_plugin) -> None:
    loaded_plugin.permission_checker = PermissionChecker(
        registry=PermissionRegistry(master_id="90001")
    )
    loaded_plugin.pending_invites["request-1"] = loaded_plugin.PendingInvite(
        request_id="request-1",
        account=InviteAccount(InviteProtocol()),
        group_id="40001",
        group_name="审核群",
        inviter_id="20001",
        inviter_name="邀请人",
        comment="",
        created_at=0,
    )

    result = await loaded_plugin.pending_invite_list.callable_target(
        make_session("90001", "member")
    )

    assert str(result) == "该指令仅支持 Master 私聊执行"
    loaded_plugin.pending_invites.clear()


@pytest.mark.asyncio
@pytest.mark.parametrize("loaded_plugin", ["group_manager"], indirect=True)
async def test_master_group_cannot_reset_capability_state(loaded_plugin) -> None:
    checker = PermissionChecker(registry=PermissionRegistry(master_id="90001"))
    service = ActionService(AccountRegistry(), checker)
    service.set_capability("10001", "member_mute", False)
    loaded_plugin.permission_checker = checker
    loaded_plugin.action_service = service

    result = await loaded_plugin.reset_capability.callable_target(
        make_session("90001", "member"), Query("account_id", None)
    )

    assert str(result) == "该指令仅支持 Master 私聊执行"
    assert service.capability_status("10001", "member_mute") is False


@pytest.mark.asyncio
@pytest.mark.parametrize("loaded_plugin", ["group_manager"], indirect=True)
async def test_expired_pending_invite_is_rejected_with_legacy_comment(
    loaded_plugin, monkeypatch
) -> None:
    protocol = InviteProtocol()
    loaded_plugin.pending_invites["request-1"] = loaded_plugin.PendingInvite(
        request_id="request-1",
        account=InviteAccount(protocol),
        group_id="40001",
        group_name="审核群",
        inviter_id="20001",
        inviter_name="邀请人",
        comment="",
        created_at=0,
    )
    sleep = AsyncMock()
    monkeypatch.setattr(loaded_plugin.asyncio, "sleep", sleep)

    await loaded_plugin._expire_invite("request-1")

    assert protocol.approvals == [
        ("request-1", False, "拒绝了你的入群邀请!"),
    ]
    assert loaded_plugin.pending_invites == {}
