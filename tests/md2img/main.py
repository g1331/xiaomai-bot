import asyncio
import os
import tempfile
import textwrap
import base64
import time
from enum import Enum
from typing import Optional, Union, Any, List, Tuple
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import markdown


class Theme(Enum):
    """Markdown 渲染主题枚举。

    Args:
        LIGHT: 浅色主题。
        DARK: 深色主题。
        SAKURA: 樱花主题。
        CYBERPUNK: 赛博朋克主题。
        SEA_BREEZE: 海风主题。
        SUNSET_GLOW: 日落余晖主题。
        FOREST_GREEN: 森林绿色主题。
        SANDY_BEACH: 沙滩主题。
        MIDNIGHT_PURPLE: 午夜紫主题。
    """
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
    """代码高亮主题枚举。

    Args:
        DEFAULT: 默认主题。
        ATOM_ONE_DARK: Atom One Dark 主题。
        GITHUB: GitHub 主题。
    """
    DEFAULT = "default"
    ATOM_ONE_DARK = "atom-one-dark"
    GITHUB = "github"


class OutputMode(Enum):
    """输出模式枚举。

    Args:
        BINARY: 返回图片的二进制数据。
        LOCAL: 保存到本地文件，并返回文件路径。
    """
    BINARY = "binary"
    LOCAL = "local"


