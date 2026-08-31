from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import pytest
from satori.exception import ActionFailed
from satori.model import IterablePageResult, PageResult

from tenko.context import MessageContext
from tenko.host.actions import (
    ActionCapability,
    ActionCapabilityUnavailable,
    ActionExecutionError,
    ActionFailure,
    ActionPermissionDenied,
    ActionService,
    ActionServiceError,
)
from tenko.host.accounts import AccountRegistry
from tenko.host.actions import ActionAccountUnavailable
from tenko.host.perm import Permission, PermissionChecker, PermissionRegistry


@dataclass
class FakeProtocol:
    calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = field(
        default_factory=list
    )
    responses: dict[str, Any] = field(default_factory=dict)

    async def guild_member_mute(self, *args: Any) -> Any:
        self.calls.append(("guild_member_mute", args, {}))
        response = self.responses.get("guild_member_mute")
        if isinstance(response, BaseException):
            raise response
        return response

    async def guild_approve(self, *args: Any) -> Any:
        self.calls.append(("guild_approve", args, {}))
        response = self.responses.get("guild_approve")
        if isinstance(response, BaseException):
            raise response
        return response

    async def send_private_message(self, *args: Any) -> Any:
        self.calls.append(("send_private_message", args, {}))
        response = self.responses.get("send_private_message")
        if isinstance(response, BaseException):
            raise response
        return response

    async def guild_member_get(self, *args: Any) -> Any:
        self.calls.append(("guild_member_get", args, {}))
        response = self.responses.get("guild_member_get")
        if isinstance(response, BaseException):
            raise response
        return response

    def guild_member_list(self, *args: Any) -> Any:
        self.calls.append(("guild_member_list", args, {}))
        return self.responses.get("guild_member_list", [])

    async def channel_mute(self, *args: Any) -> Any:
        self.calls.append(("channel_mute", args, {}))
        return self.responses.get("channel_mute")

    async def message_delete(self, *args: Any) -> Any:
        self.calls.append(("message_delete", args, {}))
        return self.responses.get("message_delete")

    async def guild_member_kick(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append(("guild_member_kick", args, kwargs))
        return self.responses.get("guild_member_kick")

    async def internal(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append(("internal", args, kwargs))
        response = self.responses.get("internal")
        if isinstance(response, BaseException):
            raise response
        return response

    async def send_message(self, *args: Any) -> Any:
        self.calls.append(("send_message", args, {}))
        response = self.responses.get("send_message")
        if isinstance(response, BaseException):
            raise response
        return response

    def guild_list(self) -> Any:
        self.calls.append(("guild_list", (), {}))
        return self.responses.get("guild_list", [])

    async def guild_get(self, *args: Any) -> Any:
        self.calls.append(("guild_get", args, {}))
        return self.responses.get("guild_get", {"id": args[0]})


@dataclass
class FakeAccount:
    self_id: str
    protocol: FakeProtocol


def make_context(
    user_id: str = "20001",
    *,
    role: str = "admin",
    account_id: str = "10001",
    group_id: str = "40001",
    chat_type: Literal["private", "group", "other"] = "group",
) -> MessageContext:
    return MessageContext(
        account_id=account_id,
        event_type="message-created",
        protocol_event_type="message.group.normal",
        chat_type=chat_type,
        channel_id=group_id,
        user_id=user_id,
        message_id="50001",
        text="",
        image_urls=(),
        member_role=role,
    )


def make_service(
    protocol: FakeProtocol | None = None,
    *,
    role: str = "admin",
    user_id: str = "20001",
    overrides: dict[str, dict[str, bool]] | None = None,
) -> tuple[ActionService, FakeAccount, MessageContext, FakeProtocol]:
    actual_protocol = protocol or FakeProtocol()
    account = FakeAccount("10001", actual_protocol)
    accounts = AccountRegistry()
    accounts.register(account, groups=["40001"])
    permissions = PermissionRegistry(
        master_id=user_id if role == "master" else None,
        bot_admin_ids=[user_id] if role == "bot_admin" else []
    )
    service = ActionService(
        accounts,
        PermissionChecker(registry=permissions),
        capability_overrides=overrides,
    )
    return service, account, make_context(user_id, role=role), actual_protocol


@pytest.mark.asyncio
async def test_standard_actions_use_satori_native_protocol_methods() -> None:
    service, account, context, protocol = make_service()

    mute = await service.mute_member(account, "40001", "20002", 90, context=context)
    whole = await service.mute_group(account, "40001", True, context=context)
    deleted = await service.delete_message(account, "50002", context=context)
    kicked = await service.kick_member(account, "40001", "20002", context=context)

    assert mute.action == "set_group_ban"
    assert whole.action == "set_group_whole_ban"
    assert deleted.action == "delete_msg"
    assert kicked.action == "set_group_kick"
    assert protocol.calls == [
        ("guild_member_mute", ("40001", "20002", 90.0), {}),
        ("channel_mute", ("40001", 60.0), {}),
        ("message_delete", ("40001", "50002"), {}),
        ("guild_member_kick", ("40001", "20002"), {"permanent": False}),
    ]


@pytest.mark.asyncio
async def test_member_queries_prefer_onebot_data_and_collect_satori_pages() -> None:
    protocol = FakeProtocol(
        responses={
            "internal": {"user_id": 20002, "permission": "admin"},
        }
    )
    service, account, _, _ = make_service(protocol)

    member = await service.get_group_member(account, "40001", "20002")
    assert member == {"user_id": 20002, "permission": "admin"}
    assert protocol.calls == [
        (
            "internal",
            ("get_group_member_info",),
            {"group_id": 40001, "user_id": 20002},
        )
    ]

    page_calls: list[str | None] = []

    async def fetch_page(next_token: str | None) -> PageResult[dict[str, str]]:
        page_calls.append(next_token)
        if next_token is None:
            return PageResult([{"user_id": "20002"}], next="page-2")
        return PageResult([{"user_id": "20003"}], next=None)

    protocol.responses["internal"] = None
    protocol.responses["guild_member_list"] = IterablePageResult(fetch_page)
    members = await service.list_group_members(account, "40001")

    assert members == ({"user_id": "20002"}, {"user_id": "20003"})
    assert page_calls == [None, "page-2"]
    assert protocol.calls[-2:] == [
        ("internal", ("get_group_member_list",), {"group_id": 40001}),
        ("guild_member_list", ("40001",), {}),
    ]


@pytest.mark.asyncio
async def test_member_query_failure_is_explicit_without_capability_learning() -> None:
    protocol = FakeProtocol(
        responses={
            "internal": RuntimeError("raw member API unavailable"),
            "guild_member_get": RuntimeError("standard member API unavailable"),
        }
    )
    service, account, _, _ = make_service(protocol)

    with pytest.raises(ActionServiceError, match="查询群 40001 成员 20002 失败"):
        await service.get_group_member(account, "40001", "20002")
    assert service.capability_status("10001", ActionCapability.MEMBER_MUTE) is None


@pytest.mark.asyncio
async def test_extension_actions_share_the_native_internal_entry() -> None:
    service, account, context, protocol = make_service(role="master")

    essence = await service.set_essence(account, "50002", context=context)
    await service.leave_group(
        account,
        "40001",
        context=make_context(role="bot_admin"),
        permission_checker=service.permission_checker,
    )

    assert essence.action == "set_essence_msg"
    assert protocol.calls == [
        ("internal", ("set_essence_msg",), {"message_id": 50002}),
        ("internal", ("set_group_leave",), {"group_id": 40001, "is_dismiss": False}),
    ]


@pytest.mark.asyncio
async def test_group_invite_approval_uses_satori_native_protocol_method() -> None:
    service, account, context, protocol = make_service(role="bot_admin")

    receipt = await service.approve_group_invite(
        account,
        "request-1",
        True,
        "已同意",
        context=context,
    )

    assert receipt.action == "set_group_add_request"
    assert protocol.calls == [
        ("guild_approve", ("request-1", True, "已同意"), {}),
    ]


@pytest.mark.asyncio
async def test_system_private_notification_uses_action_service() -> None:
    service, account, _, protocol = make_service()

    receipt = await service.send_private_message(account, "90001", "需要人工确认")

    assert receipt.action == "send_private_msg"
    assert protocol.calls == [
        ("send_private_message", ("90001", "需要人工确认"), {}),
    ]


@pytest.mark.asyncio
async def test_permission_failed_receipt_does_not_latch_capability() -> None:
    protocol = FakeProtocol(
        responses={
            "guild_member_mute": {
                "status": "failed",
                "retcode": 1200,
                "data": None,
                "message": "没有权限",
                "wording": "permission denied",
                "echo": "1",
            }
        }
    )
    service, account, context, _ = make_service(protocol)

    with pytest.raises(ActionExecutionError) as caught:
        await service.mute_member(account, "40001", "20002", 90, context=context)

    failure = caught.value.failure
    assert failure is not None
    assert failure.capability is ActionCapability.MEMBER_MUTE
    assert failure.retcode == 1200
    assert failure.message == "没有权限"
    assert failure.wording == "permission denied"
    assert service.capability_status("10001", ActionCapability.MEMBER_MUTE) is None

    with pytest.raises(ActionExecutionError):
        await service.mute_member(account, "40001", "20002", 90, context=context)
    assert len(protocol.calls) == 2


@pytest.mark.asyncio
async def test_napcat_permission_error_text_does_not_latch_capability() -> None:
    protocol = FakeProtocol(
        responses={
            "guild_member_mute": ActionFailed(
                "1200: {'status': 'failed', 'retcode': 1200, "
                "'message': 'ERR_NOT_GROUP_ADMIN', "
                "'wording': 'ERR_NOT_GROUP_ADMIN', 'echo': '1'}"
            )
        }
    )
    service, account, context, _ = make_service(protocol)

    with pytest.raises(ActionExecutionError) as caught:
        await service.mute_member(account, "40001", "20002", 90, context=context)

    failure = caught.value.failure
    assert failure is not None
    assert failure.status == "failed"
    assert failure.retcode == 1200
    assert failure.message == "ERR_NOT_GROUP_ADMIN"
    assert failure.wording == "ERR_NOT_GROUP_ADMIN"
    assert service.capability_status("10001", ActionCapability.MEMBER_MUTE) is None

    protocol.responses["guild_member_mute"] = None
    receipt = await service.mute_member(account, "40001", "20002", 90, context=context)
    assert receipt.account_id == "10001"
    assert service.capability_status("10001", ActionCapability.MEMBER_MUTE) is True
    assert len(protocol.calls) == 2


@pytest.mark.parametrize(
    "code",
    ["ERR_NOT_GROUP_ADMIN", "ERR_NOT_GROUP_OWNER", "ERR_NOT_FRIEND"],
)
def test_napcat_permission_error_codes_are_classified(code: str) -> None:
    service, _, _, _ = make_service()
    failure = ActionFailure(
        account_id="10001",
        capability=ActionCapability.MEMBER_MUTE,
        action="set_group_ban",
        status="failed",
        retcode=1200,
        message=code,
        wording=code,
    )

    assert service._is_permission_failure(failure)


def test_permission_failure_clears_stale_learned_capability() -> None:
    service, _, _, _ = make_service()
    service.set_capability("10001", ActionCapability.MEMBER_MUTE, False)
    failure = ActionFailure(
        account_id="10001",
        capability=ActionCapability.MEMBER_MUTE,
        action="set_group_ban",
        status="failed",
        retcode=1200,
        message="ERR_NOT_GROUP_ADMIN",
        wording="ERR_NOT_GROUP_ADMIN",
    )

    service._remember_failure(failure)

    assert service.capability_status("10001", ActionCapability.MEMBER_MUTE) is None


@pytest.mark.asyncio
async def test_permission_failure_does_not_contaminate_another_group() -> None:
    protocol = FakeProtocol(
        responses={
            "guild_member_mute": {
                "status": "failed",
                "retcode": 1200,
                "message": "没有权限",
            }
        }
    )
    service, account, context, _ = make_service(protocol)
    service.registry.bind_group("40002", account)

    with pytest.raises(ActionExecutionError):
        await service.mute_member(account, "40001", "20002", 90, context=context)

    protocol.responses["guild_member_mute"] = None
    other_context = make_context(group_id="40002")
    receipt = await service.mute_member(
        account, "40002", "20002", 90, context=other_context
    )

    assert receipt.account_id == "10001"
    assert service.capability_status("10001", ActionCapability.MEMBER_MUTE) is True
    assert [call[0] for call in protocol.calls] == [
        "guild_member_mute",
        "guild_member_mute",
    ]


@pytest.mark.asyncio
async def test_platform_failed_receipt_latches_capability_unavailable() -> None:
    protocol = FakeProtocol(
        responses={
            "guild_member_mute": {
                "status": "failed",
                "retcode": 1200,
                "data": None,
            }
        }
    )
    service, account, context, _ = make_service(protocol)

    with pytest.raises(ActionExecutionError):
        await service.mute_member(account, "40001", "20002", 90, context=context)

    assert service.capability_status("10001", ActionCapability.MEMBER_MUTE) is False
    with pytest.raises(ActionCapabilityUnavailable):
        await service.mute_member(account, "40001", "20002", 90, context=context)
    assert len(protocol.calls) == 1


@pytest.mark.asyncio
async def test_transient_action_failure_does_not_latch_capability_unavailable() -> None:
    protocol = FakeProtocol(
        responses={"send_message": ConnectionError("connection reset")}
    )
    service, account, context, _ = make_service(
        protocol, role="bot_admin", user_id="20003"
    )

    with pytest.raises(ActionExecutionError):
        await service.send_group_message(account, "40001", "测试", context=context)

    assert (
        service.capability_status("10001", ActionCapability.SEND_GROUP_MESSAGE) is None
    )

    with pytest.raises(ActionExecutionError):
        await service.send_group_message(account, "40001", "测试", context=context)
    assert len(protocol.calls) == 2


@pytest.mark.asyncio
async def test_group_manager_action_falls_back_to_another_admin_account() -> None:
    first_protocol = FakeProtocol(
        responses={
            "guild_member_mute": {
                "status": "failed",
                "retcode": 1200,
                "message": "没有权限",
            }
        }
    )
    second_protocol = FakeProtocol()
    first = FakeAccount("10001", first_protocol)
    second = FakeAccount("10002", second_protocol)
    accounts = AccountRegistry()
    accounts.register(first, groups=["40001"])
    accounts.register(second, groups=["40001"])
    accounts.set_group_permission(second, "40001", Permission.GroupAdmin)
    permissions = PermissionChecker(registry=PermissionRegistry())
    service = ActionService(accounts, permissions)
    context = make_context(account_id="10001")

    receipt = await service.mute_member(first, "40001", "20002", 90, context=context)

    assert receipt.account_id == "10002"
    assert len(first_protocol.calls) == 1
    assert len(second_protocol.calls) == 1
    assert service.capability_status("10001", ActionCapability.MEMBER_MUTE) is None
    assert service.capability_status("10002", ActionCapability.MEMBER_MUTE) is True


@pytest.mark.asyncio
async def test_group_manager_discovers_admin_from_raw_onebot_member_info() -> None:
    first_protocol = FakeProtocol(
        responses={
            "guild_member_mute": {
                "status": "failed",
                "retcode": 1200,
                "message": "没有权限",
            }
        }
    )
    second_protocol = FakeProtocol(responses={"internal": {"role": "admin"}})
    first = FakeAccount("10001", first_protocol)
    second = FakeAccount("10002", second_protocol)
    accounts = AccountRegistry()
    accounts.register(first, groups=["40001"])
    accounts.register(second, groups=["40001"])
    service = ActionService(
        accounts,
        PermissionChecker(registry=PermissionRegistry()),
    )

    receipt = await service.mute_member(
        first,
        "40001",
        "20002",
        90,
        context=make_context(account_id="10001"),
    )

    assert receipt.account_id == "10002"
    assert second_protocol.calls[0] == (
        "internal",
        ("get_group_member_info",),
        {"group_id": 40001, "user_id": 10002},
    )
    assert second_protocol.calls[1][0] == "guild_member_mute"
    assert accounts.group_permission(second, "40001") == Permission.GroupAdmin


@pytest.mark.asyncio
async def test_explicit_capability_override_wins_over_failed_learning() -> None:
    protocol = FakeProtocol(
        responses={
            "guild_member_mute": {
                "status": "failed",
                "retcode": 1200,
                "data": None,
            }
        }
    )
    service, account, context, _ = make_service(
        protocol,
        overrides={"10001": {"member_mute": True}},
    )

    with pytest.raises(ActionExecutionError):
        await service.mute_member(account, "40001", "20002", 90, context=context)
    with pytest.raises(ActionExecutionError):
        await service.mute_member(account, "40001", "20002", 90, context=context)

    assert service.capability_status("10001", "member_mute") is True
    assert len(protocol.calls) == 2


@pytest.mark.asyncio
async def test_send_failure_is_observed_by_account_mute_state_machine() -> None:
    protocol = FakeProtocol(
        responses={
            "send_message": ActionFailed(
                "1200: failed",
                {"status": "failed", "retcode": 1200},
            )
        }
    )
    service, account, context, _ = make_service(
        protocol, role="bot_admin", user_id="20003"
    )

    with pytest.raises(ActionExecutionError):
        await service.send_group_message(account, "40001", "公告", context=context)

    assert service.registry.is_muted("10001", "40001")
    assert service.last_failure is not None
    assert service.last_failure.capability is ActionCapability.SEND_GROUP_MESSAGE


@pytest.mark.asyncio
async def test_successful_group_send_clears_stale_mute_state() -> None:
    service, account, context, _ = make_service(role="bot_admin", user_id="20003")
    service.registry.set_muted(account, "40001", True)

    receipt = await service.send_group_message(
        account, "40001", "恢复测试", context=context
    )

    assert receipt.account_id == account.self_id
    assert not service.registry.is_muted(account, "40001")


@pytest.mark.asyncio
async def test_group_discovery_uses_satori_guild_list() -> None:
    protocol = FakeProtocol(
        responses={
            "guild_list": [
                {"group_id": 40001, "group_name": "one"},
                {"id": "40002", "name": "two"},
            ]
        }
    )
    service, account, _, _ = make_service(protocol)

    assert await service.get_group_list(account) == ("40001", "40002")
    assert protocol.calls == [("guild_list", (), {})]


@pytest.mark.asyncio
async def test_verify_group_membership_uses_standard_guild_get() -> None:
    service, account, _, protocol = make_service(
        FakeProtocol(responses={"guild_get": {"id": "40001"}})
    )

    assert await service.verify_group_membership(account, "40001") is True
    assert protocol.calls == [("guild_get", ("40001",), {})]


@pytest.mark.asyncio
async def test_verify_group_membership_surfaces_failed_group_lookup() -> None:
    protocol = FakeProtocol(
        responses={
            "guild_get": {
                "status": "failed",
                "retcode": 100,
                "message": "not found",
            }
        }
    )
    service, account, _, _ = make_service(protocol)

    with pytest.raises(RuntimeError, match="群信息查询失败"):
        await service.verify_group_membership(account, "40001")


@pytest.mark.asyncio
async def test_permission_and_account_checks_happen_before_protocol_call() -> None:
    service, account, _, protocol = make_service(role="member")

    with pytest.raises(ActionPermissionDenied, match="权限不足"):
        await service.mute_member(
            account,
            "40001",
            "20002",
            90,
            context=make_context(role="member"),
        )
    assert protocol.calls == []

    service.registry.set_available(account, False)
    with pytest.raises(ActionAccountUnavailable):
        await service.mute_member(
            account,
            "40001",
            "20002",
            90,
            context=make_context(),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("duration", [-1, 30 * 24 * 60 * 60 + 1])
async def test_member_mute_rejects_out_of_range_standard_duration(
    duration: int,
) -> None:
    service, account, context, protocol = make_service()

    with pytest.raises(ValueError, match="禁言时长"):
        await service.mute_member(account, "40001", "20002", duration, context=context)
    assert protocol.calls == []
