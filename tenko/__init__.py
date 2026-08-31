"""Tenko 的 Entari + Satori/OneBot 11 最小运行时。"""

import time

from .commands import configure_command_prefix

# ``tenko`` 包在 ``python -m tenko`` 进入 ``__main__`` 之前初始化；在这里
# 记录单调时钟，才能把配置读取和插件装配时间纳入启动耗时。
_process_start_monotonic = time.perf_counter()

# 插件模块会在导入期间构造 Alconna 对象；在任何
# ``tenko.plugins`` 包被导入之前先设置默认值。
configure_command_prefix()

__all__ = ["configure_command_prefix"]
