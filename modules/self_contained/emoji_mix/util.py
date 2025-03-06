import asyncio
import json
import shutil
import tempfile
from json import JSONDecodeError
from pathlib import Path
from typing import List, Optional, Set, Tuple

import aiofiles
from aiohttp import ClientError, ClientSession
from creart import create
from loguru import logger

from core.config import GlobalConfig

# 常量定义，使用更明确的命名
PROXY = create(GlobalConfig).proxy if create(GlobalConfig).proxy != "proxy" else ""

# 路径相关常量 - 重构文件路径
METADATA_JSON_URL = "https://raw.githubusercontent.com/xsalazar/emoji-kitchen-backend/main/app/metadata.json"
ASSETS_DIR = Path(__file__).parent / "assets"
DATA_DIR = Path("data/emoji_mix")
CACHE_DIR = DATA_DIR / "cache"  # 缓存目录
METADATA_DIR = DATA_DIR / "metadata"  # 元数据目录

# 文件路径
FALLBACK_METADATA_FILE = ASSETS_DIR / "emojiData.json"  # 只读的回退文件保留在assets目录
UPDATED_METADATA_FILE = METADATA_DIR / "update.json"  # 更新的文件放在data目录
BACKUP_METADATA_FILE = METADATA_DIR / "update.backup.json"  # 备份也放在data目录

# API URL 模板
EMOJI_KITCHEN_API_URL = "https://www.gstatic.com/android/keyboard/emojikitchen/{date}/u{left_emoji}/u{left_emoji}_u{right_emoji}.png"


# 确保目录存在
def ensure_directory_exists(path: Path) -> None:
    """确保指定路径的目录存在"""
    if path.suffix:  # 如果是文件路径，检查父目录
        if not path.parent.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
    else:  # 如果是目录路径直接创建
        if not path.exists():
            path.mkdir(parents=True, exist_ok=True)


# 确保所有目录存在
ensure_directory_exists(CACHE_DIR)
ensure_directory_exists(ASSETS_DIR)
ensure_directory_exists(METADATA_DIR)


# 缓存文件名处理
def generate_cache_filename(left_emoji: str, right_emoji: str) -> str:
    """生成缓存文件名，确保相同的emoji组合生成相同的文件名"""
    left_code = emoji_to_codepoint(left_emoji)
    right_code = emoji_to_codepoint(right_emoji)
    # 排序确保一致性
    if left_code > right_code:
        left_code, right_code = right_code, left_code
    return f"{left_code}_{right_code}.png"


def is_emoji_cached(left_emoji: str, right_emoji: str) -> bool:
    """检查emoji组合是否已缓存"""
    cache_file = CACHE_DIR / generate_cache_filename(left_emoji, right_emoji)
    return cache_file.exists()


def get_emoji_cache_path(left_emoji: str, right_emoji: str) -> Path:
    """获取emoji组合的缓存文件路径"""
    return CACHE_DIR / generate_cache_filename(left_emoji, right_emoji)


# 下载更新的metadata数据
async def download_metadata_update() -> None:
    """下载最新的metadata.json文件，使用安全的备份机制"""
    # 直接使用临时文件对象而不是固定的TEMP_DIR
    with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as temp:
        temp_file = Path(temp.name)

    try:
        # 下载到临时文件
        async with ClientSession() as session:
            async with session.get(METADATA_JSON_URL, proxy=PROXY) as response:
                if response.status == 200:
                    async with aiofiles.open(temp_file, "wb") as file:
                        # 分块读取，避免内存问题
                        chunk_size = 5 * 1024 * 1024  # 5MB
                        async for chunk in response.content.iter_chunked(chunk_size):
                            await file.write(chunk)

                    # 验证下载文件是否为有效的 JSON
                    try:
                        with open(temp_file, "r", encoding="utf-8") as check_file:
                            json.load(check_file)  # 尝试解析 JSON

                        # 备份当前文件（如果存在）
                        if UPDATED_METADATA_FILE.exists():
                            shutil.copy2(UPDATED_METADATA_FILE, BACKUP_METADATA_FILE)
                            logger.debug("[EmojiMix] 已创建现有metadata文件的备份")

                        # 将临时文件移动到正式位置
                        ensure_directory_exists(UPDATED_METADATA_FILE.parent)
                        shutil.copy2(temp_file, UPDATED_METADATA_FILE)
                        logger.success("[EmojiMix] metadata.json 更新成功")
                        return
                    except JSONDecodeError:
                        logger.error("[EmojiMix] 下载的metadata.json不是有效的JSON格式")
                        if BACKUP_METADATA_FILE.exists():
                            logger.info("[EmojiMix] 正在恢复之前的备份...")
                            shutil.copy2(BACKUP_METADATA_FILE, UPDATED_METADATA_FILE)
                        return
                else:
                    logger.error(
                        f"[EmojiMix] 下载metadata.json失败，状态码: {response.status}"
                    )
                    return
    except asyncio.TimeoutError:
        logger.error("[EmojiMix] 下载metadata.json超时")
    except ClientError as error:
        logger.error(f"[EmojiMix] 网络请求失败: {error}")
    except Exception as error:
        logger.error(f"[EmojiMix] metadata.json 下载失败: {error}")
    finally:
        # 无论成功与否，都清理临时文件
        if temp_file.exists():
            temp_file.unlink()


