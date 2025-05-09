import asyncio
from decimal import ROUND_HALF_UP, Decimal
from io import BytesIO
from math import radians, tan
from pathlib import Path

import numpy as np
import PIL.Image
from graia.ariadne.app import Ariadne
from graia.ariadne.event.message import Group, GroupMessage
from graia.ariadne.message.chain import MessageChain
from graia.ariadne.message.element import Image, Source
from graia.ariadne.message.parser.twilight import (
    RegexMatch,
    RegexResult,
    SpacePolicy,
    Twilight,
)
from graia.ariadne.util.saya import decorate, dispatch, listen
from graia.saya import Channel
from PIL import ImageDraw, ImageFont

from core.control import Distribute, FrequencyLimitation, Function, Permission
from core.models import saya_model


def _round(f, r=ROUND_HALF_UP):
    return int(Decimal(str(f)).quantize(Decimal("0"), rounding=r))


def rgb(r, g, b):
    return (r, g, b)


LEFT_PART_VERTICAL_BLANK_MULTIPLY_FONT_HEIGHT = 2
LEFT_PART_HORIZONTAL_BLANK_MULTIPLY_FONT_WIDTH = 1 / 4
RIGHT_PART_VERTICAL_BLANK_MULTIPLY_FONT_HEIGHT = 1
RIGHT_PART_HORIZONTAL_BLANK_MULTIPLY_FONT_WIDTH = 1 / 4
RIGHT_PART_RADII = 10
BG_COLOR = "#000000"
BOX_COLOR = "#F7971D"
LEFT_TEXT_COLOR = "#FFFFFF"
RIGHT_TEXT_COLOR = "#000000"
FONT_SIZE = 50

upper_font_path = str(Path.cwd() / "statics" / "fonts" / "NotoSansCJKSC-Black.ttf")
downer_font_path = str(Path.cwd() / "statics" / "fonts" / "NotoSerifCJKSC-Black.ttf")

module_controller = saya_model.get_module_controller()
channel = Channel.current()
channel.meta["name"] = "StylePictureGenerator"
channel.meta["author"] = "SAGIRI-kawaii"
channel.meta["description"] = (
    "一个可以生成不同风格图片的插件，在群中发送 `[5000兆|ph|yt] 文字1 文字2` 即可"
)
channel.metadata = module_controller.get_metadata_from_path(Path(__file__))


@listen(GroupMessage)
@dispatch(
    Twilight(
        [
            RegexMatch("(5000兆|ph|yt)").space(SpacePolicy.FORCE) @ "logo_type",
            RegexMatch(r"[^\s]+"),
            RegexMatch(r"[^\s]+"),
        ]
    )
)
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module, 3),
    Permission.group_require(channel.metadata.level),
    Permission.user_require(Permission.User),
)
async def style_picture_generator(
    app: Ariadne,
    message: MessageChain,
    group: Group,
    source: Source,
    logo_type: RegexResult,
):
    logo_type = logo_type.result.display
    if logo_type == "5000兆":
        await app.send_group_message(
            group,
            await asyncio.to_thread(gosencho_en_hoshi_style_image_generator, message),
            quote=source,
        )
    elif logo_type == "ph":
        await app.send_group_message(
            group,
            await asyncio.to_thread(pornhub_style_image_generator, message),
            quote=source,
        )
    elif logo_type == "yt":
        await app.send_group_message(
            group,
            await asyncio.to_thread(youtube_style_image_generator, message),
            quote=source,
        )


def gosencho_en_hoshi_style_image_generator(message: MessageChain) -> MessageChain:
    try:
        _, left_text, right_text = message.display.split(" ")
        try:
            img_byte = BytesIO()
            GoSenChoEnHoShiStyleUtils.gen_image(
                word_a=left_text, word_b=right_text
            ).save(img_byte, format="PNG")
            return MessageChain([Image(data_bytes=img_byte.getvalue())])
        except TypeError:
            return MessageChain("不支持的内容！不要给我一些稀奇古怪的东西！")
    except ValueError:
        return MessageChain("参数非法！使用格式：5000兆 text1 text2")


