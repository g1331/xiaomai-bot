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
    page = await _get(server.app, "/webui")
    wrong_page = await _get(server.app, "/webui", token="onebot-secret")
    remote_page = await _get(
        server.app,
        "/webui",
        client_host="192.0.2.10",
    )
    allowed = await _get(server.app, "/webui/api/accounts", token="web-secret")
    index = await _get(server.app, "/webui", token="web-secret")
    query_index = await _get(server.app, "/webui?token=web-secret")
    query_api = await _get(server.app, "/webui/api/accounts?token=web-secret")

    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert remote.status_code == 401
    assert page.status_code == 200
    assert wrong_page.status_code == 200
    assert remote_page.status_code == 401
    assert allowed.status_code == 200
    assert index.status_code == 200
    assert query_index.status_code == 200
    assert query_api.status_code == 401
    assert '<input id="token"' in page.text
    assert "application/json" not in page.headers["content-type"]
    assert "Tenko WebUI" in index.text
    assert "Tenko WebUI" in query_index.text
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
                    "response_strategies": [
                        {"group_id": "40001", "strategy": "random"},
                        {"group_id": "40002", "strategy": "random"},
                    ],
                },
                {
                    "id": "10002",
                    "platform": "satori",
                    "online": False,
                    "group_count": 1,
                    "response_strategies": [
                        {"group_id": "40002", "strategy": "random"},
                    ],
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
            "protected": False,
            "loaded": False,
            "enabled": False,
            "maintenance": False,
            "global_enabled": None,
            "groups": {"40001": False, "40002": True},
        },
        {
            "plugin": "global",
            "name": "global",
            "scope": "group",
            "protected": False,
            "loaded": False,
            "enabled": False,
            "maintenance": False,
            "global_enabled": False,
            "groups": {"40001": False, "40002": False},
        },
        {
            "plugin": "maintenance",
            "name": "maintenance",
            "scope": "group",
            "protected": False,
            "loaded": False,
            "enabled": False,
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


@pytest.mark.asyncio
async def test_management_auth_persistence_and_failure_boundaries(
    tenko_database, tmp_path, monkeypatch
):
    from tenko.config import TenkoConfig
    from tenko.connection import OneBotConnection
    from tenko.db.repositories import ManagementRepository, AccountStateRepository
    from tenko.host.account_management import AccountManagement
    from tenko.host.actions import ActionService

    config = TenkoConfig.from_mapping(
        {
            "webui": {
                "enabled": True,
                "token": "reader-secret",
                "admin_token": "admin-secret",
            },
            "onebot": {"access_token": "onebot-secret"},
        }
    )
    accounts = AccountRegistry(AccountStateRepository())
    await accounts.initialize()
    management = AccountManagement(accounts, ActionService(registry=accounts))
    management.repository = ManagementRepository()
    await management.initialize({})
    first = SimpleNamespace(self_id="10001", platform="onebot")
    second = SimpleNamespace(self_id="10001", platform="telegram")
    accounts.register(first, available=True, groups=("40001",))
    accounts.register(second, available=True)
    # 内存 SQLite 共用连接，先完成路由任务，避免测试事务相互回滚。
    await accounts.flush_persistence()
    connection = OneBotConnection(config.onebot)
    service = WebUIService(
        connection.server,
        config.webui,
        accounts=accounts,
        management=management,
        connection=connection,
        tenko_config=config,
        feature_service=FeatureService(),
    )
    transport = httpx.ASGITransport(
        app=connection.server.app, client=("127.0.0.1", 12345)
    )
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        path = "/webui/api/manage/accounts/onebot/10001/disable"
        for headers, code in [
            ({}, 401),
            ({"Authorization": "Bearer reader-secret"}, 403),
            (
                {
                    "Authorization": "Bearer admin-secret",
                    "Origin": "https://evil.invalid",
                },
                403,
            ),
        ]:
            response = await client.post(path, headers=headers, json={"confirm": True})
            assert response.status_code == code
        client.headers["Authorization"] = "Bearer admin-secret"
        assert (await client.post(path, json={"confirm": 1})).status_code == 400
        assert (
            await client.post(
                path, content="x" * 17000, headers={"Content-Type": "application/json"}
            )
        ).status_code == 400
        original = management.repository.save_account

        async def fail(_value):
            raise OSError("secret must not appear in API errors")

        monkeypatch.setattr(management.repository, "save_account", fail)
        failed = await client.post(path, json={"confirm": True})
        assert failed.status_code == 503
        assert "secret must" not in failed.text
        assert accounts.is_available(first)
        monkeypatch.setattr(management.repository, "save_account", original)
        assert (await client.post(path, json={"confirm": True})).status_code == 200
        assert not accounts.is_available(first)
        assert accounts.is_available(second)
        accounts.register(first, available=True)
        assert not accounts.is_available(first)
        assert not management.can_connect("onebot", "10001")
        assert accounts.get(("telegram", "10001")) is second
        rows = (await client.get("/webui/api/manage/accounts")).json()["data"][
            "accounts"
        ]
        assert len(rows) == 2
        assert all("access_token" not in row for row in rows)
        pairing = await client.get("/webui/api/manage/pairing")
        assert "onebot-secret" not in pairing.text
        reveal = await client.post(
            "/webui/api/manage/pairing", json={"action": "reveal"}
        )
        assert reveal.json()["data"]["access_token"] == "onebot-secret"
        assert reveal.headers["cache-control"] == "no-store"
        assert (
            await client.post(
                "/webui/api/manage/settings", json={"default_enabled": False}
            )
        ).status_code == 200
        assert not service.feature_service.default_enabled

    restored = AccountManagement(AccountRegistry(), ActionService())
    restored.repository = ManagementRepository()
    await restored.initialize({})
    restored.accounts.register(first, available=True)
    assert not restored.accounts.is_available(first)
    feature = FeatureService(default_enabled=True)
    await restored.restore_settings(feature, None)
    assert not feature.default_enabled
    await accounts.flush_persistence()


@pytest.mark.asyncio
async def test_pairing_rotation_is_atomic_and_detects_external_config_changes(
    tmp_path, monkeypatch
):
    import tomllib
    from tenko.config import TenkoConfig
    from tenko.connection import OneBotConnection

    path = tmp_path / "tenko.toml"
    original = '[onebot]\naccess_token = "old-secret"\n[webui]\nenabled = true\ntoken = "reader"\nadmin_token = "admin"\n'
    path.write_text(original)
    config = TenkoConfig.load(path)
    connection = OneBotConnection(config.onebot)
    service = WebUIService(
        connection.server, config.webui, connection=connection, tenko_config=config
    )
    transport = httpx.ASGITransport(
        app=connection.server.app, client=("127.0.0.1", 12345)
    )
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        headers={"Authorization": "Bearer admin"},
    ) as client:
        url = "/webui/api/manage/pairing"
        body = {"action": "rotate", "confirm": True}
        path.write_text(original + "# external change\n")
        assert (await client.post(url, json=body)).status_code == 409
        assert connection.adapter.access_token == "old-secret"
        path.write_text(original)
        import tenko.webui.service as webui_module

        replace = webui_module.os.replace

        def fail_replace(*args):
            raise OSError("disk failure")

        monkeypatch.setattr(webui_module.os, "replace", fail_replace)
        assert (await client.post(url, json=body)).status_code == 503
        assert path.read_text() == original
        assert connection.adapter.access_token == "old-secret"
        monkeypatch.setattr(webui_module.os, "replace", replace)
        response = await client.post(url, json=body)
        assert response.status_code == 200, response.text
        token = response.json()["data"]["access_token"]
        assert token != "old-secret" and len(token) >= 32
        assert tomllib.loads(path.read_text())["onebot"]["access_token"] == token
        assert connection.adapter.access_token == token
        assert service.logs.redact(f"old-secret {token}") == "[REDACTED] [REDACTED]"
        assert not list(tmp_path.glob(".tenko-config-*"))


