import re
from pathlib import Path
from typing import Optional

from aiohttp import ClientSession, ClientError
from creart import create
from launart import Launart, Launchable
from loguru import logger

from core.config import GlobalConfig

try:
    from git import Repo, Commit, Head

    has_git = True
except ImportError:
    Repo = Commit = Head = None  # 在 except 块中重新定义变量
    logger.error("未检测到git！")
    has_git = False

config = create(GlobalConfig)
proxy = config.proxy if config.proxy != "proxy" else ""


def get_current_repo() -> Optional["Repo"]:
    if (git_path := Path.cwd() / ".git").exists() and git_path.is_dir():
        return Repo(Path.cwd())
    return None


def get_current_commit(repo: "Repo") -> "Commit":
    try:
        return next(repo.iter_commits())
    except StopIteration as e:
        raise RuntimeError("无法获取当前提交，请检查当前目录是否为 Git 仓库") from e


def get_current_branch(repo: "Repo") -> "Head":
    return repo.active_branch


def get_github_repo(repo: "Repo") -> str:
    remote_url = repo.remote().url
    remote_url += "" if remote_url.endswith(".git") else ".git"
    if github_match := re.search(r"(?<=github.com[/:]).+?(?=\.git)", remote_url):
        return github_match.group()
    raise RuntimeError("无法获取 GitHub 仓库地址，请检查当前目录是否为克隆自 GitHub 的 Git 仓库")


async def get_remote_commit_sha(repo: str, branch: str) -> str:
    link = f"https://api.github.com/repos/{repo}/commits/{branch}"
    async with ClientSession() as session, session.get(
            link, proxy=proxy
    ) as resp:
        return (await resp.json()).get("sha", "")


async def compare_commits(repo: str, base: str, head: str) -> list[dict]:
    link = f"https://api.github.com/repos/{repo}/compare/{base}...{head}"
    async with ClientSession() as session, session.get(
            link, proxy=proxy
    ) as resp:
        return (await resp.json()).get("commits", [])


async def check_update() -> list[dict]:
    repo = get_current_repo()
    if repo is None:
        return []
    current_commit = get_current_commit(repo)
    current_branch = get_current_branch(repo)
    github_repo = get_github_repo(repo)
    remote_commit_sha = await get_remote_commit_sha(github_repo, current_branch.name)
    if remote_commit_sha == current_commit.hexsha:
        return []
    history = await compare_commits(
        github_repo, current_commit.hexsha, remote_commit_sha
    )
    history.reverse()
    return history


def perform_update():
    repo = get_current_repo()
    if repo is None:
        return
    repo.remotes.origin.pull()


class UpdaterService(Launchable):
    id = "umaru.core.updater"

    @property
    def required(self):
        return set()

    @property
    def stages(self):
        return {"preparing"}

    async def launch(self, _mgr: Launart):
        async with self.stage("preparing"):
            await self.check_update()

    @staticmethod
    async def check_update():
        if not has_git:
            return
        logger.debug("【自动更新】正在检查更新...")
        try:
            if not (update := await check_update()):
                logger.opt(colors=True).success("<green>【自动更新】当前版本已是最新</green>")
                return
        except ClientError:
            logger.opt(colors=True).error("<red>【自动更新】无法连接到 GitHub</red>")
            return
        except RuntimeError:
            logger.warning("【自动更新】未检测到 .git 文件夹，只有使用 git 时才检测更新！")
            return
        else:
            output = []
            for commit in update:
                sha = commit.get("sha", "")[:7]
                message = commit.get("commit", {}).get("message", "")
                message = message.replace("<", r"\<").splitlines()[0]
                output.append(f"<red>{sha}</red> <yellow>{message}</yellow>")
            history = "\n".join(["", *output, ""])
            logger.opt(colors=True).warning(f"<yellow>【自动更新】发现新版本</yellow>\n{history}")
