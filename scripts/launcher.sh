#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
STABLE_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd -P)"
UV="${UV:-uv}"

cd -- "${STABLE_ROOT}"

exec "${UV}" run --project "${STABLE_ROOT}" --no-sync python -c '
import json
import os
import runpy
import sys
import tomllib
from pathlib import Path

stable_root = Path(sys.argv[1]).resolve()
arguments = sys.argv[2:]
config_value = "config/tenko.toml"
for index, value in enumerate(arguments):
    if value == "--config" and index + 1 < len(arguments):
        config_value = arguments[index + 1]
        break
    if value.startswith("--config="):
        config_value = value.partition("=")[2]
        break

config_path = Path(config_value).expanduser()
if not config_path.is_absolute():
    config_path = stable_root / config_path
install_value = ".tenko/upgrades"
try:
    with config_path.open("rb") as config_file:
        config_data = tomllib.load(config_file)
except FileNotFoundError:
    config_data = {}
upgrade_data = config_data.get("upgrade", {})
if isinstance(upgrade_data, dict):
    install_value = upgrade_data.get("install_root", install_value)

configured_root = os.environ.get("TENKO_UPGRADE_ROOT") or install_value
upgrade_root = Path(configured_root).expanduser()
if not upgrade_root.is_absolute():
    upgrade_root = stable_root / upgrade_root
active_file = upgrade_root.resolve() / "active.json"
release_root = stable_root
if active_file.is_file():
    try:
        pointer = json.loads(active_file.read_text(encoding="utf-8"))
        if not isinstance(pointer, dict):
            raise ValueError("active 指针必须是 object")
        release_root = Path(pointer["path"]).expanduser().resolve()
        versions_root = (upgrade_root / "versions").resolve()
        if release_root.parent != versions_root or not release_root.is_dir():
            raise ValueError("active 指针必须指向 versions 下的版本目录")
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise SystemExit(f"active 指针无效: {active_file}: {error}") from error

sys.path.insert(0, str(release_root))
sys.argv = ["tenko", *arguments]
runpy.run_module("tenko", run_name="__main__")
' "${STABLE_ROOT}" "$@"
