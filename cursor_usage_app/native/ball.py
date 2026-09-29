"""Floating usage ball: a native per-pixel-alpha layered window (no Tk).

Dragging is delegated to the system move loop (WM_NCHITTEST -> HTCAPTION), so
moving the ball never re-renders it. A click is a move loop that ended where
it started. All methods run on the native UI thread.
"""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from pathlib import Path
from typing import Any, Callable

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from ..i18n import L
from .win import (
    IS_WINDOWS,
    LayeredBitmap,
    clamp_to_virtual,
    clear_topmost,
    default_ball_position,
    dpi_for_window,
    is_fullscreen_session,
    keep_topmost,
    paint_layered,
)

WM_DESTROY = 0x0002
WM_NCHITTEST = 0x0084
WM_NCRBUTTONUP = 0x00A5
WM_CONTEXTMENU = 0x007B
WM_ENTERSIZEMOVE = 0x0231
WM_EXITSIZEMOVE = 0x0232
WM_DPICHANGED = 0x02E0
HTCAPTION = 2
WS_POPUP = 0x80000000
WS_EX_LAYERED = 0x00080000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_TOPMOST = 0x00000008
WS_EX_NOACTIVATE = 0x08000000
SW_HIDE = 0
SW_SHOWNA = 8
TPM_RETURNCMD = 0x0100
TPM_RIGHTBUTTON = 0x0002
MF_STRING = 0x0000
MF_SEPARATOR = 0x0800
ID_SHOW, ID_RESET, ID_CLOSE = 2001, 2002, 2003

if IS_WINDOWS:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    LRESULT = ctypes.c_ssize_t
    WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

    class WNDCLASSEXW(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.UINT),
            ("style", wintypes.UINT),
            ("lpfnWndProc", WNDPROC),
            ("cbClsExtra", ctypes.c_int),
            ("cbWndExtra", ctypes.c_int),
            ("hInstance", wintypes.HINSTANCE),
            ("hIcon", wintypes.HICON),
            ("hCursor", wintypes.HANDLE),
            ("hbrBackground", wintypes.HBRUSH),
            ("lpszMenuName", wintypes.LPCWSTR),
            ("lpszClassName", wintypes.LPCWSTR),
            ("hIconSm", wintypes.HICON),
        ]

    user32.DefWindowProcW.restype = LRESULT
    user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.CreateWindowExW.restype = wintypes.HWND
    user32.CreateWindowExW.argtypes = [
        wintypes.DWORD,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.HWND,
        wintypes.HMENU,
        wintypes.HINSTANCE,
        wintypes.LPVOID,
    ]
    user32.RegisterClassExW.restype = wintypes.ATOM
    user32.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
    user32.UnregisterClassW.argtypes = [wintypes.LPCWSTR, wintypes.HINSTANCE]
    user32.DestroyWindow.argtypes = [wintypes.HWND]
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.IsWindow.argtypes = [wintypes.HWND]
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.c_void_p]
    user32.LoadCursorW.restype = wintypes.HANDLE
    user32.LoadCursorW.argtypes = [wintypes.HINSTANCE, ctypes.c_void_p]
    user32.CreatePopupMenu.restype = wintypes.HMENU
    user32.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_size_t, wintypes.LPCWSTR]
    user32.TrackPopupMenuEx.restype = wintypes.UINT
    user32.TrackPopupMenuEx.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.LPVOID]
    user32.DestroyMenu.argtypes = [wintypes.HMENU]
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
    kernel32.GetModuleHandleW.restype = wintypes.HMODULE
    kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]


def _usd(cents: float) -> str:
    return f"${float(cents or 0) / 100.0:.0f}"


def _font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    fonts = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    names = ["segoeuib.ttf", "msyhbd.ttc", "segoeui.ttf"] if bold else ["segoeui.ttf", "msyh.ttc"]
    for name in names:
        path = fonts / name
        if path.is_file():
            try:
                return ImageFont.truetype(str(path), size)
            except OSError:
                continue
    return ImageFont.load_default()


def ring_color(ratio: float) -> tuple[int, int, int, int]:
    if ratio >= 0.9:
        return (220, 38, 38, 255)
    if ratio >= 0.7:
        return (217, 119, 6, 255)
    return (37, 99, 235, 255)


