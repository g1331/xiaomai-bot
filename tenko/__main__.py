from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from loguru import logger

from .config import TenkoConfig


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Tenko Entari/OneBot 11 runtime")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config/tenko.toml"),
        help="TOML 配置文件路径（默认：config/tenko.toml）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只加载配置并打印连接信息，不启动网络服务",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = TenkoConfig.load(args.config)

    if args.dry_run:
        logger.info("Tenko dry-run: configuration loaded; no network connection opened")
        logger.info(
            "OneBot 11 reverse WebSocket endpoint: {}", config.onebot.reverse_ws_url
        )
        return 0

    from .runtime import run

    run(config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
