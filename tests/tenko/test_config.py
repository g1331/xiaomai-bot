from __future__ import annotations

from pathlib import Path

import pytest
from arclet.entari.config import EntariConfig as NativeEntariConfig
from arclet.entari.config.model import BasicConfig, LogSaveInfo

from tenko.config import TenkoConfig, WebUIConfig


def test_default_config_is_local_and_does_not_send() -> None:
    config = TenkoConfig()

    assert isinstance(config.basic, BasicConfig)
    assert config.basic.prefix == ["/"]
    assert config.basic.log.save is None
    assert config.onebot.reverse_ws_url == "ws://127.0.0.1:8080/onebot/v11/ws"
    assert config.runtime.command_prefix == "/"
    assert config.debug.enabled is False
    assert config.debug.masters == ()
    assert config.exception.message_buffer_size == 10
    assert config.exception.evidence_dir == ".tenko/exceptions"
    assert config.database.url == "sqlite+aiosqlite:///./.tenko/tenko.db"
    assert config.database.create_table_at == "preparing"
    assert config.webui == WebUIConfig()
    assert config.webui.token is None
    assert "web-secret" not in repr(WebUIConfig(enabled=True, token="web-secret"))
    assert config.upgrade.restart_watch_timeout == 300
    assert config.notify_group is None


