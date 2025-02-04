from io import BytesIO
from pathlib import Path

import imageio.v2 as imageio
from PIL import Image, ImageFont, ImageDraw


def calculate_text_size(font: ImageFont.FreeTypeFont, text: str) -> tuple[int, int]:
    bbox = font.getbbox(text)
    return int(bbox[2] - bbox[0]), int(bbox[3] - bbox[1])


ENG_FONT = ImageFont.truetype(
    str(Path.cwd() / "statics" / "fonts" / "Alte DIN 1451 Mittelschrift gepraegt Regular.ttf"), 36
)
CHN_FONT = ImageFont.truetype(
    str(Path.cwd() / "statics" / "fonts" / "字魂59号-创粗黑.ttf"), 36
)
COUNTING_FONT = ImageFont.truetype(
    str(Path.cwd() / "statics" / "fonts" / "Alte DIN 1451 Mittelschrift gepraegt Regular.ttf"), 110
)
BOTTOM_FONT = ImageFont.truetype(
    str(Path.cwd() / "statics" / "fonts" / "Alte DIN 1451 Mittelschrift gepraegt Regular.ttf"), 18
)


def gen_counting_down(
        top_text: str, start_text: str, counting: str, end_text: str, bottom_text: str, rgba: bool = False
) -> bytes:
    top_size = calculate_text_size(CHN_FONT, top_text)
    start_size = calculate_text_size(CHN_FONT, start_text)
    counting_size = calculate_text_size(COUNTING_FONT, counting)
    end_size = calculate_text_size(CHN_FONT, end_text)

    bottom_texts = bottom_text.split("\n")
    bottom_widths = [calculate_text_size(BOTTOM_FONT, t)[0] for t in bottom_texts]
    bottom_size = (max(bottom_widths), len(bottom_texts) * 26)

    top_over_width = top_size[0] - start_size[0] - 20
    if top_over_width < 0:
        top_over_width = 0
    start_over_width = start_size[0] - top_size[0] if start_size[0] >= top_size[0] else 0
    width = max([
        max(top_size[0], start_size[0]) + 20 + counting_size[0] + end_size[0],
        top_over_width + bottom_size[0]
    ]) + 60
    height = 104 + 46 * len(bottom_texts) + 40

    if rgba:
        img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    else:
        img = Image.new("RGB", (width, height), (0, 0, 0))
    draw = ImageDraw.Draw(img)

    rec_start = 20 if start_over_width > 0 else top_over_width
    rec_box = (rec_start + 30, 70, rec_start + 34, 150)
    start_start = rec_start + 40
    count_start = rec_start + 46 + start_size[0] if start_over_width > 0 else start_over_width + top_size[0] + 30
    top_start = count_start - top_size[0] - 6 if start_over_width > 0 else 20
    if start_over_width == 0 and top_over_width == 0:
        count_start = start_start + 6 + start_size[0]
        top_start = start_start
    end_start = count_start + counting_size[0] + 6 if start_over_width > 0 else top_size[0] + 40 + counting_size[0]
    if start_over_width == 0 and top_over_width == 0:
        end_start += 8

    draw.text((top_start, 20), top_text, fill="#FFFFFF", font=CHN_FONT)
    draw.text((count_start, -5), counting, fill="#FF0000", font=COUNTING_FONT)
    draw.text((start_start, 66), start_text, fill="#FFFFFF", font=CHN_FONT)
    draw.text((end_start, 66), end_text, fill="#FFFFFF", font=CHN_FONT)
    draw.rectangle(rec_box, fill="#FF0000")
    for i, t in enumerate(bottom_texts):
        draw.text((rec_start + 44, 106 + i * 24), t, fill="#FFFFFF", font=BOTTOM_FONT)

    bytesio = BytesIO()
    img.save(bytesio, format="png")
    return bytesio.getvalue()


def gen_gif(
        top_text: str, start_text: str, counting: str, end_text: str, bottom_text: str, rgba: bool = False
) -> bytes:
    counting_int = int(counting)
    frames = [
        imageio.imread(
            gen_counting_down(top_text, start_text, str(i), end_text, bottom_text, rgba)
        )
        for i in range(counting_int, -1, -1)
    ]
    bytesio = BytesIO()
    imageio.mimsave(bytesio, frames, format="GIF", duration=1)
    return bytesio.getvalue()
