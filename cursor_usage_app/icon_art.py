"""The app icon: a graphite rounded tile with a precise usage gauge.

Used by scripts/make_icon.py (app.ico / app.png) and by the tray, where the
gauge shows live on-demand usage. Colour is used sparingly: the tile stays
neutral and only the progress arc carries the accent (blue, then amber / red
near the limit). Sizes <= 24 px drop the needle and use a heavier arc.
"""

from __future__ import annotations

import math

from PIL import Image, ImageChops, ImageDraw

TILE_TOP = (40, 40, 46)
TILE_BOTTOM = (18, 18, 21)
ARC = {
    "brand": (79, 140, 255),  # accent blue
    "warn": (245, 158, 11),
    "danger": (239, 68, 68),
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


def _vertical_gradient(size: int, top: tuple[int, int, int], bottom: tuple[int, int, int]) -> Image.Image:
    mask = Image.linear_gradient("L").resize((size, size))
    return Image.composite(Image.new("RGB", (size, size), bottom), Image.new("RGB", (size, size), top), mask).convert("RGBA")


def _point(cx: float, cy: float, r: float, deg: float) -> tuple[float, float]:
    a = math.radians(deg)
    return cx + r * math.cos(a), cy + r * math.sin(a)


def _arc(draw: ImageDraw.ImageDraw, box: tuple[float, float, float, float], start: float, end: float, width: int, fill: tuple[int, ...]) -> None:
    """Arc with round caps."""
    draw.arc(box, start, end, fill=fill, width=width)
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    r = (box[2] - box[0]) / 2 - width / 2
    for angle in (start, end):
        x, y = _point(cx, cy, r, angle)
        draw.ellipse((x - width / 2, y - width / 2, x + width / 2, y + width / 2), fill=fill)


def make_icon_image(size: int, progress: float = BRAND_PROGRESS, palette: str = "brand", supersample: int | None = None) -> Image.Image:
    ss = supersample or (max(4, 1024 // size) if size < 256 else 4)
    big = size * ss
    small = size <= 24
    accent = ARC.get(palette, ARC["brand"]) + (255,)

    # Tile: graphite with a faint top-to-bottom tone and a hairline highlight.
    margin = round(big * (0.03 if small else 0.055))
    radius = round((big - 2 * margin) * 0.235)
    box = (margin, margin, big - margin - 1, big - margin - 1)
    tile = _vertical_gradient(big, TILE_TOP, TILE_BOTTOM)
    shape = Image.new("L", (big, big), 0)
    ImageDraw.Draw(shape).rounded_rectangle(box, radius=radius, fill=255)
    if not small:
        rim = Image.new("RGBA", (big, big), (0, 0, 0, 0))
        ImageDraw.Draw(rim).rounded_rectangle(box, radius=radius, outline=(255, 255, 255, 34), width=max(ss, round(big * 0.006)))
        # Keep the highlight to the upper half so it reads as light from above.
        fade = Image.linear_gradient("L").resize((big, big)).point(lambda v: max(0, 255 - v * 2))
        rim.putalpha(ImageChops.multiply(rim.getchannel("A"), fade))
        tile = Image.alpha_composite(tile, rim)

    # Gauge.
    gauge = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(gauge)
    pad = big * (0.2 if small else 0.235)
    drop = big * 0.025  # optical centring: the open bottom makes the ring look high
    gbox = (pad, pad + drop, big - pad, big - pad + drop)
    width = round(big * (0.14 if small else 0.085))
    value = max(0.0, min(1.0, progress))
    end = START_DEG + SWEEP_DEG * value
    _arc(draw, gbox, START_DEG, START_DEG + SWEEP_DEG, width, (255, 255, 255, 38 if small else 30))
    if value > 0.005:
        _arc(draw, gbox, START_DEG, end, width, accent)
    cx, cy = (gbox[0] + gbox[2]) / 2, (gbox[1] + gbox[3]) / 2
    r = (gbox[2] - gbox[0]) / 2 - width / 2
    if size >= 28 and value > 0.005:
        # A white knob on the arc tip.
        kx, ky = _point(cx, cy, r, end)
        knob = width * 0.3
        draw.ellipse((kx - knob, ky - knob, kx + knob, ky + knob), fill=(255, 255, 255, 255))
    if size >= 40:
        # A thin needle and a hub; below 40 px they only blur.
        tip = _point(cx, cy, r * 0.58, end)
        needle = max(ss, round(width * 0.36))
        draw.line((cx, cy, *tip), fill=(255, 255, 255, 235), width=needle)
        draw.ellipse((tip[0] - needle / 2, tip[1] - needle / 2, tip[0] + needle / 2, tip[1] + needle / 2), fill=(255, 255, 255, 235))
        hub = width * 0.5
        draw.ellipse((cx - hub, cy - hub, cx + hub, cy + hub), fill=(255, 255, 255, 255))
        inner = hub * 0.42
        draw.ellipse((cx - inner, cy - inner, cx + inner, cy + inner), fill=TILE_BOTTOM + (255,))

    icon = Image.alpha_composite(tile, gauge)
    icon.putalpha(ImageChops.multiply(icon.getchannel("A"), shape))
    # Resize premultiplied so transparent pixels don't bleed colour into the edges.
    return icon.convert("RGBa").resize((size, size), Image.Resampling.LANCZOS).convert("RGBA")
