from __future__ import annotations

import asyncio

import pytest
from arclet.entari.plugin import get_plugins

from tenko.config import RenderConfig, TenkoConfig
from tenko.render import (
    RenderService,
    RenderTimeoutError,
    RenderUnavailableError,
    render_or_none,
)


def test_render_config_defaults_and_mapping() -> None:
    config = TenkoConfig.from_mapping(
        {"render": {"enabled": True, "timeout": 4.5, "width": 1024, "quality": 90}}
    ).render

    assert config == RenderConfig(enabled=True, timeout=4.5, width=1024, quality=90)
    assert TenkoConfig().render == RenderConfig()


@pytest.mark.parametrize(
    "field, value",
    [("timeout", 0), ("width", 0), ("quality", 101)],
)
def test_render_config_rejects_invalid_values(field: str, value: int) -> None:
    with pytest.raises(ValueError):
        RenderConfig(**{field: value})


@pytest.mark.asyncio
async def test_render_or_none_returns_none_when_disabled_or_unavailable() -> None:
    disabled = RenderService()

    assert (
        await render_or_none(
            disabled,
            "render_template",
            "status.html",
            {"content": "text"},
        )
        is None
    )
    # Direct unit tests bypass Entari's listener injector, so absence is passed
    # explicitly instead of being resolved through a module-level fallback.
    assert await render_or_none(None, "render_template", "status.html", {}) is None

    unavailable = RenderService(enabled=True)
    unavailable._startup_error = RuntimeError("browser missing")
    assert (
        await render_or_none(
            unavailable,
            "render_template",
            "status.html",
            {"content": "text"},
        )
        is None
    )


@pytest.mark.parametrize("loaded_plugin", ["render"], indirect=True)
def test_render_plugin_registers_service_with_entari(loaded_plugin) -> None:
    native_plugin = next(
        plugin
        for plugin in get_plugins(subplugged=True)
        if plugin.id == "tenko.plugins.render"
    )

    service = native_plugin._services["tenko.render"]
    assert isinstance(service, loaded_plugin.RenderService)
    assert service.enabled is False
    assert service.timeout == 10.0
    assert service.width == 800
    assert service.quality == 85


@pytest.mark.asyncio
async def test_render_timeout_falls_back_to_none(monkeypatch) -> None:
    service = RenderService(enabled=True, timeout=0.01)

    async def slow_render(*args, **kwargs):
        await asyncio.sleep(1)

    monkeypatch.setattr(service, "_render_html_to_image", slow_render)

    assert (
        await render_or_none(
            service,
            "render_template",
            "status.html",
            {"content": "slow"},
        )
        is None
    )

    with pytest.raises(RenderTimeoutError):
        await service.render_template("status.html", {"content": "slow"})


@pytest.mark.asyncio
@pytest.mark.integration
async def test_placeholder_templates_render_to_jpeg() -> None:
    service = RenderService(enabled=True)
    try:
        try:
            await service.start()
        except RenderUnavailableError as error:
            pytest.skip(str(error))

        status_image = await service.render_template(
            "status.html",
            {
                "title": "Status",
                "content": "rendered status",
                "lines": (),
                "plugin_count": 0,
                "chat_type": "private",
                "detailed": False,
                "current_group_mute": None,
                "project_address": None,
                "version_details": (),
                "metrics": {
                    "received_count": 0,
                    "sent_count": 0,
                    "received_rate": "0条/m",
                    "sent_rate": "0条/m",
                },
                "process": {
                    "start_time": "2026-08-30 00:00:00",
                    "uptime": "0秒",
                    "rss_display": None,
                },
                "resources": None,
            },
        )
        markdown_image = await service.render_markdown("# Report\n\nrendered")
        help_image = await service.render_template(
            "help.html",
            {
                "title": "Tenko 已注册命令",
                "subtitle": "按插件状态整理可用功能",
                "usage": "/帮助 [编号] 查看单项命令详情",
                "group_id": "40001",
                "sections": (
                    {
                        "key": "required",
                        "title": "内置插件",
                        "subtitle": "系统必需功能",
                        "count": 1,
                        "items": (
                            {
                                "number": 1,
                                "name": "帮助系统",
                                "plugin": "helper",
                                "description": "生成分区帮助列表。",
                                "state": "required",
                                "state_label": "内置",
                            },
                        ),
                    },
                    {
                        "key": "available",
                        "title": "运行插件",
                        "subtitle": "当前可用功能",
                        "count": 1,
                        "items": (
                            {
                                "number": 2,
                                "name": "状态查询",
                                "plugin": "status",
                                "description": "查询 Tenko 运行状态。",
                                "state": "available",
                                "state_label": "运行中",
                            },
                        ),
                    },
                    {
                        "key": "unavailable",
                        "title": "维护插件",
                        "subtitle": "暂不可用功能",
                        "count": 0,
                        "items": (),
                    },
                ),
                "required": (),
                "available": (),
                "unavailable": (),
                "total": 2,
                "enabled_count": 2,
            },
        )
        list_image = await service.render_template(
            "list.html",
            {
                "title": "权限列表",
                "subtitle": "群40001 · 成员权限",
                "badge": "群 40001",
                "summary": "群40001权限等级: 1",
                "item_count": 1,
                "items": (
                    {
                        "number": 1,
                        "name": "30001",
                        "meta": "权限等级：32",
                        "detail": "群40001成员权限",
                        "badge": "32",
                    },
                ),
                "empty_text": "暂无额外权限成员",
            },
        )
    finally:
        await service.close()

    assert status_image.startswith(b"\xff\xd8")
    assert markdown_image.startswith(b"\xff\xd8")
    assert help_image.startswith(b"\xff\xd8")
    assert list_image.startswith(b"\xff\xd8")
