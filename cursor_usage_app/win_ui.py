"""Win32 layered window (per-pixel alpha) + multi-monitor geometry."""

from __future__ import annotations

import ctypes
import sys
import tkinter as tk
from ctypes import byref, c_void_p, sizeof
from ctypes.wintypes import BYTE, DWORD, HWND, LONG, POINT, SIZE, WORD
from typing import Any

from PIL import Image


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", DWORD),
        ("biWidth", LONG),
        ("biHeight", LONG),
        ("biPlanes", WORD),
        ("biBitCount", WORD),
        ("biCompression", DWORD),
        ("biSizeImage", DWORD),
        ("biXPelsPerMeter", LONG),
        ("biYPelsPerMeter", LONG),
        ("biClrUsed", DWORD),
        ("biClrImportant", DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", DWORD * 3)]


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [
        ("BlendOp", BYTE),
        ("BlendFlags", BYTE),
        ("SourceConstantAlpha", BYTE),
        ("AlphaFormat", BYTE),
    ]


def hwnd_of(root: tk.Misc) -> int:
    if sys.platform != "win32":
        return int(root.winfo_id())
    try:
        root.update_idletasks()
        return int(ctypes.windll.user32.GetParent(root.winfo_id()) or root.winfo_id())
    except Exception:
        return int(root.winfo_id())


# Keep refs so GC does not collect subclass procs / callbacks.
_subclass_refs: list[Any] = []


def install_rbutton_hook(hwnd: int, on_right: Any) -> None:
    """Fire on_right(x_root, y_root) on WM_RBUTTONUP for layered HWNDs."""
    if sys.platform != "win32" or not hwnd:
        return
    try:
        user32 = ctypes.windll.user32
        GWL_WNDPROC = -4
        WM_RBUTTONUP = 0x0205

        WNDPROC = ctypes.WINFUNCTYPE(
            ctypes.c_ssize_t, ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p
        )
        try:
            GetWindowLongPtr = user32.GetWindowLongPtrW
            SetWindowLongPtr = user32.SetWindowLongPtrW
        except AttributeError:
            GetWindowLongPtr = user32.GetWindowLongW
            SetWindowLongPtr = user32.SetWindowLongW

        GetWindowLongPtr.restype = ctypes.c_void_p
        SetWindowLongPtr.restype = ctypes.c_void_p
        user32.CallWindowProcW.restype = ctypes.c_ssize_t
        user32.CallWindowProcW.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_uint,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]

        old_proc = GetWindowLongPtr(HWND(hwnd), GWL_WNDPROC)

        def _proc(h, msg, wparam, lparam):  # type: ignore[no-untyped-def]
            if msg == WM_RBUTTONUP:
                try:
                    pt = POINT()
                    user32.GetCursorPos(byref(pt))
                    on_right(int(pt.x), int(pt.y))
                    return 0
                except Exception:
                    pass
            return int(user32.CallWindowProcW(old_proc, h, msg, wparam, lparam) or 0)

        new_proc = WNDPROC(_proc)
        _subclass_refs.append((new_proc, on_right, old_proc))
        SetWindowLongPtr(HWND(hwnd), GWL_WNDPROC, new_proc)
    except Exception:
        pass


