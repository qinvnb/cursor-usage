"""HiDPI floating ball with per-pixel alpha (smooth edges, multi-monitor)."""

from __future__ import annotations

import argparse
import os
import sys
import tkinter as tk
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .win_ui import (
    LayeredBitmap,
    clamp_to_virtual,
    clear_topmost,
    default_ball_position,
    hwnd_of,
    install_foreground_hook,
    install_rbutton_hook,
    is_fullscreen_session,
    keep_topmost,
    paint_layered,
)

FULLSCREEN_FALLBACK_MS = 2000


def _enable_dpi() -> float:
    scale = 1.0
    if sys.platform != "win32":
        return scale
    try:
        from ctypes import windll

        try:
            windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            windll.user32.SetProcessDPIAware()
        hdc = windll.user32.GetDC(0)
        dpi = windll.gdi32.GetDeviceCaps(hdc, 88)
        windll.user32.ReleaseDC(0, hdc)
        if dpi and dpi > 0:
            scale = max(1.0, dpi / 96.0)
    except Exception:
        scale = 1.0
    return scale


def _usd(cents: float) -> str:
    return f"${float(cents or 0) / 100.0:.0f}"


def _font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    windir = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    names = (
        ["msyhbd.ttc", "msyh.ttc", "simhei.ttf", "segoeuib.ttf", "segoeui.ttf"]
        if bold
        else ["msyh.ttc", "msyhbd.ttc", "simhei.ttf", "segoeui.ttf"]
    )
    for name in names:
        path = windir / name
        if path.is_file():
            try:
                return ImageFont.truetype(str(path), size)
            except OSError:
                continue
    return ImageFont.load_default()


def render_ball(
    size: int,
    summary: dict[str, Any] | None,
    scale: float,
    *,
    font_size: int = 14,
    ring_width: int = 7,
) -> Image.Image:
    """RGBA ball with soft shadow — edges anti-aliased via supersample."""
    ss = 6
    big = size * ss
    canvas = Image.new("RGBA", (big, big), (0, 0, 0, 0))

    pad = 5 * ss
    # Soft shadow
    shadow = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).ellipse(
        (pad + ss, pad + 2 * ss, big - pad, big - pad + ss),
        fill=(15, 23, 42, 40),
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=2.6 * ss))
    canvas = Image.alpha_composite(canvas, shadow)

    disk = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    dd = ImageDraw.Draw(disk)
    box = (pad, pad, big - pad - 1, big - pad - 1)
    dd.ellipse(box, fill=(255, 255, 255, 255))
    # Soft rim
    rim = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    ImageDraw.Draw(rim).ellipse(box, outline=(148, 163, 184, 90), width=max(ss, int(1.2 * ss)))
    rim = rim.filter(ImageFilter.GaussianBlur(radius=0.4 * ss))
    disk = Image.alpha_composite(disk, rim)
    canvas = Image.alpha_composite(canvas, disk)

    used = float((summary or {}).get("individualUsedCents") or 0)
    limit = float((summary or {}).get("individualLimitCents") or 0)
    used_pct = max(0.0, min(1.0, (used / limit) if limit > 0 else 0.0))

    color = (37, 99, 235, 255)
    if used_pct >= 0.9:
        color = (220, 38, 38, 255)
    elif used_pct >= 0.7:
        color = (217, 119, 6, 255)

    ring = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    rd = ImageDraw.Draw(ring)
    ring_w = max(3 * ss, int(ring_width * scale * ss))
    inset = pad + ring_w + ss
    track = (inset, inset, big - inset - 1, big - inset - 1)
    rd.arc(track, start=0, end=359, fill=(226, 232, 240, 255), width=ring_w)
    if summary is not None and used_pct > 0.001:
        rd.arc(track, start=-90, end=-90 + used_pct * 360, fill=color, width=ring_w)
    ring = ring.filter(ImageFilter.GaussianBlur(radius=0.5 * ss))
    canvas = Image.alpha_composite(canvas, ring)

    text = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    td = ImageDraw.Draw(text)
    cx = cy = big / 2
    fs = max(8, int(font_size * scale))
    title = _font(fs * ss, bold=True)
    body = _font(max(8, int(fs * 0.78)) * ss, bold=False)
    # Vertical spacing scales with font
    gap = max(10, int(fs * 0.95)) * ss

    def center(y: float, s: str, font: ImageFont.ImageFont, fill: tuple[int, int, int, int]) -> None:
        bb = td.textbbox((0, 0), s, font=font)
        td.text((cx - (bb[2] - bb[0]) / 2, y - (bb[3] - bb[1]) / 2), s, font=font, fill=fill)

    if summary is None:
        center(cy, "同步中", body, (100, 116, 139, 255))
    else:
        center(cy - gap * 0.5, _usd(used), title, (15, 23, 42, 255))
        center(cy + gap * 0.55, f"/ {_usd(limit)}", body, (100, 116, 139, 255))

    canvas = Image.alpha_composite(canvas, text)
    return canvas.resize((size, size), Image.Resampling.LANCZOS)