def pornhub_style_image_generator(message: MessageChain) -> MessageChain:
    message_text = message.display
    if "/" in message_text or "\\" in message_text:
        return MessageChain("不支持 '/' 与 '\\' ！")
    try:
        _, left_text, right_text = message_text.split(" ")
    except ValueError:
        return MessageChain("格式错误！使用方法：ph left right!")
    try:
        return PornhubStyleUtils.make_ph_style_logo(left_text, right_text)
    except OSError as e:
        if "[Errno 22] Invalid argument:" in str(e):
            return MessageChain("非法字符！")
        else:
            raise e


def youtube_style_image_generator(message: MessageChain) -> MessageChain:
    message_text = message.display
    if "/" in message_text or "\\" in message_text:
        return MessageChain("不支持 '/' 与 '\\' ！")
    try:
        _, left_text, right_text = message_text.split(" ")
    except ValueError:
        return MessageChain("格式错误！使用方法：ph left right!")
    try:
        return YoutubeStyleUtils.make_yt_style_logo(left_text, right_text)
    except OSError as e:
        if "[Errno 22] Invalid argument:" in str(e):
            return MessageChain("非法字符！")


class GoSenChoEnHoShiStyleUtils:
    @staticmethod
    def get_gradient_2d(start, stop, width, height, is_horizontal=False):
        if is_horizontal:
            return np.tile(np.linspace(start, stop, width), (height, 1))
        else:
            return np.tile(np.linspace(start, stop, height), (width, 1)).T

    @staticmethod
    def getTextWidth(text, font, width=100, height=500, recursive=False):
        step = 100
        img = PIL.Image.new("L", (width, height))
        draw = ImageDraw.Draw(img)
        draw.text((0, 0), text, font=font, fill=255)
        box = img.getbbox()
        if box[2] < width - step or (recursive and box[2] == width - step):
            return box[2]
        else:
            return GoSenChoEnHoShiStyleUtils.getTextWidth(
                text=text, font=font, width=width + step, height=height, recursive=True
            )

    @staticmethod
    def get_gradient_3d(
        width, height, start_list, stop_list, is_horizontal_list=(False, False, False)
    ):
        result = np.zeros((height, width, len(start_list)), dtype=float)
        for i, (start, stop, is_horizontal) in enumerate(
            zip(start_list, stop_list, is_horizontal_list)
        ):
            result[:, :, i] = GoSenChoEnHoShiStyleUtils.get_gradient_2d(
                start, stop, width, height, is_horizontal
            )
        return result

    @staticmethod
    def createLinearGradient(steps, width, height):
        result = np.zeros((0, width, len(steps[0])), dtype=float)
        for i, k in enumerate(steps.keys()):
            if i == 0:
                continue
            pk = list(steps.keys())[i - 1]
            h = _round(height * (k - pk))
            array = GoSenChoEnHoShiStyleUtils.get_gradient_3d(
                width, h, steps[pk], steps[k]
            )
            result = np.vstack([result, array])
        return result

    @staticmethod
    def genBaseImage(width=1500, height=150):
        downerSilverArray = GoSenChoEnHoShiStyleUtils.createLinearGradient(
            {
                0.0: rgb(0, 15, 36),
                0.10: rgb(255, 255, 255),
                0.18: rgb(55, 58, 59),
                0.25: rgb(55, 58, 59),
                0.5: rgb(200, 200, 200),
                0.75: rgb(55, 58, 59),
                0.85: rgb(25, 20, 31),
                0.91: rgb(240, 240, 240),
                0.95: rgb(166, 175, 194),
                1: rgb(50, 50, 50),
            },
            width=width,
            height=height,
        )
        goldArray = GoSenChoEnHoShiStyleUtils.createLinearGradient(
            {
                0: rgb(253, 241, 0),
                0.25: rgb(245, 253, 187),
                0.4: rgb(255, 255, 255),
                0.75: rgb(253, 219, 9),
                0.9: rgb(127, 53, 0),
                1: rgb(243, 196, 11),
            },
            width=width,
            height=height,
        )
        redArray = GoSenChoEnHoShiStyleUtils.createLinearGradient(
            {
                0: rgb(230, 0, 0),
                0.5: rgb(123, 0, 0),
                0.51: rgb(240, 0, 0),
                1: rgb(5, 0, 0),
            },
            width=width,
            height=height,
        )
        strokeRedArray = GoSenChoEnHoShiStyleUtils.createLinearGradient(
            {
                0: rgb(255, 100, 0),
                0.5: rgb(123, 0, 0),
                0.51: rgb(240, 0, 0),
                1: rgb(5, 0, 0),
            },
            width=width,
            height=height,
        )
        silver2Array = GoSenChoEnHoShiStyleUtils.createLinearGradient(
            {
                0: rgb(245, 246, 248),
                0.15: rgb(255, 255, 255),
                0.35: rgb(195, 213, 220),
                0.5: rgb(160, 190, 201),
                0.51: rgb(160, 190, 201),
                0.52: rgb(196, 215, 222),
                1.0: rgb(255, 255, 255),
            },
            width=width,
            height=height,
        )
        navyArray = GoSenChoEnHoShiStyleUtils.createLinearGradient(
            {
                0: rgb(16, 25, 58),
                0.03: rgb(255, 255, 255),
                0.08: rgb(16, 25, 58),
                0.2: rgb(16, 25, 58),
                1: rgb(16, 25, 58),
            },
            width=width,
            height=height,
        )
        result = {
            "downerSilver": PIL.Image.fromarray(np.uint8(downerSilverArray)).crop(
                (0, 0, width, height)
            ),
            "gold": PIL.Image.fromarray(np.uint8(goldArray)).crop(
                (0, 0, width, height)
            ),
            "red": PIL.Image.fromarray(np.uint8(redArray)).crop((0, 0, width, height)),
            "strokeRed": PIL.Image.fromarray(np.uint8(strokeRedArray)).crop(
                (0, 0, width, height)
            ),
            "silver2": PIL.Image.fromarray(np.uint8(silver2Array)).crop(
                (0, 0, width, height)
            ),
            "strokeNavy": PIL.Image.fromarray(np.uint8(navyArray)).crop(
                (0, 0, width, height)
            ),  # Width: 7
            "baseStrokeBlack": PIL.Image.new(
                "RGBA", (width, height), rgb(0, 0, 0)
            ).crop((0, 0, width, height)),
            # Width: 17
            "strokeBlack": PIL.Image.new("RGBA", (width, height), rgb(16, 25, 58)).crop(
                (0, 0, width, height)
            ),  # Width: 17
            "strokeWhite": PIL.Image.new(
                "RGBA", (width, height), rgb(221, 221, 221)
            ).crop((0, 0, width, height)),
            # Width: 8
            "baseStrokeWhite": PIL.Image.new(
                "RGBA", (width, height), rgb(255, 255, 255)
            ).crop((0, 0, width, height)),
            # Width: 8
        }
        for k in result:
            result[k].putalpha(255)
        return result

    @staticmethod
    def gen_image(
        word_a="5000兆円",
        word_b="欲しい!",
        default_width=1500,
        height=500,
        bg="white",
        subset=250,
        default_base=None,
    ):
        # width = max_width
        k = 0.8
        alpha = (0, 0, 0, 0)
        leftmargin = 50
        upmargin = 20
        font_upper = ImageFont.truetype(
            upper_font_path, _round(height * 0.35 * k) + upmargin
        )
        font_downer = ImageFont.truetype(
            downer_font_path, _round(height * 0.35 * k) + upmargin
        )

        # Prepare Width
        upper_width = (
            max(
                [
                    default_width,
                    GoSenChoEnHoShiStyleUtils.getTextWidth(
                        word_a,
                        font_upper,
                        width=default_width,
                        height=_round(height / 2),
                    ),
                ]
            )
            + 300
        )
        downer_width = (
            max(
                [
                    default_width,
                    GoSenChoEnHoShiStyleUtils.getTextWidth(
                        word_b,
                        font_upper,
                        width=default_width,
                        height=_round(height / 2),
                    ),
                ]
            )
            + 300
        )

        # Prepare base - Upper (if required)
        if default_width == upper_width:
            upper_base = default_base
        else:
            upper_base = GoSenChoEnHoShiStyleUtils.genBaseImage(
                width=upper_width + leftmargin, height=_round(height / 2) + upmargin
            )

        # Prepare base - Downer (if required)
        downer_base = GoSenChoEnHoShiStyleUtils.genBaseImage(
            width=downer_width + leftmargin, height=_round(height / 2) + upmargin
        )
        # if default_width == downer_width:
        #     downer_base = default_base
        # else:

        # Prepare mask - Upper
        upper_mask_base = PIL.Image.new(
            "L", (upper_width + leftmargin, _round(height / 2) + upmargin), 0
        )

        mask_img_upper = []
        upper_data = [
            [(4, 4), (4, 4), (0, 0), (0, 0), (2, -3), (0, -3), (0, -3), (0, -3)],
            [22, 20, 16, 10, 6, 6, 3, 0],
            [
                "baseStrokeBlack",
                "downerSilver",
                "baseStrokeBlack",
                "gold",
                "baseStrokeBlack",
                "baseStrokeWhite",
                "strokeRed",
                "red",
            ],
        ]
        for pos, stroke, color in zip(upper_data[0], upper_data[1], upper_data[2]):
            mask_img_upper.append(upper_mask_base.copy())
            mask_draw_upper = ImageDraw.Draw(mask_img_upper[-1])
            mask_draw_upper.text(
                (pos[0], pos[1]),
                word_a,
                font=font_upper,
                fill=255,
                stroke_width=_round(stroke * height / 500),
            )

        # Prepare mask - Downer
        downer_mask_base = PIL.Image.new(
            "L", (downer_width + leftmargin, _round(height / 2) + upmargin), 0
        )
        mask_img_downer = []
        downer_data = [
            [(5, 2), (5, 2), (0, 0), (0, 0), (0, 0), (0, -3)],
            [22, 19, 17, 8, 7, 0],
            [
                "baseStrokeBlack",
                "downerSilver",
                "strokeBlack",
                "strokeWhite",
                "strokeNavy",
                "silver2",
            ],
        ]
        for pos, stroke, color in zip(downer_data[0], downer_data[1], downer_data[2]):
            mask_img_downer.append(downer_mask_base.copy())
            mask_draw_downer = ImageDraw.Draw(mask_img_downer[-1])
            mask_draw_downer.text(
                (pos[0] + leftmargin, pos[1]),
                word_b,
                font=font_downer,
                fill=255,
                stroke_width=_round(stroke * height / 500),
            )

        # Draw text - Upper
        img_upper = PIL.Image.new("RGBA", (upper_width, _round(height / 2)), alpha)

        for i, (pos, stroke, color) in enumerate(
            zip(upper_data[0], upper_data[1], upper_data[2])
        ):
            img_upper_part = PIL.Image.new(
                "RGBA", (upper_width, _round(height / 2)), alpha
            )
            img_upper_part.paste(upper_base[color], (0, 0), mask=mask_img_upper[i])
            img_upper.alpha_composite(img_upper_part)

        # Draw text - Downer
        img_downer = PIL.Image.new(
            "RGBA", (downer_width + leftmargin, _round(height / 2)), alpha
        )
        for i, (pos, stroke, color) in enumerate(
            zip(downer_data[0], downer_data[1], downer_data[2])
        ):
            img_downer_part = PIL.Image.new(
                "RGBA", (downer_width + leftmargin, _round(height / 2)), alpha
            )
            img_downer_part.paste(downer_base[color], (0, 0), mask=mask_img_downer[i])
            img_downer.alpha_composite(img_downer_part)

        # tilt image
        tiltres = []
        angle = 20
        for img in [img_upper, img_downer]:
            dist = img.height * tan(radians(angle))
            data = (1, tan(radians(angle)), -dist, 0, 1, 0)
            imgc = img.crop((0, 0, img.width + dist, img.height))
            imgt = imgc.transform(imgc.size, PIL.Image.AFFINE, data, PIL.Image.BILINEAR)
            tiltres.append(imgt)

        # finish
        previmg = PIL.Image.new(
            "RGBA",
            (
                max([upper_width, downer_width]) + leftmargin + subset + 100,
                height + upmargin + 100,
            ),
            (255, 255, 255, 0),
        )
        previmg.alpha_composite(tiltres[0], (0, 50), (0, 0))
        if upper_width > downer_width + subset:
            previmg.alpha_composite(
                tiltres[1],
                (upper_width + subset - downer_width, _round(height / 2) + 50),
                (0, 0),
            )
        else:
            previmg.alpha_composite(
                tiltres[1], (subset, _round(height / 2) + 50), (0, 0)
            )
        croprange = previmg.getbbox()
        img = previmg.crop(croprange)
        final_image = PIL.Image.new("RGB", (img.size[0] + 100, img.size[1] + 100), bg)
        final_image.paste(img, (50, 50))

        return final_image


