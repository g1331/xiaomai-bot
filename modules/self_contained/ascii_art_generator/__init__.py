import io
from pathlib import Path

import aiohttp
from creart import create
from graia.ariadne.app import Ariadne
from graia.ariadne.event.message import GroupMessage
from graia.ariadne.message.chain import MessageChain
from graia.ariadne.message.element import Image, Source
from graia.ariadne.message.parser.twilight import (
    Twilight,
    ElementMatch,
    ElementResult,
    SpacePolicy,
    UnionMatch,
    ArgumentMatch,
    ArgResult,
)
from graia.ariadne.model import Group
from graia.ariadne.util.saya import listen, decorate, dispatch
from graia.saya import Channel, Saya

from core.config import GlobalConfig
from core.control import Permission, Function, FrequencyLimitation, Distribute
from core.models import saya_model
from .generator import ASCIIArtGenerator

module_controller = saya_model.get_module_controller()
global_config = create(GlobalConfig)
saya = Saya.current()
# 获取属于这个模组的实例
channel = Channel.current()
channel.meta["name"] = "字符画生成器"
channel.meta["description"] = "使用图片生成字符画"
channel.meta["author"] = "13"
channel.metadata = module_controller.get_metadata_from_path(Path(__file__))


@listen(GroupMessage)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level),
    Permission.user_require(Permission.User, if_noticed=True),
)
@dispatch(
    Twilight(
        [
            UnionMatch("-ascii", "字符画").space(SpacePolicy.PRESERVE),
            ArgumentMatch(
                "-density",
                "-d",
                type=str,
                choices=["low", "medium", "high"],
                optional=True,
            )
            @ "density",
            ArgumentMatch("-brightness", "-b", type=float, optional=True)
            @ "brightness",
            ArgumentMatch("-contrast", "-c", type=float, optional=True) @ "contrast",
            ArgumentMatch("-invert", "-i", action="store_true", optional=True)
            @ "invert",
            ArgumentMatch("-width", "-w", type=int, optional=True) @ "width",
            ElementMatch(Image, optional=False) @ "img",
        ]
    )
)
async def ascii_art(
    app: Ariadne,
    group: Group,
    source: Source,
    density: ArgResult,
    brightness: ArgResult,
    contrast: ArgResult,
    invert: ArgResult,
    width: ArgResult,
    img: ElementResult,
):
    # 设置默认参数
    density_value = density.result or None
    brightness_value = brightness.result if brightness.matched else 1.0
    contrast_value = contrast.result if contrast.matched else 1.5
    invert_value = invert.matched  # 布尔值
    width_value = width.result if width.matched else 160

    # 获取图片地址
    img: Image = img.result
    img_url = img.url

    # 下载图片数据
    async with aiohttp.ClientSession() as session:
        async with session.get(img_url) as resp:
            image_data = await resp.read()

    # 创建 ASCIIArtGenerator 实例，传入参数
    _generator = ASCIIArtGenerator(
        width=width_value,
        density=density_value,
        contrast_factor=contrast_value,
        brightness=brightness_value,
        invert=invert_value,
    )

    # 处理图片
    try:
        ascii_image = await _generator.image_to_ascii_image(image_data)
    except Exception as e:
        await app.send_group_message(
            group, MessageChain(f"生成字符画时出错：{e}"), quote=source
        )
        return

    # 保存 ASCII 图像到缓冲区
    buffer = io.BytesIO()
    if isinstance(ascii_image, list):
        # 处理 GIF 动图
        ascii_image[0].save(
            buffer,
            format="GIF",
            save_all=True,
            append_images=ascii_image[1:],
            loop=0,
            duration=100,
            optimize=True,
        )
    else:
        ascii_image.save(buffer, format="PNG")
    buffer.seek(0)
    await app.send_group_message(
        group, MessageChain(Image(data_bytes=buffer.getvalue())), quote=source
    )
