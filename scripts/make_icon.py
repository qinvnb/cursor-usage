"""Generate crisp multi-size app.ico / app.png for EXE and tray."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw


def make_icon_image(size: int) -> Image.Image:
    """Supersample every frame for clean alpha edges at small DPI sizes."""
    ss = 4
    big = size * ss
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    m = max(ss, round(size * 0.035) * ss)
    fill = (37, 99, 235, 255)
    d.ellipse((m, m, big - m - 1, big - m - 1), fill=fill)
    inset = round(big * 0.22)
    ring_width = max(2 * ss, round(size * 0.075) * ss)
    d.ellipse(
        (inset, inset, big - inset - 1, big - inset - 1),
        outline=(255, 255, 255, 255),
        width=ring_width,
    )
    c0, c1 = big * 0.42, big * 0.58
    d.ellipse((c0, c0, c1, c1), fill=(255, 255, 255, 255))
    return img.resize((size, size), Image.Resampling.LANCZOS)


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    out_dir = root / "assets"
    out_dir.mkdir(parents=True, exist_ok=True)
    ico_path = out_dir / "app.ico"
    png_path = out_dir / "app.png"

    # Include exact Windows DPI-scaled 24px variants (125%=30, 150%=36, 175%=42).
    sizes = [16, 20, 24, 28, 30, 32, 36, 40, 42, 48, 64, 128, 256]
    images = [make_icon_image(s) for s in sizes]
    # High-res PNG for tray / docs
    images[-1].save(png_path)
    # Multi-resolution ICO: pass largest as primary with append_images
    images[-1].save(
        ico_path,
        format="ICO",
        sizes=[(s, s) for s in sizes],
        append_images=images[:-1],
    )
    print(f"Wrote {ico_path} ({', '.join(str(s) for s in sizes)})")
    print(f"Wrote {png_path}")


if __name__ == "__main__":
    main()
