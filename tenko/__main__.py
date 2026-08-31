from __future__ import annotations

import argparse
import asyncio
import os
import sys
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


def _current_code_root() -> Path:
    """返回当前已加载 Tenko 包的代码根目录。"""

    return Path(__file__).resolve().parent.parent


def _exec_release_root(
    release_root: Path, stable_root: Path, arguments: Sequence[str]
) -> None:
    """在 fresh Python 进程中以候选目录优先重新执行 Tenko。"""

    bootstrap = (
        "import runpy,sys;"
        "release_root=sys.argv.pop(1);"
        "sys.path.insert(0,release_root);"
        "sys.argv[0]='tenko';"
        "runpy.run_module('tenko',run_name='__main__')"
    )
    environment = os.environ.copy()
    existing_pythonpath = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = os.pathsep.join(
        value for value in (str(release_root), existing_pythonpath) if value
    )
    os.chdir(stable_root)
    os.execve(
        sys.executable,
        [sys.executable, "-c", bootstrap, str(release_root), *arguments],
        environment,
    )


def _run_startup_bootstrap(config: TenkoConfig, arguments: Sequence[str]) -> bool:
    """消费 handoff，并在 active 代码不是当前代码时重新执行。"""

    from .host.updater import UpgradeConfigError, UpgradeManager, read_project_version

    stable_root = Path.cwd().resolve()
    manager = UpgradeManager.from_config(config.upgrade, project_root=stable_root)
    if manager.layout.handoff_file.is_file():
        result = asyncio.run(manager.apply_handoff(start_process=False))
        if not result.success:
            if getattr(result, "rolled_back", False):
                logger.warning(
                    "Tenko upgrade handoff failed and was rolled back; "
                    "continuing with the recovered active version: {}",
                    result.reason,
                )
            else:
                logger.warning(
                    "Tenko upgrade handoff was not applied; "
                    "continuing with the active version: {}",
                    result.reason,
                )

    active = manager.layout.read_active()
    if active is None:
        return False

    try:
        stable_version = read_project_version(stable_root)
    except UpgradeConfigError:
        stable_version = None
    if stable_version is not None and active.version < stable_version:
        logger.warning(
            "稳定根版本 {} 新于 active 指针 {}，使用稳定根代码；"
            "可删除 active.json 或执行 /升级 重建指针",
            stable_version,
            active.version,
        )
        if _current_code_root() != stable_root:
            _exec_release_root(stable_root, stable_root, arguments)
            return True
        return False

    if active.path == _current_code_root():
        return False

    logger.info(
        "Tenko selecting active release {} from {}",
        active.version,
        active.path,
    )
    _exec_release_root(active.path, stable_root, arguments)
    return True


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    args = build_parser().parse_args(arguments)
    config = TenkoConfig.load(args.config)

    if args.dry_run:
        logger.info("Tenko dry-run: configuration loaded; no network connection opened")
        logger.info(
            "OneBot 11 reverse WebSocket endpoint: {}", config.onebot.reverse_ws_url
        )
        return 0

    if _run_startup_bootstrap(config, arguments):
        return 0

    from .runtime import run

    run(config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
