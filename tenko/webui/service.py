from __future__ import annotations

import inspect
import ipaddress
import secrets
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from launart import Launart, Service
from loguru import logger
from satori.server import Server
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response

from ..config import WebUIConfig
from ..events import MessageMetrics, message_metrics
from ..host.accounts import AccountRegistry, account_registry
from ..host.features import FeatureService, feature_service as default_feature_service
from ..host.plugins import PluginRuntime

WEBUI_PATH = "/webui"
_STATIC_INDEX = Path(__file__).parent / "static" / "index.html"


def _error_response(code: str, message: str, status_code: int) -> JSONResponse:
    return JSONResponse(
        {
            "ok": False,
            "error": {"code": code, "message": message},
        },
        status_code=status_code,
    )


def _success_response(data: object) -> JSONResponse:
    return JSONResponse({"ok": True, "data": data})


def _is_webui_path(path: str) -> bool:
    return path == WEBUI_PATH or path.startswith(f"{WEBUI_PATH}/")


class WebUIAuthMiddleware(BaseHTTPMiddleware):
    """仅保护 `/webui` 路径的独立 IP 和 Bearer token 鉴权。"""

    def __init__(self, app: Any, *, config: WebUIConfig) -> None:
        super().__init__(app)
        self.config = config

    def _allowed_ip(self, request: Request) -> bool:
        client = request.client
        if client is None:
            return False
        try:
            client_ip = str(ipaddress.ip_address(client.host))
        except ValueError:
            return False
        return client_ip in self.config.allowed_ips

    def _authorized(self, request: Request) -> bool:
        authorization = request.headers.get("authorization", "")
        scheme, separator, token = authorization.partition(" ")
        if (
            separator
            and scheme.lower() == "bearer"
            and token
            and self.config.token is not None
        ):
            return secrets.compare_digest(token, self.config.token)

        # 页面导航无法预先设置请求头，仅允许根页面用 query token 启动；
        # API 仍然只接受 Bearer，避免令牌进入 API URL 和访问日志。
        return bool(
            request.method == "GET"
            and request.url.path == WEBUI_PATH
            and self.config.token is not None
            and request.query_params.get("token")
            and secrets.compare_digest(request.query_params["token"], self.config.token)
        )

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if not _is_webui_path(request.url.path):
            return await call_next(request)
        if not self.config.enabled:
            return _error_response("not_found", "Not Found", 404)
        if not self._allowed_ip(request) or not self._authorized(request):
            return _error_response("unauthorized", "Unauthorized", 401)
        return await call_next(request)


