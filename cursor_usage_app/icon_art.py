"""The app icon: a rounded gradient tile with a white usage gauge.

Used by scripts/make_icon.py (app.ico / app.png) and by the tray, where the
gauge shows live on-demand usage and the tile turns amber / red near the limit.
Sizes <= 24 px use a simplified, heavier gauge without the needle.
"""

from __future__ import annotations

import math

from PIL import Image, ImageChops, ImageDraw

PALETTES = {
    "brand": ((37, 99, 235), (124, 58, 237)),  # included blue -> on-demand violet
    "warn": ((245, 158, 11), (234, 88, 12)),
    "danger": ((239, 68, 68), (185, 28, 28)),
}
START_DEG = 135  # the gauge opens at the bottom; PIL angles run clockwise from 3 o'clock
SWEEP_DEG = 270
BRAND_PROGRESS = 0.68


def palette_for(progress: float) -> str:
    # Same thresholds as the floating ball and taskbar widget.
    if progress >= 0.9:
        return "danger"
    if progress >= 0.7:
        return "warn"
    return "brand"


def _diagonal_gradient(size: int, top_left: tuple[int, int, int], bottom_right: tuple[int, int, int]) -> Image.Image:
    ramp = Image.linear_gradient("L").rotate(45, resample=Image.Resampling.BICUBIC, expand=True)
    w, h = ramp.size
    side = w // 2  # largest axis-aligned square inside the rotated one
    mask = ramp.crop(((w - side) // 2, (h - side) // 2, (w + side) // 2, (h + side) // 2)).resize((size, size))
    return Image.composite(Image.new("RGB", (size, size), bottom_right), Image.new("RGB", (size, size), top_left), mask).convert("RGBA")


def _arc(draw: ImageDraw.ImageDraw, box: tuple[float, float, float, float], start: float, end: float, width: int, fill: tuple[int, ...]) -> None:
    """Arc with round caps."""
    draw.arc(box, start, end, fill=fill, width=width)
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    r = (box[2] - box[0]) / 2 - width / 2
    for angle in (start, end):
        x = cx + r * math.cos(math.radians(angle))
        y = cy + r * math.sin(math.radians(angle))
        draw.ellipse((x - width / 2, y - width / 2, x + width / 2, y + width / 2), fill=fill)


def make_icon_image(size: int, progress: float = BRAND_PROGRESS, palette: str = "brand", supersample: int | None = None) -> Image.Image:
    ss = supersample or (max(4, 1024 // size) if size < 256 else 4)
    big = size * ss
    small = size <= 24
    top_left, bottom_right = PALETTES.get(palette, PALETTES["brand"])
    accent = bottom_right + (255,)

    margin = round(big * (0.04 if small else 0.06))
    tile = _diagonal_gradient(big, top_left, bottom_right)
    if not small:
        # Soft top-to-bottom light wash for depth.
        wash = Image.linear_gradient("L").resize((big, big)).point(lambda v: round((255 - v) * 0.16))
        light = Image.new("RGBA", (big, big), (255, 255, 255, 0))
        light.putalpha(wash)
        tile = Image.alpha_composite(tile, light)
    shape = Image.new("L", (big, big), 0)
    ImageDraw.Draw(shape).rounded_rectangle((margin, margin, big - margin - 1, big - margin - 1), radius=round(big * 0.23), fill=255)

    gauge = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(gauge)
    pad = big * (0.2 if small else 0.235)
    box = (pad, pad + big * 0.02, big - pad, big - pad + big * 0.02)
    width = round(big * (0.15 if small else 0.105))
    value = max(0.0, min(1.0, progress))
    end = START_DEG + SWEEP_DEG * value
    _arc(draw, box, START_DEG, START_DEG + SWEEP_DEG, width, (255, 255, 255, 70))
    if value > 0.005:
        _arc(draw, box, START_DEG, end, width, (255, 255, 255, 255))
    if not small:
        # Needle from the hub towards the arc tip, so it reads as a gauge.
        cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
        r = (box[2] - box[0]) / 2 - width / 2
        a = math.radians(end)
        tip = (cx + r * 0.62 * math.cos(a), cy + r * 0.62 * math.sin(a))
        needle = round(width * 0.42)
        draw.line((cx, cy, *tip), fill=(255, 255, 255, 255), width=needle)
        draw.ellipse((tip[0] - needle / 2, tip[1] - needle / 2, tip[0] + needle / 2, tip[1] + needle / 2), fill=(255, 255, 255, 255))
        hub = width * 0.62
        draw.ellipse((cx - hub, cy - hub, cx + hub, cy + hub), fill=(255, 255, 255, 255))
        inner = hub * 0.45
        draw.ellipse((cx - inner, cy - inner, cx + inner, cy + inner), fill=accent)

    icon = Image.alpha_composite(tile, gauge)
    icon.putalpha(ImageChops.multiply(icon.getchannel("A"), shape))
    # Resize premultiplied so transparent pixels don't bleed colour into the edges.
    return icon.convert("RGBa").resize((size, size), Image.Resampling.LANCZOS).convert("RGBA")
