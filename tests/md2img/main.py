import asyncio
import os
import time

from md2img import MarkdownToImageConverter, Theme, HighlightTheme, OutputMode


# ============================
# 使用示例 1：每次转换新建实例（不复用），异步示例
# ============================
async def async_usage_example():
    """异步示例：遍历所有主题与代码高亮组合进行转换（每次转换均新建实例），用于对比首次启动浏览器的额外耗时。"""
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
    # 每次转换均新建一个实例
    for theme in Theme:
        for highlight_theme in HighlightTheme:
            output_filename = f"output_{theme.value}_{highlight_theme.value}.png"
            print(
                f"准备渲染主题：{theme.value}，代码高亮：{highlight_theme.value} -> 输出：{output_filename}"
            )
            task = asyncio.create_task(
                MarkdownToImageConverter.convert_markdown(
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
# 使用示例 2：复用同一实例进行多次转换，异步示例
# ============================
async def reuse_example():
    """异步示例：复用同一实例进行多次转换，降低重复启动/关闭浏览器的开销，并统计性能差异。"""
    sample_md = r"""
    # 复用实例测试

    这是用于测试复用同一实例进行多次转换的 Markdown 文本示例。
    """
    # 使用 async with 自动管理浏览器实例的启动与关闭
    async with MarkdownToImageConverter(headless=True, debug=True) as converter:
        tasks = []
        for theme in Theme:
            for highlight_theme in HighlightTheme:
                output_filename = (
                    f"reuse_output_{theme.value}_{highlight_theme.value}.png"
                )
                print(
                    f"准备渲染主题：{theme.value}，代码高亮：{highlight_theme.value} -> 输出：{output_filename}"
                )
                # 调用异步接口转换
                task = asyncio.create_task(
                    converter.convert_markdown(
                        md_content=sample_md,
                        output_path=output_filename,
                        theme=theme,
                        highlight_theme=highlight_theme,
                        output_mode=OutputMode.LOCAL,
                    )
                )
                tasks.append(task)
        results = await asyncio.gather(*tasks)
        for res in results:
            print("转换结果：", res)


# ============================
# 性能测试函数：对比新建实例与复用实例的性能
# ============================
async def performance_test(iterations: int = 5) -> None:
    """对比测试：分别统计每次新建实例和复用同一实例进行转换的性能，并输出平均、最小、最大耗时。

    Args:
        iterations: 每种模式下的转换次数，默认为 5 次。
    """
    sample_md = r"""
    # 性能测试

    这是用于性能测试的 Markdown 示例文档。
    """
    times_new_instance: list[float] = []
    times_reuse_instance: list[float] = []

    # 测试每次新建实例模式（同步调用）
    for i in range(iterations):
        t_start = time.perf_counter()
        output_file = f"performance_new_{i}.png"
        # 每次调用都会新建一个转换实例（同步接口内部封装了异步调用）
        await MarkdownToImageConverter.convert_markdown(
            md_content=sample_md,
            output_path=output_file,
            theme=Theme.LIGHT,
            highlight_theme=HighlightTheme.DEFAULT,
            output_mode=OutputMode.LOCAL,
            debug=False,
            headless=True,
        )
        t_end = time.perf_counter()
        elapsed_ms = (t_end - t_start) * 1000
        times_new_instance.append(elapsed_ms)
        print(f"[新建实例] 第 {i + 1} 次转换耗时：{elapsed_ms:.2f} 毫秒")
        if os.path.exists(output_file):
            os.remove(output_file)

    # 测试复用实例模式（同步接口）
    for i in range(iterations):
        t_start = time.perf_counter()
        output_file = f"performance_reuse_{i}.png"
        await MarkdownToImageConverter.convert_markdown(
            md_content=sample_md,
            output_path=output_file,
            theme=Theme.LIGHT,
            highlight_theme=HighlightTheme.DEFAULT,
            output_mode=OutputMode.LOCAL,
            debug=False,
            headless=True,
        )
        t_end = time.perf_counter()
        elapsed_ms = (t_end - t_start) * 1000
        times_reuse_instance.append(elapsed_ms)
        print(f"[复用实例] 第 {i + 1} 次转换耗时：{elapsed_ms:.2f} 毫秒")
        if os.path.exists(output_file):
            os.remove(output_file)

    def calc_stats(times: list[float]) -> tuple[float, float, float]:
        return (sum(times) / len(times), min(times), max(times))

    avg_new, min_new, max_new = calc_stats(times_new_instance)
    avg_reuse, min_reuse, max_reuse = calc_stats(times_reuse_instance)

    print("\n=== 性能对比统计 ===")
    print(
        f"【新建实例】平均耗时：{avg_new:.2f} 毫秒，最小耗时：{min_new:.2f} 毫秒，最大耗时：{max_new:.2f} 毫秒"
    )
    print(
        f"【复用实例】平均耗时：{avg_reuse:.2f} 毫秒，最小耗时：{min_reuse:.2f} 毫秒，最大耗时：{max_reuse:.2f} 毫秒"
    )


# ============================
# 手动创建实例示例（同步调用）
# ============================
async def manual_instance_example():
    """手动创建实例进行转换示例，使用同步接口调用转换函数。"""
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
    output_file = "output_dark_atom-one-dark.png"
    result = await MarkdownToImageConverter.convert_markdown(
        md_content=sample_md,
        output_path=output_file,
        theme=Theme.DARK,
        highlight_theme=HighlightTheme.ATOM_ONE_DARK,
        output_mode=OutputMode.LOCAL,
        debug=True,
        headless=True,
    )
    print("转换完成：", result)


# ============================
# 主函数：调用各个测试示例
# ============================
async def main():
    print("=== 异步示例（每次转换新建实例） ===")
    await async_usage_example()
    print("\n=== 异步示例（复用同一实例） ===")
    await reuse_example()
    print("\n=== 性能测试（对比新建实例与复用实例） ===")
    await performance_test(iterations=3)
    print("\n=== 手动创建实例示例 ===")
    await manual_instance_example()


if __name__ == "__main__":
    asyncio.run(main())
