from __future__ import annotations

import asyncio

import pytest

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

    assert await render_or_none(disabled, "status.html", {"content": "text"}) is None
    assert await render_or_none(None, "status.html", {}) is None

    unavailable = RenderService(enabled=True)
    unavailable._startup_error = RuntimeError("browser missing")
    assert (
        await render_or_none(
            unavailable.render_template, "status.html", {"content": "text"}
        )
        is None
    )


@pytest.mark.asyncio
async def test_render_timeout_falls_back_to_none(monkeypatch) -> None:
    service = RenderService(enabled=True, timeout=0.01)

    async def slow_render(*args, **kwargs):
        await asyncio.sleep(1)

    monkeypatch.setattr(service, "_render_html_to_image", slow_render)

    assert (
        await render_or_none(
            service.render_template, "status.html", {"content": "slow"}
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
            "status.html", {"title": "Status", "content": "rendered status"}
        )
        markdown_image = await service.render_markdown("# Report\n\nrendered")
    finally:
        await service.close()

    assert status_image.startswith(b"\xff\xd8")
    assert markdown_image.startswith(b"\xff\xd8")
