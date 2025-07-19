import hashlib
from datetime import datetime, timedelta

from creart import create
from graia.ariadne import Ariadne
from graia.ariadne.exception import AccountMuted, UnknownTarget
from graia.ariadne.message.chain import MessageChain
from graia.ariadne.message.element import Image
from graia.broadcast.builtin.event import ExceptionThrowed
from graia.saya import Channel
from graia.saya.builtins.broadcast.schema import ListenerSchema
from unwind import ReportFlag, get_report

from core.config import GlobalConfig
from utils.text2img import md2img

channel = Channel.current()

channel.meta["name"] = "ExceptionCatcher"
channel.meta["author"] = "13"  # Updated to reflect the original author for consistency.
channel.meta["description"] = "一个简单高效的异常捕获插件"

config = create(GlobalConfig)

# 简化的错误管理
last_error_time: dict[str, datetime] = {}
ERROR_COOLDOWN = timedelta(seconds=30)  # 同类错误冷却时间


def get_error_hash(exception: BaseException) -> str:
    """生成错误的唯一标识"""
    return hashlib.md5(
        f"{exception.__class__.__name__}:{str(exception)}".encode()
    ).hexdigest()


async def send_error_report(exception: BaseException) -> None:
    """发送错误报告"""
    try:
        app = Ariadne.current(config.default_account)
        report = generate_reports_md(exception)
        image = await md2img(
            report,
            {"viewport": {"width": 1920, "height": 10}, "color_scheme": "dark"},
        )
        await app.send_friend_message(
            config.Master, MessageChain(Image(data_bytes=image))
        )
    except Exception as e:
        print(f"发送错误报告时发生异常: {e}")


@channel.use(ListenerSchema(listening_events=[ExceptionThrowed]))
async def except_handle(event: ExceptionThrowed):
    """简化的异常处理函数"""
    # 忽略特定类型的异常
    if isinstance(event.event, ExceptionThrowed):
        return
    if isinstance(event.exception, AccountMuted | UnknownTarget):
        return

    # 获取错误哈希
    error_hash = get_error_hash(event.exception)
    now = datetime.now()

    # 检查是否在冷却时间内
    if error_hash in last_error_time:
        if (now - last_error_time[error_hash]) < ERROR_COOLDOWN:
            return  # 在冷却时间内，忽略此错误

    # 更新最后错误时间
    last_error_time[error_hash] = now

    # 直接发送错误报告
    await send_error_report(event.exception)


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
            ReportFlag.CALL_CALLABLE: (
                "调用对象出错",
                "代码正在调用一个可调用对象, 可能是函数, 也可能是实现了__call__的对象",
            ),
            ReportFlag.AWAIT_AWAITABLE: (
                "等待协程对象出错",
                "代码正在等待协程对象, 即调用了__await__方法",
            ),
            ReportFlag.ENTER_CONTEXT: ("进入上下文出错", "代码正在进入一个上下文"),
            ReportFlag.ITER_ITERABLE: (
                "循环可迭代对象出错",
                "代码正在循环一个可迭代对象",
            ),
        }
        return reason_map.get(flag, ("执行代码", "执行代码"))

    for index, report in enumerate(reports):
        reason, description = get_reason_description(report.flag)
        # 使用二级标题，并在标题中直接包含原因和索引，使其更具信息性
        report_md.append(f"\n---\n\n## step[{index + 1}]: {reason}\n")
        report_md.append(f"*异常描述*: `{description}`\n")
        report_md.append(
            f"*出错位置*: `{report.info.file}` 第 `{report.info.line_index}` 行, 函数 `{report.info.name}`\n"
        )
        report_md.append(f"*出错代码*: \n\n```python\n{report.info.codes}\n```\n")
        if report.flag == ReportFlag.ACTIVE:
            report_md.extend(
                [f"*错误类型*: `{report.type}`\n", f"*错误内容*: `{report.content}`\n"]
            )
        elif report.flag == ReportFlag.OPERATE:
            locals_ = report.info.locals or "无"
            if isinstance(locals_, dict):
                # 生成局部变量的Markdown格式
                locals_formatted = "\n".join(
                    [
                        f" - `{k}`: `{v}`" if str(k) in report.info.locals else ""
                        for k, v in locals_.items()
                    ]
                )
                report_md.append(f"*局部变量*: \n{locals_formatted}\n")
            else:
                report_md.append(f"*局部变量*: \n{locals_}\n")
        else:
            params = report.args or "无"
            if isinstance(params, dict):
                params_formatted = "\n".join([f"`{k}: {v}`" for k, v in params.items()])
                report_md.append(f"*参数*: \n{params_formatted}")
            else:
                report_md.append(f"*参数*: \n{params}")

    return "\n".join(report_md)
