import os
import sys
from pathlib import Path

from loguru import logger

# 项目根目录
ROOT_DIR = Path(__file__).parent.parent

# 从core.__init__中获取版本信息
try:
    sys.path.insert(0, str(ROOT_DIR))
    from core import __version__
except ImportError as e:
    logger.error(f"从core模块导入版本信息失败: {e}")
    # 回退方案：尝试从pyproject.toml读取
    try:
        import tomli

        with open(ROOT_DIR / "pyproject.toml", "rb") as f:
            data = tomli.load(f)
            __version__ = data.get("project", {}).get("version", "0.0.0")
    except Exception as e:
        logger.error(f"读取版本信息失败: {e}")
        __version__ = "0.0.0"
finally:
    # 确保恢复sys.path
    if str(ROOT_DIR) in sys.path:
        sys.path.remove(str(ROOT_DIR))

try:
    from git import Repo

    has_git = True
except ImportError:
    logger.warning("未检测到GitPython库，无法获取git信息")
    Repo = None
    has_git = False


def get_version() -> str:
    """获取项目版本号"""
    return __version__


def get_git_info() -> dict[str, str]:
    """获取git仓库信息"""
    result = {
        "branch": "未知分支",
        "commit": "未知提交",
        "commit_short": "未知",
        "commit_time": "未知时间",
        "commit_author": "未知作者",
        "commit_message": "未知消息",
    }

    if not has_git:
        return result

    try:
        repo = Repo(ROOT_DIR)
        if repo.bare:
            return result

        commit = repo.head.commit
        result.update(
            {
                "branch": repo.active_branch.name,
                "commit": commit.hexsha,
                "commit_short": commit.hexsha[:7],
                "commit_time": str(commit.authored_datetime),
                "commit_author": commit.author.name,
                "commit_message": commit.message.strip(),
            }
        )
    except Exception as e:
        logger.error(f"获取git信息失败: {e}")

    return result


def get_b2v() -> dict[str, str]:
    """获取b2v的配置（build to version）

    用于显示构建信息，如果项目使用CI/CD部署，可以通过环境变量设置
    """
    return {
        "build_number": os.environ.get("B2V_BUILD_NUMBER", "开发环境"),
        "build_date": os.environ.get("B2V_BUILD_DATE", ""),
        "build_type": os.environ.get("B2V_BUILD_TYPE", "dev"),
    }


def get_full_version_info() -> tuple[str, dict[str, str], dict[str, str]]:
    """获取完整的版本信息

    返回:
        version: 版本号
        git_info: git仓库信息
        b2v_info: 构建信息
    """
    return get_version(), get_git_info(), get_b2v()
