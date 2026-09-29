"""Generate the multi-size app.ico / app.png (EXE, tray, plugin, README).

The artwork lives in cursor_usage_app/icon_art.py so the tray can draw the
same gauge with live usage.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from cursor_usage_app.icon_art import make_icon_image  # noqa: E402


def main() -> None:
    out_dir = ROOT / "assets"
    out_dir.mkdir(parents=True, exist_ok=True)
    ico_path = out_dir / "app.ico"
    png_path = out_dir / "app.png"

    # Include exact Windows DPI-scaled 24px variants (125%=30, 150%=36, 175%=42).
    sizes = [16, 20, 24, 28, 30, 32, 36, 40, 42, 48, 64, 128, 256]
    images = [make_icon_image(s) for s in sizes]
    images[-1].save(png_path)
    images[-1].save(ico_path, format="ICO", sizes=[(s, s) for s in sizes], append_images=images[:-1])
    print(f"Wrote {ico_path} ({', '.join(str(s) for s in sizes)})")
    print(f"Wrote {png_path}")


if __name__ == "__main__":
    main()
