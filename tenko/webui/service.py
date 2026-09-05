from __future__ import annotations

import asyncio
import copy
import inspect
import json
import os
import tempfile
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

from ..config import WebUIConfig, TenkoConfig
from ..db.errors import DatabaseError
from ..host.account_management import AccountManagement
from .logs import LogReader
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
        headers={"Cache-Control": "no-store"},
    )


def _success_response(data: object) -> JSONResponse:
    return JSONResponse(
        {"ok": True, "data": data}, headers={"Cache-Control": "no-store"}
    )


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

    def _role(self, request: Request) -> str | None:
        scheme, separator, token = request.headers.get("authorization", "").partition(
            " "
        )
        if not separator or scheme.lower() != "bearer" or not token:
            return None
        for role, expected in (
            ("admin", self.config.admin_token),
            ("reader", self.config.token),
        ):
            if expected and secrets.compare_digest(token.encode(), expected.encode()):
                return role
        return None

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await self._dispatch(request, call_next)
        if _is_webui_path(request.url.path) and request.method not in {"GET", "HEAD"}:
            logger.info(
                "WebUI audit: method={} target={} action={} source={} status={}",
                request.method,
                json.dumps(request.url.path[:300], ensure_ascii=False),
                getattr(request.state, "webui_action", "request"),
                request.client.host if request.client else "unknown",
                response.status_code,
            )
        return response

    async def _dispatch(self, request: Request, call_next: Callable) -> Response:
        path = request.url.path
        if not _is_webui_path(path):
            return await call_next(request)
        if not self.config.enabled:
            return _error_response("not_found", "Not Found", 404)
        if not self._allowed_ip(request):
            return _error_response("unauthorized", "Unauthorized", 401)
        if request.method == "GET" and path in {WEBUI_PATH, f"{WEBUI_PATH}/"}:
            return await call_next(request)
        role = self._role(request)
        if role is None:
            return _error_response("unauthorized", "Unauthorized", 401)
        request.state.webui_role = role
        administrative = path.startswith(f"{WEBUI_PATH}/api/manage/")
        if administrative and role != "admin":
            return _error_response("forbidden", "需要独立管理令牌", 403)
        if request.method not in {"GET", "HEAD"}:
            if role != "admin":
                return _error_response("forbidden", "需要独立管理令牌", 403)
            origin = request.headers.get("origin")
            expected = f"{request.url.scheme}://{request.url.netloc}"
            if origin is not None and origin != expected:
                return _error_response("forbidden", "不允许跨来源管理操作", 403)
            if (
                request.headers.get("content-type", "").split(";")[0].strip()
                != "application/json"
            ):
                return _error_response("invalid_request", "请使用 JSON 请求体", 415)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response