def render_ball(size: int, summary: dict[str, Any] | None, scale: float, *, font_size: int = 14, ring_width: int = 7) -> Image.Image:
    """RGBA ball with a soft shadow; 4x supersampled for smooth edges."""
    ss = 4
    big = size * ss
    pad = 5 * ss
    canvas = Image.new("RGBA", (big, big), (0, 0, 0, 0))

    shadow = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).ellipse((pad + ss, pad + 2 * ss, big - pad, big - pad + ss), fill=(15, 23, 42, 44))
    canvas = Image.alpha_composite(canvas, shadow.filter(ImageFilter.GaussianBlur(radius=2.6 * ss)))

    draw = ImageDraw.Draw(canvas)
    box = (pad, pad, big - pad - 1, big - pad - 1)
    draw.ellipse(box, fill=(255, 255, 255, 255), outline=(203, 213, 225, 255), width=max(1, ss))

    used = float((summary or {}).get("individualUsedCents") or 0)
    limit = float((summary or {}).get("individualLimitCents") or 0)
    ratio = max(0.0, min(1.0, used / limit if limit > 0 else 0.0))
    ring_w = max(3 * ss, int(ring_width * scale * ss))
    inset = pad + ring_w // 2 + 3 * ss
    track = (inset, inset, big - inset - 1, big - inset - 1)
    draw.arc(track, start=0, end=360, fill=(226, 232, 240, 255), width=ring_w)
    if summary is not None and ratio > 0.001:
        draw.arc(track, start=-90, end=-90 + ratio * 360, fill=ring_color(ratio), width=ring_w)

    fs = max(8, int(font_size * scale))
    title = _font(fs * ss, bold=True)
    body = _font(max(8, int(fs * 0.74)) * ss)
    cx = cy = big / 2
    gap = max(10, int(fs * 0.95)) * ss

    def center(y: float, text: str, font: ImageFont.ImageFont, fill: tuple[int, int, int, int]) -> None:
        bb = draw.textbbox((0, 0), text, font=font)
        draw.text((cx - (bb[2] - bb[0]) / 2 - bb[0], y - (bb[3] - bb[1]) / 2 - bb[1]), text, font=font, fill=fill)

    if summary is None:
        center(cy, "…", body, (100, 116, 139, 255))
    else:
        center(cy - gap * 0.42, _usd(used), title, (15, 23, 42, 255))
        center(cy + gap * 0.6, f"/ {_usd(limit)}", body, (100, 116, 139, 255))
    return canvas.resize((size, size), Image.Resampling.LANCZOS)


