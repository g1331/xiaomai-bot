from __future__ import annotations

import pytest

from tenko.config import TenkoConfig


def test_default_config_is_local_and_does_not_send() -> None:
    config = TenkoConfig()

    assert config.onebot.reverse_ws_url == "ws://127.0.0.1:8080/onebot/v11/ws"
    assert config.runtime.send_replies is False
    assert config.runtime.command_prefix == "/"
    assert config.debug.enabled is False
    assert config.debug.masters == ()


def test_config_loads_reverse_ws_and_runtime_options(tmp_path) -> None:
    path = tmp_path / "tenko.toml"
    path.write_text(
        """
[onebot]
listen_host = "0.0.0.0"
listen_port = 9000
access_token = "secret"
satori_host = "127.0.0.1"

[onebot.capability_overrides."10001"]
member_mute = true
group_essence = false

[runtime]
send_replies = true
reply_text = "收到"
log_level = "DEBUG"
command_prefix = "!"
superusers = { onebot = [12345, "67890"] }

[debug]
enabled = true
masters = [12345, "67890"]
""",
        encoding="utf-8",
    )

    config = TenkoConfig.load(path)

    assert config.onebot.reverse_ws_url == "ws://0.0.0.0:9000/onebot/v11/ws"
    assert config.onebot.access_token == "secret"
    assert config.onebot.satori_client_host == "127.0.0.1"
    assert config.onebot.capability_overrides == {
        "10001": {"member_mute": True, "group_essence": False}
    }
    assert config.runtime.send_replies is True
    assert config.runtime.reply_text == "收到"
    assert config.runtime.log_level == "DEBUG"
    assert config.runtime.command_prefix == "!"
    assert config.runtime.superusers == {
        "onebot": ("12345", "67890"),
    }
    assert config.debug.enabled is True
    assert config.debug.masters == ("12345", "67890")


def test_empty_command_prefix_is_rejected() -> None:
    with pytest.raises(ValueError, match="command_prefix"):
        TenkoConfig.from_mapping({"runtime": {"command_prefix": ""}})


def test_entari_superusers_are_inherited_by_debug_and_upgrade() -> None:
    config = TenkoConfig.from_mapping(
        {
            "entari": {"superusers": {"onebot": [12345], "satori": ["67890"]}},
        }
    )

    assert config.entari.superusers == {
        "onebot": ("12345",),
        "satori": ("67890",),
    }
    assert config.runtime.superusers == config.entari.superusers
    assert config.debug.masters == ("12345", "67890")
    assert config.upgrade.superuser_ids == ("12345", "67890")


def test_explicit_debug_and_upgrade_superusers_override_inheritance() -> None:
    config = TenkoConfig.from_mapping(
        {
            "entari": {"superusers": {"onebot": ["10001"]}},
            "runtime": {"superusers": {"onebot": ["legacy"]}},
            "debug": {"masters": ["20001"]},
            "upgrade": {"superuser_ids": ["30001"]},
        }
    )

    assert config.entari.superusers == {"onebot": ("10001",)}
    assert config.runtime.superusers == config.entari.superusers
    assert config.debug.masters == ("20001",)
    assert config.upgrade.superuser_ids == ("30001",)