class WebUIService(Service):
    """复用 Satori Server app 的 WebUI 路由和只读数据服务。"""

    id = "tenko.webui"
    required = {"satori-python.server"}
    stages = {"preparing", "blocking", "cleanup"}

    def __init__(
        self,
        server: Server,
        config: WebUIConfig,
        *,
        accounts: AccountRegistry = account_registry,
        metrics: MessageMetrics = message_metrics,
        feature_service: FeatureService = default_feature_service,
        feature_repository: Any | None = None,
        plugin_runtime: PluginRuntime | None = None,
    ) -> None:
        super().__init__()
        self.server = server
        self.config = config
        self.accounts = accounts
        self.metrics = metrics
        self.feature_service = feature_service
        self.feature_repository = feature_repository
        self.plugin_runtime = plugin_runtime
        self._register_routes()

    def _register_routes(self) -> None:
        self.server.app.add_middleware(WebUIAuthMiddleware, config=self.config)
        self.server.asgi_route(
            f"{WEBUI_PATH}/api/overview",
            methods=["GET"],
            name="webui-api-overview",
        )(self.overview)
        self.server.asgi_route(
            f"{WEBUI_PATH}/api/accounts",
            methods=["GET"],
            name="webui-api-accounts",
        )(self.accounts_view)
        self.server.asgi_route(
            f"{WEBUI_PATH}/api/features",
            methods=["GET"],
            name="webui-api-features",
        )(self.features_view)
        self.server.asgi_route(
            WEBUI_PATH,
            methods=["GET"],
            name="webui-index",
        )(self.index)
        if self.config.enabled:
            self.server.mount(WEBUI_PATH, _STATIC_INDEX)

    async def _read(
        self,
        operation: str,
        reader: Callable[[], object],
    ) -> JSONResponse:
        try:
            result = reader()
            if inspect.isawaitable(result):
                result = await result
        except Exception as error:
            logger.exception("WebUI {} read failed: {}", operation, error)
            return _error_response(
                f"{operation}_unavailable",
                "WebUI 数据暂不可用",
                500,
            )
        return _success_response(result)

    def _status_data(self) -> Mapping[str, Any]:
        from tenko.plugins.status import build_status_data

        runtime = self.plugin_runtime or PluginRuntime()
        context = SimpleNamespace(chat_type="private", channel_id="")
        return build_status_data(
            context,
            len(runtime.discover()),
            registry=self.accounts,
            metrics=self.metrics,
        )

    @staticmethod
    def _version(status_data: Mapping[str, Any]) -> str:
        for line in status_data.get("version_details", ()):
            if str(line).startswith("版本信息："):
                return str(line).removeprefix("版本信息：v")
        return "unknown"

    def _overview_data(self) -> dict[str, Any]:
        status_data = self._status_data()
        online_bots = str(status_data.get("online_bots", "0/0"))
        online_count, separator, _total_count = online_bots.partition("/")
        if not separator:
            online_count = "0"
        try:
            online_accounts = int(online_count)
        except ValueError:
            online_accounts = 0

        process = status_data["process"]
        metrics = status_data["metrics"]
        return {
            "version": self._version(status_data),
            "uptime_seconds": process["uptime_seconds"],
            "online_accounts": online_accounts,
            "active_groups": status_data["active_groups"],
            "messages": {
                "received_count": metrics["received_count"],
                "sent_count": metrics["sent_count"],
            },
        }

    async def overview(self, request: Request) -> JSONResponse:
        del request
        return await self._read("overview", self._overview_data)

    def _accounts_data(self) -> dict[str, Any]:
        accounts = []
        for account_id, account in self.accounts.accounts.items():
            platform = getattr(account, "platform", None)
            if not platform:
                platform = getattr(
                    getattr(account, "self_info", None), "platform", None
                )
            groups = self.accounts.groups_for_account(account_id)
            response_strategies = [
                {"group_id": group_id, "strategy": strategy}
                for group_id in groups
                if (strategy := self.accounts.response_type_for_group(group_id))
                is not None
            ]
            accounts.append(
                {
                    "id": str(account_id),
                    "platform": str(platform or "unknown"),
                    "online": bool(self.accounts.is_available(account_id)),
                    "group_count": len(groups),
                    "response_strategies": response_strategies,
                }
            )
        return {"accounts": accounts}

    async def accounts_view(self, request: Request) -> JSONResponse:
        del request
        return await self._read("accounts", self._accounts_data)

    def _plugin_infos(self) -> tuple[Any, ...]:
        runtime = self.plugin_runtime or PluginRuntime()
        return tuple(runtime.discover())

    @staticmethod
    def _empty_feature_state() -> dict[str, Any]:
        return {"maintenance": False, "groups": {}}

    def _feature_states_from_records(
        self, records: Iterable[Any]
    ) -> dict[str, dict[str, Any]]:
        states: dict[str, dict[str, Any]] = {}
        for record in records:
            plugin_name = str(record.plugin_name)
            state = states.setdefault(plugin_name, self._empty_feature_state())
            group_id = record.group_id
            if group_id is None:
                state["maintenance"] = bool(record.maintenance)
                if record.enabled is not None:
                    state["global_enabled"] = bool(record.enabled)
            elif record.enabled is not None:
                state["groups"][str(group_id)] = bool(record.enabled)
        return states

    def _feature_states_from_service(self) -> dict[str, dict[str, Any]]:
        states: dict[str, dict[str, Any]] = {}
        for plugin_name, value in self.feature_service.state.items():
            state = self._empty_feature_state()
            state["maintenance"] = bool(value.get("maintenance", False))
            state["groups"] = {
                str(group_id): bool(enabled)
                for group_id, enabled in value.get("groups", {}).items()
            }
            if "global_enabled" in value:
                state["global_enabled"] = bool(value["global_enabled"])
            states[str(plugin_name)] = state
        return states

    async def _features_data(self) -> dict[str, Any]:
        if self.feature_repository is None:
            states = self._feature_states_from_service()
        else:
            records = await self.feature_repository.list_states()
            states = self._feature_states_from_records(records)

        infos = self._plugin_infos()
        plugin_names = [str(getattr(info, "name", info)) for info in infos]
        plugin_names.extend(name for name in states if name not in plugin_names)
        group_ids = list(self.accounts.group_ids)
        for state in states.values():
            for group_id in state["groups"]:
                if group_id not in group_ids:
                    group_ids.append(group_id)

        default_enabled = bool(getattr(self.feature_service, "default_enabled", True))
        if not bool(getattr(self.feature_service, "ready", True)):
            default_enabled = False
        features = []
        for plugin_name in plugin_names:
            state = states.get(plugin_name, self._empty_feature_state())
            metadata_name = plugin_name
            scope = "group"
            info = next(
                (
                    candidate
                    for candidate in infos
                    if str(getattr(candidate, "name", candidate)) == plugin_name
                ),
                None,
            )
            if info is not None:
                metadata_name = str(getattr(info, "display_name", plugin_name))
                scope = self._plugin_scope(info)

            groups = {
                group_id: self._effective_enabled(state, group_id, default_enabled)
                for group_id in group_ids
            }
            features.append(
                {
                    "plugin": plugin_name,
                    "name": metadata_name,
                    "scope": scope,
                    "maintenance": bool(state["maintenance"]),
                    "global_enabled": state.get("global_enabled"),
                    "groups": groups,
                }
            )
        return {"features": features}

    @staticmethod
    def _effective_enabled(
        state: Mapping[str, Any], group_id: str, default_enabled: bool
    ) -> bool:
        if state.get("maintenance"):
            return False
        global_enabled = state.get("global_enabled")
        if global_enabled is not None:
            return bool(global_enabled)
        if group_id in state.get("groups", {}):
            return bool(state["groups"][group_id])
        return default_enabled

    @staticmethod
    def _plugin_scope(info: object) -> str:
        try:
            from arclet.entari.plugin import get_plugins

            lookup_names = set(getattr(info, "lookup_names", ()))
            native = next(
                (
                    plugin
                    for plugin in get_plugins(subplugged=True)
                    if plugin.id in lookup_names
                ),
                None,
            )
        except (AttributeError, TypeError):
            native = None
        return str(getattr(getattr(native, "metadata", None), "feature_scope", "group"))

    async def features_view(self, request: Request) -> JSONResponse:
        del request
        return await self._read("features", self._features_data)

    async def index(self, request: Request) -> FileResponse:
        del request
        return FileResponse(_STATIC_INDEX, media_type="text/html")

    async def launch(self, manager: Launart) -> None:
        async with self.stage("preparing"):
            await self.wait_for_required()
        async with self.stage("blocking"):
            await manager.status.wait_for_sigexit()
        async with self.stage("cleanup"):
            pass


__all__ = [
    "WEBUI_PATH",
    "WebUIAuthMiddleware",
    "WebUIService",
]