class MarkdownToImageConverter:
    """将 Markdown 文本渲染为 PNG 图片的工具，支持 KaTeX 数学公式、代码高亮、任务列表、删除线等语法。

    Dependencies:
        - selenium
        - pymdown-extensions (支持任务列表与删除线)
        - Chrome 浏览器及对应版本的 ChromeDriver

    性能优化说明：
      1. 复用同一实例可避免反复启动/关闭 Chrome 驱动带来的额外耗时。
      2. Chrome 启动参数中增加禁用扩展、后台计时器、后台网络等参数，可减少不必要的资源消耗。
      3. 在页面加载、等待渲染、截图等关键步骤中添加耗时日志，便于量化和对比性能。
    """

    # 本地静态资源的相对路径（相对于项目根目录）
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

    def __init__(
            self,
            driver: Optional[webdriver.Chrome] = None,
            driver_path: Optional[str] = None,
            headless: bool = True,
            debug: bool = False
    ) -> None:
        """初始化 Chrome 驱动。
    
        Args:
            driver: 已存在的 Chrome 驱动实例（可选）。若为 None，则创建新的驱动实例。
            driver_path: ChromeDriver 的路径（可选）。若为 None，则使用系统 PATH 中的驱动。
            headless: 是否启用无头模式，默认 True。
            debug: 是否启用调试日志，默认 False。
        """
        self.debug = debug
        if driver:
            self.driver = driver
            self._log("使用外部提供的 Chrome 驱动实例.")
        else:
            chrome_options = Options()
            if headless:
                # 使用新版 headless 模式（Chrome v109+）
                chrome_options.add_argument("--headless=new")
            chrome_options.add_argument("--disable-gpu")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--window-size=1920x1080")

            # ========== 性能优化参数 ==========
            # --disable-extensions：关闭扩展，减少不必要的加载时间
            # --disable-background-timer-throttling：防止后台计时器被延迟
            # --disable-renderer-backgrounding：确保后台标签页渲染不降低优先级
            # --disable-background-networking：禁用后台网络请求，减少无效流量
            chrome_options.add_argument("--disable-extensions")
            chrome_options.add_argument("--disable-background-timer-throttling")
            chrome_options.add_argument("--disable-renderer-backgrounding")
            chrome_options.add_argument("--disable-background-networking")

            self.driver = webdriver.Chrome(
                options=chrome_options,
                service=webdriver.ChromeService(executable_path=driver_path) if driver_path else None
            )
            self.driver.set_page_load_timeout(30)
            self._log("创建新的 Chrome 驱动实例.")

    def __enter__(self) -> "MarkdownToImageConverter":
        """上下文管理入口。

        Returns:
            当前实例。
        """
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        """上下文管理出口，关闭 Chrome 驱动。"""
        self.close()

    def _log(self, msg: str) -> None:
        """在 debug 模式下打印日志。

        Args:
            msg: 要打印的调试信息。
        """
        if self.debug:
            print("[DEBUG]", msg)

    def _local_path_to_uri(self, relative_path: str) -> str:
        """将相对路径转换为 file:// URI。

        Args:
            relative_path: 本地文件的相对路径。

        Returns:
            带有 file:// 前缀的绝对路径 URI。
        """
        base_dir = os.path.dirname(os.path.abspath(__file__))
        abs_path = os.path.join(base_dir, relative_path)
        return "file:///" + abs_path.replace("\\", "/")

    def _generate_html(
            self,
            md_content: str,
            css: Optional[str],
            theme: Theme,
            highlight_theme: HighlightTheme
    ) -> str:
        """生成包含 KaTeX 自动渲染、代码高亮和自定义 CSS 的 HTML 页面。

        性能日志：
          - 记录 HTML 生成耗时。

        Args:
            md_content: Markdown 文本。
            css: 额外自定义 CSS（可选）。
            theme: Markdown 样式主题。
            highlight_theme: 代码高亮主题。

        Returns:
            生成的完整 HTML 字符串。
        """
        t_start = time.perf_counter()
        md_content = textwrap.dedent(md_content)
        html_content = markdown.markdown(
            md_content,
            extensions=["extra", "tables", "pymdownx.tasklist", "pymdownx.tilde"],
            extension_configs={
                "pymdownx.tasklist": {"custom_checkbox": True},
                "pymdownx.tilde": {}
            }
        )

        # 转换本地资源路径为 file:// URI
        md_theme_uri = self._local_path_to_uri(self.MARKDOWN_THEMES[theme])
        hl_theme_uri = self._local_path_to_uri(self.HIGHLIGHT_THEMES[highlight_theme])
        highlight_js = self._local_path_to_uri("static/js/highlight.min.js")
        katex_css = self._local_path_to_uri("static/css/katex.min.css")
        katex_js = self._local_path_to_uri("static/js/katex.min.js")
        katex_auto = self._local_path_to_uri("static/js/auto-render.min.js")

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
            <!-- Markdown 主题样式 -->
            <link rel="stylesheet" href="{md_theme_uri}">
            <!-- 代码高亮主题样式 -->
            <link rel="stylesheet" href="{hl_theme_uri}">
            <!-- KaTeX 样式 -->
            <link rel="stylesheet" href="{katex_css}">
            <style>
                {self._custom_styles(theme)}
                {css or ""}
            </style>
            <!-- 引入代码高亮脚本 -->
            <script src="{highlight_js}"></script>
            <!-- 引入 KaTeX 脚本及自动渲染扩展 -->
            <script src="{katex_js}"></script>
            <script src="{katex_auto}"></script>
        </head>
        <body>
            <article class="markdown-body">
                {html_content}
            </article>
            {render_script}
        </body>
        </html>
        """)
        t_elapsed = time.perf_counter() - t_start
        self._log(f"HTML 生成耗时：{t_elapsed * 1000:.2f} 毫秒")
        return html

    def _custom_styles(self, theme: Theme) -> str:
        """返回根据主题定制的 CSS 样式。重点改善深色主题下代码块背景过暗的问题，使其更亮、更易阅读。
    
        Args:
            theme: 选择的主题枚举。
    
        Returns:
            CSS 字符串，用于设置背景、文字颜色等。
        """
        if theme == Theme.LIGHT:
            bg_color = "#ffffff"
            text_color = "#24292e"
            # 浅色主题下代码块背景采用略微加深的白色
            fallback_pre_bg = "#f0f2f5"
            table_border = "#ddd"
            table_header_bg = "#f6f8fa"
            table_even_bg = "#f9f9f9"

        elif theme == Theme.DARK:
            bg_color = "#12151C"
            text_color = "#C9D1D9"
            # 将代码块背景调亮一些，形成明显对比
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
            # 增加代码块背景亮度，避免文字与背景颜色相近
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
            # 调整为更亮的代码块背景，提升与深色背景的对比
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

        # “毛玻璃”效果：为代码块增加轻微半透明滤镜效果
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

    def convert(
            self,
            md_content: str,
            output_path: Optional[str] = None,
            css: Optional[str] = None,
            theme: Theme = Theme.LIGHT,
            highlight_theme: HighlightTheme = HighlightTheme.DEFAULT,
            output_mode: OutputMode = OutputMode.BINARY
    ) -> Union[bytes, str]:
        """将 Markdown 文本转换为 PNG 图片。

        性能日志记录：
          - 记录 HTML 生成、页面加载、KaTeX 渲染等待、截图等关键步骤的耗时。

        Args:
            md_content: Markdown 文本（数学公式请确保符合 KaTeX 语法）。
            output_path: 当 output_mode=LOCAL 时，指定图片保存路径。
            css: 额外自定义 CSS（可选）。
            theme: Markdown 主题。
            highlight_theme: 代码高亮主题。
            output_mode: 输出模式，BINARY 返回二进制数据，LOCAL 返回文件路径。

        Returns:
            如果 output_mode 为 BINARY，则返回图片二进制数据；
            如果为 LOCAL，则返回图片保存的文件路径。

        Raises:
            ValueError: 当 output_mode=LOCAL 而未指定 output_path 时抛出异常。
        """
        t_total_start = time.perf_counter()

        # 生成 HTML
        html_str = self._generate_html(md_content, css, theme, highlight_theme)
        t_html_done = time.perf_counter()
        self._log(f"生成 HTML 总耗时：{(t_html_done - t_total_start) * 1000:.2f} 毫秒")

        # 写入临时 HTML 文件
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".html", encoding="utf-8") as f:
            f.write(html_str)
            temp_path = f.name
        self._log(f"生成临时 HTML 文件: {temp_path}")

        try:
            # 加载页面
            t_load_start = time.perf_counter()
            self.driver.get(f"file:///{temp_path}")
            self._log("等待 markdown-body 元素加载...")
            WebDriverWait(self.driver, 15).until(
                EC.presence_of_element_located((By.CLASS_NAME, "markdown-body"))
            )
            t_load_end = time.perf_counter()
            self._log(f"页面加载及元素等待耗时：{(t_load_end - t_load_start) * 1000:.2f} 毫秒")

            # 等待 KaTeX 渲染完成
            t_katex_start = time.perf_counter()
            if self.driver.execute_script("return document.body.getAttribute('data-katex-done');") != "true":
                self._log("等待 KaTeX 渲染完成...")
                WebDriverWait(self.driver, 15).until(
                    lambda d: d.execute_script("return document.body.getAttribute('data-katex-done');") == "true"
                )
                self._log("KaTeX 渲染完成.")
            else:
                self._log("已检测到 KaTeX 渲染完成标识.")
            t_katex_end = time.perf_counter()
            self._log(f"KaTeX 渲染等待耗时：{(t_katex_end - t_katex_start) * 1000:.2f} 毫秒")

            # 获取截图区域
            clip = self.driver.execute_script("""
                var rect = document.querySelector('.markdown-body').getBoundingClientRect();
                return {x: rect.left, y: rect.top, width: rect.width, height: rect.height};
            """)
            self._log(f"截图区域: {clip}")

            # 设置模拟分辨率，确保截图区域正确
            self.driver.execute_cdp_cmd("Emulation.setDeviceMetricsOverride", {
                "width": int(clip["width"]),
                "height": int(clip["height"]),
                "deviceScaleFactor": 1,
                "mobile": False
            })

            # 截图
            t_shot_start = time.perf_counter()
            screenshot_result = self.driver.execute_cdp_cmd("Page.captureScreenshot", {
                "format": "png",
                "clip": {
                    "x": clip["x"],
                    "y": clip["y"],
                    "width": clip["width"],
                    "height": clip["height"],
                    "scale": 1
                }
            })
            screenshot_data = base64.b64decode(screenshot_result.get("data", ""))
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
        finally:
            os.remove(temp_path)
            self._log(f"删除临时文件: {temp_path}")

    def close(self) -> None:
        """关闭 Chrome 驱动。"""
        self.driver.quit()
        self._log("Chrome 驱动已关闭.")

    @classmethod
    def convert_markdown(
            cls,
            md_content: str,
            output_path: Optional[str] = None,
            driver_path: Optional[str] = None,
            headless: bool = True,
            css: Optional[str] = None,
            theme: Theme = Theme.LIGHT,
            highlight_theme: HighlightTheme = HighlightTheme.DEFAULT,
            output_mode: OutputMode = OutputMode.BINARY,
            debug: bool = False
    ) -> Union[bytes, str]:
        """通过类方法调用，将 Markdown 转换为图片，无需手动管理实例。

        Args:
            md_content: Markdown 文本。
            output_path: 当 output_mode=LOCAL 时，指定图片保存路径。
            driver_path: ChromeDriver 的路径（可选）。
            headless: 是否使用无头模式，默认 True。
            css: 额外自定义 CSS。
            theme: Markdown 主题。
            highlight_theme: 代码高亮主题。
            output_mode: 输出模式（BINARY 或 LOCAL）。
            debug: 是否启用调试日志。

        Returns:
            如果 output_mode 为 BINARY，则返回图片二进制数据；如果为 LOCAL，则返回图片保存的路径。
        """
        with cls(driver_path=driver_path, headless=headless, debug=debug) as converter:
            return converter.convert(
                md_content=md_content,
                output_path=output_path,
                css=css,
                theme=theme,
                highlight_theme=highlight_theme,
                output_mode=output_mode
            )

    @classmethod
    async def async_convert_markdown(
            cls,
            md_content: str,
            output_path: Optional[str] = None,
            driver_path: Optional[str] = None,
            headless: bool = True,
            css: Optional[str] = None,
            theme: Theme = Theme.LIGHT,
            highlight_theme: HighlightTheme = HighlightTheme.DEFAULT,
            output_mode: OutputMode = OutputMode.BINARY,
            debug: bool = False,
    ) -> Union[bytes, str]:
        """异步版本，将 Markdown 转换为图片。

        Args:
            md_content: Markdown 文本（数学公式需符合 KaTeX 语法）。
            output_path: 当 output_mode=LOCAL 时，指定图片保存路径。
            driver_path: ChromeDriver 路径（可选）。
            headless: 是否使用无头模式，默认为 True。
            css: 额外自定义 CSS。
            theme: Markdown 主题。
            highlight_theme: 代码高亮主题。
            output_mode: 输出模式（BINARY 或 LOCAL）。
            debug: 是否启用调试日志。

        Returns:
            若 output_mode 为 BINARY，则返回图片二进制数据；若为 LOCAL，则返回图片保存路径。
        """
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            lambda: cls.convert_markdown(
                md_content=md_content,
                output_path=output_path,
                driver_path=driver_path,
                headless=headless,
                css=css,
                theme=theme,
                highlight_theme=highlight_theme,
                output_mode=output_mode,
                debug=debug
            )
        )
        return result


# ============================
# 使用示例 1：每次转换新建实例（保留之前用法）
# ============================
async def async_usage_example():
    """异步示例：遍历所有主题与代码高亮组合进行转换（每次转换均新建实例），用于对比性能。"""
    sample_md = r"""
    # 多主题测试

    这是一个综合测试文档，涵盖数学公式、代码块、表格、图片、链接、引用、列表和任务列表等内容。

    ## 数学公式
    行内公式：当 $a \ne 0$ 时，二次方程 $ax^2 + bx + c = 0$ 的解为
    $$
    x = \frac{-b \pm \sqrt{b^2-4ac}}{2a}
    $$

    ## 代码块
    ```python
    def greet(name):
        print(f"Hello, {name}!")
    
    greet("World")
    ```

    ## 表格
    | 产品名称   | 价格(元) | 库存量 |
    | ---------- | -------- | ------ |
    | iPhone 13  | 6999     | 50     |
    | MacBook Pro| 12999    | 20     |
    | AirPods Pro| 1999     | 150    |

    ## 图片
    ![示例图片](https://repobeats.axiom.co/api/embed/eebef43ecb6c77ef043dcb65c4cda7e9dfd29af7.svg)

    ## 链接
    [百度](https://www.baidu.com)

    ## 引用
    > “经典话语在这里闪耀。”

    ## 列表
    - 第一项
    - 第二项
        - 子项 1
        - 子项 2

    ## 任务列表
    - [ ] 任务未完成
    - [x] 任务已完成

    ## 删除线
    这是一段 ~~被删除~~ 的文字.

    ## HTML 测试
    <div style="color: red; border: 1px solid red; padding: 5px;">
      这是一个自定义的 HTML 区块.
    </div>
    """
    tasks = []
    # 每次转换均新建实例（不复用），用于测试首次启动驱动的额外耗时
    for theme in Theme:
        for highlight_theme in HighlightTheme:
            output_filename = f"output_{theme.value}_{highlight_theme.value}.png"
            print(f"准备渲染主题：{theme.value}，代码高亮：{highlight_theme.value} -> 输出：{output_filename}")
            task = asyncio.create_task(
                MarkdownToImageConverter.async_convert_markdown(
                    md_content=sample_md,
                    output_path=output_filename,
                    theme=theme,
                    highlight_theme=highlight_theme,
                    output_mode=OutputMode.LOCAL,
                    debug=True,
                    headless=True,
                )
            )
            tasks.append(task)
    results = await asyncio.gather(*tasks)
    for res in results:
        print("转换结果：", res)


# ============================
# 使用示例 2：复用同一实例进行多次转换
# ============================
async def reuse_example():
    """异步示例：复用同一实例进行多次转换，降低重复启动/关闭浏览器的开销，并统计性能差异。"""
    sample_md = r"""
    # 复用实例测试

    这是用于测试复用同一 Chrome 实例进行多次转换的 Markdown 文本示例。
    """
    converter = MarkdownToImageConverter(headless=True, debug=True)
    tasks = []
    try:
        for theme in Theme:
            for highlight_theme in HighlightTheme:
                output_filename = f"reuse_output_{theme.value}_{highlight_theme.value}.png"
                print(f"准备渲染主题：{theme.value}，代码高亮：{highlight_theme.value} -> 输出：{output_filename}")
                # 复用同一 converter 实例
                task = asyncio.create_task(
                    converter.async_convert_markdown(
                        md_content=sample_md,
                        output_path=output_filename,
                        theme=theme,
                        highlight_theme=highlight_theme,
                        output_mode=OutputMode.LOCAL
                    )
                )
                tasks.append(task)
        results = await asyncio.gather(*tasks)
        for res in results:
            print("转换结果：", res)
    finally:
        converter.close()


# ============================
# 性能测试函数：量化对比复用实例与不复用实例的性能
# ============================
def performance_test(iterations: int = 5) -> None:
    """对比测试：分别统计每次新建实例和复用同一实例进行转换的性能，并输出平均、最小、最大耗时。

    Args:
        iterations: 每种模式下的转换次数，默认为 5 次。
    """
    sample_md = r"""
    # 性能测试

    这是用于性能测试的 Markdown 示例文档。
    """
    times_new_instance: List[float] = []
    times_reuse_instance: List[float] = []

    # 测试每次新建实例模式
    for i in range(iterations):
        t_start = time.perf_counter()
        output_file = f"performance_new_{i}.png"
        # 每次调用都会新建一个实例
        MarkdownToImageConverter.convert_markdown(
            md_content=sample_md,
            output_path=output_file,
            theme=Theme.LIGHT,
            highlight_theme=HighlightTheme.DEFAULT,
            output_mode=OutputMode.LOCAL,
            debug=False,
            headless=True
        )
        t_end = time.perf_counter()
        elapsed_ms = (t_end - t_start) * 1000
        times_new_instance.append(elapsed_ms)
        print(f"[新建实例] 第 {i + 1} 次转换耗时：{elapsed_ms:.2f} 毫秒")
        if os.path.exists(output_file):
            os.remove(output_file)

    # 测试复用实例模式
    converter = MarkdownToImageConverter(headless=True, debug=False)
    try:
        for i in range(iterations):
            t_start = time.perf_counter()
            output_file = f"performance_reuse_{i}.png"
            converter.convert(
                md_content=sample_md,
                output_path=output_file,
                theme=Theme.LIGHT,
                highlight_theme=HighlightTheme.DEFAULT,
                output_mode=OutputMode.LOCAL
            )
            t_end = time.perf_counter()
            elapsed_ms = (t_end - t_start) * 1000
            times_reuse_instance.append(elapsed_ms)
            print(f"[复用实例] 第 {i + 1} 次转换耗时：{elapsed_ms:.2f} 毫秒")
            if os.path.exists(output_file):
                os.remove(output_file)
    finally:
        converter.close()

    def calc_stats(times: List[float]) -> Tuple[float, float, float]:
        return (sum(times) / len(times), min(times), max(times))

    avg_new, min_new, max_new = calc_stats(times_new_instance)
    avg_reuse, min_reuse, max_reuse = calc_stats(times_reuse_instance)

    print("\n=== 性能对比统计 ===")
    print(f"【新建实例】平均耗时：{avg_new:.2f} 毫秒，最小耗时：{min_new:.2f} 毫秒，最大耗时：{max_new:.2f} 毫秒")
    print(f"【复用实例】平均耗时：{avg_reuse:.2f} 毫秒，最小耗时：{min_reuse:.2f} 毫秒，最大耗时：{max_reuse:.2f} 毫秒")


# ============================
# 外部创建 Chrome 驱动实例，用于复用
# ============================
def manual_driver_example():
    """手动创建 Chrome 驱动实例，用于外部复用。"""
    driver = webdriver.Chrome()
    sample_md = r"""
    # 多主题测试

    这是一个综合测试文档，涵盖数学公式、代码块、表格、图片、链接、引用、列表和任务列表等内容。

    ## 数学公式
    行内公式：当 $a \ne 0$ 时，二次方程 $ax^2 + bx + c = 0$ 的解为
    $$
    x = \frac{-b \pm \sqrt{b^2-4ac}}{2a}
    $$

    ## 代码块
    ```python
    def greet(name):
        print(f"Hello, {name}!")
    
    greet("World")
    ```

    ## 表格
    | 产品名称   | 价格(元) | 库存量 |
    | ---------- | -------- | ------ |
    | iPhone 13  | 6999     | 50     |
    | MacBook Pro| 12999    | 20     |
    | AirPods Pro| 1999     | 150    |

    ## 图片
    ![示例图片](https://repobeats.axiom.co/api/embed/eebef43ecb6c77ef043dcb65c4cda7e9dfd29af7.svg)

    ## 链接
    [百度](https://www.baidu.com)

    ## 引用
    > “经典话语在这里闪耀。”

    ## 列表
    - 第一项
    - 第二项
        - 子项 1
        - 子项 2

    ## 任务列表
    - [ ] 任务未完成
    - [x] 任务已完成

    ## 删除线
    这是一段 ~~被删除~~ 的文字.

    ## HTML 测试
    <div style="color: red; border: 1px solid red; padding: 5px;">
      这是一个自定义的 HTML 区块.
    </div>
    """
    try:
        converter = MarkdownToImageConverter(driver=driver, debug=True)
        # 使用 converter 进行转换
        output_file = "output_dark_atom-one-dark.png"
        converter.convert(
            md_content=sample_md,
            output_path=output_file,
            theme=Theme.DARK,
            highlight_theme=HighlightTheme.ATOM_ONE_DARK,
            output_mode=OutputMode.LOCAL
        )
        print("转换完成：", output_file)
    finally:
        driver.quit()


# ============================
# 主函数：同时调用异步示例、复用实例示例和性能测试
# ============================
async def main():
    print("=== 异步示例（每次转换新建实例） ===")
    # await async_usage_example()
    print("\n=== 异步示例（复用同一实例） ===")
    # await reuse_example()
    print("\n=== 性能测试（对比新建实例与复用实例） ===")
    # performance_test(iterations=5)
    print("\n=== 手动创建 Chrome 驱动实例示例 ===")
    manual_driver_example()


if __name__ == "__main__":
    asyncio.run(main())
