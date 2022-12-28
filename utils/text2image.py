import hashlib
import asyncio

from io import BytesIO
from pathlib import Path
from loguru import logger
from datetime import datetime, timedelta
from PIL import Image, ImageFont, ImageDraw

from .strings import get_cut_str

font_file = "./statics/fonts/sarasa-mono-sc-semibold.ttf"
try:
    font = ImageFont.truetype(font_file, 22)
except OSError:
    logger.error(
        f"未找到字体文件：{font_file}，请前往 https://github.com/djkcyl/ABot-Resource/releases/tag/Font 进行下载后解压至 ABot 根目录"
    )
    exit(1)
cache = Path("./cache/t2i")
cache.mkdir(exist_ok=True, parents=True)


async def create_image(text: str, cut=64) -> bytes:
    return await asyncio.to_thread(_cache, text, cut)


def _cache(text: str, cut: int) -> bytes:
    str_hash = hashlib.md5(text.encode("utf-8")).hexdigest()
    cache.joinpath(str_hash[:2]).mkdir(exist_ok=True)
    cache_file = cache.joinpath(f"{str_hash}.jpg")
    if cache_file.exists():
        logger.info(f"T2I Cache hit: {str_hash}")
    else:
        cache_file.write_bytes(_create_image(text, cut))

    return cache_file.read_bytes()


def _create_image(text: str, cut: int) -> bytes:
    cut_str = "\n".join(get_cut_str(text, cut))
    textx, texty = font.getsize_multiline(cut_str)
    image = Image.new("RGB", (textx + 40, texty + 40), (235, 235, 235))
    draw = ImageDraw.Draw(image)
    draw.text((20, 20), cut_str, font=font, fill=(31, 31, 33))
    imageio = BytesIO()
    image.save(
        imageio,
        format="JPEG",
        quality=90,
        subsampling=2,
        qtables="web_high",
    )
    return imageio.getvalue()


def delete_old_cache():
    cache_files = cache.glob("*")
    i = 0
    r = 0
    for cache_file in cache_files:
        i += 1
        if (
            cache_file.stat().st_mtime
            < ((datetime.now() - timedelta(days=14)).timestamp())
            and cache_file.is_file()
        ):
            cache_file.unlink()
            r += 1
    return i, r


delete_old_cache()
