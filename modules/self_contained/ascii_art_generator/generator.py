import asyncio
import io
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont


class ASCIIArtGenerator:
    CHAR_SETS = {
        "low": "@%#*+=-:. ",
        "medium": "@#W$9876543210?!abc;:+=-,._ ",
        "high": "@$%B&WM#*haokbdpqwmZO0QCLJUYXzcvunxrjft/\\|)(1}{][?_-+~i!lI;:,\"^`'. ",
    }

    # 线程池执行器，用于处理同步的PIL操作
    _executor = ThreadPoolExecutor()

    # 锁，确保同一时刻只能处理一个GIF任务
    _gif_lock = asyncio.Lock()

    def __init__(
        self,
        width: int = 160,
        font_path: str | None = None,
        font_size: int = 10,
        density: str | None = None,  # 允许density为None
        contrast_factor: float = 1.5,
        brightness: float = 1.0,
        invert: bool = False,
        max_frames: int = 60,  # 默认最大帧数设置为60
    ) -> None:
        """
        初始化ASCIIArtGenerator。

        :param width: ASCII艺术图像的宽度（字符数）
        :param font_path: 字体文件的路径，默认为None，使用默认字体
        :param font_size: 字体大小
        :param density: 字符密度，可以是"low"、"medium"、"high"或其他。默认为None，根据图像分辨率自动选择
        :param contrast_factor: 对比度增强因子
        :param brightness: 亮度调整因子
        :param invert: 是否反转字符集
        :param max_frames: 处理动画GIF时的最大帧数，默认为60
        """
        self.width: int = width
        self.font_path: str | None = font_path
        self.font_size: int = font_size
        self.contrast_factor: float = contrast_factor
        self.brightness: float = brightness
        self.invert: bool = invert
        self.density: str | None = density  # 允许density为None
        self.max_frames: int = max_frames

        # 如果density未指定，根据分辨率自动选择
        self.char_set: str | None = None  # 初始为None

        # 预加载字体
        try:
            self.font: ImageFont.FreeTypeFont = (
                ImageFont.truetype(self.font_path, self.font_size)
                if self.font_path
                else ImageFont.load_default()
            )
        except OSError:
            self.font = ImageFont.load_default()

        # 计算字符宽高
        bbox: tuple[int, int, int, int] = self.font.getbbox("A")
        self.char_width: int = bbox[2] - bbox[0]
        self.char_height: int = bbox[3] - bbox[1]

    def gray_to_char(self, gray: float) -> str:
        """将灰度值转换为对应的字符"""
        num_chars: int = len(self.char_set)
        unit: float = 256 / num_chars
        index: int = min(int(gray / unit), num_chars - 1)  # 防止越界
        return self.char_set[index]

    def get_image_features(self, image: Image.Image) -> tuple[float, float]:
        """
        提取图像特征（亮度、边缘强度）。

        :param image: PIL图像对象
        :return: 图像的平均亮度和边缘强度
        """
        grayscale: Image.Image = image.convert("L")
        pixels: np.ndarray = np.array(grayscale)
        mean_brightness: float = np.mean(pixels)

        # 边缘检测来判断细节复杂度
        edges: Image.Image = grayscale.filter(ImageFilter.FIND_EDGES)
        edge_pixels: np.ndarray = np.array(edges)
        edge_intensity: float = np.mean(edge_pixels)  # 边缘强度的平均值

        return mean_brightness, edge_intensity

    def auto_adjust_params(self, image: Image.Image) -> tuple[float, float, str]:
        """
        根据图像特征和分辨率自动调整对比度、亮度、字符密度等参数。
        """
        mean_brightness, edge_intensity = self.get_image_features(image)
        width, height = image.size

        # 自动调整对比度和亮度
        if mean_brightness > 180:  # 图像偏亮
            contrast_factor: float = 1.5
            brightness_factor: float = 0.9  # 减少亮度
        elif mean_brightness < 70:  # 图像偏暗
            contrast_factor = 1.5
            brightness_factor = 1.1  # 增加亮度
        else:
            contrast_factor = 1.3
            brightness_factor = 1.0  # 正常亮度

        # 如果没有指定density, 根据边缘强度调整密度
        if self.density is None:
            if edge_intensity > 120:
                density = "high"
            elif edge_intensity > 80:
                density = "medium"
            else:
                density = "low"
        else:
            # 如果指定了，使用指定的密度
            density = self.density

        return contrast_factor, brightness_factor, density

    async def image_to_ascii_image(
        self,
        image_input: str | bytes | io.BytesIO,
        auto_adjust: bool = True,
        force_animated: bool | None = None,  # 新增参数
    ) -> Image.Image | list[Image.Image]:
        """
        异步将图像转换为字符画并返回图像对象或图像列表（对于GIF）

        :param image_input: 图像的路径、bytes 或 BytesIO 对象
        :param auto_adjust: 是否自动调整对比度、亮度和密度
        :param force_animated: 强制指定图像是否为动画GIF，优先级高于自动检测
        :return: ASCII字符画图像或图像帧列表
        """
        # 打开图像
        if isinstance(image_input, str):
            img: Image.Image = await asyncio.get_event_loop().run_in_executor(
                self._executor, Image.open, image_input
            )
        elif isinstance(image_input, bytes | io.BytesIO):
            img: Image.Image = await asyncio.get_event_loop().run_in_executor(
                self._executor, Image.open, io.BytesIO(image_input)
            )
        else:
            raise ValueError("image_input 必须是文件路径、bytes 或 BytesIO 对象。")

        # 判断是否为动画GIF
        is_animated = False
        if force_animated is not None:
            is_animated = force_animated
        else:
            is_animated = getattr(img, "is_animated", False) and img.format == "GIF"

        frames = []

        # 处理 GIF 动态图片
        if is_animated:
            async with self._gif_lock:
                total_frames = img.n_frames
                if total_frames > self.max_frames:
                    # 计算跳帧间隔
                    frame_indices = np.linspace(
                        0, total_frames - 1, self.max_frames, dtype=int
                    )
                else:
                    frame_indices = list(range(total_frames))

                for frame in frame_indices:
                    await asyncio.get_event_loop().run_in_executor(
                        self._executor, img.seek, frame
                    )
                    # 复制当前帧
                    frame_copy = await asyncio.get_event_loop().run_in_executor(
                        self._executor, img.copy
                    )
                    # 处理当前帧
                    frame_img = await self.process_single_frame(frame_copy, auto_adjust)
                    frames.append(frame_img)
            return frames
        else:
            # 处理单帧图片
            frame_img = await self.process_single_frame(img, auto_adjust)
            return frame_img

    async def process_single_frame(
        self, img: Image.Image, auto_adjust: bool = True
    ) -> Image.Image:
        """
        异步处理单帧图片，将其转换为字符画
        """

        def _process():
            # 自动调整参数（如果启用）
            if auto_adjust:
                self.contrast_factor, self.brightness, self.char_set_name = (
                    self.auto_adjust_params(img)
                )
                self.char_set = self.CHAR_SETS.get(
                    self.char_set_name, self.CHAR_SETS["medium"]
                )
                if self.invert:
                    self.char_set = self.char_set[::-1]  # 反转字符集
            else:
                # 使用初始化时指定的字符密度
                if not self.char_set:
                    self.char_set = self.CHAR_SETS.get("medium")
                elif self.invert:
                    self.char_set = self.char_set[::-1]

            # 计算新的尺寸，调整长宽比例
            original_width, original_height = img.size
            image_aspect_ratio: float = original_height / original_width
            char_aspect_ratio: float = self.char_width / self.char_height
            adjusted_aspect_ratio: float = image_aspect_ratio * char_aspect_ratio
            new_width: int = self.width
            new_height: int = max(
                1, int(new_width * adjusted_aspect_ratio)
            )  # 确保高度至少为1

            # 调整图像尺寸
            img_resized = img.resize(
                (new_width, new_height), resample=Image.Resampling.LANCZOS
            )

            # 转换为灰度图
            img_gray = img_resized.convert("L")

            # 调整对比度和亮度
            enhancer_contrast = ImageEnhance.Contrast(img_gray)
            img_contrast = enhancer_contrast.enhance(self.contrast_factor)
            enhancer_brightness = ImageEnhance.Brightness(img_contrast)
            img_enhanced = enhancer_brightness.enhance(self.brightness)

            # 获取像素数据
            pixels: np.ndarray = np.array(img_enhanced)

            # 创建空白画布
            canvas_width: int = new_width * self.char_width
            canvas_height: int = new_height * self.char_height
            ascii_img: Image.Image = Image.new(
                "RGB", (canvas_width, canvas_height), color="white"
            )
            draw: ImageDraw.Draw = ImageDraw.Draw(ascii_img)

            # 绘制字符画
            for y in range(new_height):
                for x in range(new_width):
                    pixel: float = pixels[y, x]
                    char: str = self.gray_to_char(pixel)
                    if char.strip():  # 仅绘制非空字符
                        draw.text(
                            (x * self.char_width, y * self.char_height),
                            char,
                            font=self.font,
                            fill="black",
                        )

            return ascii_img

        # 在线程池中执行CPU密集型操作
        ascii_img = await asyncio.get_event_loop().run_in_executor(
            self._executor, _process
        )
        return ascii_img

    def save_ascii_image_sync(
        self, ascii_img: Image.Image | list[Image.Image], output_path: str
    ) -> None:
        """将生成的字符画保存为图像文件或GIF文件（同步方法）"""
        if isinstance(ascii_img, list):
            if not ascii_img:
                raise ValueError("ASCII图像帧列表为空。")
            ascii_img[0].save(
                output_path,
                save_all=True,
                append_images=ascii_img[1:],
                loop=0,
                duration=100,
                optimize=True,
                format="GIF",
            )
        else:
            ascii_img.save(output_path)

    async def save_ascii_image_async(
        self, ascii_img: Image.Image | list[Image.Image], output_path: str
    ) -> None:
        """异步将生成的字符画保存为图像文件或GIF文件"""

        def _save():
            if isinstance(ascii_img, list):
                if not ascii_img:
                    raise ValueError("ASCII图像帧列表为空。")
                ascii_img[0].save(
                    output_path,
                    save_all=True,
                    append_images=ascii_img[1:],
                    loop=0,
                    duration=100,
                    optimize=True,
                    format="GIF",
                )
            else:
                ascii_img.save(output_path)

        await asyncio.get_event_loop().run_in_executor(self._executor, _save)

    async def show_ascii_image_async(
        self, ascii_img: Image.Image | list[Image.Image]
    ) -> None:
        """异步展示生成的字符画图像或GIF"""

        def _show():
            if isinstance(ascii_img, list):
                # 对于GIF，可以选择展示第一帧或通过外部工具播放
                ascii_img[0].show()
            else:
                ascii_img.show()

        await asyncio.get_event_loop().run_in_executor(self._executor, _show)