class WebUIService(Service):
    """复用 Satori Server app 的管理面板；写操作独立授权。"""

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
        management: AccountManagement | None = None,
        connection: Any | None = None,
        tenko_config: TenkoConfig | None = None,
    ) -> None:
        super().__init__()
        self.server = server
        self.config = config
        self.accounts = accounts
        self.metrics = metrics
        self.feature_service = feature_service
        self.feature_repository = feature_repository
        self.plugin_runtime = plugin_runtime
        self.management = management
        self.connection = connection
        self.tenko_config = tenko_config
        self._write_lock = management.lock if management is not None else asyncio.Lock()
        self.logs = LogReader(self._secrets)
        self._log_sink: int | None = None
        self._retired_tokens: list[str] = []
        native = tenko_config.entari_config if tenko_config else None
        self._config_path = Path(native.path) if native is not None else None
        self._config_stamp = self._stamp()
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
        routes = (
            ("/api/session", ["GET"], self.session),
            ("/api/manage/accounts", ["GET"], self.managed_accounts),
            (
                "/api/manage/accounts/{platform}/{account_id}/{action}",
                ["POST"],
                self.manage_account,
            ),
            ("/api/manage/pairing", ["GET", "POST"], self.pairing),
            ("/api/manage/plugins/{plugin}", ["POST"], self.manage_plugin),
            ("/api/manage/features/{plugin}", ["POST"], self.manage_feature),
            ("/api/manage/settings", ["GET", "POST"], self.settings),
            ("/api/manage/logs", ["GET"], self.log_view),
        )
        for path, methods, handler in routes:
            self.server.asgi_route(f"{WEBUI_PATH}{path}", methods=methods)(handler)
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
                    "id": str(account.self_id),
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
                    "protected": bool(
                        info is not None
                        and self.plugin_runtime is not None
                        and getattr(
                            self.plugin_runtime, "is_protected", lambda _: False
                        )(info)
                    ),
                    "loaded": bool(
                        info is not None
                        and self.plugin_runtime is not None
                        and getattr(self.plugin_runtime, "is_loaded", lambda _: False)(
                            info
                        )
                    ),
                    "enabled": bool(
                        info is not None
                        and self.plugin_runtime is not None
                        and getattr(self.plugin_runtime, "is_enabled", lambda _: False)(
                            info
                        )
                    ),
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

    def _stamp(self):
        if self._config_path is None or not self._config_path.is_file():
            return None
        import hashlib

        return hashlib.sha256(self._config_path.read_bytes()).digest()

    def _secrets(self) -> tuple[str, ...]:
        values = [self.config.token, self.config.admin_token, *self._retired_tokens]
        if self.tenko_config is not None:
            values.extend(
                (
                    self.tenko_config.onebot.access_token,
                    self.tenko_config.onebot.satori_token,
                )
            )
        if self.connection is not None:
            values.append(self.connection.adapter.access_token)
        return tuple(value for value in values if isinstance(value, str) and value)

    async def session(self, request: Request) -> JSONResponse:
        return _success_response(
            {
                "role": request.state.webui_role,
                "management_configured": bool(self.config.admin_token),
            }
        )

    async def _body(self, request: Request) -> dict[str, Any]:
        data = bytearray()
        async for chunk in request.stream():
            if len(data) + len(chunk) > 16384:
                raise ValueError("请求体不能超过 16 KiB")
            data.extend(chunk)
        try:
            value = json.loads(data)
        except (ValueError, UnicodeDecodeError) as error:
            raise ValueError("请求体必须是有效 JSON") from error
        if not isinstance(value, dict):
            raise ValueError("请求体必须是 JSON 对象")
        return value

    async def _manage(self, request: Request, operation: Callable) -> JSONResponse:
        try:
            async with self._write_lock:
                value = await operation()
        except ValueError as error:
            return _error_response("invalid_request", str(error), 400)
        except KeyError:
            return _error_response("not_found", "操作目标不存在", 404)
        except PermissionError as error:
            return _error_response("forbidden", str(error), 403)
        except DatabaseError:
            logger.error("WebUI database operation failed: {}", request.url.path)
            return _error_response(
                "database_unavailable", "数据库暂不可用，未确认保存成功", 503
            )
        except RuntimeError as error:
            return _error_response("conflict", str(error), 409)
        except Exception as error:
            # 凭据读写边界禁止记录请求体或异常 locals。
            logger.error(
                "WebUI operation failed: {} ({})",
                request.url.path,
                type(error).__name__,
            )
            return _error_response(
                "operation_failed", "操作失败，请检查宿主日志；未确认保存成功", 503
            )
        return _success_response(value)

    def _management(self) -> AccountManagement:
        if (
            self.management is None
            or not self.management.ready
            or self.management.repository is None
        ):
            raise RuntimeError("管理数据库尚未就绪")
        return self.management

    async def managed_accounts(self, request: Request) -> JSONResponse:
        async def read():
            management = self._management()
            rows = management.list_accounts()
            for row in rows:
                key = (row["platform"], row["id"])
                account = self.accounts.get(key)
                row.update(
                    online=self.accounts.is_online(key),
                    available=self.accounts.is_available(key),
                    group_count=len(self.accounts.groups_for_account(key)),
                    groups=list(self.accounts.groups_for_account(key)),
                    connected=bool(
                        self.connection
                        and key[0] == "onebot"
                        and key[1] in self.connection.adapter.connections
                    ),
                    name=str(
                        getattr(getattr(account, "self_info", None), "user", None).name
                        or row["id"]
                    )
                    if getattr(getattr(account, "self_info", None), "user", None)
                    else row["id"],
                    manageable=key[0] == "onebot",
                )
            from ..host.actions import ActionCapability

            return {
                "accounts": rows,
                "capabilities": [item.value for item in ActionCapability],
            }

        return await self._manage(request, read)

    async def manage_account(self, request: Request) -> JSONResponse:
        async def change():
            management = self._management()
            platform, identifier, action = (
                request.path_params[name]
                for name in ("platform", "account_id", "action")
            )
            if any(
                not value or len(value) > 128 or any(ord(c) < 32 for c in value)
                for value in (platform, identifier)
            ):
                raise ValueError("平台和账户 ID 必须是 1–128 字的有效标识")
            key = (platform, identifier)
            if not management.contains(key):
                raise KeyError(key)
            if platform != "onebot" or self.connection is None:
                raise RuntimeError("当前协议适配器尚未提供账户管理能力")
            body = await self._body(request)
            if action == "preferences":
                if set(body) - {"alias", "capabilities"}:
                    raise ValueError("仅支持别名和能力覆盖")
                await management.update(key, body)
            elif action in {"enable", "disable", "kick", "forget"}:
                if set(body) != {"confirm"} or body["confirm"] is not True:
                    raise ValueError("请确认账户操作")
                if action == "forget":
                    if (
                        identifier in self.connection.adapter.connections
                        or self.accounts.is_online(key)
                    ):
                        raise RuntimeError(
                            "账户仍连接中，请先停用或在协议端断开，再移除记录"
                        )
                    await management.forget(key)
                elif action == "kick":
                    if not await self.connection.adapter.disconnect(identifier):
                        raise RuntimeError("账户当前没有连接")
                else:
                    await management.update(key, {"enabled": action == "enable"})
                    if action == "disable":
                        await self.connection.adapter.disconnect(identifier)
            else:
                raise ValueError("未知账户操作")
            return {"action": action, "platform": platform, "id": identifier}

        return await self._manage(request, change)

    def _pairing_data(self) -> dict[str, Any]:
        if self.connection is None or self.tenko_config is None:
            raise RuntimeError("协议连接未配置")
        config = self.tenko_config.onebot
        return {
            "url": config.reverse_ws_url,
            "path": config.reverse_ws_path_value,
            "requires_host": config.listen_host in {"0.0.0.0", "::"},
            "token_configured": bool(self.connection.adapter.access_token),
            "can_rotate": self._config_stamp is not None,
        }

    def _rotate_token(self) -> str:
        import tomllib

        if self._config_path is None or self._config_stamp is None:
            raise RuntimeError("没有可写回的配置文件")
        if self._config_path.suffix != ".toml":
            raise RuntimeError("令牌轮换仅支持当前项目的 TOML 配置")
        if self._stamp() != self._config_stamp:
            raise RuntimeError("配置文件已被外部修改，请重启加载后再轮换")
        raw = tomllib.loads(self._config_path.read_text())
        value = raw.get("onebot", {}).get("access_token", "")
        if isinstance(value, str) and "${" in value:
            raise RuntimeError("OneBot token 由环境变量提供，请在配置来源中轮换")
        token = secrets.token_urlsafe(32)
        native = copy.deepcopy(self.tenko_config.entari_config)
        native.data.setdefault("onebot", {})["access_token"] = token
        descriptor, name = tempfile.mkstemp(
            prefix=".tenko-config-", suffix=".toml", dir=self._config_path.parent
        )
        os.close(descriptor)
        temporary = Path(name)
        try:
            native.save(temporary)
            parsed = tomllib.loads(temporary.read_text())
            if parsed.get("onebot", {}).get("access_token") != token:
                raise RuntimeError("配置保存未生成预期令牌")
            TenkoConfig.from_mapping(parsed)
            with temporary.open("rb") as stream:
                os.fsync(stream.fileno())
            if self._stamp() != self._config_stamp:
                raise RuntimeError("配置文件发生并发修改，请重试")
            os.replace(temporary, self._config_path)
        finally:
            temporary.unlink(missing_ok=True)
        self._config_stamp = self._stamp()
        self.tenko_config.entari_config.data.setdefault("onebot", {})[
            "access_token"
        ] = token
        self.tenko_config.entari_config.save_flag = True
        previous = self.connection.adapter.access_token
        if previous:
            self._retired_tokens.append(previous)
        self.connection.adapter.access_token = token
        return token

    async def pairing(self, request: Request) -> JSONResponse:
        async def action():
            data = self._pairing_data()
            if request.method == "GET":
                return data
            body = await self._body(request)
            if body == {"action": "reveal"}:
                request.state.webui_action = "reveal"
                data["access_token"] = self.connection.adapter.access_token or ""
            elif (
                set(body) == {"action", "confirm"}
                and body["action"] == "rotate"
                and body["confirm"] is True
            ):
                request.state.webui_action = "rotate"
                data["access_token"] = self._rotate_token()
                data["token_configured"] = True
            else:
                raise ValueError("请选择显示凭据，或确认轮换令牌")
            return data

        return await self._manage(request, action)

    def _plugin(self, name: str):
        if self.plugin_runtime is None:
            raise RuntimeError("插件运行时尚未就绪")
        info = next(
            (info for info in self.plugin_runtime.discover() if info.name == name), None
        )
        if info is None:
            raise KeyError(name)
        if self.plugin_runtime.is_protected(info):
            raise PermissionError("控制平面插件不能通过面板停用或修改开关")
        return info

    async def manage_plugin(self, request: Request) -> JSONResponse:
        async def change():
            repository = self._management().repository
            info = self._plugin(request.path_params["plugin"])
            body = await self._body(request)
            if (
                set(body) != {"enabled", "confirm"}
                or type(body["enabled"]) is not bool
                or body["confirm"] is not True
            ):
                raise ValueError("请确认插件启停操作")
            before = self.plugin_runtime.is_enabled(info)
            enabled = body["enabled"]
            request.state.webui_action = "enable" if enabled else "disable"
            disabled = set(await repository.setting("disabled-plugins") or [])
            if enabled:
                disabled.discard(info.name)
            else:
                disabled.add(info.name)
            if not await self.plugin_runtime.set_enabled(info, enabled):
                raise RuntimeError("插件当前未加载，无法切换状态")
            try:
                await repository.save_setting("disabled-plugins", sorted(disabled))
            except Exception:
                await self.plugin_runtime.set_enabled(info, before)
                raise
            return {"plugin": info.name, "enabled": enabled}

        return await self._manage(request, change)

    async def manage_feature(self, request: Request) -> JSONResponse:
        async def change():
            self._management()
            if not self.feature_service.ready:
                raise RuntimeError("功能状态尚未就绪")
            info = self._plugin(request.path_params["plugin"])
            body = await self._body(request)
            if set(body) == {"maintenance"} and type(body["maintenance"]) is bool:
                self.feature_service.set_maintenance(info.name, body["maintenance"])
            elif set(body) == {"group_id", "enabled"} and body["group_id"] is None:
                if body["enabled"] is None:
                    self.feature_service.reset_global(info.name)
                elif type(body["enabled"]) is bool:
                    self.feature_service.set_global_enabled(info.name, body["enabled"])
                else:
                    raise ValueError("全局开关必须为布尔值或 null")
            else:
                if (
                    set(body) != {"group_id", "enabled"}
                    or type(body["enabled"]) is not bool
                ):
                    raise ValueError("必须指定群 ID 与布尔开关值")
                if self._plugin_scope(info) == "global":
                    raise ValueError("此插件使用全局开关")
                group_id = body["group_id"]
                if (
                    not isinstance(group_id, str)
                    or group_id not in self.accounts.group_ids
                ):
                    raise ValueError("群 ID 不在已知路由中")
                state = self.feature_service.state.get(info.name, {})
                if state.get("maintenance") or "global_enabled" in state:
                    raise RuntimeError("请先在插件页解除维护或全局覆盖，再修改群级开关")
                self.feature_service.set_enabled(info.name, group_id, body["enabled"])
            await self.feature_service.persist_state()
            return {
                "plugin": info.name,
                "state": dict(self.feature_service.state.get(info.name, {})),
            }

        return await self._manage(request, change)

    async def settings(self, request: Request) -> JSONResponse:
        async def action():
            repository = self._management().repository
            if request.method == "POST":
                body = await self._body(request)
                if (
                    set(body) != {"default_enabled"}
                    or type(body["default_enabled"]) is not bool
                ):
                    raise ValueError("default_enabled 必须是布尔值")
                await repository.save_setting(
                    "feature-default", body["default_enabled"]
                )
                self.feature_service.default_enabled = body["default_enabled"]
            return {
                "default_enabled": self.feature_service.default_enabled,
                "stored": await repository.setting("feature-default") is not None,
            }

        return await self._manage(request, action)

    def _log_directory(self) -> Path | None:
        if self.tenko_config is None or self.tenko_config.basic.log.save is None:
            return None
        from arclet.entari.localdata import local_data

        return local_data._get_base_log_dir()

    async def log_view(self, request: Request) -> JSONResponse:
        async def read():
            params = request.query_params
            query = params.get("q", "")
            if len(query) > 200:
                raise ValueError("搜索词不能超过 200 字")
            directory = self._log_directory()
            name = params.get("file")
            if name:
                data = await asyncio.to_thread(
                    self.logs.history, directory, name, query
                )
            else:
                after = int(params.get("after", "0"))
                if after < 0:
                    raise ValueError("日志游标不能为负数")
                data = self.logs.live(after, query, params.get("level", ""))
            data["files"] = await asyncio.to_thread(self.logs.files, directory)
            data["history_enabled"] = directory is not None
            return data

        # 高频只读日志不产生审计日志，避免轮询形成递归日志流。
        return await self._manage(request, read)

    async def index(self, request: Request) -> FileResponse:
        del request
        return FileResponse(
            _STATIC_INDEX,
            media_type="text/html",
            headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
        )

    async def launch(self, manager: Launart) -> None:
        async with self.stage("preparing"):
            await self.wait_for_required()
            self._log_sink = logger.add(
                self.logs.sink, level="INFO", format="{message}"
            )
        async with self.stage("blocking"):
            await manager.status.wait_for_sigexit()
        async with self.stage("cleanup"):
            if self._log_sink is not None:
                logger.remove(self._log_sink)
                self._log_sink = None


__all__ = [
    "WEBUI_PATH",
    "WebUIAuthMiddleware",
    "WebUIService",
]