def install_foreground_hook(on_change: Any) -> bool:
    """Call on_change() whenever the foreground window changes.

    Uses an out-of-context WinEvent hook, which is delivered through the
    calling thread's message loop (Tk's mainloop pumps it), so no polling
    thread is needed. Returns False when the hook cannot be installed.
    """
    if sys.platform != "win32":
        return False
    try:
        user32 = ctypes.windll.user32
        EVENT_SYSTEM_FOREGROUND = 0x0003
        WINEVENT_OUTOFCONTEXT = 0x0000
        WINEVENT_SKIPOWNPROCESS = 0x0002

        WINEVENTPROC = ctypes.WINFUNCTYPE(
            None,
            ctypes.c_void_p,
            DWORD,
            HWND,
            LONG,
            LONG,
            DWORD,
            DWORD,
        )

        def _proc(_hook, _event, _hwnd, _obj, _child, _thread, _time):  # type: ignore[no-untyped-def]
            try:
                on_change()
            except Exception:
                pass

        callback = WINEVENTPROC(_proc)
        user32.SetWinEventHook.restype = ctypes.c_void_p
        user32.SetWinEventHook.argtypes = [
            DWORD,
            DWORD,
            ctypes.c_void_p,
            WINEVENTPROC,
            DWORD,
            DWORD,
            DWORD,
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
        _subclass_refs.append((callback, on_change, hook))
        return True
    except Exception:
        return False


def virtual_screen() -> tuple[int, int, int, int]:
    """Full virtual desktop across all monitors: (left, top, right, bottom)."""
    if sys.platform == "win32":
        try:
            user32 = ctypes.windll.user32
            # SM_XVIRTUALSCREEN=76, Y=77, CX=78, CY=79
            left = int(user32.GetSystemMetrics(76))
            top = int(user32.GetSystemMetrics(77))
            width = int(user32.GetSystemMetrics(78))
            height = int(user32.GetSystemMetrics(79))
            if width > 0 and height > 0:
                return left, top, left + width, top + height
        except Exception:
            pass
    root = tk.Tk()
    root.withdraw()
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    root.destroy()
    return 0, 0, sw, sh


def primary_work_area() -> tuple[int, int, int, int]:
    """Primary monitor work area (excludes taskbar): (left, top, right, bottom)."""
    if sys.platform == "win32":
        try:
            from ctypes import wintypes

            class RECT(wintypes.RECT):
                pass

            rect = RECT()
            if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, byref(rect), 0):
                return int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)
        except Exception:
            pass
    return virtual_screen()


def default_ball_position(size: int, margin: int = 24) -> tuple[int, int]:
    """Bottom-right of the primary work area."""
    left, top, right, bottom = primary_work_area()
    x = right - size - margin
    y = bottom - size - margin
    return clamp_to_virtual(x, y, size, size)


def default_dock_position(width: int, height: int, scale: float = 1.0) -> tuple[int, int]:
    """Bottom-left of the primary work area (just above the taskbar, not on it)."""
    left, _top, _right, bottom = primary_work_area()
    x = int(left + 8 * scale)
    y = int(bottom - height - 8 * scale)
    return clamp_to_virtual(x, y, width, height)


