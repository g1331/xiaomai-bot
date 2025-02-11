import os
import textwrap
import time
from enum import Enum
from typing import Optional, Union, Any

import markdown
from playwright.async_api import async_playwright, Browser, Page


class Theme(Enum):
    """Markdown 渲染主题枚举。"""
    LIGHT = "light"
    DARK = "dark"
    SAKURA = "sakura"
    CYBERPUNK = "cyberpunk"
    SEA_BREEZE = "sea_breeze"
    SUNSET_GLOW = "sunset_glow"
    FOREST_GREEN = "forest_green"
    SANDY_BEACH = "sandy_beach"
    MIDNIGHT_PURPLE = "midnight_purple"


class HighlightTheme(Enum):
    """代码高亮主题枚举。"""
    DEFAULT = "default"
    ATOM_ONE_DARK = "atom-one-dark"
    GITHUB = "github"


class OutputMode(Enum):
    """输出模式枚举。"""
    BINARY = "binary"
    LOCAL = "local"


class MarkdownToImageConverter:
    """
    将 Markdown 文本渲染为 PNG 图片的工具，支持 KaTeX 数学公式、代码高亮、任务列表、删除线等语法。
    
    采用 Playwright 渲染页面，通过直接设置 HTML 内容（内联静态资源），避免了临时文件的生成，同时解决浏览器拒绝加载 file:// 本地资源的问题。
    """

    # 本地静态资源相对路径（相对于项目根目录）
    MARKDOWN_THEMES = {
        Theme.LIGHT: "static/css/github-markdown-light.min.css",
        Theme.DARK: "static/css/github-markdown-dark.min.css",
        Theme.SAKURA: "static/css/github-markdown-light.min.css",
        Theme.CYBERPUNK: "static/css/github-markdown-dark.min.css",
        Theme.SEA_BREEZE: "static/css/github-markdown-light.min.css",
        Theme.SUNSET_GLOW: "static/css/github-markdown-light.min.css",
        Theme.FOREST_GREEN: "static/css/github-markdown-light.min.css",
        Theme.SANDY_BEACH: "static/css/github-markdown-light.min.css",
        Theme.MIDNIGHT_PURPLE: "static/css/github-markdown-dark.min.css"
    }

    HIGHLIGHT_THEMES = {
        HighlightTheme.DEFAULT: "static/css/default.min.css",
        HighlightTheme.ATOM_ONE_DARK: "static/css/atom-one-dark.min.css",
        HighlightTheme.GITHUB: "static/css/github.min.css"
    }

    def __init__(self, headless: bool = True, debug: bool = False, browser: Optional[Browser] = None) -> None:
        """
        Args:
            headless: 是否启用无头模式，默认 True。
            debug: 是否启用调试日志，默认 False。
            browser: 可选的外部 Browser 实例。如果提供，将复用该实例创建页面，不关闭浏览器。
        """
        self.headless = headless
        self.debug = debug
        self.playwright = None  # 当内部创建时才有值
        self.browser = browser  # 外部传入的 Browser 实例或 None
        self.page: Optional[Page] = None
        self._external_browser = browser is not None

    async def __aenter__(self) -> "MarkdownToImageConverter":
        if self.browser is None:
            # 启动时传入允许 file 访问的参数（仅在开发/测试环境使用）
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.launch(headless=self.headless)
            self._external_browser = False
            self._log("Playwright 浏览器已启动（内部创建）。")
        else:
            self._log("复用外部传入的 Browser 实例。")
        # 使用当前浏览器创建一个新页面
        self.page = await self.browser.new_page()
        self._log("浏览器页面已创建。")
        return self

    async def __aexit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        # 关闭本次创建的页面
        if self.page:
            await self.page.close()
        # 若是内部创建的浏览器，则需要关闭浏览器和停止 Playwright
        if not self._external_browser:
            if self.browser:
                await self.browser.close()
            if self.playwright:
                await self.playwright.stop()
            self._log("内部创建的 Playwright 浏览器及实例已关闭。")
        else:
            self._log("外部传入的 Browser 实例未关闭。")

    def _log(self, msg: str) -> None:
        """在 debug 模式下输出日志。"""
        if self.debug:
            print("[DEBUG]", msg)

    @classmethod
    def load_resource(cls, relative_path: str) -> str:
        """
        读取静态资源文件内容，用于内联资源。
        """
        base_dir = os.path.dirname(os.path.abspath(__file__))
        abs_path = os.path.join(base_dir, relative_path)
        with open(abs_path, "r", encoding="utf-8") as f:
            return f.read()

    @classmethod
    def generate_html(
            cls,
            md_content: str,
            css: Optional[str] = None,
            theme: Theme = Theme.LIGHT,
            highlight_theme: HighlightTheme = HighlightTheme.ATOM_ONE_DARK
    ) -> str:
        """
        生成包含 KaTeX 自动渲染、代码高亮和自定义 CSS 的 HTML 页面，并将所有静态资源内联到页面中。
        """
        md_content = textwrap.dedent(md_content)
        html_content = markdown.markdown(
            md_content,
            extensions=["extra", "tables", "pymdownx.tasklist", "pymdownx.tilde"],
            extension_configs={
                "pymdownx.tasklist": {"custom_checkbox": True},
                "pymdownx.tilde": {}
            }
        )

        # 内联各类静态资源内容
        md_theme_content = cls.load_resource(cls.MARKDOWN_THEMES[theme])
        hl_theme_content = cls.load_resource(cls.HIGHLIGHT_THEMES[highlight_theme])
        highlight_js_content = cls.load_resource("static/js/highlight.min.js")
        katex_css_content = cls.load_resource("static/css/katex.min.css")
        katex_js_content = cls.load_resource("static/js/katex.min.js")
        katex_auto_content = cls.load_resource("static/js/auto-render.min.js")

        render_script = textwrap.dedent(r"""
        <script>
        document.addEventListener('DOMContentLoaded', function() {
            try {
                renderMathInElement(document.body, {
                    delimiters: [
                        {left: "$$", right: "$$", display: true},
                        {left: "$",  right: "$",  display: false}
                    ]
                });
                document.body.setAttribute("data-katex-done", "true");
                console.log("KaTeX 渲染完成");
            } catch(e) {
                console.error("KaTeX 渲染错误:", e);
                document.body.setAttribute("data-katex-done", "error");
            }
            hljs.highlightAll();
            document.querySelectorAll('pre code').forEach(function(block) {
                var classes = block.className.split(' ');
                var langClass = classes.find(function(c) { return c.indexOf('language-') === 0; });
                if (langClass) {
                    var lang = langClass.replace('language-', '');
                    var label = document.createElement('div');
                    label.textContent = lang;
                    label.style.position = 'absolute';
                    label.style.top = '5px';
                    label.style.left = '5px';
                    label.style.backgroundColor = 'rgba(0, 0, 0, 0.6)';
                    label.style.color = '#fff';
                    label.style.padding = '2px 4px';
                    label.style.fontSize = '12px';
                    label.style.borderRadius = '3px';
                    var pre = block.parentElement;
                    pre.style.position = 'relative';
                    pre.appendChild(label);
                    pre.classList.add('has-lang-label');
                }
            });
        });
        </script>
        """)

        html = textwrap.dedent(f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <!-- Markdown 主题样式（内联） -->
            <style>
            {md_theme_content}
            </style>
            <!-- 代码高亮主题样式（内联） -->
            <style>
            {hl_theme_content}
            </style>
            <!-- KaTeX 样式（内联） -->
            <style>
            {katex_css_content}
            </style>
            <style>
                {cls._custom_styles(theme)}
                {css or ""}
            </style>
            <!-- 内联代码高亮脚本 -->
            <script>
            {highlight_js_content}
            </script>
            <!-- 内联 KaTeX 脚本及自动渲染扩展 -->
            <script>
            {katex_js_content}
            </script>
            <script>
            {katex_auto_content}
            </script>
        </head>
        <body>
            <article class="markdown-body">
                {html_content}
            </article>
            {render_script}
        </body>
        </html>
        """)
        return html

    @staticmethod
    def _custom_styles(theme: Theme) -> str:
        """返回根据主题定制的 CSS 样式。"""
        if theme == Theme.LIGHT:
            bg_color = "#ffffff"
            text_color = "#24292e"
            fallback_pre_bg = "#f0f2f5"
            table_border = "#ddd"
            table_header_bg = "#f6f8fa"
            table_even_bg = "#f9f9f9"
        elif theme == Theme.DARK:
            bg_color = "#12151C"
            text_color = "#C9D1D9"
            fallback_pre_bg = "#3C3F44"
            table_border = "#30363d"
            table_header_bg = "#161b22"
            table_even_bg = "#1e242d"
        elif theme == Theme.SAKURA:
            bg_color = "#fff0f5"
            text_color = "#333333"
            fallback_pre_bg = "#ffeef8"
            table_border = "#f5c6e0"
            table_header_bg = "#ffeaf3"
            table_even_bg = "#ffe4ef"
        elif theme == Theme.CYBERPUNK:
            bg_color = "#0d0d0d"
            text_color = "#dcdcdc"
            fallback_pre_bg = "#3C3E50"
            table_border = "#e94560"
            table_header_bg = "#1a1a2e"
            table_even_bg = "#27293d"
        elif theme == Theme.SEA_BREEZE:
            bg_color = "#dff9fb"
            text_color = "#006064"
            fallback_pre_bg = "#b2ebf2"
            table_border = "#26c6da"
            table_header_bg = "#d0f5f9"
            table_even_bg = "#c3eef3"
        elif theme == Theme.SUNSET_GLOW:
            bg_color = "#FFEBD1"
            text_color = "#6B3C2A"
            fallback_pre_bg = "#FFDAB8"
            table_border = "#FFB385"
            table_header_bg = "#FFE4CA"
            table_even_bg = "#FFDCC2"
        elif theme == Theme.FOREST_GREEN:
            bg_color = "#F1F8F4"
            text_color = "#2E4A3B"
            fallback_pre_bg = "#D0E8D0"
            table_border = "#A1CFA2"
            table_header_bg = "#C5E4CB"
            table_even_bg = "#DAF1DB"
        elif theme == Theme.SANDY_BEACH:
            bg_color = "#FAF2E2"
            text_color = "#5A4B3B"
            fallback_pre_bg = "#EFE2CC"
            table_border = "#D8C9B7"
            table_header_bg = "#F7ECCF"
            table_even_bg = "#F2E4C0"
        elif theme == Theme.MIDNIGHT_PURPLE:
            bg_color = "#1D0B2F"
            text_color = "#E0D6EB"
            fallback_pre_bg = "#44305A"
            table_border = "#7F5DA9"
            table_header_bg = "#2A1740"
            table_even_bg = "#37214F"
        else:
            bg_color = "#ffffff"
            text_color = "#24292e"
            fallback_pre_bg = "#f6f8fa"
            table_border = "#ddd"
            table_header_bg = "#f6f8fa"
            table_even_bg = "#f9f9f9"

        blur_style = textwrap.dedent(f"""
            backdrop-filter: blur(6px);
            -webkit-backdrop-filter: blur(6px);
            background-color: rgba(255, 255, 255, 0.08);
        """)

        return textwrap.dedent(f"""
            html, body {{
                overflow: hidden;
                margin: 0;
                padding: 0;
                background-color: {bg_color};
            }}
            .markdown-body {{
                box-sizing: border-box;
                margin: 0 auto;
                padding: 20px;
                max-width: 980px;
                background-color: {bg_color};
                color: {text_color};
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
            }}
            pre {{
                background: {fallback_pre_bg};
                {blur_style}
                padding: 16px;
                border-radius: 6px;
                overflow-x: auto;
                position: relative;
                color: {text_color};
            }}
            pre.has-lang-label {{
                padding-top: 36px;
            }}
            table {{
                width: 100%;
                border-collapse: collapse;
                margin-bottom: 16px;
            }}
            table th, table td {{
                border: 1px solid {table_border};
                padding: 8px;
                text-align: left;
            }}
            table th {{
                background-color: {table_header_bg};
            }}
            table tr:nth-child(even) {{
                background-color: {table_even_bg};
            }}
            hr {{
                border: 1px solid {table_border};
                margin: 16px 0;
            }}
            ::-webkit-scrollbar {{
                display: none;
            }}
        """)

    async def convert(
            self,
            md_content: str,
            output_path: Optional[str] = None,
            css: Optional[str] = None,
            theme: Theme = Theme.LIGHT,
            highlight_theme: HighlightTheme = HighlightTheme.DEFAULT,
            output_mode: OutputMode = OutputMode.BINARY
    ) -> Union[bytes, str]:
        """
        将 Markdown 文本转换为 PNG 图片（异步执行）。

        Args:
            md_content: Markdown 文本（数学公式需符合 KaTeX 语法）。
            output_path: 当 output_mode=LOCAL 时，指定图片保存路径。
            css: 额外自定义 CSS（可选）。
            theme: Markdown 主题。
            highlight_theme: 代码高亮主题。
            output_mode: 输出模式（BINARY 返回图片二进制数据，LOCAL 返回文件路径）。

        Returns:
            如果 output_mode 为 BINARY，则返回图片二进制数据；
            如果为 LOCAL，则返回图片保存的路径。
        """
        t_total_start = time.perf_counter()

        # 生成 HTML 内容
        html_str = self.generate_html(md_content, css, theme, highlight_theme)
        t_html_done = time.perf_counter()
        self._log(f"生成 HTML 总耗时：{(t_html_done - t_total_start) * 1000:.2f} 毫秒")

        # 直接设置页面内容，无需写入临时文件
        await self.page.set_content(html_str, wait_until="networkidle")
        self._log("页面内容加载完成，等待 '.markdown-body' 元素出现...")
        await self.page.wait_for_selector(".markdown-body", timeout=15000)
        t_load_end = time.perf_counter()
        self._log(f"页面加载及等待耗时：{(t_load_end - t_total_start) * 1000:.2f} 毫秒")

        # 等待 KaTeX 渲染完成（依赖于页面内 JS 设置 data-katex-done 属性）
        t_katex_start = time.perf_counter()
        # 获取当前 KaTeX 渲染状态
        katex_status = await self.page.evaluate("document.body.getAttribute('data-katex-done')")
        self._log(f"当前 KaTeX 渲染状态：{katex_status}")
        if katex_status not in ("true", "error"):
            self._log("等待 KaTeX 渲染完成...")
            await self.page.wait_for_function(
                "['true', 'error'].includes(document.body.getAttribute('data-katex-done'))",
                timeout=15000
            )
            katex_status = await self.page.evaluate("document.body.getAttribute('data-katex-done')")
        if katex_status == "error":
            self._log("警告：KaTeX 渲染出错，截图可能不包含正确的公式。")
        else:
            self._log("KaTeX 渲染完成.")
        t_katex_end = time.perf_counter()
        self._log(f"KaTeX 渲染等待耗时：{(t_katex_end - t_katex_start) * 1000:.2f} 毫秒")

        # 直接截图 .markdown-body 元素
        element = await self.page.query_selector(".markdown-body")
        self._log("开始截图...")
        t_shot_start = time.perf_counter()
        screenshot_data = await element.screenshot(type="png")
        t_shot_end = time.perf_counter()
        self._log(f"截图耗时：{(t_shot_end - t_shot_start) * 1000:.2f} 毫秒")

        t_total_end = time.perf_counter()
        self._log(f"整个转换过程总耗时：{(t_total_end - t_total_start) * 1000:.2f} 毫秒")

        if output_mode == OutputMode.LOCAL:
            if not output_path:
                raise ValueError("当 output_mode=LOCAL 时必须指定 output_path.")
            with open(output_path, "wb") as f:
                f.write(screenshot_data)
            self._log(f"图片已保存到: {output_path}")
            return output_path
        else:
            self._log("返回二进制图片数据.")
            return screenshot_data

    @classmethod
    async def convert_markdown(
            cls,
            md_content: str,
            output_path: Optional[str] = None,
            headless: bool = True,
            css: Optional[str] = None,
            theme: Theme = Theme.LIGHT,
            highlight_theme: HighlightTheme = HighlightTheme.DEFAULT,
            output_mode: OutputMode = OutputMode.BINARY,
            debug: bool = False,
            browser: Optional[Browser] = None  # 新增参数，用于传入外部浏览器实例
    ) -> Union[bytes, str]:
        """
        异步接口，将 Markdown 转换为图片。
        """
        async with cls(headless=headless, debug=debug, browser=browser) as converter:
            return await converter.convert(
                md_content=md_content,
                output_path=output_path,
                css=css,
                theme=theme,
                highlight_theme=highlight_theme,
                output_mode=output_mode
            )
