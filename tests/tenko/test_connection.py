from __future__ import annotations

from tenko.config import OneBotConfig
from tenko.connection import OneBotConnection


def test_ipv6_client_endpoint_is_valid_url() -> None:
    connection = OneBotConnection(OneBotConfig(listen_host="::1"))

    assert str(connection.client_config.ws_base) == "ws://[::1]:8080/satori/v1"
