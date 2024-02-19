from unwind import get_report, ReportFlag

from creart import create
from graia.ariadne import Ariadne
from graia.saya import Saya, Channel
from graia.ariadne.message.element import Image
from graia.ariadne.message.chain import MessageChain
from graia.broadcast.builtin.event import ExceptionThrowed
from graia.saya.builtins.broadcast.schema import ListenerSchema
from graia.ariadne.exception import AccountMuted, UnknownTarget

from core.config import GlobalConfig
from utils.text2img import md2img

saya = create(Saya)
channel = Channel.current()

channel.name("ExceptionCatcher")
channel.author("SAGIRI-kawaii")
channel.author("13")
channel.description("一个能够捕获错误并将其转为图片发给主人的插件")

config = create(GlobalConfig)


@channel.use(ListenerSchema(listening_events=[ExceptionThrowed]))
async def except_handle(event: ExceptionThrowed):
    app = Ariadne.current(config.default_account)
    if isinstance(event.event, ExceptionThrowed):
        return
    if isinstance(
            event.exception,
            (AccountMuted, UnknownTarget)
    ):
        return
    image = await md2img(generate_reports_md(event.exception),
                         {"viewport": {"width": 1920, "height": 10}, "color_scheme": "dark"})
    return await app.send_friend_message(
        config.Master,
        MessageChain(Image(data_bytes=image))
    )


def generate_reports_md(exception: BaseException) -> str:
    """
    根据异常信息生成Markdown格式的报错文档。

    参数:
        exception (BaseException): 抛出的异常对象。

    返回:
        str: Markdown格式的异常报告。
    """
    # 异常信息标题
    report_md = [f"# 异常信息: `{exception.__class__.__name__}` `{exception}`"]

    try:
        reports = get_report(exception)
    except Exception as e:
        return f"生成报告时发生错误: {e}"

    # 定义辅助函数以获取描述和原因
    def get_reason_description(flag) -> tuple[str, str]:
        reason_map = {
            ReportFlag.ACTIVE: ("主动抛出异常", "代码主动抛出了一个错误"),
            ReportFlag.OPERATE: ("变量操作出错", "代码在进行变量操作"),
            ReportFlag.UNKNOWN: ("未知错误", "此处代码无法被获取, 请检查代码逻辑"),
            ReportFlag.CALL_CALLABLE: ("调用对象出错", "代码正在调用一个可调用对象, 可能是函数, 也可能是实现了__call__的对象"),
            ReportFlag.AWAIT_AWAITABLE: ("等待协程对象出错", "代码正在等待协程对象, 即调用了__await__方法"),
            ReportFlag.ENTER_CONTEXT: ("进入上下文出错", "代码正在进入一个上下文"),
            ReportFlag.ITER_ITERABLE: ("循环可迭代对象出错", "代码正在循环一个可迭代对象"),
        }
        return reason_map.get(flag, ("执行代码", "执行代码"))

    for index, report in enumerate(reports):
        reason, description = get_reason_description(report.flag)
        # 使用二级标题，并在标题中直接包含原因和索引，使其更具信息性
        report_md.append(
            f"\n---\n\n## step[{index + 1}]: {reason}\n"
            f"*异常描述*: `{description}`\n"
            f"*出错位置*: `{report.info.file}` 第 `{report.info.line}` 行, 函数 `{report.info.name}`\n"
            f"*出错代码*: \n\n```python\n{report.info.code}\n```\n"
        )
        if report.flag == ReportFlag.ACTIVE:
            report_md.extend([
                f"*错误类型*: `{report.type}`\n",
                f"*错误内容*: `{report.content}`\n"
            ])
        elif report.flag == ReportFlag.OPERATE:
            locals_ = report.info.locals or '无'
            if isinstance(locals_, dict):
                # 生成局部变量的Markdown格式
                locals_formatted = "\n".join(
                    [f" - `{k}`: `{v}`" if str(k) in report.info.code else "" for k, v in
                     locals_.items()])
                report_md.append(f"*局部变量*: \n{locals_formatted}")
            else:
                report_md.append(f"*局部变量*: \n{locals_}")
        else:
            params = report.args or '无'
            if isinstance(params, dict):
                params_formatted = "\n".join([f"`{k}: {v}`" for k, v in params.items()])
                report_md.append(f"*参数*: \n{params_formatted}")
            else:
                report_md.append(f"*参数*: \n{params}")

    return "\n".join(report_md).replace("\n", "<br>")