def apply_opacity(img: Image.Image, opacity: float) -> Image.Image:
    opacity = max(0.05, min(1.0, float(opacity)))
    if opacity >= 0.999:
        return img.convert("RGBA")
    out = img.convert("RGBA")
    r, g, b, a = out.split()
    a = a.point(lambda p: int(p * opacity))
    out = Image.merge("RGBA", (r, g, b, a))
    return out


class FloatingBall:
    def __init__(self, refresh_ms: int = 4000) -> None:
        from . import store

        self.store = store
        self.scale = _enable_dpi()
        settings = store.load_settings()
        base_size = int(settings.get("ballSize") or 120)
        self.size = max(72, min(280, int(round(base_size * self.scale))))
        self.opacity = max(0.4, min(1.0, int(settings.get("ballOpacity") or 100) / 100.0))
        self.refresh_ms = max(2000, int(settings.get("ballRefreshMs") or refresh_ms))
        self.font_size = max(8, min(28, int(settings.get("ballFontSize") or 14)))
        self.ring_width = max(3, min(18, int(settings.get("ballRingWidth") or 7)))
        self._img: Image.Image | None = None
        self._bitmap: LayeredBitmap | None = None
        self._summary_key: tuple[Any, ...] | None = None
        self._fs_check_pending = False
        self._x, self._y = self._initial_pos()

        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title("Cursor 用量悬浮球")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg="#000001")
        self.root.geometry(f"{self.size}x{self.size}+{self._x}+{self._y}")

        self.frame = tk.Frame(self.root, bg="#000001", width=self.size, height=self.size)
        self.frame.pack(fill="both", expand=True)
        for w in (self.root, self.frame):
            w.bind("<ButtonPress-1>", self._on_press)
            w.bind("<B1-Motion>", self._on_drag)
            w.bind("<ButtonRelease-1>", self._on_release)
            w.bind("<Button-3>", self._on_right)
            w.bind("<ButtonPress-3>", self._on_right)
            w.bind("<Control-Button-1>", self._on_right)

        self._menu = tk.Menu(self.root, tearoff=0)
        self._menu.add_command(label="显示看板", command=self._cmd_show)
        self._menu.add_command(label="重置位置", command=self._cmd_reset_pos)
        self._menu.add_separator()
        self._menu.add_command(label="关闭悬浮球", command=self._cmd_close)
        self._menu_open = False
        self._hidden_fs = False
        self._topmost_on = True

        self._drag_x = 0
        self._drag_y = 0
        self._moved = False

        self._draw(None)
        self.root.deiconify()
        self._apply_topmost(True)
        self._paint()
        try:
            install_rbutton_hook(hwnd_of(self.root), self._popup_at)
        except Exception:
            pass
        # Foreground changes (app switch, video going fullscreen via a new
        # window) trigger an immediate check; a slow timer covers in-place
        # fullscreen toggles that do not change the foreground window.
        install_foreground_hook(self._schedule_fs_check)
        self._tick()
        self.root.after(FULLSCREEN_FALLBACK_MS, self._keep_alive)

    def _initial_pos(self) -> tuple[int, int]:
        settings = self.store.load_settings()
        bx, by = settings.get("ballX"), settings.get("ballY")
        if bx is not None and by is not None:
            return clamp_to_virtual(int(bx), int(by), self.size, self.size)
        return default_ball_position(self.size)

    def _save_pos(self) -> None:
        try:
            self.store.save_settings({"ballX": self._x, "ballY": self._y})
        except Exception:
            pass

    def _pos(self) -> tuple[int, int]:
        return int(self._x), int(self._y)

    def _move_to(self, x: int, y: int) -> None:
        self._x, self._y = clamp_to_virtual(x, y, self.size, self.size)
        self.root.geometry(f"+{self._x}+{self._y}")
        self._paint()

    def _paint(self) -> None:
        if self._img is None or self._hidden_fs or self._menu_open:
            return
        try:
            if self._bitmap is None:
                self._bitmap = LayeredBitmap(apply_opacity(self._img, self.opacity))
            paint_layered(hwnd_of(self.root), self._bitmap, self._x, self._y)
        except Exception:
            pass

    def _apply_topmost(self, on: bool) -> None:
        self._topmost_on = bool(on)
        try:
            hwnd = hwnd_of(self.root)
            if on:
                keep_topmost(hwnd)
            else:
                clear_topmost(hwnd)
        except Exception:
            pass

    def _set_fs_hidden(self, hide: bool) -> None:
        if hide == self._hidden_fs:
            return
        self._hidden_fs = hide
        try:
            if hide:
                self._apply_topmost(False)
                self.root.withdraw()
            else:
                self.root.deiconify()
                self._apply_topmost(True)
                self._paint()
        except Exception:
            pass

    def _check_fullscreen(self) -> None:
        # Nested event loop during tk_popup still fires this — never raise while menu open.
        self._fs_check_pending = False
        if self._menu_open:
            return
        try:
            fs = is_fullscreen_session()
            self._set_fs_hidden(fs)
            if not fs:
                # Z-order only: no deiconify, ShowWindow or layered repaint.
                keep_topmost(hwnd_of(self.root))
                self._topmost_on = True
        except Exception:
            pass

    def _schedule_fs_check(self) -> None:
        if self._fs_check_pending:
            return
        self._fs_check_pending = True
        try:
            # Let the new foreground window settle into its final geometry.
            self.root.after(150, self._check_fullscreen)
        except Exception:
            self._fs_check_pending = False

    def _keep_alive(self) -> None:
        self._check_fullscreen()
        self.root.after(FULLSCREEN_FALLBACK_MS, self._keep_alive)

    def _on_press(self, event: tk.Event) -> None:  # type: ignore[type-arg]
        self._drag_x = event.x_root
        self._drag_y = event.y_root
        self._moved = False

    def _on_drag(self, event: tk.Event) -> None:  # type: ignore[type-arg]
        dx = event.x_root - self._drag_x
        dy = event.y_root - self._drag_y
        if abs(dx) + abs(dy) > 3:
            self._moved = True
        self._move_to(self._x + dx, self._y + dy)
        self._drag_x = event.x_root
        self._drag_y = event.y_root

    def _on_release(self, _event: tk.Event) -> None:  # type: ignore[type-arg]
        if self._moved:
            self._save_pos()
            return
        self._cmd_show()

    def _on_right(self, event: tk.Event) -> None:  # type: ignore[type-arg]
        self._popup_at(event.x_root, event.y_root)

    def _popup_at(self, x: int, y: int) -> None:
        def _show() -> None:
            if self._menu_open:
                return
            self._menu_open = True
            # Drop topmost so the Tk menu is not covered by this overlay.
            self._apply_topmost(False)
            try:
                self._menu.tk_popup(int(x), int(y))
            except Exception:
                try:
                    self._menu.post(int(x), int(y))
                except Exception:
                    pass
            finally:
                try:
                    self._menu.grab_release()
                except Exception:
                    pass
                self._menu_open = False
                if not self._hidden_fs:
                    self._apply_topmost(True)
                    self._paint()

        try:
            self.root.after(0, _show)
        except Exception:
            _show()

    def _cmd_show(self) -> None:
        try:
            from .instance import send_command

            if send_command("show-main", timeout=1.0):
                return
        except Exception:
            pass
        try:
            self.store.write_command({"action": "show-main"})
        except Exception:
            pass

    def _cmd_reset_pos(self) -> None:
        try:
            self.store.save_settings({"ballX": None, "ballY": None})
        except Exception:
            pass
        x, y = default_ball_position(self.size)
        self._move_to(x, y)
        self._save_pos()

    def _cmd_close(self) -> None:
        try:
            from .instance import send_command

            if not send_command("hide-ball", timeout=1.0):
                self.store.write_command({"action": "hide-ball"})
        except Exception:
            try:
                self.store.write_command({"action": "hide-ball"})
            except Exception:
                pass
        self.root.after(50, self.root.destroy)

    def _load_summary(self) -> dict[str, Any] | None:
        try:
            return self.store.load_summary()
        except Exception:
            return None

    def _draw(self, summary: dict[str, Any] | None) -> None:
        self._img = render_ball(
            self.size,
            summary,
            self.scale,
            font_size=self.font_size,
            ring_width=self.ring_width,
        )
        self._bitmap = None
        self._paint()

    def _tick(self) -> None:
        if not self._hidden_fs and not self._menu_open:
            summary = self._load_summary()
            # render_ball only depends on these two values; skip the expensive
            # supersampled redraw when neither changed.
            key = (
                None
                if summary is None
                else (
                    _usd(summary.get("individualUsedCents") or 0),
                    _usd(summary.get("individualLimitCents") or 0),
                    round(
                        float(summary.get("individualUsedCents") or 0)
                        / max(1.0, float(summary.get("individualLimitCents") or 0)),
                        3,
                    ),
                )
            )
            if key != self._summary_key or self._img is None:
                self._summary_key = key
                self._draw(summary)
        self.root.after(self.refresh_ms, self._tick)

    def run(self) -> None:
        self.root.mainloop()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Cursor 用量悬浮球")
    parser.add_argument("--refresh-ms", type=int, default=4000)
    parser.parse_args(argv)
    from . import store

    store.data_dir()
    FloatingBall().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
