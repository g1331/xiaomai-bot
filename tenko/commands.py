from __future__ import annotations

from arclet.alconna import config as alconna_config

DEFAULT_COMMAND_PREFIX = "/"


def configure_command_prefix(prefix: str = DEFAULT_COMMAND_PREFIX) -> None:
    """Configure the one native prefix source shared by all Tenko commands.

    Alconna copies ``default_namespace.prefixes`` when each command is built,
    so this function must run before Tenko plugins are imported.  Entari's
    command dispatcher also has an optional message-level prefix stripper;
    clearing it after Entari initialization prevents the same prefix from
    being consumed twice before Alconna sees the message.
    """

    if not isinstance(prefix, str) or not prefix:
        raise ValueError("command_prefix 必须是非空字符串")

    alconna_config.default_namespace.prefixes = [prefix]

    # Keep the integration with Entari in this central adapter instead of
    # making every plugin opt out of the dispatcher preprocessor.
    try:
        from arclet.entari.config import EntariConfig
    except ImportError:  # pragma: no cover - Alconna-only tooling
        return

    if EntariConfig._inited:
        EntariConfig.instance.basic.prefix = []
