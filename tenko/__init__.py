"""Tenko 的 Entari + Satori/OneBot 11 最小运行时。"""

from .commands import configure_command_prefix


# 插件模块会在导入期间构造 Alconna 对象；在任何
# ``tenko.plugins`` 包被导入之前先设置默认值。
configure_command_prefix()

__all__ = ["configure_command_prefix"]
