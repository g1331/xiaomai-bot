#!/usr/bin/env python
"""
bump.py - 项目版本号自动管理脚本

支持：
- 使用 bump-my-version 修改版本
- 自动同步 uv.lock
- 可选生成 changelog（需安装 git-cliff）
- 可选自动 commit 和打 Git tag

用法示例：
    python -m scripts.bump patch --commit --tag --changelog  # 更新补丁版本并提交、打标签
    python -m scripts.bump pre_l  # 递增预发布标签（如 dev → alpha → beta → rc）
    python -m scripts.bump pre_n  # 递增预发布版本号（如 alpha1 → alpha2）
    python -m scripts.bump patch --no-pre  # 直接更新补丁版本，不添加预发布标签
    python -m scripts.bump patch --new-version 0.2.0  # 直接指定目标版本号
    python -m scripts.bump release  # 移除预发布标签，发布正式版
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 使用 tomli
    import tomli as tomllib


MANIFEST_PATH = Path("upgrade-manifest.json")
PYPROJECT_PATH = Path("pyproject.toml")
_SEMVER_IDENTIFIER = r"(?:0|[1-9]\d*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*)"
_SEMVER_PATTERN = re.compile(
    rf"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    rf"(?:-{_SEMVER_IDENTIFIER}(?:\.{_SEMVER_IDENTIFIER})*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)


class ReleaseMetadataError(ValueError):
    """发布所需的配置协议元数据缺失或非法。"""


def validate_semver(value: object) -> str:
    """校验并返回不带隐式转换的 SemVer 字符串。"""
    if not isinstance(value, str) or _SEMVER_PATTERN.fullmatch(value) is None:
        raise ReleaseMetadataError(f"min_config_version 不是合法 SemVer: {value!r}")
    return value


def read_min_config_version(path: str | Path = PYPROJECT_PATH) -> str:
    """从 pyproject.toml 读取并校验配置协议最低版本。"""
    path = Path(path)
    try:
        with path.open("rb") as file:
            data = tomllib.load(file)
        value = data["tool"]["tenko"]["upgrade"]["min_config_version"]
    except (OSError, KeyError, TypeError, tomllib.TOMLDecodeError) as exc:
        raise ReleaseMetadataError(
            f"无法从 {path} 读取 [tool.tenko.upgrade].min_config_version"
        ) from exc
    return validate_semver(value)


def generate_upgrade_manifest(
    *,
    pyproject_path: str | Path = PYPROJECT_PATH,
    manifest_path: str | Path = MANIFEST_PATH,
) -> Path:
    """根据发布源元数据生成根目录的 canonical 升级 manifest。"""
    min_config_version = read_min_config_version(pyproject_path)
    target = Path(manifest_path)
    try:
        target.write_text(
            json.dumps(
                {"min_config_version": min_config_version},
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        raise ReleaseMetadataError(f"无法写入升级兼容性清单: {target}") from exc
    print(f"✅ 已生成升级兼容性清单: {target}")
    return target


# 检查是否安装了 bump-my-version 作为 uv 工具
def is_bumpmyversion_installed():
    """检查 bump-my-version 是否已作为 uv 工具安装"""
    return shutil.which("bump-my-version") is not None


def check_bumpmyversion():
    """检查 bump-my-version 是否已安装"""
    if not is_bumpmyversion_installed():
        print("错误: 未安装 bump-my-version，请先运行: uv tool install bump-my-version")
        sys.exit(1)


def get_current_version():
    """获取当前版本号，优先从 pyproject.toml 读取"""
    # 从 pyproject.toml 获取
    try:
        with PYPROJECT_PATH.open("rb") as file:
            data = tomllib.load(file)
            # 先检查 tool.bumpversion.current_version
            version = data.get("tool", {}).get("bumpversion", {}).get("current_version")
            if version:
                return version.strip("\"'")
            # 再检查 project.version
            version = data.get("project", {}).get("version")
            if version:
                return version.strip("\"'")
    except Exception:
        pass

    return "未知"


def get_base_version(version: str) -> str:
    """从版本号中提取基础版本（不含预发布标签）"""
    match = re.match(r"\d+\.\d+\.\d+", version)
    return match.group(0) if match else version


def run_bumpmyversion(part, new_version=None, no_pre=False):
    """执行 bump-my-version，不自动 commit 或 tag

    返回：
        tuple: (bool, str) 执行成功返回 (True, 新版本号)，失败返回 (False, None)
    """
    cmd = ["bump-my-version", "bump"]  # 添加 'bump' 子命令

    # 明确指定当前版本，避免从预发布版本升级时的问题
    current_version = get_current_version()
    cmd += ["--current-version", current_version]

    # 初始化 result_version
    result_version = None

    if new_version:
        cmd += ["--new-version", new_version]
        # 如果指定了新版本，就不需要指定要更新的部分了
        part = None
        result_version = new_version  # 如果指定了新版本，直接使用该版本号
    # 如果指定 no_pre=True，先提取基础版本号，然后根据命令增加相应的版本号部分
    elif no_pre:
        base_version = get_base_version(current_version)

        # 根据命令构造新版本号
        if part == "major":
            parts = base_version.split(".")
            new_ver = f"{int(parts[0]) + 1}.0.0"
        elif part == "minor":
            parts = base_version.split(".")
            new_ver = f"{parts[0]}.{int(parts[1]) + 1}.0"
        elif part == "patch":
            parts = base_version.split(".")
            new_ver = f"{parts[0]}.{parts[1]}.{int(parts[2]) + 1}"
        else:
            new_ver = base_version

        cmd = [
            "bump-my-version",
            "bump",
            "--current-version",
            current_version,
            "--new-version",
            new_ver,
        ]
        result_version = new_ver
        part = None

    # 仅当未指定新版本时才添加部分参数
    if part:
        cmd.append(part)

    try:
        print(f"执行命令: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"❌ bump-my-version 执行失败: {result.stderr or result.stdout}")
            return False, None

        print(result.stdout or "✅ 版本号已更新")

        # 如果没有指定新版本号，则从文件中读取
        if new_version is None:
            result_version = get_current_version()

        return True, result_version
    except Exception as e:
        print(f"❌ bump-my-version 出错: {e}")
        return False, None


def update_pyproject_version_directly(new_version):
    """直接更新 pyproject.toml 中的版本号（在 bump-my-version 失败时的备用方案）"""
    try:
        content = PYPROJECT_PATH.read_text(encoding="utf-8")

        # 更新项目版本
        content = re.sub(
            r'(?m)^([ \t]*version[ \t]*=[ \t]*)"[^"]+"',
            f'\\1"{new_version}"',
            content,
        )

        # 更新 bumpversion 配置中的当前版本
        content = re.sub(
            r'(?m)^([ \t]*current_version[ \t]*=[ \t]*)"[^"]+"',
            f'\\1"{new_version}"',
            content,
        )

        PYPROJECT_PATH.write_text(content, encoding="utf-8")

        print(f"✅ 已直接更新版本号至 {new_version}")
        return True
    except Exception as e:
        print(f"❌ 直接更新版本号失败: {e}")
        return False


def update_uv_lock():
    """更新 uv.lock 文件"""
    if not os.path.exists("uv.lock"):
        print("⚠️ 未找到 uv.lock，跳过")
        return
    try:
        result = subprocess.run(["uv", "lock"], capture_output=True, text=True)
        if result.returncode != 0:
            print(f"❌ uv lock 执行失败: {result.stderr}")
            sys.exit(1)
        print("✅ uv.lock 已更新")
    except Exception as e:
        print(f"❌ 执行 uv lock 出错: {e}")
        sys.exit(1)


def generate_changelog(version: str):
    """生成 changelog"""
    cmd = [
        "git-cliff",
        "--tag",
        f"v{version}",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"❌ changelog 生成失败: {result.stderr}")
            sys.exit(1)
        print("✅ changelog 已更新并追加到 CHANGELOG.md")
    except Exception as e:
        print(f"❌ 执行 git-cliff 出错: {e}")
        sys.exit(1)


def git_commit_and_tag(prev_version: str, new_version: str, tag: bool):
    """提交更改并创建 Git tag"""
    files = ["pyproject.toml", "uv.lock", "upgrade-manifest.json"]
    if os.path.exists("CHANGELOG.md"):
        files.append("CHANGELOG.md")

    subprocess.run(["git", "add"] + files, check=True)
    message = f"chore(release): bump version v{prev_version} → v{new_version}"
    subprocess.run(["git", "commit", "-m", message], check=True)

    if tag:
        subprocess.run(["git", "tag", f"v{new_version}"], check=True)
        print(f"✅ Git tag v{new_version} 已创建")


def main():
    parser = argparse.ArgumentParser(
        description="项目版本号自动更新脚本（基于 bump-my-version）",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "command",
        choices=[
            "major",
            "minor",
            "patch",
            "pre_l",
            "pre_n",
            "release",
            "info",
        ],
        help=(
            "版本操作命令：\n"
            "  major     主版本号 +1，如 1.2.3 → 2.0.0\n"
            "  minor     次版本号 +1，如 1.2.3 → 1.3.0\n"
            "  patch     补丁号 +1，如 1.2.3 → 1.2.4\n"
            "  pre_l     递增预发布标签，如 dev → alpha → beta → rc\n"
            "  pre_n     递增预发布版本号，如 alpha1 → alpha2\n"
            "  release   移除预发布标签，发布正式版\n"
            "  info      显示当前版本信息"
        ),
    )
    parser.add_argument("--tag", action="store_true", help="创建 Git tag（如 v1.2.4）")
    commit_options = parser.add_mutually_exclusive_group()
    commit_options.add_argument(
        "--commit", action="store_true", help="自动提交所有版本变更文件"
    )
    commit_options.add_argument(
        "--no-commit", action="store_true", help="只更新文件，不提交（默认行为）"
    )
    parser.add_argument(
        "--changelog", action="store_true", help="生成 changelog（依赖 git-cliff）"
    )
    parser.add_argument(
        "--no-pre", action="store_true", help="直接更新版本号，不添加预发布标签"
    )
    parser.add_argument("--new-version", help="直接指定新的版本号（例如：0.2.0）")
    parser.add_argument(
        "--force",
        action="store_true",
        help="强制直接修改文件（当 bump-my-version 失败时使用）",
    )

    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(0)

    args = parser.parse_args()

    if args.command == "info":
        version = get_current_version()
        print(f"当前版本号: v{version}")
        return

    try:
        read_min_config_version()
    except ReleaseMetadataError as exc:
        print(f"❌ {exc}")
        sys.exit(1)

    check_bumpmyversion()

    prev_version = get_current_version()
    new_version = None

    # 处理明确指定的新版本号
    if args.new_version:
        print(f"⚙️ 准备将版本从 {prev_version} 更新到 {args.new_version}")
        success, new_version = run_bumpmyversion(None, new_version=args.new_version)
        if not success:
            print("❌ 版本更新失败")
            if args.force:
                print("⚠️ bump-my-version 失败，尝试直接修改文件...")
                update_pyproject_version_directly(args.new_version)
                new_version = args.new_version
            else:
                print("❌ 如果你确定要强制更新，请添加 --force 参数")
                sys.exit(1)
    else:
        # 处理预发布版本和标准版本更新
        if args.command == "release":
            # 移除预发布标签，发布正式版
            base = get_base_version(prev_version)
            success, new_version = run_bumpmyversion(None, new_version=base)
            if not success:
                print("❌ 移除预发布标签失败")
                if args.force:
                    print("⚠️ bump-my-version 失败，尝试直接修改文件...")
                    update_pyproject_version_directly(base)
                    new_version = base
                else:
                    print("❌ 如果你确定要强制更新，请添加 --force 参数")
                    sys.exit(1)
        else:
            # 直接使用 bump-my-version 的内置功能处理所有版本更新
            # 包括 major、minor、patch、pre_l、pre_n 等
            success, new_version = run_bumpmyversion(args.command, no_pre=args.no_pre)
            if not success:
                print("❌ 版本更新失败")
                if args.force and args.command in ["major", "minor", "patch"]:
                    print("⚠️ bump-my-version 失败，尝试直接修改文件...")
                    # 如果是标准版本更新，可以尝试直接修改文件
                    # 计算新版本号
                    parts = prev_version.split(".")
                    if args.command == "major":
                        new_ver = f"{int(parts[0]) + 1}.0.0"
                    elif args.command == "minor":
                        new_ver = f"{parts[0]}.{int(parts[1]) + 1}.0"
                    elif args.command == "patch":
                        new_ver = (
                            f"{parts[0]}.{parts[1]}.{int(parts[2].split('-')[0]) + 1}"
                        )
                    update_pyproject_version_directly(new_ver)
                    new_version = new_ver
                else:
                    print("❌ 如果你确定要强制更新，请添加 --force 参数")
                    sys.exit(1)

    # 如果没有获取到新版本号，则尝试从文件中读取
    if new_version is None:
        new_version = get_current_version()

    # 更新 uv.lock
    update_uv_lock()

    # 生成 changelog（如指定）
    if args.changelog:
        generate_changelog(new_version)

    try:
        generate_upgrade_manifest()
    except ReleaseMetadataError as exc:
        print(f"❌ {exc}")
        sys.exit(1)

    # 提交和打 tag（如指定）
    if args.commit:
        git_commit_and_tag(prev_version, new_version, tag=args.tag)


if __name__ == "__main__":
    main()
