from __future__ import annotations

from arclet.alconna import config as alconna_config

DEFAULT_COMMAND_PREFIX = "/"


def configure_command_prefix(prefix: str = DEFAULT_COMMAND_PREFIX) -> None:
    """配置所有 Tenko 命令共用的唯一原生命令前缀来源。

    Alconna 在构建每条命令时会复制 ``default_namespace.prefixes``，因此此函数
    必须在导入 Tenko 插件之前运行。Entari 的 command dispatcher 还提供可选的
    消息级 prefix stripper；在 Entari 初始化后将其清空，可避免同一前缀在
    Alconna 看到消息前被重复消费。
    """

    if not isinstance(prefix, str) or not prefix:
        raise ValueError("command_prefix 必须是非空字符串")

    alconna_config.default_namespace.prefixes = [prefix]

    # 在这个中央适配器中统一处理与 Entari 的集成，避免每个插件都必须单独退出
    # dispatcher 的 preprocessor。
    try:
        from arclet.entari.config import EntariConfig
    except ImportError:  # pragma: no cover - 仅供 Alconna 工具使用
        return

    if EntariConfig._inited:
        EntariConfig.instance.basic.prefix = []
        EntariConfig.instance.basic.nickname = ""
