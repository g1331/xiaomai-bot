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
except ImportError:  # pragma: no cover - 依赖项单独声明
    Environment = FileSystemLoader = StrictUndefined = select_autoescape = None

try:
    from markdown_it import MarkdownIt
except ImportError:  # pragma: no cover - 依赖项单独声明
    MarkdownIt = None

try:
    from playwright.async_api import async_playwright
except ImportError:  # pragma: no cover - 运行时可选渲染
    async_playwright = None


class RenderError(RuntimeError):
    """模板或浏览器渲染失败的基础错误。"""


class RenderUnavailableError(RenderError):
    """浏览器无法启动时抛出。"""


class RenderTimeoutError(RenderError):
    """单次渲染操作超过配置的超时时间时抛出。"""


_TEMPLATE_DIR = Path(__file__).with_name("templates")


class RenderService(Service):
    """使用一个共享的 Chromium 浏览器渲染 Tenko 模板。

    浏览器会在 Launart 的 preparing 阶段启动。``render_template`` 也会按需启动
    浏览器，使该服务在没有 manager 的隔离测试和小型宿主集成中仍可使用。每个
    请求都会创建新的浏览器上下文，并在请求返回前关闭。
    """

    id = "tenko.render"
    required = set()
    stages = {"preparing", "blocking", "cleanup"}

    def __init__(
        self,
        *,
        timeout: float = 10.0,
        width: int = 800,
        quality: int = 90,
        device_scale_factor: int = 2,
        max_concurrency: int = 2,
        template_dir: str | Path | None = None,
    ) -> None:
        super().__init__()
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
        """返回此服务当前是否持有可用浏览器。"""

        return self.browser is not None

    def _get_start_lock(self) -> asyncio.Lock:
        if self._start_lock is None:
            self._start_lock = asyncio.Lock()
        return self._start_lock

    def _get_render_semaphore(self) -> asyncio.Semaphore:
        if self._render_semaphore is None:
            self._render_semaphore = asyncio.Semaphore(self.max_concurrency)
        return self._render_semaphore

    async def start(self) -> bool:
        """启动共享的 Playwright 浏览器，并返回其是否已就绪。"""

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

    @staticmethod
    def _is_driver_dead(error: Exception) -> bool:
        text = str(error)
        return (
            "connection closed" in text.lower()
            or "target closed" in text.lower()
            or "driver" in text.lower()
            and "closed" in text.lower()
        )

    async def close(self) -> None:
        """关闭此服务持有的 Chromium 和 Playwright driver。"""

        browser = self.browser
        playwright = self._playwright
        self.browser = None
        self._playwright = None

        if browser is not None:
            try:
                await browser.close()
            except Exception as error:
                # 宿主退出时 Playwright driver 可能已被先行终止，此时浏览器进程
                # 会随驱动一同消失，关闭 RPC 失败属预期，不作为故障记录。
                if self._is_driver_dead(error):
                    logger.debug("Playwright driver 已先于浏览器关闭，跳过 close RPC")
                else:
                    logger.exception("关闭 RenderService Chromium 失败")
        if playwright is not None:
            try:
                await playwright.stop()
            except Exception:
                logger.exception("关闭 RenderService Playwright 失败")

    async def launch(self, manager: Launart) -> None:
        """将浏览器启动和清理接入宿主生命周期。"""

        async with self.stage("preparing"):
            try:
                await self.start()
            except RenderError as error:
                # 渲染是可选的输出增强功能。缺少浏览器不能阻止消息宿主启动。
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
            if self.browser is None:  # pragma: no cover - 由 start() 负责保护
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
        """将指定的 HTML 模板渲染为整页 JPEG 缓冲区。"""

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
        """将 Markdown 转换为 HTML，并使用报告模板渲染。"""

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
    """执行渲染操作，并将所有普通失败转换为 ``None``。

    ``service`` 参数被刻意显式传入，以便调用方使用 Entari 注入的服务，而不是
    进程级渲染器。``None`` 仅保留给明确没有注入服务的工具函数或单元测试调用方。
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