class PornhubStyleUtils:
    @staticmethod
    def create_left_part_img(text: str, font_size: int):
        font = ImageFont.truetype(
            str(Path.cwd() / "statics" / "fonts" / "ArialEnUnicodeBold.ttf"), font_size
        )
        font_width, font_height = font.getsize(text)
        offset_y = font.font.getsize(text)[1][1]
        blank_height = font_height * LEFT_PART_VERTICAL_BLANK_MULTIPLY_FONT_HEIGHT
        right_blank = int(
            font_width / len(text) * LEFT_PART_HORIZONTAL_BLANK_MULTIPLY_FONT_WIDTH
        )
        img_height = font_height + offset_y + blank_height * 2
        image_width = font_width + right_blank
        image_size = image_width, img_height
        image = PIL.Image.new("RGBA", image_size, BG_COLOR)
        draw = ImageDraw.Draw(image)
        draw.text((0, blank_height), text, fill=LEFT_TEXT_COLOR, font=font)
        return image

    @staticmethod
    def create_right_part_img(text: str, font_size: int):
        radii = RIGHT_PART_RADII
        font = ImageFont.truetype(
            str(Path.cwd() / "statics" / "fonts" / "ArialEnUnicodeBold.ttf"), font_size
        )
        font_width, font_height = font.getsize(text)
        offset_y = font.font.getsize(text)[1][1]
        blank_height = font_height * RIGHT_PART_VERTICAL_BLANK_MULTIPLY_FONT_HEIGHT
        left_blank = int(
            font_width / len(text) * RIGHT_PART_HORIZONTAL_BLANK_MULTIPLY_FONT_WIDTH
        )
        image_width = font_width + 2 * left_blank
        image_height = font_height + offset_y + blank_height * 2
        image = PIL.Image.new("RGBA", (image_width, image_height), BOX_COLOR)
        draw = ImageDraw.Draw(image)
        draw.text((left_blank, blank_height), text, fill=RIGHT_TEXT_COLOR, font=font)

        # 圆
        magnify_time = 10
        magnified_radii = radii * magnify_time
        circle = PIL.Image.new(
            "L", (magnified_radii * 2, magnified_radii * 2), 0
        )  # 创建一个黑色背景的画布
        draw = ImageDraw.Draw(circle)
        draw.ellipse(
            (0, 0, magnified_radii * 2, magnified_radii * 2), fill=255
        )  # 画白色圆形

        # 画4个角（将整圆分离为4个部分）
        magnified_alpha_width = image_width * magnify_time
        magnified_alpha_height = image_height * magnify_time
        alpha = PIL.Image.new("L", (magnified_alpha_width, magnified_alpha_height), 255)
        alpha.paste(
            circle.crop((0, 0, magnified_radii, magnified_radii)), (0, 0)
        )  # 左上角
        alpha.paste(
            circle.crop((magnified_radii, 0, magnified_radii * 2, magnified_radii)),
            (magnified_alpha_width - magnified_radii, 0),
        )  # 右上角
        alpha.paste(
            circle.crop(
                (
                    magnified_radii,
                    magnified_radii,
                    magnified_radii * 2,
                    magnified_radii * 2,
                )
            ),
            (
                magnified_alpha_width - magnified_radii,
                magnified_alpha_height - magnified_radii,
            ),
        )  # 右下角
        alpha.paste(
            circle.crop((0, magnified_radii, magnified_radii, magnified_radii * 2)),
            (0, magnified_alpha_height - magnified_radii),
        )  # 左下角
        alpha = alpha.resize((image_width, image_height), PIL.Image.ANTIALIAS)
        image.putalpha(alpha)
        return image

    @staticmethod
    def combine_img(left_text: str, right_text, font_size: int) -> bytes:
        left_img = PornhubStyleUtils.create_left_part_img(left_text, font_size)
        right_img = PornhubStyleUtils.create_right_part_img(right_text, font_size)
        blank = 30
        bg_img_width = left_img.width + right_img.width + blank * 2
        bg_img_height = left_img.height
        bg_img = PIL.Image.new("RGBA", (bg_img_width, bg_img_height), BG_COLOR)
        bg_img.paste(left_img, (blank, 0))
        bg_img.paste(
            right_img,
            (blank + left_img.width, int((bg_img_height - right_img.height) / 2)),
            mask=right_img,
        )
        byte_io = BytesIO()
        bg_img.save(byte_io, format="PNG")
        return byte_io.getvalue()

    @staticmethod
    def make_ph_style_logo(left_text: str, right_text: str) -> MessageChain:
        return MessageChain(
            Image(
                data_bytes=PornhubStyleUtils.combine_img(
                    left_text, right_text, FONT_SIZE
                )
            )
        )