def test_config_loads_reverse_ws_and_runtime_options(tmp_path) -> None:
    path = tmp_path / "tenko.toml"
    path.write_text(
        """
notify_group = 40001

[onebot]
listen_host = "0.0.0.0"
listen_port = 9000
access_token = "secret"
satori_host = "127.0.0.1"

[onebot.capability_overrides."10001"]
member_mute = true
group_essence = false

[runtime]
log_level = "DEBUG"
command_prefix = "!"
superusers = { onebot = [12345, "67890"] }

[debug]
enabled = true
masters = [12345, "67890"]

[database]
url = "sqlite+aiosqlite:///tmp/tenko.db"
echo = true
create_table_at = "prepared"
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
    assert config.basic.prefix == ["!"]
    assert config.basic.log.level == "DEBUG"
    assert "entari" not in config.entari_config.data
    assert "runtime" not in config.entari_config.data
    assert config.runtime.log_level == "DEBUG"
    assert config.runtime.command_prefix == "!"
    assert config.runtime.superusers == {
        "onebot": ("12345", "67890"),
    }
    assert config.debug.enabled is True
    assert config.debug.masters == ("12345", "67890")
    assert config.notify_group == "40001"
    assert config.database.url == "sqlite+aiosqlite:///tmp/tenko.db"
    assert config.database.echo is True
    assert config.database.create_table_at == "prepared"


def test_config_loads_notify_group_key(tmp_path) -> None:
    path = tmp_path / "tenko.toml"
    path.write_text("notify_group = 40002\n", encoding="utf-8")

    config = TenkoConfig.load(path)

    assert config.notify_group == "40002"


def test_config_loads_official_basic_and_tenko_sections_together(tmp_path) -> None:
    path = tmp_path / "tenko.toml"
    path.write_text(
        """
[basic]
prefix = ["/", "!"]
ignore_self_message = false
skip_req_missing = true
superusers = { onebot = [12345, "67890"] }

[basic.log]
level = "WARNING"
ignores = ["tenko.noisy"]
save = { rotation = "10 MB", compression = "gz", colorize = false }

[[basic.network]]
type = "ws"
host = "127.0.0.1"
port = 5140
path = "satori"
token = "placeholder"

[onebot]
listen_port = 9000

[debug]
enabled = true
""",
        encoding="utf-8",
    )

    config = TenkoConfig.load(path)

    assert isinstance(config.basic, BasicConfig)
    assert config.basic.prefix == ["/", "!"]
    assert config.basic.ignore_self_message is False
    assert config.basic.skip_req_missing is True
    assert config.basic.superusers == {"onebot": ["12345", "67890"]}
    assert config.basic.log.level == "WARNING"
    assert config.basic.log.ignores == ["tenko.noisy"]
    assert config.basic.log.save == LogSaveInfo(
        rotation="10 MB", compression="gz", colorize=False
    )
    assert config.basic.network[0].type == "ws"
    assert config.basic.network[0].port == 5140
    assert config.onebot.listen_port == 9000
    assert config.runtime.log_level == "WARNING"
    assert config.runtime.command_prefix == "/"
    assert config.runtime.superusers == {"onebot": ("12345", "67890")}
    assert config.debug.masters == ("12345", "67890")
    assert config.entari_config is NativeEntariConfig.instance


def test_config_example_is_loadable_with_official_basic_section(tmp_path) -> None:
    example = Path(__file__).parents[2] / "config/tenko.toml.example"
    path = tmp_path / "tenko.toml"
    path.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
    config = TenkoConfig.load(path)

    assert config.basic.prefix == ["/"]
    assert config.basic.log.save is None
    assert config.entari.superusers == {"onebot": ("YOUR_QQ_ID",)}
    assert config.notify_group is None


def test_config_ignores_removed_notify_group_alias() -> None:
    config = TenkoConfig.from_mapping({"test_group": "40001"})

    assert config.notify_group is None


def test_entari_save_preserves_tenko_sections_and_writes_toml(tmp_path) -> None:
    path = tmp_path / "tenko.toml"
    path.write_text(
        """
[basic]
prefix = ["/"]

[onebot]
listen_port = 9001
""",
        encoding="utf-8",
    )

    config = TenkoConfig.load(path)
    config.entari_config.data["basic"]["log"] = {
        "level": "INFO",
        "save": {"rotation": "00:00", "compression": "gz", "colorize": False},
    }
    config.entari_config.save()

    saved = TenkoConfig.load(path)
    assert saved.onebot.listen_port == 9001
    assert saved.basic.log.save == LogSaveInfo(
        rotation="00:00", compression="gz", colorize=False
    )
    assert saved.entari_config.data["onebot"]["listen_port"] == 9001


def test_empty_command_prefix_is_rejected() -> None:
    with pytest.raises(ValueError, match="command_prefix"):
        TenkoConfig.from_mapping({"runtime": {"command_prefix": ""}})


def test_official_basic_takes_precedence_over_legacy_sections() -> None:
    config = TenkoConfig.from_mapping(
        {
            "basic": {
                "prefix": ["!"],
                "log": {"level": "WARNING"},
                "superusers": {"onebot": ["official"]},
            },
            "runtime": {
                "command_prefix": "/",
                "log_level": "DEBUG",
                "superusers": {"onebot": ["legacy"]},
            },
            "entari": {"superusers": {"onebot": ["old-entari"]}},
        }
    )

    assert config.basic.prefix == ["!"]
    assert config.basic.log.level == "WARNING"
    assert config.runtime.command_prefix == "!"
    assert config.runtime.log_level == "WARNING"
    assert config.runtime.superusers == {"onebot": ("official",)}


def test_exception_evidence_configuration_is_loaded_and_validated() -> None:
    config = TenkoConfig.from_mapping(
        {
            "exception": {
                "message_buffer_size": 32,
                "evidence_dir": ".tenko/test-exceptions",
            }
        }
    )

    assert config.exception.message_buffer_size == 32
    assert config.exception.evidence_dir == ".tenko/test-exceptions"
    with pytest.raises(ValueError, match="message_buffer_size"):
        TenkoConfig.from_mapping({"exception": {"message_buffer_size": 0}})


def test_database_configuration_rejects_unknown_table_creation_stage() -> None:
    with pytest.raises(ValueError, match="create_table_at"):
        TenkoConfig.from_mapping({"database": {"create_table_at": "later"}})


def test_webui_configuration_requires_independent_token_when_enabled() -> None:
    config = TenkoConfig.from_mapping(
        {
            "onebot": {"access_token": "onebot-secret"},
            "webui": {
                "enabled": True,
                "token": "web-secret",
                "allowed_ips": ["127.0.0.1", "::1"],
            },
        }
    )

    assert config.onebot.access_token == "onebot-secret"
    assert config.webui.enabled is True
    assert config.webui.token == "web-secret"
    assert config.webui.allowed_ips == ("127.0.0.1", "::1")
    with pytest.raises(ValueError, match="独立 token"):
        TenkoConfig.from_mapping({"webui": {"enabled": True}})
    with pytest.raises(ValueError, match="非法 IP"):
        TenkoConfig.from_mapping({"webui": {"allowed_ips": ["localhost"]}})


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