def test_management_logs_redact_credentials_and_restrict_history(tmp_path):
    import gzip
    from tenko.webui.logs import LogReader

    logs = LogReader(lambda: ("private-secret",))
    message = SimpleNamespace(
        record={
            "time": datetime.now(UTC),
            "level": SimpleNamespace(name="INFO"),
            "message": 'private-secret Authorization: Bearer abc token="xyz"',
        }
    )
    logs.sink(message)
    result = logs.live(0, "", "")
    assert result["cursor"] == 1
    assert (
        "private-secret" not in str(result)
        and "abc" not in str(result)
        and "xyz" not in str(result)
    )
    assert not logs.live(1, "", "")["records"]
    (tmp_path / "latest.log").write_text("old\nprivate-secret newest\n")
    (tmp_path / "symlink.log").symlink_to(tmp_path / "latest.log")
    with gzip.open(tmp_path / "rotated.log.gz", "wt") as file:
        file.write('token="xyz"\n')
    assert "symlink.log" not in logs.files(tmp_path)
    assert logs.history(tmp_path, "latest.log", "newest")["lines"] == [
        "[REDACTED] newest"
    ]
    assert "xyz" not in str(logs.history(tmp_path, "rotated.log.gz", ""))
    with pytest.raises(ValueError):
        logs.history(tmp_path, "../latest.log", "")


