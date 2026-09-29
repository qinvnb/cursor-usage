"""Small Win32 helpers shared by the native widgets (no Tk dependency)."""

from __future__ import annotations

import ctypes
import sys
from ctypes import byref, c_void_p, sizeof, wintypes
from typing import Any, Callable

from PIL import Image, ImageChops

IS_WINDOWS = sys.platform == "win32"

if IS_WINDOWS:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)

    user32.SetWindowPos.argtypes = [
        wintypes.HWND,
        wintypes.HWND,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.UINT,
    ]
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.c_void_p]
    user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    user32.MonitorFromWindow.restype = wintypes.HANDLE
    user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    user32.GetDC.restype = wintypes.HDC
    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    gdi32.CreateCompatibleDC.restype = wintypes.HDC
    gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    gdi32.CreateDIBSection.restype = wintypes.HBITMAP
    gdi32.CreateDIBSection.argtypes = [
        wintypes.HDC,
        c_void_p,
        wintypes.UINT,
        ctypes.POINTER(c_void_p),
        wintypes.HANDLE,
        wintypes.DWORD,
    ]
    gdi32.SelectObject.restype = wintypes.HANDLE
    gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HANDLE]
    gdi32.DeleteObject.argtypes = [wintypes.HANDLE]
    gdi32.DeleteDC.argtypes = [wintypes.HDC]
    user32.UpdateLayeredWindow.argtypes = [
        wintypes.HWND,
        wintypes.HDC,
        ctypes.POINTER(wintypes.POINT),
        ctypes.POINTER(wintypes.SIZE),
        wintypes.HDC,
        ctypes.POINTER(wintypes.POINT),
        wintypes.COLORREF,
        c_void_p,
        wintypes.DWORD,
    ]

HWND_TOPMOST = -1
HWND_NOTOPMOST = -2
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SWP_ASYNCWINDOWPOS = 0x4000


def enable_dpi_awareness() -> None:
    """Per-monitor v2 DPI awareness; must run before any window is created."""
    if not IS_WINDOWS:
        return
    try:
        user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except Exception:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass


def dpi_for_window(hwnd: int) -> int:
    if not IS_WINDOWS:
        return 96
    try:
        fn = user32.GetDpiForWindow
        fn.restype = wintypes.UINT
        fn.argtypes = [wintypes.HWND]
        dpi = int(fn(hwnd)) if hwnd else int(user32.GetDpiForSystem())
        return dpi if dpi >= 96 else 96
    except Exception:
        return 96


class RECT(ctypes.Structure):
    _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG), ("right", wintypes.LONG), ("bottom", wintypes.LONG)]


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", RECT), ("rcWork", RECT), ("dwFlags", wintypes.DWORD)]


def virtual_screen() -> tuple[int, int, int, int]:
    """Full virtual desktop across all monitors: (left, top, right, bottom)."""
    if IS_WINDOWS:
        left, top = int(user32.GetSystemMetrics(76)), int(user32.GetSystemMetrics(77))
        width, height = int(user32.GetSystemMetrics(78)), int(user32.GetSystemMetrics(79))
        if width > 0 and height > 0:
            return left, top, left + width, top + height
    return 0, 0, 1920, 1080


def primary_work_area() -> tuple[int, int, int, int]:
    if IS_WINDOWS:
        rect = RECT()
        if user32.SystemParametersInfoW(0x0030, 0, byref(rect), 0):  # SPI_GETWORKAREA
            return int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)
    return virtual_screen()


def clamp_to_virtual(x: int, y: int, width: int, height: int) -> tuple[int, int]:
    """Keep at least a third of the widget on the virtual desktop."""
    left, top, right, bottom = virtual_screen()
    visible = max(24, min(width, height) // 3)
    nx = min(max(x, left - width + visible), right - visible)
    ny = min(max(y, top - height + visible), bottom - visible)
    return int(nx), int(ny)


def default_ball_position(size: int, margin: int = 24) -> tuple[int, int]:
    _left, _top, right, bottom = primary_work_area()
    return clamp_to_virtual(right - size - margin, bottom - size - margin, size, size)


def keep_topmost(hwnd: int) -> None:
    """Re-assert the topmost band without showing, moving or repainting."""
    if IS_WINDOWS and hwnd:
        flags = SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE | SWP_ASYNCWINDOWPOS
        user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, flags)


def clear_topmost(hwnd: int) -> None:
    if IS_WINDOWS and hwnd:
        flags = SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE | SWP_ASYNCWINDOWPOS
        user32.SetWindowPos(hwnd, HWND_NOTOPMOST, 0, 0, 0, 0, flags)


_OWN_TITLES = {"Cursor 用量", "Cursor Usage", "Cursor 用量悬浮球"}
_SHELL_CLASSES = {"progman", "workerw", "shell_traywnd", "shell_secondarytraywnd", "dv2controlhost"}


