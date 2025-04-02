#!/usr/bin/env python
"""
bump.py - 版本号更新工具

这个脚本是对bump2version的封装，提供了更友好的命令行界面来更新项目版本号。
支持增加主版本号、次版本号、补丁版本号，以及预发布标签（如alpha、beta、rc等）。

使用方法:
    python -m utils.bump [命令] [选项]

命令:
    major    - 增加主版本号 (1.0.0 -> 2.0.0)
    minor    - 增加次版本号 (1.0.0 -> 1.1.0)
    patch    - 增加补丁版本号 (1.0.0 -> 1.0.1)
    release  - 移除预发布标签 (1.0.0-beta -> 1.0.0)
    dev      - 添加dev预发布标签 (1.0.0 -> 1.0.0-dev)
    alpha    - 添加alpha预发布标签 (1.0.0 -> 1.0.0-alpha)
    beta     - 添加beta预发布标签 (1.0.0 -> 1.0.0-beta)
    rc       - 添加rc预发布标签 (1.0.0 -> 1.0.0-rc)
    info     - 显示当前版本信息

选项:
    --tag    - 创建Git标签
    --commit - 提交更改

示例:
    python -m utils.bump patch           # 增加补丁版本 (1.0.0 -> 1.0.1)
    python -m utils.bump minor --tag     # 增加次版本并创建标签 (1.0.0 -> 1.1.0)
    python -m utils.bump beta --commit   # 添加beta标签并提交 (1.0.0 -> 1.0.0-beta)
"""

import argparse
import importlib.util
import subprocess
import sys

# 使用 importlib.util.find_spec 检查 bumpversion 是否可用
HAS_BUMPVERSION = importlib.util.find_spec("bumpversion") is not None


def check_bumpversion():
    """检查bump2version是否已安装"""
    if not HAS_BUMPVERSION:
        print("错误: 未安装bump2version库")
        print("请安装: uv add bump2version")
        sys.exit(1)


def run_bumpversion(part, tag=False, commit=False):
    """运行bump2version命令"""
    cmd = ["bump2version"]

    if tag:
        cmd.append("--tag")

    if commit:
        cmd.append("--commit")

    cmd.append(part)

    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"执行bump2version失败: {result.stderr}")
            sys.exit(1)

        print(result.stdout or "版本已更新")
        return True
    except Exception as e:
        print(f"执行bump2version时出错: {e}")
        sys.exit(1)


def get_current_version():
    """获取当前版本号"""
    try:
        from core import __version__

        return __version__
    except ImportError:
        try:
            # 尝试从.bumpversion.cfg读取
            with open(".bumpversion.cfg") as f:
                for line in f:
                    if line.startswith("current_version"):
                        return line.split("=")[1].strip()
        except Exception:
            pass

        try:
            # 尝试从pyproject.toml读取
            import tomli

            with open("pyproject.toml", "rb") as f:
                data = tomli.load(f)
                return data.get("project", {}).get("version", "未知")
        except Exception:
            return "未知"


def show_version_info():
    """显示版本信息"""
    try:
        from utils.version_info import get_full_version_info

        version, git_info, b2v_info = get_full_version_info()

        print(f"当前版本: v{version}")

        if git_info["commit_short"] != "未知":
            print(f"Git分支: {git_info['branch']}")
            print(f"最新提交: {git_info['commit_short']} ({git_info['commit_author']})")
            print(f"提交信息: {git_info['commit_message']}")

        if b2v_info["build_number"] != "开发环境":
            print(f"构建编号: {b2v_info['build_number']}")
            if b2v_info["build_date"]:
                print(f"构建日期: {b2v_info['build_date']}")
            print(f"构建类型: {b2v_info['build_type']}")
    except ImportError:
        print(f"当前版本: v{get_current_version()}")


def main():
    parser = argparse.ArgumentParser(description="版本号更新工具")
    parser.add_argument(
        "command",
        choices=[
            "major",
            "minor",
            "patch",
            "release",
            "dev",
            "alpha",
            "beta",
            "rc",
            "info",
        ],
        help="要执行的命令",
    )
    parser.add_argument("--tag", action="store_true", help="创建Git标签")
    parser.add_argument("--commit", action="store_true", help="提交更改")

    args = parser.parse_args()

    if args.command == "info":
        show_version_info()
        return

    check_bumpversion()

    prerelease_types = ["dev", "alpha", "beta", "rc", "release"]

    if args.command in prerelease_types:
        if args.command == "release":
            run_bumpversion("release", args.tag, args.commit)
        else:
            run_bumpversion(f"pre{args.command}", args.tag, args.commit)
    else:
        run_bumpversion(args.command, args.tag, args.commit)


if __name__ == "__main__":
    main()
