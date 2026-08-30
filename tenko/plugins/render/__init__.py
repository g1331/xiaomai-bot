from __future__ import annotations

from arclet.entari import add_service, plugin
from arclet.entari.plugin import PluginRole

from tenko.render import RenderService


plugin.metadata(
    "图片渲染服务",
    PluginRole.LIBRARY,
    author=["Tenko"],
    version="0.1.0",
    description="提供 Tenko HTML 模板和 Markdown 图片渲染服务。",
    classifier=["service"],
)

_config = plugin.get_config()
# 按当前 .venv-entari 的 Entari 0.18.6 源码确认：add_service() 委托
# get_plugin(1).service()，因此必须在这个插件加载上下文中注册，不能移回宿主。
add_service(
    RenderService(
        enabled=_config.get("enabled", False),
        timeout=_config.get("timeout", 10.0),
        width=_config.get("width", 800),
        quality=_config.get("quality", 90),
        device_scale_factor=_config.get("device_scale_factor", 2),
    )
)

__all__ = ["RenderService"]
