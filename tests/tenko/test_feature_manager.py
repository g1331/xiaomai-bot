from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest
from arclet.entari.command import Match
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

from tenko.host.features import FeatureService
from tenko.host.perm import PermissionChecker, PermissionRegistry


def make_session(user_id: str = "20001", role: str = "admin"):
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
    return SimpleNamespace(event=SimpleNamespace(_origin=event))


@pytest.mark.parametrize("loaded_plugin", ["feature_manager"], indirect=True)
def test_feature_commands_keep_legacy_prefixed_aliases(loaded_plugin) -> None:
    assert loaded_plugin.enable_command.parse("/-开启 1").matched
    assert loaded_plugin.disable_command.parse("/-关闭 1").matched
    assert not loaded_plugin.enable_command.parse("-开启 1").matched
    assert not loaded_plugin.disable_command.parse("-关闭 1").matched


@pytest.mark.asyncio
@pytest.mark.parametrize("loaded_plugin", ["feature_manager"], indirect=True)
async def test_feature_commands_persist_group_switch_and_restore(
    loaded_plugin, tmp_path, monkeypatch
) -> None:
    service = FeatureService(tmp_path / "features.json")
    monkeypatch.setattr(loaded_plugin, "feature_service", service)
    loaded_plugin.permission_checker = PermissionChecker(registry=PermissionRegistry())
    session = make_session()

    disabled = await loaded_plugin.disable.callable_target(
        session, Match("announcement", True)
    )

    assert disabled.extract_plain_text() == "功能<announcement>已关闭~"
    assert not service.is_enabled("announcement", "40001")
    assert not FeatureService(tmp_path / "features.json").is_enabled(
        "announcement", "40001"
    )

    enabled = await loaded_plugin.enable.callable_target(
        session, Match("announcement", True)
    )

    assert enabled.extract_plain_text() == "功能<announcement>已开启~"
    assert FeatureService(tmp_path / "features.json").is_enabled(
        "announcement", "40001"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("loaded_plugin", ["feature_manager"], indirect=True)
async def test_feature_commands_cannot_disable_required_host_plugin(loaded_plugin):
    loaded_plugin.permission_checker = PermissionChecker(registry=PermissionRegistry())

    result = await loaded_plugin.disable.callable_target(
        make_session(), Match("feature_manager", True)
    )

    assert result.extract_plain_text() == "无法操作必须插件<功能开关>"
