from __future__ import annotations

import asyncio
import inspect
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from launart import Launart, Service
from loguru import logger

try:
    from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape
except ImportError:  # pragma: no cover - dependencies are declared separately
    Environment = FileSystemLoader = StrictUndefined = select_autoescape = None

try:
    from markdown_it import MarkdownIt
except ImportError:  # pragma: no cover - dependencies are declared separately
    MarkdownIt = None

try:
    from playwright.async_api import async_playwright
except ImportError:  # pragma: no cover - rendering is optional at runtime
    async_playwright = None


class RenderError(RuntimeError):
    """Base error for template or browser rendering failures."""


class RenderUnavailableError(RenderError):
    """Raised when rendering is disabled or the browser cannot be started."""


class RenderTimeoutError(RenderError):
    """Raised when one rendering operation exceeds its configured timeout."""


_TEMPLATE_DIR = Path(__file__).with_name("templates")


class RenderService(Service):
    """Render Tenko templates with one shared Chromium browser.

    The browser is started during Launart's preparing phase when the service is
    enabled. ``render_template`` also starts it lazily so the service remains
    useful in isolated tests and small host integrations without a manager.
    Each request gets a fresh browser context, which is closed before the
    request returns.
    """

    id = "tenko.render"
    required = set()
    stages = {"preparing", "blocking", "cleanup"}

    def __init__(
        self,
        *,
        enabled: bool = False,
        timeout: float = 10.0,
        width: int = 800,
        quality: int = 90,
        device_scale_factor: int = 2,
        max_concurrency: int = 2,
        template_dir: str | Path | None = None,
    ) -> None:
        super().__init__()
        if type(enabled) is not bool:
            raise TypeError("render enabled 必须是布尔值")
        if isinstance(timeout, bool) or not isinstance(timeout, int | float):
            raise TypeError("render timeout 必须是数字")
        if timeout <= 0:
            raise ValueError("render timeout 必须大于 0")
        if type(width) is not int or width <= 0:
            raise ValueError("render width 必须是正整数")
        if type(quality) is not int or not 0 <= quality <= 100:
            raise ValueError("render quality 必须是 0 到 100 的整数")
        if type(max_concurrency) is not int or max_concurrency <= 0:
            raise ValueError("render max_concurrency 必须是正整数")
        if type(device_scale_factor) is not int or device_scale_factor <= 0:
            raise ValueError("render device_scale_factor 必须是正整数")

        self.enabled = enabled
        self.timeout = float(timeout)
        self.width = width
        self.quality = quality
        self.device_scale_factor = device_scale_factor
        self.max_concurrency = max_concurrency
        self.template_dir = (
            Path(template_dir) if template_dir is not None else _TEMPLATE_DIR
        )
        self.browser: Any | None = None
        self._playwright: Any | None = None
        self._template_environment: Any | None = None
        self._start_lock: asyncio.Lock | None = None
        self._render_semaphore: asyncio.Semaphore | None = None
        self._startup_error: Exception | None = None

    @property
    def available(self) -> bool:
        """Whether a usable browser is currently held by this service."""

        return self.enabled and self.browser is not None

    def _get_start_lock(self) -> asyncio.Lock:
        if self._start_lock is None:
            self._start_lock = asyncio.Lock()
        return self._start_lock

    def _get_render_semaphore(self) -> asyncio.Semaphore:
        if self._render_semaphore is None:
            self._render_semaphore = asyncio.Semaphore(self.max_concurrency)
        return self._render_semaphore

    async def start(self) -> bool:
        """Start the shared Playwright browser, returning whether it is ready."""

        if not self.enabled:
            return False
        if self.browser is not None:
            return True
        if self._startup_error is not None:
            raise RenderUnavailableError("Chromium 不可用") from self._startup_error
        if async_playwright is None:
            error = ImportError("playwright 未安装")
            self._startup_error = error
            raise RenderUnavailableError("Playwright 未安装") from error

        async with self._get_start_lock():
            if self.browser is not None:
                return True
            if self._startup_error is not None:
                raise RenderUnavailableError("Chromium 不可用") from self._startup_error

            playwright = None
            try:
                playwright = await async_playwright().start()
                browser = await playwright.chromium.launch()
            except asyncio.CancelledError:
                if playwright is not None:
                    try:
                        await playwright.stop()
                    except Exception:
                        logger.exception(
                            "取消启动 RenderService 时清理 Playwright 失败"
                        )
                raise
            except Exception as error:
                self._startup_error = error
                if playwright is not None:
                    try:
                        await playwright.stop()
                    except Exception:
                        logger.exception("启动 Chromium 失败后的 Playwright 清理失败")
                raise RenderUnavailableError("Chromium 启动失败") from error

            self._playwright = playwright
            self.browser = browser
            return True

    async def close(self) -> None:
        """Close Chromium and the Playwright driver held by this service."""

        browser = self.browser
        playwright = self._playwright
        self.browser = None
        self._playwright = None

        if browser is not None:
            try:
                await browser.close()
            except Exception:
                logger.exception("关闭 RenderService Chromium 失败")
        if playwright is not None:
            try:
                await playwright.stop()
            except Exception:
                logger.exception("关闭 RenderService Playwright 失败")

    async def launch(self, manager: Launart) -> None:
        """Integrate browser startup and cleanup into the host lifecycle."""

        async with self.stage("preparing"):
            if self.enabled:
                try:
                    await self.start()
                except RenderError as error:
                    # Rendering is an optional output enhancement. A missing
                    # browser must not prevent the message host from starting.
                    logger.warning("图片渲染不可用，将使用文本回退：{}", error)

        async with self.stage("blocking"):
            await manager.status.wait_for_sigexit()

        async with self.stage("cleanup"):
            await self.close()

    def _template_name(self, template_name: str) -> str:
        if not isinstance(template_name, str) or not template_name:
            raise RenderError("模板名称必须是非空字符串")
        if "\x00" in template_name:
            raise RenderError("模板名称包含非法字符")

        template_root = self.template_dir.resolve()
        candidate = (template_root / template_name).resolve()
        try:
            relative = candidate.relative_to(template_root)
        except ValueError as error:
            raise RenderError("模板路径必须位于 tenko/templates 目录内") from error
        if not relative.parts or relative.suffix.lower() != ".html":
            raise RenderError("模板名称必须指向 HTML 文件")
        return relative.as_posix()

    def _get_template_environment(self) -> Any:
        if self._template_environment is not None:
            return self._template_environment
        if Environment is None:
            raise RenderUnavailableError("Jinja2 未安装")

        self._template_environment = Environment(
            loader=FileSystemLoader(str(self.template_dir.resolve())),
            autoescape=select_autoescape(["html", "xml"]),
            undefined=StrictUndefined,
        )
        return self._template_environment

    def _render_html(self, template_name: str, context: Mapping[str, object]) -> str:
        if not isinstance(context, Mapping):
            raise RenderError("渲染上下文必须是 mapping")
        safe_name = self._template_name(template_name)
        try:
            template = self._get_template_environment().get_template(safe_name)
            return template.render(**dict(context))
        except RenderError:
            raise
        except Exception as error:
            raise RenderError(f"模板渲染失败：{safe_name}") from error

    async def _render_html_to_image(
        self, template_name: str, context: Mapping[str, object]
    ) -> bytes:
        async with self._get_render_semaphore():
            html = self._render_html(template_name, context)
            await self.start()
            if self.browser is None:  # pragma: no cover - guarded by start()
                raise RenderUnavailableError("Chromium 不可用")

            browser_context = None
            try:
                browser_context = await self.browser.new_context(
                    viewport={"width": self.width, "height": 800},
                    device_scale_factor=self.device_scale_factor,
                )
                page = await browser_context.new_page()
                await page.set_content(html, wait_until="load")
                image = await page.screenshot(
                    full_page=True,
                    type="jpeg",
                    quality=self.quality,
                )
                if not image:
                    raise RenderError("Chromium 返回空截图")
                return bytes(image)
            finally:
                if browser_context is not None:
                    await browser_context.close()

    async def render_template(
        self, template_name: str, context: dict[str, object]
    ) -> bytes:
        """Render a named HTML template into a full-page JPEG buffer."""

        if not self.enabled:
            raise RenderUnavailableError("图片渲染未启用")
        try:
            image = await asyncio.wait_for(
                self._render_html_to_image(template_name, context),
                timeout=self.timeout,
            )
        except asyncio.CancelledError:
            raise
        except asyncio.TimeoutError as error:
            raise RenderTimeoutError(
                f"渲染超时（限制 {self.timeout:g} 秒）：{template_name}"
            ) from error
        except RenderError:
            raise
        except Exception as error:
            raise RenderError(f"图片渲染失败：{template_name}") from error
        if not isinstance(image, bytes) or not image:
            raise RenderError(f"图片渲染返回无效结果：{template_name}")
        return image

    async def render_markdown(
        self, md_text: str, template_name: str = "markdown.html"
    ) -> bytes:
        """Convert Markdown to HTML and render it with the report template."""

        if not isinstance(md_text, str):
            raise RenderError("Markdown 内容必须是字符串")
        try:
            image = await asyncio.wait_for(
                self._render_markdown(md_text, template_name), timeout=self.timeout
            )
        except asyncio.CancelledError:
            raise
        except asyncio.TimeoutError as error:
            raise RenderTimeoutError(
                f"Markdown 渲染超时（限制 {self.timeout:g} 秒）"
            ) from error
        except RenderError:
            raise
        except Exception as error:
            raise RenderError("Markdown 渲染失败") from error
        if not isinstance(image, bytes) or not image:
            raise RenderError("Markdown 渲染返回无效结果")
        return image

    async def _render_markdown(self, md_text: str, template_name: str) -> bytes:
        if MarkdownIt is None:
            raise RenderUnavailableError("markdown-it-py 未安装")
        try:
            markdown_html = self._markdown_to_html(md_text)
        except Exception as error:
            raise RenderError("Markdown 转 HTML 失败") from error
        return await self.render_template(
            template_name,
            {
                "content": markdown_html,
                "markdown_html": markdown_html,
                "source": md_text,
            },
        )

    @staticmethod
    def _highlight_code(code: str, lang: str, _attrs: str) -> str | None:
        """Pygments 代码高亮；按源码确认 markdown-it-py 会把返回值包进
        <pre><code>，故用 nowrap=True 只输出带内联样式的 span。"""
        if not lang:
            return None
        try:
            from pygments import highlight as pygments_highlight
            from pygments.formatters import HtmlFormatter
            from pygments.lexers import get_lexer_by_name
            from pygments.util import ClassNotFound
        except ImportError:
            return None
        try:
            lexer = get_lexer_by_name(lang, stripall=False)
        except ClassNotFound:
            return None
        # one-dark：深底调色板，与 markdown.html 代码块深色底 #1E3A52 匹配；
        # bg 属性单独关闭背景输出，避免覆盖模板自身的底色和圆角。
        formatter = HtmlFormatter(
            style="one-dark", noclasses=True, nowrap=True, nobackground=True
        )
        return pygments_highlight(code, lexer, formatter)

    def _markdown_to_html(self, md_text: str) -> str:
        md = MarkdownIt(
            "commonmark",
            {"html": False, "highlight": self._highlight_code},
        ).enable("table")
        return md.render(md_text)


async def render_or_none(
    service: RenderService | None,
    method_name: str,
    *args: Any,
    **kwargs: Any,
) -> bytes | None:
    """Run a render operation and turn every ordinary failure into ``None``.

    ``service`` is deliberately explicit so callers use Entari's injected
    service rather than a process-wide renderer. ``None`` is reserved for
    utility or unit-test callers that explicitly have no injected service.
    """

    if service is None or not isinstance(method_name, str):
        return None
    target: Any = getattr(service, method_name, None)

    if not callable(target):
        return None

    try:
        result = target(*args, **kwargs)
        if inspect.isawaitable(result):
            result = await result
    except asyncio.CancelledError:
        raise
    except Exception as error:
        logger.warning("图片渲染失败，回退文本输出：{}", error)
        return None

    if isinstance(result, bytes) and result:
        return result
    if result is not None:
        logger.warning("图片渲染返回空或非 bytes 结果，回退文本输出")
    return None


__all__ = [
    "RenderError",
    "RenderService",
    "RenderTimeoutError",
    "RenderUnavailableError",
    "render_or_none",
]
