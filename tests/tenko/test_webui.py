from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest
from satori.server import Server

from tenko.config import WebUIConfig
from tenko.events import MessageMetrics
from tenko.host.accounts import AccountRegistry
from tenko.host.features import FeatureService
from tenko.webui import WebUIService


async def _get(
    app,
    path: str,
    *,
    token: str | None = None,
    client_host: str = "127.0.0.1",
) -> httpx.Response:
    headers = {} if token is None else {"Authorization": f"Bearer {token}"}
    transport = httpx.ASGITransport(app=app, client=(client_host, 12345))
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        return await client.get(path, headers=headers)


def _service(
    config: WebUIConfig,
    *,
    accounts: AccountRegistry | None = None,
    metrics: MessageMetrics | None = None,
    feature_service: FeatureService | None = None,
    feature_repository=None,
    plugin_runtime=None,
) -> tuple[Server, WebUIService]:
    server = Server(host="127.0.0.1", port=0)
    service = WebUIService(
        server,
        config,
        accounts=accounts if accounts is not None else AccountRegistry(),
        metrics=metrics if metrics is not None else MessageMetrics(),
        feature_service=(
            feature_service if feature_service is not None else FeatureService()
        ),
        feature_repository=feature_repository,
        plugin_runtime=plugin_runtime,
    )
    return server, service


@pytest.mark.asyncio
async def test_webui_auth_allows_configured_local_token_and_rejects_other_sources():
    server, service = _service(WebUIConfig(enabled=True, token="web-secret"))

    assert service.required == {"satori-python.server"}
    assert "/webui" in server.resources

    missing = await _get(server.app, "/webui/api/accounts")
    wrong = await _get(server.app, "/webui/api/accounts", token="onebot-secret")
    remote = await _get(
        server.app,
        "/webui/api/accounts",
        token="web-secret",
        client_host="192.0.2.10",
    )
    allowed = await _get(server.app, "/webui/api/accounts", token="web-secret")
    index = await _get(server.app, "/webui", token="web-secret")

    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert remote.status_code == 401
    assert allowed.status_code == 200
    assert index.status_code == 200
    assert "Tenko WebUI" in index.text
    assert allowed.json() == {"ok": True, "data": {"accounts": []}}
    assert missing.json() == {
        "ok": False,
        "error": {"code": "unauthorized", "message": "Unauthorized"},
    }


@pytest.mark.asyncio
async def test_webui_disabled_returns_not_found_for_root_and_api():
    server, _service_instance = _service(WebUIConfig())

    root = await _get(server.app, "/webui")
    api = await _get(server.app, "/webui/api/overview")

    assert root.status_code == 404
    assert api.status_code == 404
    assert root.json() == {
        "ok": False,
        "error": {"code": "not_found", "message": "Not Found"},
    }
    assert api.json() == root.json()


@pytest.mark.asyncio
async def test_webui_read_only_apis_expose_safe_account_and_feature_data():
    accounts = AccountRegistry()
    first = SimpleNamespace(self_id="10001", platform="onebot")
    second = SimpleNamespace(self_id="10002", platform="satori")
    accounts.register(first, available=True, groups=("40001", "40002"))
    accounts.register(second, available=False, groups=("40002",))

    class FeatureRepository:
        async def list_states(self):
            return (
                SimpleNamespace(
                    plugin_name="demo",
                    group_id="40001",
                    enabled=False,
                    maintenance=False,
                ),
                SimpleNamespace(
                    plugin_name="global",
                    group_id=None,
                    enabled=False,
                    maintenance=False,
                ),
                SimpleNamespace(
                    plugin_name="maintenance",
                    group_id=None,
                    enabled=None,
                    maintenance=True,
                ),
            )

    plugin_info = SimpleNamespace(name="demo", display_name="演示插件", lookup_names=())
    plugin_runtime = SimpleNamespace(discover=lambda: (plugin_info,))
    server, _service_instance = _service(
        WebUIConfig(enabled=True, token="web-secret"),
        accounts=accounts,
        feature_service=FeatureService(default_enabled=True),
        feature_repository=FeatureRepository(),
        plugin_runtime=plugin_runtime,
    )

    account_response = await _get(server.app, "/webui/api/accounts", token="web-secret")
    feature_response = await _get(server.app, "/webui/api/features", token="web-secret")

    assert account_response.status_code == 200
    assert account_response.json() == {
        "ok": True,
        "data": {
            "accounts": [
                {
                    "id": "10001",
                    "platform": "onebot",
                    "online": True,
                    "group_count": 2,
                },
                {
                    "id": "10002",
                    "platform": "satori",
                    "online": False,
                    "group_count": 1,
                },
            ]
        },
    }
    features = feature_response.json()["data"]["features"]
    assert features == [
        {
            "plugin": "demo",
            "name": "演示插件",
            "scope": "group",
            "maintenance": False,
            "global_enabled": None,
            "groups": {"40001": False, "40002": True},
        },
        {
            "plugin": "global",
            "name": "global",
            "scope": "group",
            "maintenance": False,
            "global_enabled": False,
            "groups": {"40001": False, "40002": False},
        },
        {
            "plugin": "maintenance",
            "name": "maintenance",
            "scope": "group",
            "maintenance": True,
            "global_enabled": None,
            "groups": {"40001": False, "40002": False},
        },
    ]
    assert "web-secret" not in account_response.text + feature_response.text
    assert "access_token" not in account_response.text + feature_response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("loaded_plugin", ["status"], indirect=True)
async def test_webui_overview_uses_status_data_metrics_and_counts(
    loaded_plugin, monkeypatch
):
    status = loaded_plugin
    accounts = AccountRegistry()
    accounts.register(
        SimpleNamespace(self_id="10001", platform="onebot"),
        available=True,
        groups=("40001", "40002"),
    )
    accounts.register(
        SimpleNamespace(self_id="10002", platform="onebot"),
        available=False,
        groups=("40002",),
    )
    metrics = MessageMetrics()
    metrics._received_count = 17
    metrics._sent_count = 5
    process = status.ProcessInfo(
        start_time=datetime(2026, 9, 1, tzinfo=UTC),
        uptime_seconds=42.5,
        rss=None,
    )
    resources = status.SystemResources(0, 0, 1, 0, 0, 1, 0, 0, 0)
    version_details = ("版本信息：v9.8.7",)
    monkeypatch.setattr(status, "collect_process_info", lambda: process)
    monkeypatch.setattr(status, "collect_system_resources", lambda: resources)
    monkeypatch.setattr(status, "get_version_details", lambda: version_details)
    plugin_runtime = SimpleNamespace(discover=lambda: (object(),))
    server, _service_instance = _service(
        WebUIConfig(enabled=True, token="web-secret"),
        accounts=accounts,
        metrics=metrics,
        plugin_runtime=plugin_runtime,
    )

    response = await _get(server.app, "/webui/api/overview", token="web-secret")
    expected_status = status.build_status_data(
        SimpleNamespace(chat_type="private", channel_id=""),
        1,
        registry=accounts,
        metrics=metrics,
    )

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "data": {
            "version": "9.8.7",
            "uptime_seconds": expected_status["process"]["uptime_seconds"],
            "online_accounts": 1,
            "active_groups": expected_status["active_groups"],
            "messages": {
                "received_count": expected_status["metrics"]["received_count"],
                "sent_count": expected_status["metrics"]["sent_count"],
            },
        },
    }
