from __future__ import annotations

from collections.abc import Iterable

from arclet.alconna import config as alconna_config

DEFAULT_COMMAND_PREFIX = "/"


def configure_command_prefix(
    prefix: str | Iterable[str] = DEFAULT_COMMAND_PREFIX,
    *,
    use_entari_prefix: bool = False,
) -> None:
    """配置所有 Tenko 命令共用的原生命令前缀来源。

    Alconna 在构建每条命令时会复制 ``default_namespace.prefixes``，因此此函数
    必须在导入 Tenko 插件之前运行。使用 Entari 官方 basic.prefix 时，Tenko
    命令定义不再重复携带同一前缀，由 Entari 的消息级 prefix stripper 统一处理。
    """

    if isinstance(prefix, str):
        prefixes = [prefix]
    else:
        prefixes = list(prefix)
        if not all(isinstance(item, str) for item in prefixes):
            raise ValueError("command_prefix 必须是字符串列表")

    if not use_entari_prefix and (not prefixes or any(not item for item in prefixes)):
        raise ValueError("command_prefix 必须是非空字符串")

    alconna_config.default_namespace.prefixes = [] if use_entari_prefix else prefixes

    if use_entari_prefix:
        return

    # 旧调用方仍可使用 Alconna 前缀模式；运行时的新路径不进入此分支，因此
    # 不会修改官方 basic.prefix。
    try:
        from arclet.entari.config import EntariConfig
    except ImportError:  # pragma: no cover - 仅供 Alconna 工具使用
        return

    if EntariConfig._inited:
        EntariConfig.instance.basic.prefix = []
        EntariConfig.instance.basic.nickname = ""
