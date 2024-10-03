import asyncio
import json
from json import JSONDecodeError
from pathlib import Path
from typing import List, Tuple, Optional, Set

import aiofiles
from aiohttp import ClientSession, ClientError
from creart import create
from loguru import logger

from core.config import GlobalConfig

config = create(GlobalConfig)
proxy = config.proxy if config.proxy != "proxy" else ""

# 更新后的JSON链接
_JSON_LINK = (
    "https://raw.githubusercontent.com/xsalazar/"
    "emoji-kitchen-backend/main/app/metadata.json"
)
_ASSETS = Path(__file__).parent / "assets"
_FILE = _ASSETS / "metadata.json"
_UPDATE = _ASSETS / "update.json"
_KITCHEN: str = (
    "https://www.gstatic.com/android/keyboard/emojikitchen"
    "/{date}/u{left_emoji}/u{left_emoji}_u{right_emoji}.png"
)

# 下载最新的metadata.json
async def _download_update():
    try:
        async with ClientSession() as session:
            async with session.get(_JSON_LINK, proxy=proxy) as resp:  # 超时时间 10 秒
                if resp.status == 200:
                    ensure_path_exists(_UPDATE)
                    async with aiofiles.open(_UPDATE, "wb") as f:
                        async for chunk in resp.content.iter_chunked(1024 * 1024 * 5):  # 每次读取 5MB 数据
                            await f.write(chunk)
                    logger.success("[EmojiMix] metadata.json 下载完成")
                    return
                else:
                    logger.error(f"[EmojiMix] 下载 metadata.json 失败，状态码: {resp.status}")
                    return
    except asyncio.TimeoutError:
        logger.error(f"[EmojiMix] 请求超时")
    except ClientError as ce:
        logger.error(f"[EmojiMix] 网络请求失败: {ce}")
    except Exception as e:
        logger.error(f"[EmojiMix] metadata.json 下载失败: {e}")

def ensure_path_exists(path: Path):
    """确保路径和文件夹存在"""
    if path.suffix:  # 如果是文件路径
        if not path.parent.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
    else:  # 如果是文件夹路径
        if not path.exists():
            path.mkdir(parents=True, exist_ok=True)

def read_data(path: Path) -> List[Tuple[str, str, str]]:
    ensure_path_exists(path)
    data: List[Tuple[str, str, str]] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            f_content = json.load(f)
            logger.debug(f"Loaded JSON content from {path}")

            data_field = f_content.get("data", {})
            if not isinstance(data_field, dict):
                logger.error(f"Expected 'data' to be a dict, got {type(data_field)}")
                return data

            for emoji_entry_key, emoji_entry in data_field.items():
                combinations = emoji_entry.get("combinations", {})
                if not isinstance(combinations, dict):
                    logger.error(f"Expected 'combinations' to be a dict in '{emoji_entry_key}', got {type(combinations)}")
                    continue

                for combination_key, combination_list in combinations.items():
                    if not isinstance(combination_list, list):
                        logger.error(f"Expected combination list for key '{combination_key}', got {type(combination_list)}")
                        continue

                    for pair in combination_list:
                        if isinstance(pair, dict):
                            # 修改这里，使用 'leftEmojiCodepoint' 和 'rightEmojiCodepoint'
                            left = pair.get("leftEmojiCodepoint")
                            right = pair.get("rightEmojiCodepoint")
                            date = pair.get("date")
                            if left and right and date:
                                data.append((left, right, date))
                            else:
                                logger.error(f"Missing keys in pair: {pair}")
                        else:
                            logger.warning(f"Skipping non-dict pair under key '{combination_key}': {pair}")
    except FileNotFoundError:
        logger.warning(f"[EmojiMix] 文件 {path} 不存在或已损坏，返回空数据")
    except JSONDecodeError:
        logger.error(f"[EmojiMix] 文件 {path} JSON 解码失败")
    return data

# 使用更新的metadata.json
try:
    _MIX_DATA: List[Tuple[str, str, str]] = read_data(_UPDATE)
    if not _MIX_DATA:
        raise FileNotFoundError
except (FileNotFoundError, JSONDecodeError, KeyError):
    logger.warning("[EmojiMix] metadata.json 不存在或已损坏，使用回退数据")
    _UPDATE.unlink(missing_ok=True)
    _MIX_DATA: List[Tuple[str, str, str]] = read_data(_FILE)

# 将codepoint转换为emoji字符
def get_emoji(code_point: str) -> str:
    if "-" not in code_point:
        return chr(int(code_point, 16))
    emoji = code_point.split("-")
    return "".join(chr(int(i, 16)) for i in emoji)

# 获取所有emoji组合
def get_all_emoji() -> Set[str]:
    emoji_set = set()
    for left_emoji, right_emoji, _ in _MIX_DATA:
        emoji_set.add(get_emoji(left_emoji))
        emoji_set.add(get_emoji(right_emoji))
    return emoji_set

# 所有emoji
_ALL_EMOJI: Set[str] = get_all_emoji()

# 将emoji转换为codepoint
def emoji_to_codepoint(emoji: str) -> str:
    if len(emoji) == 1:
        return f"{ord(emoji):x}"
    return "-".join(f"{ord(char):x}" for char in emoji)

# 获取emoji组合的图片URL
def get_mix_emoji_url(left_emoji: str, right_emoji: str) -> Optional[str]:
    left_code = emoji_to_codepoint(left_emoji)
    right_code = emoji_to_codepoint(right_emoji)
    for _left_emoji, _right_emoji, date in _MIX_DATA:
        if (_left_emoji == left_code and _right_emoji == right_code) or (_left_emoji == right_code and _right_emoji == left_code):
            return _KITCHEN.format(
                date=date,
                left_emoji=_left_emoji.replace("-", "-u"),
                right_emoji=_right_emoji.replace("-", "-u"),
            )
    return None

# 获取与某个emoji匹配的组合
def get_available_pairs(emoji: str) -> Set[str]:
    emoji_code = emoji_to_codepoint(emoji)
    pairs = set()
    for _left_emoji, _right_emoji, _ in _MIX_DATA:
        if _left_emoji == emoji_code:
            pairs.add(get_emoji(_right_emoji))
        elif _right_emoji == emoji_code:
            pairs.add(get_emoji(_left_emoji))
    return pairs
