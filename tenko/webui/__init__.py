"""Tenko 内置 WebUI 的服务与配置适配。"""

from .service import WebUIAuthMiddleware, WebUIService

__all__ = ["WebUIAuthMiddleware", "WebUIService"]
