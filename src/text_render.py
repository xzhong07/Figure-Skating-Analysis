"""Pillow で日本語の文字を描く（OpenCV の putText は日本語を描けないため）。"""
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

FONT_DIR = Path(r"C:\Windows\Fonts")
REGULAR_FONTS = ["BIZ-UDGothicR.ttc", "YuGothM.ttc", "meiryo.ttc", "msgothic.ttc"]
BOLD_FONTS = ["BIZ-UDGothicB.ttc", "YuGothB.ttc", "meiryob.ttc", "msgothic.ttc"]

# 行頭に来てはいけない文字（禁則）
NO_LINE_START = set("、。，．）」』】〕・ー？！%°")

Color = tuple[int, int, int]  # RGB


@lru_cache(maxsize=None)
def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    for name in BOLD_FONTS if bold else REGULAR_FONTS:
        path = FONT_DIR / name
        if path.exists():
            return ImageFont.truetype(str(path), size)
    raise FileNotFoundError(f"日本語フォントが見つかりません: {FONT_DIR}")


def wrap(text: str, size: int, width: int, bold: bool = False) -> list[str]:
    """幅 width（ピクセル）に収まるよう、1文字ずつ折り返す。"""
    f = font(size, bold)
    lines: list[str] = []
    line = ""
    for ch in text:
        if ch == "\n":
            lines.append(line)
            line = ""
            continue
        if line and f.getlength(line + ch) > width and ch not in NO_LINE_START:
            lines.append(line)
            line = ch
        else:
            line += ch
    if line:
        lines.append(line)
    return lines


class Canvas:
    """BGR の numpy 画像に Pillow で描くためのラッパー。描き終えたら to_bgr() で戻す。"""

    def __init__(self, bgr: np.ndarray) -> None:
        self.image = Image.fromarray(bgr[:, :, ::-1]).convert("RGBA")
        self.overlay = Image.new("RGBA", self.image.size, (0, 0, 0, 0))
        self.draw = ImageDraw.Draw(self.overlay)

    def rect(self, box: tuple[int, int, int, int], fill: tuple[int, int, int, int], radius: int = 0) -> None:
        self.draw.rounded_rectangle(box, radius=radius, fill=fill)

    def text(self, xy: tuple[int, int], text: str, size: int, fill: Color = (255, 255, 255),
             bold: bool = False, anchor: str = "la") -> None:
        self.draw.text(xy, text, font=font(size, bold), fill=fill + (255,), anchor=anchor)

    def paragraph(self, xy: tuple[int, int], text: str, size: int, width: int, fill: Color = (255, 255, 255),
                  bold: bool = False, line_gap: float = 0.4) -> int:
        """折り返して描き、描き終えた位置の y を返す。"""
        x, y = xy
        for line in wrap(text, size, width, bold):
            self.text((x, y), line, size, fill, bold)
            y += int(size * (1 + line_gap))
        return y

    @staticmethod
    def paragraph_height(text: str, size: int, width: int, bold: bool = False, line_gap: float = 0.4) -> int:
        return len(wrap(text, size, width, bold)) * int(size * (1 + line_gap))

    def to_bgr(self) -> np.ndarray:
        merged = Image.alpha_composite(self.image, self.overlay).convert("RGB")
        return np.asarray(merged)[:, :, ::-1].copy()
