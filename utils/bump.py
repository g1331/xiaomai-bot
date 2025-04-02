#!/usr/bin/env python
"""
bump.py - 项目版本号自动管理脚本

支持：
- 使用 bump2version 修改版本
- 自动同步 uv.lock
- 可选生成 changelog（需安装 git-cliff）
- 可选自动 commit 和打 Git tag

用法示例：
    python -m utils.bump patch --commit --tag --changelog
    python -m utils.bump alpha
    python -m utils.bump release --commit
"""

import argparse
import importlib.util
import subprocess
import sys
import re
import os

HAS_BUMPVERSION = importlib.util.find_spec("bumpversion") is not None


def check_bumpversion():
    if not HAS_BUMPVERSION:
        print("错误: 未安装 bump2version，请先运行: uv add bump2version")
        sys.exit(1)


def run_bumpversion(part, new_version=None):
    """执行 bump2version，不自动 commit 或 tag"""
    cmd = ["bump2version"]
    if new_version:
        cmd += ["--new-version", new_version]
    cmd.append(part)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"❌ bump2version 执行失败: {result.stderr}")
            sys.exit(1)
        print(result.stdout or "✅ 版本号已更新")
        return True
    except Exception as e:
        print(f"❌ bump2version 出错: {e}")
        sys.exit(1)


def update_uv_lock():
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


def get_current_version():
    try:
        from core import __version__

        return __version__
    except ImportError:
        try:
            with open(".bumpversion.cfg") as f:
                for line in f:
                    if line.startswith("current_version"):
                        return line.split("=")[1].strip()
        except Exception:
            pass
        try:
            import tomli

            with open("pyproject.toml", "rb") as f:
                data = tomli.load(f)
                return data.get("project", {}).get("version", "未知")
        except Exception:
            return "未知"


def get_base_version(version: str) -> str:
    match = re.match(r"\d+\.\d+\.\d+", version)
    return match.group(0) if match else version


def generate_changelog(version: str):
    cmd = ["git-cliff", "--tag", f"v{version}", "-o", "CHANGELOG.md"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"❌ changelog 生成失败: {result.stderr}")
            sys.exit(1)
        print("✅ changelog 已生成")
    except Exception as e:
        print(f"❌ 执行 git-cliff 出错: {e}")
        sys.exit(1)


def git_commit_and_tag(version: str, tag: bool):
    files = ["pyproject.toml", "uv.lock", ".bumpversion.cfg"]
    if os.path.exists("core/__init__.py"):
        files.append("core/__init__.py")
    if os.path.exists("CHANGELOG.md"):
        files.append("CHANGELOG.md")

    subprocess.run(["git", "add"] + files, check=True)
    subprocess.run(["git", "commit", "-m", f"bump: v{version}"], check=True)

    if tag:
        subprocess.run(["git", "tag", f"v{version}"], check=True)
        print(f"✅ Git tag v{version} 已创建")


def main():
    parser = argparse.ArgumentParser(
        description="项目版本号自动更新脚本（基于 bump2version）",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "command",
        choices=[
            "major",
            "minor",
            "patch",
            "dev",
            "alpha",
            "beta",
            "rc",
            "release",
            "info",
        ],
        help=(
            "版本操作命令：\n"
            "  major     主版本号 +1，如 1.2.3 → 2.0.0\n"
            "  minor     次版本号 +1，如 1.2.3 → 1.3.0\n"
            "  patch     补丁号 +1，如 1.2.3 → 1.2.4\n"
            "  dev       添加 -dev 预发布标签\n"
            "  alpha     添加 -alpha 标签\n"
            "  beta      添加 -beta 标签\n"
            "  rc        添加 -rc 标签\n"
            "  release   移除预发布标签，发布正式版\n"
            "  info      显示当前版本信息"
        ),
    )
    parser.add_argument("--tag", action="store_true", help="创建 Git tag（如 v1.2.4）")
    parser.add_argument(
        "--commit", action="store_true", help="自动提交所有版本变更文件"
    )
    parser.add_argument(
        "--changelog", action="store_true", help="生成 changelog（依赖 git-cliff）"
    )

    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(0)

    args = parser.parse_args()

    if args.command == "info":
        version = get_current_version()
        print(f"当前版本号: v{version}")
        return

    check_bumpversion()

    # 决定是预发布标志还是版本升级
    pre_types = ["dev", "alpha", "beta", "rc", "release"]
    if args.command in pre_types:
        current = get_current_version()
        base = get_base_version(current)
        new_version = base if args.command == "release" else f"{base}-{args.command}"
        run_bumpversion("patch", new_version=new_version)
    else:
        run_bumpversion(args.command)

    # 更新 uv.lock 中的 version
    update_uv_lock()

    # 获取最新版本号
    version = get_current_version()

    # 生成 changelog（可选）
    if args.changelog:
        generate_changelog(version)

    # 手动提交（如果指定 --commit）
    if args.commit:
        git_commit_and_tag(version, tag=args.tag)


if __name__ == "__main__":
    main()