class YoutubeStyleUtils:
    BG_COLOR = "#FFFFFF"
    BOX_COLOR = "#FF0000"
    LEFT_TEXT_COLOR = "#000000"
    RIGHT_TEXT_COLOR = "#FFFFFF"

    @staticmethod
    def create_left_part_img(text: str, font_size: int):
        font = ImageFont.truetype(
            str(Path.cwd() / "statics" / "fonts" / "ArialEnUnicodeBold.ttf"), font_size
        )
        font_width, font_height = font.getsize(text)
        offset_y = font.font.getsize(text)[1][1]
        blank_height = font_height * LEFT_PART_VERTICAL_BLANK_MULTIPLY_FONT_HEIGHT
        right_blank = int(
            font_width / len(text) * LEFT_PART_HORIZONTAL_BLANK_MULTIPLY_FONT_WIDTH
        )
        img_height = font_height + offset_y + blank_height * 2
        image_width = font_width + right_blank
        image_size = image_width, img_height
        image = PIL.Image.new("RGBA", image_size, YoutubeStyleUtils.BG_COLOR)
        draw = ImageDraw.Draw(image)
        draw.text(
            (0, blank_height), text, fill=YoutubeStyleUtils.LEFT_TEXT_COLOR, font=font
        )
        return image

    @staticmethod
    def create_right_part_img(text: str, font_size: int):
        radii = RIGHT_PART_RADII
        font = ImageFont.truetype(
            str(Path.cwd() / "statics" / "fonts" / "ArialEnUnicodeBold.ttf"), font_size
        )
        font_width, font_height = font.getsize(text)
        offset_y = font.font.getsize(text)[1][1]
        blank_height = font_height * RIGHT_PART_VERTICAL_BLANK_MULTIPLY_FONT_HEIGHT
        left_blank = int(
            font_width / len(text) * RIGHT_PART_HORIZONTAL_BLANK_MULTIPLY_FONT_WIDTH
        )
        image_width = font_width + 2 * left_blank
        image_height = font_height + offset_y + blank_height * 2
        image = PIL.Image.new(
            "RGBA", (image_width, image_height), YoutubeStyleUtils.BOX_COLOR
        )
        draw = ImageDraw.Draw(image)
        draw.text(
            (left_blank, blank_height),
            text,
            fill=YoutubeStyleUtils.RIGHT_TEXT_COLOR,
            font=font,
        )

        # 圆
        magnify_time = 10
        magnified_radii = radii * magnify_time
        circle = PIL.Image.new(
            "L", (magnified_radii * 2, magnified_radii * 2), 1
        )  # 创建一个黑色背景的画布
        draw = ImageDraw.Draw(circle)
        draw.ellipse(
            (0, 0, magnified_radii * 2, magnified_radii * 2), fill=255
        )  # 画白色圆形

        # 画4个角（将整圆分离为4个部分）
        magnified_alpha_width = image_width * magnify_time
        magnified_alpha_height = image_height * magnify_time
        alpha = PIL.Image.new("L", (magnified_alpha_width, magnified_alpha_height), 255)
        alpha.paste(
            circle.crop((0, 0, magnified_radii, magnified_radii)), (0, 0)
        )  # 左上角
        alpha.paste(
            circle.crop((magnified_radii, 0, magnified_radii * 2, magnified_radii)),
            (magnified_alpha_width - magnified_radii, 0),
        )  # 右上角
        alpha.paste(
            circle.crop(
                (
                    magnified_radii,
                    magnified_radii,
                    magnified_radii * 2,
                    magnified_radii * 2,
                )
            ),
            (
                magnified_alpha_width - magnified_radii,
                magnified_alpha_height - magnified_radii,
            ),
        )  # 右下角
        alpha.paste(
            circle.crop((0, magnified_radii, magnified_radii, magnified_radii * 2)),
            (0, magnified_alpha_height - magnified_radii),
        )  # 左下角
        alpha = alpha.resize((image_width, image_height), PIL.Image.ANTIALIAS)
        image.putalpha(alpha)
        return image

    @staticmethod
    def combine_img(left_text: str, right_text, font_size: int) -> bytes:
        left_img = YoutubeStyleUtils.create_left_part_img(left_text, font_size)
        right_img = YoutubeStyleUtils.create_right_part_img(right_text, font_size)
        blank = 30
        bg_img_width = left_img.width + right_img.width + blank * 2
        bg_img_height = left_img.height
        bg_img = PIL.Image.new(
            "RGBA", (bg_img_width, bg_img_height), YoutubeStyleUtils.BG_COLOR
        )
        bg_img.paste(left_img, (blank, 0))
        bg_img.paste(
            right_img,
            (blank + left_img.width, int((bg_img_height - right_img.height) / 2)),
            mask=right_img,
        )
        byte_io = BytesIO()
        bg_img.save(byte_io, format="PNG")
        return byte_io.getvalue()

    @staticmethod
    def make_yt_style_logo(left_text: str, right_text: str) -> MessageChain:
        return MessageChain(
            [
                Image(
                    data_bytes=YoutubeStyleUtils.combine_img(
                        left_text, right_text, FONT_SIZE
                    )
                )
            ]
        )