@pytest.mark.asyncio
async def test_plugin_and_group_switches_use_host_state_and_protect_control_plane(
    repositories, monkeypatch
):
    from unittest.mock import AsyncMock
    from tenko.config import TenkoConfig
    from tenko.connection import OneBotConnection
    from tenko.db.repositories import ManagementRepository
    from tenko.host.account_management import AccountManagement
    from tenko.host.actions import ActionService
    from tenko.host.plugins import PluginRuntime

    config = TenkoConfig.from_mapping(
        {"webui": {"enabled": True, "token": "reader", "admin_token": "admin"}}
    )
    accounts = AccountRegistry()
    accounts.register(
        SimpleNamespace(self_id="10001", platform="onebot"), groups=("40001",)
    )
    features = FeatureService(repositories["feature"])
    await features.initialize()
    management = AccountManagement(accounts, ActionService(registry=accounts))
    management.repository = ManagementRepository()
    await management.initialize({})
    runtime = PluginRuntime()
    state = {"status": True, "updater": True}
    monkeypatch.setattr(runtime, "is_protected", lambda info: info.name == "updater")
    monkeypatch.setattr(runtime, "is_enabled", lambda info: state[info.name])

    async def set_enabled(info, enabled):
        state[info.name] = enabled
        return True

    monkeypatch.setattr(runtime, "set_enabled", set_enabled)
    connection = OneBotConnection(config.onebot)
    service = WebUIService(
        connection.server,
        config.webui,
        accounts=accounts,
        feature_service=features,
        management=management,
        connection=connection,
        plugin_runtime=runtime,
        tenko_config=config,
    )
    transport = httpx.ASGITransport(
        app=connection.server.app, client=("127.0.0.1", 12345)
    )
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        headers={"Authorization": "Bearer admin"},
    ) as client:
        plugin = "/webui/api/manage/plugins/"
        feature = "/webui/api/manage/features/"
        assert (
            await client.post(
                plugin + "updater", json={"enabled": False, "confirm": True}
            )
        ).status_code == 403
        assert (
            await client.post(
                plugin + "missing", json={"enabled": False, "confirm": True}
            )
        ).status_code == 404
        assert (
            await client.post(
                plugin + "status", json={"enabled": False, "confirm": True}
            )
        ).status_code == 200
        assert not state["status"]
        assert await management.repository.setting("disabled-plugins") == ["status"]
        original = management.repository.save_setting
        monkeypatch.setattr(
            management.repository,
            "save_setting",
            AsyncMock(side_effect=OSError("disk full")),
        )
        assert (
            await client.post(
                plugin + "status", json={"enabled": True, "confirm": True}
            )
        ).status_code == 503
        assert not state["status"]
        monkeypatch.setattr(management.repository, "save_setting", original)
        assert (
            await client.post(
                feature + "status", json={"group_id": "unknown", "enabled": False}
            )
        ).status_code == 400
        assert (
            await client.post(
                feature + "status", json={"group_id": "40001", "enabled": False}
            )
        ).status_code == 200
        restored = FeatureService(repositories["feature"])
        await restored.initialize()
        assert not restored.is_enabled("status", "40001")
        assert (
            await client.post(feature + "status", json={"maintenance": True})
        ).status_code == 200
        assert (
            await client.post(
                feature + "status", json={"group_id": "40001", "enabled": True}
            )
        ).status_code == 409
        assert (
            await client.post(feature + "status", json={"maintenance": False})
        ).status_code == 200
        assert (
            await client.post(
                feature + "status", json={"group_id": None, "enabled": True}
            )
        ).status_code == 200
        assert (
            await client.post(
                feature + "status", json={"group_id": None, "enabled": None}
            )
        ).status_code == 200
        assert not features.is_enabled("status", "40001")
        assert service is not None


@pytest.mark.asyncio
async def test_capability_import_is_once_even_after_forgetting_account(tenko_database):
    from tenko.db.repositories import ManagementRepository
    from tenko.host.account_management import AccountManagement
    from tenko.host.actions import ActionService

    preferences = AccountManagement(AccountRegistry(), ActionService())
    preferences.repository = ManagementRepository()
    old = {"10001": {"set_group_ban": False}}
    await preferences.initialize(old)
    assert preferences.preferences[("onebot", "10001")]["capabilities"] == {
        "member_mute": False
    }
    await preferences.forget(("onebot", "10001"))
    await preferences.initialize(old)
    assert not preferences.preferences