def is_fullscreen_session() -> bool:
    """True for exclusive fullscreen/presentation or a window covering a whole monitor.

    Maximized windows only cover the work area and do not count.
    """
    if not IS_WINDOWS:
        return False
    try:
        state = ctypes.c_int(0)
        if shell32.SHQueryUserNotificationState(byref(state)) == 0 and state.value in (3, 4):
            return True
    except Exception:
        pass
    try:
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return False
        buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, buf, 256)
        if (buf.value or "").lower() in _SHELL_CLASSES:
            return False
        user32.GetWindowTextW(hwnd, buf, 256)
        if buf.value in _OWN_TITLES:
            return False
        win = RECT()
        if not user32.GetWindowRect(hwnd, byref(win)):
            return False
        ww, wh = win.right - win.left, win.bottom - win.top
        if ww < 400 or wh < 300:
            return False
        info = MONITORINFO()
        info.cbSize = sizeof(MONITORINFO)
        if not user32.GetMonitorInfoW(user32.MonitorFromWindow(hwnd, 2), byref(info)):
            return False
        mr = info.rcMonitor
        return (
            abs(win.left - mr.left) <= 2
            and abs(win.top - mr.top) <= 2
            and abs(ww - (mr.right - mr.left)) <= 6
            and abs(wh - (mr.bottom - mr.top)) <= 6
        )
    except Exception:
        return False


_hook_refs: list[Any] = []


def install_foreground_hook(on_change: Callable[[], None]) -> bool:
    """Call on_change() on foreground-window changes, via this thread's message loop."""
    if not IS_WINDOWS:
        return False
    EVENT_SYSTEM_FOREGROUND = 0x0003
    WINEVENT_OUTOFCONTEXT = 0x0000
    WINEVENT_SKIPOWNPROCESS = 0x0002
    proc_type = ctypes.WINFUNCTYPE(
        None, c_void_p, wintypes.DWORD, wintypes.HWND, wintypes.LONG, wintypes.LONG, wintypes.DWORD, wintypes.DWORD
    )

    def _proc(*_args: Any) -> None:
        try:
            on_change()
        except Exception:
            pass

    callback = proc_type(_proc)
    user32.SetWinEventHook.restype = c_void_p
    user32.SetWinEventHook.argtypes = [
        wintypes.DWORD,
        wintypes.DWORD,
        c_void_p,
        proc_type,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
    ]
    hook = user32.SetWinEventHook(
        EVENT_SYSTEM_FOREGROUND,
        EVENT_SYSTEM_FOREGROUND,
        None,
        callback,
        0,
        0,
        WINEVENT_OUTOFCONTEXT | WINEVENT_SKIPOWNPROCESS,
    )
    if not hook:
        return False
    _hook_refs.append((callback, hook))
    return True


class LayeredBitmap:
    """Premultiplied bottom-up BGRA pixels, prepared once and reused on every paint."""

    __slots__ = ("width", "height", "raw")

    def __init__(self, image: Image.Image) -> None:
        rgba = image.convert("RGBA")
        r, g, b, a = rgba.split()
        premultiplied = Image.merge(
            "RGBA", (ImageChops.multiply(r, a), ImageChops.multiply(g, a), ImageChops.multiply(b, a), a)
        )
        self.width, self.height = premultiplied.size
        self.raw = premultiplied.transpose(Image.Transpose.FLIP_TOP_BOTTOM).tobytes("raw", "BGRA")


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class _BLENDFUNCTION(ctypes.Structure):
    _fields_ = [
        ("BlendOp", wintypes.BYTE),
        ("BlendFlags", wintypes.BYTE),
        ("SourceConstantAlpha", wintypes.BYTE),
        ("AlphaFormat", wintypes.BYTE),
    ]


def paint_layered(hwnd: int, bitmap: LayeredBitmap, x: int, y: int, alpha: int = 255) -> None:
    """Show a per-pixel-alpha image on a WS_EX_LAYERED window at (x, y)."""
    if not IS_WINDOWS or not hwnd:
        return
    w, h = bitmap.width, bitmap.height
    screen = user32.GetDC(None)
    mem = gdi32.CreateCompatibleDC(screen)
    header = _BITMAPINFOHEADER()
    header.biSize = sizeof(_BITMAPINFOHEADER)
    header.biWidth, header.biHeight, header.biPlanes, header.biBitCount = w, h, 1, 32
    bits = c_void_p()
    hbmp = gdi32.CreateDIBSection(mem, byref(header), 0, byref(bits), None, 0)
    try:
        if not hbmp or not bits.value:
            return
        ctypes.memmove(bits, bitmap.raw, len(bitmap.raw))
        old = gdi32.SelectObject(mem, hbmp)
        blend = _BLENDFUNCTION(0, 0, max(0, min(255, int(alpha))), 1)  # AC_SRC_OVER, AC_SRC_ALPHA
        user32.UpdateLayeredWindow(
            hwnd,
            screen,
            byref(wintypes.POINT(int(x), int(y))),
            byref(wintypes.SIZE(w, h)),
            mem,
            byref(wintypes.POINT(0, 0)),
            0,
            ctypes.cast(byref(blend), c_void_p),
            0x2,  # ULW_ALPHA
        )
        gdi32.SelectObject(mem, old)
    finally:
        if hbmp:
            gdi32.DeleteObject(hbmp)
        gdi32.DeleteDC(mem)
        user32.ReleaseDC(None, screen)
