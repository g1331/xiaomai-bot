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


def parse_version(value):
    if not isinstance(value, str):
        raise ValueError("版本必须是字符串")
    version, separator, build = value.partition("+")
    core, prerelease_separator, prerelease = version.partition("-")
    parts = core.split(".")
    if len(parts) != 3 or any(
        not part.isascii()
        or not part.isdigit()
        or (len(part) > 1 and part.startswith("0"))
        for part in parts
    ):
        raise ValueError(f"非法版本号: {value!r}")
    identifiers = tuple(prerelease.split(".")) if prerelease_separator else ()
    for identifier in identifiers:
        if not identifier or not all(
            "0" <= char <= "9"
            or "A" <= char <= "Z"
            or "a" <= char <= "z"
            or char == "-"
            for char in identifier
        ):
            raise ValueError(f"非法版本号: {value!r}")
        if (
            identifier.isdigit()
            and len(identifier) > 1
            and identifier.startswith("0")
        ):
            raise ValueError(f"非法版本号: {value!r}")
    if separator and (
        not build
        or any(
            not item
            or not all(
                "0" <= char <= "9"
                or "A" <= char <= "Z"
                or "a" <= char <= "z"
                or char == "-"
                for char in item
            )
            for item in build.split(".")
        )
    ):
        raise ValueError(f"非法版本号: {value!r}")
    return tuple(int(part) for part in parts), identifiers


def version_is_older(left, right):
    if left[0] != right[0]:
        return left[0] < right[0]
    left_pre, right_pre = left[1], right[1]
    if not left_pre or not right_pre:
        return bool(left_pre) and not right_pre
    for left_identifier, right_identifier in zip(left_pre, right_pre):
        if left_identifier == right_identifier:
            continue
        left_numeric = left_identifier.isdigit()
        right_numeric = right_identifier.isdigit()
        if left_numeric and right_numeric:
            return int(left_identifier) < int(right_identifier)
        if left_numeric != right_numeric:
            return left_numeric
        return left_identifier < right_identifier
    return len(left_pre) < len(right_pre)


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
stable_version = None
try:
    with (stable_root / "pyproject.toml").open("rb") as project_file:
        stable_version = parse_version(tomllib.load(project_file)["project"]["version"])
except (OSError, KeyError, TypeError, ValueError, tomllib.TOMLDecodeError):
    pass
if active_file.is_file():
    try:
        pointer = json.loads(active_file.read_text(encoding="utf-8"))
        if not isinstance(pointer, dict):
            raise ValueError("active 指针必须是 object")
        pointer_version = parse_version(pointer["version"])
        pointer_root = Path(pointer["path"]).expanduser().resolve()
        versions_root = (upgrade_root / "versions").resolve()
        if pointer_root.parent != versions_root or not pointer_root.is_dir():
            raise ValueError("active 指针必须指向 versions 下的版本目录")
        if stable_version is None or not version_is_older(
            pointer_version, stable_version
        ):
            release_root = pointer_root
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise SystemExit(f"active 指针无效: {active_file}: {error}") from error

sys.path.insert(0, str(release_root))
sys.argv = ["tenko", *arguments]
runpy.run_module("tenko", run_name="__main__")
' "${STABLE_ROOT}" "$@"
