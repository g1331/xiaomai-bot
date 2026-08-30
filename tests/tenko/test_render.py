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
    finally:
        await service.close()

    assert status_image.startswith(b"\xff\xd8")
    assert markdown_image.startswith(b"\xff\xd8")