def clamp_to_virtual(x: int, y: int, width: int, height: int, margin: int = 0) -> tuple[int, int]:
    """Clamp to virtual desktop (all monitors), including taskbar areas."""
    left, top, right, bottom = virtual_screen()
    # Keep at least ~40% of the widget visible on some screen edge.
    min_visible = max(24, min(width, height) // 3)
    max_x = right - min_visible
    max_y = bottom - min_visible
    min_x = left - width + min_visible
    min_y = top - height + min_visible
    nx = min(max(x, min_x + margin), max_x - margin)
    ny = min(max(y, min_y + margin), max_y - margin)
    return int(nx), int(ny)


def enable_layered(hwnd: int) -> None:
    if sys.platform != "win32":
        return
    user32 = ctypes.windll.user32
    GWL_EXSTYLE = -20
    WS_EX_LAYERED = 0x00080000
    WS_EX_TOOLWINDOW = 0x00000080
    WS_EX_TOPMOST = 0x00000008
    WS_EX_NOACTIVATE = 0x08000000
    style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    user32.SetWindowLongW(
        hwnd,
        GWL_EXSTYLE,
        style | WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_TOPMOST | WS_EX_NOACTIVATE,
    )


def is_window_visible(hwnd: int) -> bool:
    if sys.platform != "win32" or not hwnd:
        return False
    try:
        return bool(ctypes.windll.user32.IsWindowVisible(hwnd))
    except Exception:
        return False


def ensure_overlay_visible(hwnd: int) -> None:
    """Re-show overlay only when actually hidden (avoids taskbar-click flash)."""
    if sys.platform != "win32" or not hwnd:
        return
    try:
        user32 = ctypes.windll.user32
        if not user32.IsWindowVisible(hwnd):
            user32.ShowWindow(hwnd, 4)  # SW_SHOWNOACTIVATE
        keep_topmost(hwnd)
    except Exception:
        pass


class LayeredBitmap:
    """Premultiplied bottom-up BGRA pixels, prepared once and reused on every paint."""

    __slots__ = ("width", "height", "raw")

    def __init__(self, image: Image.Image) -> None:
        from PIL import ImageChops

        rgba = image.convert("RGBA")
        r, g, b, a = rgba.split()
        premultiplied = Image.merge(
            "RGBA",
            (ImageChops.multiply(r, a), ImageChops.multiply(g, a), ImageChops.multiply(b, a), a),
        )
        self.width, self.height = premultiplied.size
        self.raw = premultiplied.transpose(Image.Transpose.FLIP_TOP_BOTTOM).tobytes("raw", "BGRA")


def paint_layered(hwnd: int, image: Image.Image | LayeredBitmap, x: int, y: int) -> None:
    """Draw an RGBA image onto a layered window with per-pixel alpha (smooth edges)."""
    if sys.platform != "win32":
        return

    bitmap = image if isinstance(image, LayeredBitmap) else LayeredBitmap(image)
    w, h = bitmap.width, bitmap.height
    raw = bitmap.raw

    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32

    enable_layered(hwnd)

    hdc_screen = user32.GetDC(0)
    hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)

    bmi = BITMAPINFO()
    ctypes.memset(byref(bmi), 0, sizeof(bmi))
    bmi.bmiHeader.biSize = sizeof(BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth = w
    bmi.bmiHeader.biHeight = h
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 32
    bmi.bmiHeader.biCompression = 0  # BI_RGB

    bits = c_void_p()
    hbmp = gdi32.CreateDIBSection(hdc_mem, byref(bmi), 0, byref(bits), None, 0)
    if not hbmp or not bits.value:
        gdi32.DeleteDC(hdc_mem)
        user32.ReleaseDC(0, hdc_screen)
        return

    ctypes.memmove(bits, raw, len(raw))
    old = gdi32.SelectObject(hdc_mem, hbmp)

    blend = BLENDFUNCTION(0x00, 0x00, 255, 0x01)  # AC_SRC_OVER, AC_SRC_ALPHA
    size = SIZE(w, h)
    pt_src = POINT(0, 0)
    pt_dst = POINT(int(x), int(y))

    user32.UpdateLayeredWindow(
        HWND(hwnd),
        hdc_screen,
        byref(pt_dst),
        byref(size),
        hdc_mem,
        byref(pt_src),
        0,
        byref(blend),
        0x00000002,  # ULW_ALPHA
    )

    gdi32.SelectObject(hdc_mem, old)
    gdi32.DeleteObject(hbmp)
    gdi32.DeleteDC(hdc_mem)
    user32.ReleaseDC(0, hdc_screen)


def keep_topmost(hwnd: int) -> None:
    """Re-assert the Win32 topmost band without showing or repainting."""
    if sys.platform != "win32" or not hwnd:
        return
    try:
        user32 = ctypes.windll.user32
        user32.SetWindowPos.argtypes = [
            HWND,
            HWND,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_uint,
        ]
        user32.SetWindowPos.restype = ctypes.c_int
        # HWND_TOPMOST=-1; NOSIZE|NOMOVE|NOACTIVATE|ASYNCWINDOWPOS.
        # Crucially: no SHOWWINDOW and no UpdateLayeredWindow, so this cannot flash.
        flags = 0x0001 | 0x0002 | 0x0010 | 0x4000
        user32.SetWindowPos(HWND(hwnd), HWND(-1), 0, 0, 0, 0, flags)
    except Exception:
        pass


def clear_topmost(hwnd: int) -> None:
    """Temporarily leave the topmost band so menus can appear above the overlay."""
    if sys.platform != "win32" or not hwnd:
        return
    try:
        user32 = ctypes.windll.user32
        user32.SetWindowPos.argtypes = [
            HWND,
            HWND,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_uint,
        ]
        user32.SetWindowPos.restype = ctypes.c_int
        # HWND_NOTOPMOST=-2; NOSIZE|NOMOVE|NOACTIVATE|ASYNCWINDOWPOS
        flags = 0x0001 | 0x0002 | 0x0010 | 0x4000
        user32.SetWindowPos(HWND(hwnd), HWND(-2), 0, 0, 0, 0, flags)
    except Exception:
        pass


class RECT(ctypes.Structure):
    _fields_ = [("left", LONG), ("top", LONG), ("right", LONG), ("bottom", LONG)]


class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", DWORD),
        ("rcMonitor", RECT),
        ("rcWork", RECT),
        ("dwFlags", DWORD),
    ]