# 解析metadata数据
def parse_metadata_file(file_path: Path) -> List[Tuple[str, str, str]]:
    """解析metadata.json文件，提取emoji组合数据"""
    ensure_directory_exists(file_path)
    emoji_combinations: List[Tuple[str, str, str]] = []

    try:
        with open(file_path, "r", encoding="utf-8") as file:
            json_data = json.load(file)
            logger.debug(f"加载JSON数据: {file_path}")

            data_dict = json_data.get("data", {})
            if not isinstance(data_dict, dict):
                logger.error(f"预期'data'是字典类型，实际是 {type(data_dict)}")
                return emoji_combinations

            for emoji_key, emoji_entry in data_dict.items():
                combinations = emoji_entry.get("combinations", {})
                if not isinstance(combinations, dict):
                    logger.error(
                        f"预期'combinations'是字典类型，在'{emoji_key}'中实际是 {type(combinations)}"
                    )
                    continue

                for combo_key, combo_list in combinations.items():
                    if not isinstance(combo_list, list):
                        logger.error(
                            f"预期组合列表是list类型，对于键'{combo_key}'实际是 {type(combo_list)}"
                        )
                        continue

                    for pair in combo_list:
                        if isinstance(pair, dict):
                            left = pair.get("leftEmojiCodepoint")
                            right = pair.get("rightEmojiCodepoint")
                            date = pair.get("date")

                            if left and right and date:
                                emoji_combinations.append((left, right, date))
                            else:
                                logger.error(f"组合数据不完整: {pair}")
                        else:
                            logger.warning(f"跳过非字典类型数据'{combo_key}': {pair}")
    except FileNotFoundError:
        logger.warning(f"[EmojiMix] 文件不存在: {file_path}")
    except JSONDecodeError:
        logger.error(f"[EmojiMix] JSON解析失败: {file_path}")

    return emoji_combinations


# 加载emoji组合数据，包含备份恢复机制
def load_emoji_combinations() -> List[Tuple[str, str, str]]:
    """加载emoji组合数据，如果主文件损坏则尝试从备份恢复"""
    # 尝试从主文件加载
    try:
        combinations = parse_metadata_file(UPDATED_METADATA_FILE)
        if combinations:
            return combinations
    except (FileNotFoundError, JSONDecodeError, KeyError) as e:
        logger.warning(f"[EmojiMix] 主metadata文件读取失败: {e}")

    # 尝试从备份文件加载
    try:
        if BACKUP_METADATA_FILE.exists():
            logger.info("[EmojiMix] 尝试从备份文件加载数据...")
            combinations = parse_metadata_file(BACKUP_METADATA_FILE)
            if combinations:
                # 恢复备份到主文件
                shutil.copy2(BACKUP_METADATA_FILE, UPDATED_METADATA_FILE)
                logger.info("[EmojiMix] 已从备份文件恢复metadata")
                return combinations
    except (JSONDecodeError, KeyError) as e:
        logger.warning(f"[EmojiMix] 备份metadata文件读取失败: {e}")

    # 如果主文件和备份都失败，使用内置的备用文件
    logger.warning("[EmojiMix] 使用内置备用metadata数据")
    return parse_metadata_file(FALLBACK_METADATA_FILE)


# 加载emoji组合数据
EMOJI_COMBINATIONS: List[Tuple[str, str, str]] = load_emoji_combinations()


# Emoji处理函数
def codepoint_to_emoji(code_point: str) -> str:
    """将codepoint转换为emoji字符"""
    if "-" not in code_point:
        return chr(int(code_point, 16))
    parts = code_point.split("-")
    return "".join(chr(int(part, 16)) for part in parts)


def emoji_to_codepoint(emoji: str) -> str:
    """将emoji字符转换为codepoint"""
    if len(emoji) == 1:
        return f"{ord(emoji):x}"
    return "-".join(f"{ord(char):x}" for char in emoji)


def collect_all_emojis() -> Set[str]:
    """获取所有可用的emoji"""
    emoji_set = set()
    for left, right, _ in EMOJI_COMBINATIONS:
        emoji_set.add(codepoint_to_emoji(left))
        emoji_set.add(codepoint_to_emoji(right))
    return emoji_set


# 所有可用的emoji集合
ALL_EMOJIS: Set[str] = collect_all_emojis()


# 查询函数
def get_mix_emoji_url(left_emoji: str, right_emoji: str) -> Optional[str]:
    """获取emoji组合的图片URL"""
    left_code = emoji_to_codepoint(left_emoji)
    right_code = emoji_to_codepoint(right_emoji)

    for left_cp, right_cp, date in EMOJI_COMBINATIONS:
        if (left_cp == left_code and right_cp == right_code) or (
            left_cp == right_code and right_cp == left_code
        ):
            # 替换连字符以匹配API格式
            formatted_left = left_cp.replace("-", "-u")
            formatted_right = right_cp.replace("-", "-u")
            return EMOJI_KITCHEN_API_URL.format(
                date=date, left_emoji=formatted_left, right_emoji=formatted_right
            )
    return None


def get_available_pairs(emoji: str) -> Set[str]:
    """获取与指定emoji可以组合的其他emoji"""
    emoji_code = emoji_to_codepoint(emoji)
    compatible_pairs = set()

    for left_cp, right_cp, _ in EMOJI_COMBINATIONS:
        if left_cp == emoji_code:
            compatible_pairs.add(codepoint_to_emoji(right_cp))
        elif right_cp == emoji_code:
            compatible_pairs.add(codepoint_to_emoji(left_cp))

    return compatible_pairs