class FloatingBall:
    class_name = "CursorUsageFloatingBall"

    def __init__(
        self,
        settings: dict[str, Any],
        *,
        on_show: Callable[[], None],
        on_close: Callable[[], None],
        on_moved: Callable[[int, int], None],
    ) -> None:
        self.on_show = on_show
        self.on_close = on_close
        self.on_moved = on_moved
        self.base_size = max(72, min(240, int(settings.get("ballSize") or 120)))
        self.opacity = max(40, min(100, int(settings.get("ballOpacity") or 100)))
        self.font_size = max(8, min(28, int(settings.get("ballFontSize") or 14)))
        self.ring_width = max(3, min(18, int(settings.get("ballRingWidth") or 7)))
        self.saved_pos = (settings.get("ballX"), settings.get("ballY"))
        self.hwnd = 0
        self.hinstance = kernel32.GetModuleHandleW(None)
        self.scale = 1.0
        self.size = self.base_size
        self.x = self.y = 0
        self.summary: dict[str, Any] | None = None
        self.summary_key: tuple[Any, ...] | None = ("init",)
        self.bitmap: LayeredBitmap | None = None
        self.hidden_fullscreen = False
        self.menu_open = False
        self.move_origin: tuple[int, int] | None = None
        self._wndproc = WNDPROC(self._window_proc)

    # --- lifecycle ----------------------------------------------------------

    def start(self) -> None:
        wc = WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(wc)
        wc.lpfnWndProc = self._wndproc
        wc.hInstance = self.hinstance
        wc.hCursor = user32.LoadCursorW(None, ctypes.c_void_p(32649))  # IDC_HAND
        wc.lpszClassName = self.class_name
        if not user32.RegisterClassExW(ctypes.byref(wc)) and ctypes.get_last_error() != 1410:
            raise ctypes.WinError(ctypes.get_last_error())
        self.scale = dpi_for_window(0) / 96.0
        self.size = int(round(self.base_size * self.scale))
        bx, by = self.saved_pos
        if bx is not None and by is not None:
            self.x, self.y = clamp_to_virtual(int(bx), int(by), self.size, self.size)
        else:
            self.x, self.y = default_ball_position(self.size)
        self.hwnd = int(
            user32.CreateWindowExW(
                WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_TOPMOST | WS_EX_NOACTIVATE,
                self.class_name,
                "Cursor 用量悬浮球",
                WS_POPUP,
                self.x,
                self.y,
                self.size,
                self.size,
                None,
                None,
                self.hinstance,
                None,
            )
            or 0
        )
        if not self.hwnd:
            raise ctypes.WinError(ctypes.get_last_error())
        self._render()
        user32.ShowWindow(self.hwnd, SW_SHOWNA)
        self.check_fullscreen()

    def stop(self) -> None:
        if self.hwnd and user32.IsWindow(self.hwnd):
            user32.DestroyWindow(self.hwnd)
        self.hwnd = 0
        try:
            user32.UnregisterClassW(self.class_name, self.hinstance)
        except Exception:
            pass

    def reset_position(self) -> None:
        self.x, self.y = default_ball_position(self.size)
        self._paint()
        self.on_moved(self.x, self.y)

    # --- data ---------------------------------------------------------------

    def set_summary(self, summary: dict[str, Any] | None) -> None:
        key = None
        if summary is not None:
            used = float(summary.get("individualUsedCents") or 0)
            limit = float(summary.get("individualLimitCents") or 0)
            key = (_usd(used), _usd(limit), round(used / limit, 3) if limit > 0 else 0)
        self.summary = summary
        if key != self.summary_key:
            self.summary_key = key
            self._render()

    def _render(self) -> None:
        if not self.hwnd:
            return
        image = render_ball(self.size, self.summary, self.scale, font_size=self.font_size, ring_width=self.ring_width)
        self.bitmap = LayeredBitmap(image)
        self._paint()

    def _paint(self) -> None:
        if self.hwnd and self.bitmap and not self.hidden_fullscreen and not self.menu_open:
            paint_layered(self.hwnd, self.bitmap, self.x, self.y, alpha=round(self.opacity * 2.55))

    # --- fullscreen / z-order -------------------------------------------------

    def check_fullscreen(self) -> None:
        if not self.hwnd or self.menu_open:
            return
        fullscreen = is_fullscreen_session()
        if fullscreen != self.hidden_fullscreen:
            self.hidden_fullscreen = fullscreen
            if fullscreen:
                user32.ShowWindow(self.hwnd, SW_HIDE)
            else:
                user32.ShowWindow(self.hwnd, SW_SHOWNA)
                self._paint()
        if not fullscreen:
            keep_topmost(self.hwnd)

    # --- window procedure -----------------------------------------------------

    def _show_menu(self) -> None:
        menu = user32.CreatePopupMenu()
        if not menu:
            return
        self.menu_open = True
        clear_topmost(self.hwnd)
        try:
            user32.AppendMenuW(menu, MF_STRING, ID_SHOW, L("显示看板", "Show dashboard"))
            user32.AppendMenuW(menu, MF_STRING, ID_RESET, L("重置位置", "Reset position"))
            user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
            user32.AppendMenuW(menu, MF_STRING, ID_CLOSE, L("关闭悬浮球", "Close floating ball"))
            point = wintypes.POINT()
            user32.GetCursorPos(ctypes.byref(point))
            user32.SetForegroundWindow(self.hwnd)
            command = int(user32.TrackPopupMenuEx(menu, TPM_RIGHTBUTTON | TPM_RETURNCMD, point.x, point.y, self.hwnd, None) or 0)
        finally:
            user32.DestroyMenu(menu)
            self.menu_open = False
            keep_topmost(self.hwnd)
        if command == ID_SHOW:
            self.on_show()
        elif command == ID_RESET:
            self.reset_position()
        elif command == ID_CLOSE:
            self.on_close()

    def _window_rect(self) -> tuple[int, int]:
        rect = wintypes.RECT()
        user32.GetWindowRect(self.hwnd, ctypes.byref(rect))
        return int(rect.left), int(rect.top)

    def _window_proc(self, hwnd: int, msg: int, wparam: int, lparam: int) -> int:
        try:
            if msg == WM_NCHITTEST:
                return HTCAPTION
            if msg == WM_ENTERSIZEMOVE:
                self.move_origin = self._window_rect()
                return 0
            if msg == WM_EXITSIZEMOVE:
                origin, self.move_origin = self.move_origin, None
                self.x, self.y = self._window_rect()
                if origin == (self.x, self.y):
                    self.on_show()
                else:
                    self.on_moved(self.x, self.y)
                return 0
            if msg in (WM_NCRBUTTONUP, WM_CONTEXTMENU):
                self._show_menu()
                return 0
            if msg == WM_DPICHANGED:
                self.scale = dpi_for_window(hwnd) / 96.0
                self.size = int(round(self.base_size * self.scale))
                self._render()
                return 0
        except Exception:
            pass
        return int(user32.DefWindowProcW(hwnd, msg, wparam, lparam))
