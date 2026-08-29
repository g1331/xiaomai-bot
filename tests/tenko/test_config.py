from __future__ import annotations

from tenko.config import TenkoConfig


def test_default_config_is_local_and_does_not_send() -> None:
    config = TenkoConfig()

    assert config.onebot.reverse_ws_url == "ws://127.0.0.1:8080/onebot/v11/ws"
    assert config.runtime.send_replies is False


def test_config_loads_reverse_ws_and_runtime_options(tmp_path) -> None:
    path = tmp_path / "tenko.toml"
    path.write_text(
        """
[onebot]
listen_host = "0.0.0.0"
listen_port = 9000
access_token = "secret"
satori_host = "127.0.0.1"

[runtime]
send_replies = true
reply_text = "收到"
log_level = "DEBUG"
""",
        encoding="utf-8",
    )

    config = TenkoConfig.load(path)

    assert config.onebot.reverse_ws_url == "ws://0.0.0.0:9000/onebot/v11/ws"
    assert config.onebot.access_token == "secret"
    assert config.onebot.satori_client_host == "127.0.0.1"
    assert config.runtime.send_replies is True
    assert config.runtime.reply_text == "收到"
    assert config.runtime.log_level == "DEBUG"
