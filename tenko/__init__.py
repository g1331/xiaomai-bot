"""Tenko 的 Entari + Satori/OneBot 11 最小运行时。"""

from .commands import configure_command_prefix


# Plugin modules construct their Alconna objects during import.  Establish the
# default before any ``tenko.plugins`` package can be imported.
configure_command_prefix()

__all__ = ["configure_command_prefix"]