def is_fullscreen_session() -> bool:
    """
    Hide overlays for true fullscreen:
    D3D/presentation, or window covering the full monitor (F11 / video FS).
    Maximized windows cover work area only — do not hide.
    """
    if sys.platform != "win32":
        return False

    # 1) Shell notification state — exclusive fullscreen / presentation only.
    try:
        state = ctypes.c_int(0)
        hr = ctypes.windll.shell32.SHQueryUserNotificationState(byref(state))
        # QUNS_RUNNING_D3D_FULL_SCREEN=3, QUNS_PRESENTATION_MODE=4
        if hr == 0 and state.value in (3, 4):
            return True
    except Exception:
        pass

    # 2) Foreground geometry: full monitor = hide; work-area maximize = keep.
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return False

        class_buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, class_buf, 256)
        cls = (class_buf.value or "").lower()
        if cls in (
            "progman",
            "workerw",
            "shell_traywnd",
            "shell_secondarytraywnd",
            "dv2controlhost",
        ):
            return False

        title_buf = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, title_buf, 512)
        title = title_buf.value or ""
        if title in ("Cursor 用量悬浮球", "Cursor 用量提示条", "Cursor 用量"):
            return False

        win = RECT()
        if not user32.GetWindowRect(hwnd, byref(win)):
            return False
        ww = win.right - win.left
        wh = win.bottom - win.top
        if ww < 400 or wh < 300:
            return False

        monitor = user32.MonitorFromWindow(hwnd, 2)
        mi = MONITORINFO()
        mi.cbSize = sizeof(MONITORINFO)
        if not user32.GetMonitorInfoW(monitor, byref(mi)):
            return False

        mr = mi.rcMonitor
        mw = mr.right - mr.left
        mh = mr.bottom - mr.top
        wr = mi.rcWork
        ww_work = wr.right - wr.left
        wh_work = wr.bottom - wr.top
        if mw <= 0 or mh <= 0:
            return False

        def _near(a: int, b: int, tol: int = 4) -> bool:
            return abs(a - b) <= tol

        covers_monitor = (
            _near(win.left, mr.left, 2)
            and _near(win.top, mr.top, 2)
            and _near(ww, mw, 6)
            and _near(wh, mh, 6)
        )
        covers_work = (
            _near(win.left, wr.left, 8)
            and _near(win.top, wr.top, 8)
            and _near(ww, ww_work, 16)
            and _near(wh, wh_work, 16)
        )
        if covers_work and not covers_monitor:
            return False
        if covers_monitor:
            return True
        return False
    except Exception:
        return False


# Back-compat aliases used by older imports
def work_area() -> tuple[int, int, int, int]:
    return virtual_screen()


def clamp_to_screen(x: int, y: int, width: int, height: int, margin: int = 0) -> tuple[int, int]:
    return clamp_to_virtual(x, y, width, height, margin=margin)


def apply_elliptic_region(*_a: Any, **_k: Any) -> None:
    return None


def apply_round_rect_region(*_a: Any, **_k: Any) -> None:
    return None
