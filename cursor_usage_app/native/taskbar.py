"""Windows 11 native taskbar usage widget implemented with ctypes only.

The visible window is a per-pixel-alpha layered popup re-parented into the
primary ``Shell_TrayWnd`` and positioned inside its free visual band. Windows
11's XAML compositor obscures ordinary Win32 children, but a layered window
first in the child z-order is composited above it. A separate hidden window
receives Explorer restart and display/settings broadcasts.
"""

from __future__ import annotations

import ctypes
import sys
import threading
import time
from ctypes import wintypes
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from PIL import Image, ImageDraw

from ..i18n import L
from .win import LayeredBitmap, paint_layered, ui_font

IS_WINDOWS = sys.platform == "win32"

WM_DESTROY = 0x0002
WM_SETTINGCHANGE = 0x001A
WM_DISPLAYCHANGE = 0x007E
WM_CONTEXTMENU = 0x007B
WM_TIMER = 0x0113
WM_COMMAND = 0x0111
WM_LBUTTONUP = 0x0202
WM_RBUTTONUP = 0x0205
WM_DPICHANGED = 0x02E0

WS_POPUP = 0x80000000
WS_CLIPSIBLINGS = 0x04000000
WS_CLIPCHILDREN = 0x02000000
WS_EX_TOPMOST = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_LAYERED = 0x00080000
WS_EX_NOACTIVATE = 0x08000000
CS_HREDRAW = 0x0002
CS_VREDRAW = 0x0001

SW_HIDE = 0
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040
HWND_TOP = None
GW_CHILD = 5

TPM_RIGHTBUTTON = 0x0002
TPM_RETURNCMD = 0x0100
MF_STRING = 0x0000
MF_SEPARATOR = 0x0800

MONITOR_DEFAULTTOPRIMARY = 1

ID_SHOW = 1001
ID_REFRESH = 1002
ID_CLOSE = 1003
TIMER_MAINTENANCE = 1
TIMER_INTERVAL_MS = 2000
POLL_SECONDS = 4.0
LAYOUT_CHECK_SECONDS = 30.0
UIA_CACHE_SECONDS = 30.0
MAX_RETRY_SECONDS = 60.0
WM_APP_UIA_READY = 0x8000 + 1
_UIA_LOCK = threading.Lock()
_UIA_CACHE: tuple[int, float, list[dict[str, Any]], str | None] | None = None
_UIA_WORKER: threading.Thread | None = None
_UIA_NOTIFY_HWND = 0
# Screen rect of the last embedded widget. UIA reports the widget itself as a
# taskbar element, and cached geometry can outlive a destroyed widget.
_LAST_WIDGET_RECT: tuple[int, int, int, int] | None = None
_LAST_STATUS: dict[str, Any] | None = None
_SETTINGS_CACHE: dict[str, Any] | None = None


if IS_WINDOWS:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    ntdll = ctypes.WinDLL("ntdll", use_last_error=True)

    LRESULT = ctypes.c_ssize_t
    WNDPROC = ctypes.WINFUNCTYPE(
        LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
    )

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

    class RTL_OSVERSIONINFOW(ctypes.Structure):
        _fields_ = [
            ("dwOSVersionInfoSize", wintypes.DWORD),
            ("dwMajorVersion", wintypes.DWORD),
            ("dwMinorVersion", wintypes.DWORD),
            ("dwBuildNumber", wintypes.DWORD),
            ("dwPlatformId", wintypes.DWORD),
            ("szCSDVersion", wintypes.WCHAR * 128),
        ]

    # Explicit signatures are important on 64-bit Python/PyInstaller.
    user32.DefWindowProcW.restype = LRESULT
    user32.DefWindowProcW.argtypes = [
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    ]
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
    user32.FindWindowW.restype = wintypes.HWND
    user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.IsWindow.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.RegisterWindowMessageW.argtypes = [wintypes.LPCWSTR]
    user32.RegisterWindowMessageW.restype = wintypes.UINT
    user32.MonitorFromWindow.restype = wintypes.HANDLE
    user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    user32.LoadCursorW.restype = wintypes.HANDLE
    user32.LoadCursorW.argtypes = [wintypes.HINSTANCE, ctypes.c_void_p]
    user32.RegisterClassExW.restype = wintypes.ATOM
    user32.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
    user32.UnregisterClassW.argtypes = [wintypes.LPCWSTR, wintypes.HINSTANCE]
    user32.SetParent.restype = wintypes.HWND
    user32.SetParent.argtypes = [wintypes.HWND, wintypes.HWND]
    user32.GetWindow.restype = wintypes.HWND
    user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.SetTimer.argtypes = [
        wintypes.HWND,
        ctypes.c_size_t,
        wintypes.UINT,
        ctypes.c_void_p,
    ]
    user32.SetTimer.restype = ctypes.c_size_t
    user32.DestroyWindow.argtypes = [wintypes.HWND]
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.SetWindowPos.argtypes = [
        wintypes.HWND,
        wintypes.HWND,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.UINT,
    ]
    user32.PostMessageW.argtypes = [
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    ]
    user32.KillTimer.argtypes = [wintypes.HWND, ctypes.c_size_t]
    user32.CreatePopupMenu.restype = wintypes.HMENU
    user32.AppendMenuW.argtypes = [
        wintypes.HMENU,
        wintypes.UINT,
        ctypes.c_size_t,
        wintypes.LPCWSTR,
    ]
    user32.TrackPopupMenuEx.restype = wintypes.UINT
    user32.TrackPopupMenuEx.argtypes = [
        wintypes.HMENU,
        wintypes.UINT,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.HWND,
        wintypes.LPVOID,
    ]
    user32.DestroyMenu.argtypes = [wintypes.HMENU]
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
    user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
    kernel32.GetModuleHandleW.restype = wintypes.HMODULE
    kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_component_status(fields: dict[str, Any]) -> None:
    """Record widget health in memory (shown in the settings drawer and tray)."""
    global _LAST_STATUS
    if _LAST_STATUS is not None and all(
        _LAST_STATUS.get(key) == value for key, value in fields.items()
    ):
        return
    status = dict(_LAST_STATUS or {})
    status.update(fields)
    status["updatedAt"] = _utc_now()
    _LAST_STATUS = status


def component_status() -> dict[str, Any]:
    return dict(_LAST_STATUS or {"state": "stopped", "visible": False, "reason": "disabled"})


def _widget_settings() -> dict[str, Any]:
    """Settings snapshot passed in by TaskbarWidget; the widget is recreated on style changes."""
    return _SETTINGS_CACHE or {}


def _windows_version() -> dict[str, Any]:
    if not IS_WINDOWS:
        return {"major": 0, "minor": 0, "build": 0, "isWindows11": False}
    info = RTL_OSVERSIONINFOW()
    info.dwOSVersionInfoSize = ctypes.sizeof(info)
    try:
        status = ntdll.RtlGetVersion(ctypes.byref(info))
        if status != 0:
            raise OSError(status)
        major, minor, build = (
            int(info.dwMajorVersion),
            int(info.dwMinorVersion),
            int(info.dwBuildNumber),
        )
    except Exception:
        major = minor = build = 0
    return {
        "major": major,
        "minor": minor,
        "build": build,
        "isWindows11": major == 10 and build >= 22000,
    }


def _window_class(hwnd: int) -> str:
    if not IS_WINDOWS or not hwnd:
        return ""
    buf = ctypes.create_unicode_buffer(256)
    return buf.value if not user32.GetClassNameW(hwnd, buf, len(buf)) else buf.value


def _rect(hwnd: int) -> tuple[int, int, int, int] | None:
    if not IS_WINDOWS or not hwnd:
        return None
    value = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(value)):
        return None
    return int(value.left), int(value.top), int(value.right), int(value.bottom)


def _dpi_for_window(hwnd: int) -> int:
    if not IS_WINDOWS:
        return 96
    try:
        fn = user32.GetDpiForWindow
        fn.restype = wintypes.UINT
        fn.argtypes = [wintypes.HWND]
        dpi = int(fn(hwnd))
        return dpi if dpi >= 96 else 96
    except Exception:
        return 96


def _taskbar_alignment() -> int | None:
    """Return 1 for centered, 0 for left, None if the registry is unreadable.

    Windows 11 only writes ``TaskbarAl`` after the user changes the setting,
    so a missing value means the default centered layout.
    """
    try:
        import winreg

        key_name = r"Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_name) as key:
            value, _kind = winreg.QueryValueEx(key, "TaskbarAl")
        return int(value)
    except FileNotFoundError:
        return 1
    except Exception:
        return None


def _uia_taskbar_elements_sync(taskbar: int) -> tuple[list[dict[str, Any]], str | None]:
    """Read occupied taskbar element bounds through Windows UI Automation."""
    try:
        import uiautomation as automation

        root = automation.ControlFromHandle(taskbar)
        if root is None:
            return [], "uia-taskbar-unavailable"
        found: list[dict[str, Any]] = []
        seen: set[tuple[int, int, int, int, str]] = set()
        # Direct UIA children expose the notification area and aggregate task
        # button group. Recursing into every XAML descendant can block Explorer
        # for minutes on some Windows 11 builds and is unnecessary for finding
        # a free interval.
        for child in root.GetChildren():
            try:
                rect = child.BoundingRectangle
                bounds = (
                    int(rect.left),
                    int(rect.top),
                    int(rect.right),
                    int(rect.bottom),
                )
                # Names and control-type properties can trigger expensive
                # cross-process XAML queries; geometry alone is authoritative.
                kind = "UIAElement"
                name = ""
                key = (*bounds, kind)
                if key in seen or bounds[2] <= bounds[0] or bounds[3] <= bounds[1]:
                    continue
                seen.add(key)
                found.append({"rect": bounds, "type": kind, "name": name})
            except Exception:
                continue
        return found, None
    except Exception as exc:
        return [], f"uia-unavailable:{type(exc).__name__}"


def _uia_taskbar_elements(
    taskbar: int, *, max_age: float = UIA_CACHE_SECONDS
) -> tuple[list[dict[str, Any]], str | None]:
    """Return cached UIA geometry; refresh in the background, never blocking.

    When a refresh completes, ``WM_APP_UIA_READY`` is posted to
    ``_UIA_NOTIFY_HWND`` so the widget can re-evaluate its layout.
    """
    global _UIA_WORKER
    now = time.monotonic()
    with _UIA_LOCK:
        stale = _UIA_CACHE if _UIA_CACHE and _UIA_CACHE[0] == taskbar else None
        if stale and now - stale[1] < max_age:
            return list(stale[2]), stale[3]
        if _UIA_WORKER is None or not _UIA_WORKER.is_alive():

            def collect() -> None:
                global _UIA_CACHE, _UIA_WORKER
                elements, error = _uia_taskbar_elements_sync(taskbar)
                with _UIA_LOCK:
                    previous = _UIA_CACHE
                    _UIA_CACHE = (taskbar, time.monotonic(), elements, error)
                    _UIA_WORKER = None
                    notify = _UIA_NOTIFY_HWND
                changed = (
                    previous is None
                    or previous[0] != taskbar
                    or previous[2] != elements
                    or previous[3] != error
                )
                if notify and changed and IS_WINDOWS:
                    user32.PostMessageW(notify, WM_APP_UIA_READY, 0, 0)

            _UIA_WORKER = threading.Thread(
                target=collect, daemon=True, name="taskbar-uia-geometry"
            )
            _UIA_WORKER.start()
        if stale:
            return list(stale[2]), stale[3]
    return [], "uia-pending"


def _first_free_x(
    *,
    left: int,
    right: int,
    top: int,
    bottom: int,
    width: int,
    margin: int,
    occupied: list[dict[str, Any]],
) -> int | None:
    intervals: list[tuple[int, int]] = []
    for item in occupied:
        rect = item["rect"]
        if rect[3] <= top or rect[1] >= bottom:
            continue
        item_width = rect[2] - rect[0]
        if item_width >= (right - left) * 0.8:
            continue
        intervals.append((max(left, rect[0] - margin), min(right, rect[2] + margin)))
    intervals.sort()
    cursor = left + margin
    for start, end in intervals:
        if start - cursor >= width:
            return cursor
        cursor = max(cursor, end)
    return cursor if right - margin - cursor >= width else None


def _embedding_layout(
    taskbar: int,
    *,
    ignore_rect: tuple[int, int, int, int] | None = None,
) -> tuple[dict[str, int] | None, str]:
    if not IS_WINDOWS or not taskbar or not user32.IsWindow(taskbar):
        return None, "explorer-unavailable"
    if _window_class(taskbar) != "Shell_TrayWnd":
        return None, "unexpected-taskbar-class"
    version = _windows_version()
    if not version["isWindows11"]:
        return None, "requires-windows-11"
    tray = _rect(taskbar)
    if not tray:
        return None, "taskbar-rect-unavailable"
    left, top, right, bottom = tray
    tray_width, tray_height = right - left, bottom - top
    dpi = _dpi_for_window(taskbar)
    scale = dpi / 96.0
    if tray_width < int(800 * scale) or tray_height < int(30 * scale):
        return None, "taskbar-too-small-or-auto-hidden"
    if tray_width <= tray_height * 4 or tray_height > int(96 * scale):
        return None, "vertical-or-nonstandard-taskbar"
    margin = max(6, round(10 * scale))
    settings = _widget_settings()
    requested_width = int(settings.get("dockWidth") or 220)
    compact = bool(settings.get("dockCompact"))
    width = round(max(150 if compact else 172, min(420, requested_width)) * scale)
    height = tray_height - margin
    y = max(2, (tray_height - height) // 2)
    occupied, uia_error = _uia_taskbar_elements(taskbar)
    if uia_error:
        return None, uia_error
    if ignore_rect is not None:
        occupied = [item for item in occupied if item["rect"] != ignore_rect]
    search_right = right - margin
    x_screen = _first_free_x(
        left=left,
        right=search_right,
        top=top + y,
        bottom=top + y + height,
        width=width,
        margin=margin,
        occupied=occupied,
    )
    if x_screen is None:
        return None, "no-uia-confirmed-free-space"
    x = x_screen - left
    return {"x": x, "y": y, "width": width, "height": height, "dpi": dpi}, "ok"


def probe() -> dict[str, Any]:
    version = _windows_version()
    if not IS_WINDOWS:
        return {
            "taskbarHwnd": 0,
            "rect": None,
            "class": "",
            "windowsVersion": version,
            "canEmbed": False,
            "reason": "not-windows",
        }
    taskbar = int(user32.FindWindowW("Shell_TrayWnd", None) or 0)
    tray_rect = _rect(taskbar)
    uia_elements, uia_error = _uia_taskbar_elements(taskbar)
    deadline = time.monotonic() + 5.0
    while uia_error == "uia-pending" and time.monotonic() < deadline:
        time.sleep(0.1)
        uia_elements, uia_error = _uia_taskbar_elements(taskbar)
    layout, reason = _embedding_layout(taskbar)
    return {
        "taskbarHwnd": taskbar,
        "rect": (
            {
                "left": tray_rect[0],
                "top": tray_rect[1],
                "right": tray_rect[2],
                "bottom": tray_rect[3],
                "width": tray_rect[2] - tray_rect[0],
                "height": tray_rect[3] - tray_rect[1],
            }
            if tray_rect
            else None
        ),
        "class": _window_class(taskbar),
        "windowsVersion": version,
        "dpi": _dpi_for_window(taskbar) if taskbar else None,
        "alignment": _taskbar_alignment(),
        "uia": {
            "available": uia_error is None,
            "error": uia_error,
            "elementCount": len(uia_elements),
            "occupied": [
                {
                    "name": item["name"],
                    "type": item["type"],
                    "rect": list(item["rect"]),
                }
                for item in uia_elements
                if item["rect"][2] - item["rect"][0]
                < ((tray_rect[2] - tray_rect[0]) * 0.8 if tray_rect else 0)
            ][:32],
        },
        "canEmbed": layout is not None,
        "reason": reason,
        "suggestedChildRect": layout,
    }


def _summary_from_report(report: dict[str, Any] | None) -> tuple[float, float] | None:
    if not isinstance(report, dict):
        return None
    if "individualUsedCents" in report:
        try:
            return (
                float(report.get("individualUsedCents") or 0),
                float(report.get("individualLimitCents") or 0),
            )
        except (TypeError, ValueError):
            return None
    summary = report.get("summary")
    if isinstance(summary, dict):
        try:
            return (
                float(summary.get("individualUsedCents") or 0),
                float(summary.get("individualLimitCents") or 0),
            )
        except (TypeError, ValueError):
            pass
    period = report.get("periodUsage")
    spend = period.get("spendLimitUsage") if isinstance(period, dict) else None
    if isinstance(spend, dict):
        try:
            return (
                float(spend.get("individualUsed") or 0),
                float(spend.get("individualLimit") or 0),
            )
        except (TypeError, ValueError):
            pass
    return None


def _money(cents: float) -> str:
    dollars = max(0.0, cents) / 100.0
    return f"${dollars:,.0f}" if dollars >= 100 else f"${dollars:,.2f}"


def _app_icon_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "assets" / "app.png"
    return Path(__file__).resolve().parents[2] / "assets" / "app.png"


_ICON_CACHE: dict[int, Image.Image | None] = {}


def _app_icon(size: int) -> Image.Image | None:
    if size not in _ICON_CACHE:
        try:
            with Image.open(_app_icon_path()) as source:
                _ICON_CACHE[size] = source.convert("RGBA").resize((size, size), Image.Resampling.LANCZOS)
        except OSError:
            _ICON_CACHE[size] = None
    return _ICON_CACHE[size]


def _accent(progress: float) -> tuple[int, int, int, int]:
    # Same thresholds and colors as the floating ball ring.
    if progress >= 0.9:
        return (220, 38, 38, 255)
    if progress >= 0.7:
        return (217, 119, 6, 255)
    return (37, 99, 235, 255)


def render_dock(width: int, height: int, dpi: int, usage: tuple[float, float] | None) -> Image.Image:
    """RGBA widget image: rounded card, app icon, "$used / $limit" and a progress bar."""
    scale = dpi / 96
    ss = 3
    radius = max(10, round(12 * scale))
    icon_size = max(22, round(24 * scale))
    icon_x = max(7, round(8 * scale))
    text_left = icon_x + icon_size + max(7, round(8 * scale))
    text_right = width - max(8, round(10 * scale))
    track_h = max(5, round(6 * scale))
    track_y = height - track_h - max(4, round(5 * scale))

    if usage is None:
        text, progress = "-- / --", 0.0
    else:
        used, limit = usage
        text = f"{_money(used)} / {_money(limit)}"
        progress = min(1.0, used / limit) if limit > 0 else 0.0

    # Shapes are supersampled for smooth corners; text is drawn at 1x to stay crisp.
    big = Image.new("RGBA", (width * ss, height * ss), (0, 0, 0, 0))
    draw = ImageDraw.Draw(big)
    draw.rounded_rectangle(
        (0, 0, width * ss - 1, height * ss - 1),
        radius=radius * ss,
        fill=(255, 255, 255, 255),
        outline=(219, 227, 238, 255),
        width=max(1, round(scale)) * ss,
    )
    track = (text_left * ss, track_y * ss, text_right * ss, (track_y + track_h) * ss)
    draw.rounded_rectangle(track, radius=track_h * ss // 2, fill=(226, 232, 240, 255))
    fill_right = text_left + round((text_right - text_left) * progress)
    if fill_right - text_left >= track_h:
        draw.rounded_rectangle(
            (track[0], track[1], fill_right * ss, track[3]), radius=track_h * ss // 2, fill=_accent(progress)
        )
    image = big.resize((width, height), Image.Resampling.LANCZOS)

    icon = _app_icon(icon_size)
    if icon is not None:
        image.alpha_composite(icon, (icon_x, max(3, (height - icon_size) // 2)))

    draw = ImageDraw.Draw(image)
    font = ui_font(max(13, round(14 * scale)), bold=True)
    available = text_right - text_left
    while len(text) > 1 and draw.textlength(text, font=font) > available:
        text = text[:-2] + "…"
    box = draw.textbbox((0, 0), text, font=font)
    band_bottom = track_y - max(1, round(2 * scale))
    y = (band_bottom - (box[3] - box[1])) / 2 - box[1]
    draw.text((text_left, y), text, font=font, fill=(15, 23, 42, 255))
    return image


class TaskbarWidget:
    """Own the Win32 controller and taskbar child windows.

    Runs inside the shared native UI thread: start()/stop() and every other
    method must be called on that thread.
    """

    class_name = "CursorUsageTaskbarWidget"

    def __init__(
        self,
        settings: dict[str, Any],
        *,
        on_show: Callable[[], None],
        on_refresh: Callable[[], None],
        on_close: Callable[[], None],
    ) -> None:
        if not IS_WINDOWS:
            raise RuntimeError("Windows 11 is required")
        global _SETTINGS_CACHE
        _SETTINGS_CACHE = dict(settings)
        self.on_show = on_show
        self.on_refresh = on_refresh
        self.on_close = on_close
        self.refresh_seconds = POLL_SECONDS
        self.hinstance = kernel32.GetModuleHandleW(None)
        self.controller_hwnd = 0
        self.widget_hwnd = 0
        self.taskbar_hwnd = 0
        self.taskbar_created = int(user32.RegisterWindowMessageW("TaskbarCreated"))
        self.running = True
        self.visible = False
        self.retry_seconds = 1.0
        self.next_retry_at = 0.0
        self.next_poll_at = 0.0
        self.next_layout_at = 0.0
        self.layout: dict[str, int] | None = None
        self.usage: tuple[float, float] | None = None
        self.reason = "starting"
        self._wndproc = WNDPROC(self._window_proc)
        self._register_class()

    def _register_class(self) -> None:
        cursor = user32.LoadCursorW(None, ctypes.c_void_p(32512))  # IDC_ARROW
        wc = WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(wc)
        wc.style = CS_HREDRAW | CS_VREDRAW
        wc.lpfnWndProc = self._wndproc
        wc.hInstance = self.hinstance
        wc.hCursor = cursor
        wc.lpszClassName = self.class_name
        atom = user32.RegisterClassExW(ctypes.byref(wc))
        if not atom and ctypes.get_last_error() == 1410:  # ERROR_CLASS_ALREADY_EXISTS
            # A leftover class would route messages to the previous instance's
            # WNDPROC: the new widget would never paint or run its timers.
            user32.UnregisterClassW(self.class_name, self.hinstance)
            atom = user32.RegisterClassExW(ctypes.byref(wc))
        if not atom:
            raise ctypes.WinError(ctypes.get_last_error())

    def _create_controller(self) -> None:
        self.controller_hwnd = int(
            user32.CreateWindowExW(
                0,
                self.class_name,
                "Cursor Usage Taskbar Controller",
                WS_CLIPCHILDREN,
                0,
                0,
                0,
                0,
                None,
                None,
                self.hinstance,
                None,
            )
            or 0
        )
        if not self.controller_hwnd:
            raise ctypes.WinError(ctypes.get_last_error())
        global _UIA_NOTIFY_HWND
        _UIA_NOTIFY_HWND = self.controller_hwnd
        user32.SetTimer(self.controller_hwnd, TIMER_MAINTENANCE, TIMER_INTERVAL_MS, None)

    def _destroy_widget(self) -> None:
        hwnd, self.widget_hwnd = self.widget_hwnd, 0
        self.visible = False
        self.layout = None
        if hwnd and user32.IsWindow(hwnd):
            try:
                user32.DestroyWindow(hwnd)
            except Exception:
                pass

    def _hide(self, reason: str, *, retry: bool) -> None:
        self.reason = reason
        self.visible = False
        if self.widget_hwnd and user32.IsWindow(self.widget_hwnd):
            user32.ShowWindow(self.widget_hwnd, SW_HIDE)
        if retry:
            self.next_retry_at = time.monotonic() + self.retry_seconds
            self.retry_seconds = min(MAX_RETRY_SECONDS, self.retry_seconds * 2.0)
        else:
            # No free space: re-check at the normal poll cadence
            # instead of on every maintenance tick.
            self.next_retry_at = time.monotonic() + POLL_SECONDS
        _write_component_status(
            {
                "state": "retrying" if retry else "hidden",
                "visible": False,
                "reason": reason,
                "taskbarHwnd": int(self.taskbar_hwnd or 0),
                "widgetHwnd": int(self.widget_hwnd or 0),
                "retrySeconds": self.retry_seconds if retry else None,
            }
        )

    def _attach(self, *, force: bool = False) -> bool:
        """Compute the layout and apply it only when something actually changed."""
        self.next_layout_at = time.monotonic() + LAYOUT_CHECK_SECONDS
        taskbar = int(user32.FindWindowW("Shell_TrayWnd", None) or 0)
        global _LAST_WIDGET_RECT
        current_rect = _rect(self.widget_hwnd) if self.widget_hwnd else None
        layout, reason = _embedding_layout(taskbar, ignore_rect=current_rect or _LAST_WIDGET_RECT)
        if not layout:
            if taskbar != self.taskbar_hwnd:
                self._destroy_widget()
            self.taskbar_hwnd = taskbar
            self._hide(reason, retry=reason == "explorer-unavailable")
            return False
        if force or taskbar != self.taskbar_hwnd:
            self._destroy_widget()
        self.taskbar_hwnd = taskbar
        if (
            self.visible
            and layout == self.layout
            and self.widget_hwnd
            and user32.IsWindow(self.widget_hwnd)
        ):
            return True
        taskbar_rect = _rect(taskbar)
        if not taskbar_rect:
            self._hide("taskbar-rect-unavailable", retry=True)
            return False
        screen_x = taskbar_rect[0] + layout["x"]
        screen_y = taskbar_rect[1] + layout["y"]
        if not self.widget_hwnd or not user32.IsWindow(self.widget_hwnd):
            hwnd = int(
                user32.CreateWindowExW(
                    WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_TOPMOST | WS_EX_NOACTIVATE,
                    self.class_name,
                    "Cursor Usage",
                    WS_POPUP | WS_CLIPSIBLINGS,
                    0,
                    0,
                    layout["width"],
                    layout["height"],
                    None,
                    None,
                    self.hinstance,
                    None,
                )
                or 0
            )
            if not hwnd:
                self._hide("create-widget-failed", retry=True)
                return False
            # Windows 11 composites the taskbar's XAML island over its ordinary
            # children; a layered popup re-parented into Shell_TrayWnd and kept
            # first in the child z-order is drawn above it. As a child it moves
            # with the taskbar, so Explorer re-stacking (Win+D, Task View)
            # cannot cover it.
            if not user32.SetParent(hwnd, taskbar):
                user32.DestroyWindow(hwnd)
                self._hide("set-parent-failed", retry=True)
                return False
            self.widget_hwnd = hwnd
        self.layout = dict(layout)
        user32.SetWindowPos(
            self.widget_hwnd,
            HWND_TOP,
            layout["x"],
            layout["y"],
            layout["width"],
            layout["height"],
            SWP_NOACTIVATE | SWP_SHOWWINDOW,
        )
        self._render()
        _LAST_WIDGET_RECT = (
            screen_x,
            screen_y,
            screen_x + layout["width"],
            screen_y + layout["height"],
        )
        self.visible = True
        self.reason = "ok"
        self.retry_seconds = 1.0
        self.next_retry_at = 0.0
        _write_component_status(
            {
                "state": "running",
                "visible": True,
                "reason": "ok",
                "taskbarHwnd": taskbar,
                "widgetHwnd": self.widget_hwnd,
                "dpi": layout["dpi"],
                "rect": {k: layout[k] for k in ("x", "y", "width", "height")},
                "retrySeconds": None,
            }
        )
        return True

    def set_summary(self, summary: dict[str, Any] | None) -> None:
        usage = _summary_from_report(summary)
        if usage == self.usage:
            return
        self.usage = usage
        if self.visible:
            self._render()

    def _render(self) -> None:
        if not self.layout or not self.widget_hwnd:
            return
        image = render_dock(self.layout["width"], self.layout["height"], self.layout["dpi"], self.usage)
        paint_layered(self.widget_hwnd, LayeredBitmap(image), self.layout["x"], self.layout["y"])

    def _keep_first_child(self) -> None:
        """Stay above the XAML island: first among Shell_TrayWnd's children."""
        if self.taskbar_hwnd and self.widget_hwnd:
            if int(user32.GetWindow(self.taskbar_hwnd, GW_CHILD) or 0) != self.widget_hwnd:
                user32.SetWindowPos(
                    self.widget_hwnd, HWND_TOP, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE
                )

    def _poll_visible(self) -> None:
        """Cheap periodic check while embedded: child order + periodic layout."""
        if time.monotonic() >= self.next_layout_at:
            self._attach()
            return
        self._keep_first_child()

    def _maintenance(self) -> None:
        now = time.monotonic()
        explorer_valid = bool(
            self.taskbar_hwnd and user32.IsWindow(self.taskbar_hwnd)
        )
        child_valid = bool(self.widget_hwnd and user32.IsWindow(self.widget_hwnd))
        if not explorer_valid or (self.visible and not child_valid):
            self._destroy_widget()
            if now >= self.next_retry_at:
                self._attach(force=True)
        elif not self.visible and now >= self.next_retry_at:
            self._attach()
        if now >= self.next_poll_at:
            self.next_poll_at = now + self.refresh_seconds
            if self.visible:
                self._poll_visible()

    def _show_menu(self, x: int, y: int) -> None:
        # The widget is a child of Explorer's taskbar; the menu belongs to our
        # own top-level controller so it can take the foreground.
        hwnd = self.controller_hwnd
        menu = user32.CreatePopupMenu()
        if not menu:
            return
        try:
            user32.AppendMenuW(menu, MF_STRING, ID_SHOW, L("显示看板", "Show dashboard"))
            user32.AppendMenuW(menu, MF_STRING, ID_REFRESH, L("立即刷新", "Refresh now"))
            user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
            user32.AppendMenuW(menu, MF_STRING, ID_CLOSE, L("关闭", "Close"))
            if x == -1 and y == -1:
                point = wintypes.POINT()
                user32.GetCursorPos(ctypes.byref(point))
                x, y = int(point.x), int(point.y)
            user32.SetForegroundWindow(hwnd)
            command = int(
                user32.TrackPopupMenuEx(
                    menu,
                    TPM_RIGHTBUTTON | TPM_RETURNCMD,
                    x,
                    y,
                    hwnd,
                    None,
                )
                or 0
            )
            if command == ID_SHOW:
                self.on_show()
            elif command == ID_REFRESH:
                self.on_refresh()
            elif command == ID_CLOSE:
                self.on_close()
        finally:
            user32.DestroyMenu(menu)

    def _window_proc(self, hwnd: int, msg: int, wparam: int, lparam: int) -> int:
        try:
            if msg == self.taskbar_created and hwnd == self.controller_hwnd:
                self._destroy_widget()
                self.retry_seconds = 1.0
                self.next_retry_at = 0.0
                self._attach(force=True)
                return 0
            if msg == WM_APP_UIA_READY and hwnd == self.controller_hwnd:
                self._attach()
                return 0
            if msg == WM_DPICHANGED and hwnd == self.widget_hwnd:
                self._attach()
                return 0
            if msg in (WM_DPICHANGED, WM_DISPLAYCHANGE, WM_SETTINGCHANGE) and (
                hwnd == self.controller_hwnd
            ):
                # Geometry may have changed: refresh UIA in the background and
                # re-layout now with cached data; WM_APP_UIA_READY follows.
                if self.taskbar_hwnd:
                    _uia_taskbar_elements(self.taskbar_hwnd, max_age=0.0)
                self._attach(force=msg == WM_DPICHANGED)
                return 0
            if msg == WM_TIMER and hwnd == self.controller_hwnd:
                self._maintenance()
                return 0
            if msg == WM_LBUTTONUP and hwnd == self.widget_hwnd:
                self.on_show()
                return 0
            if msg == WM_RBUTTONUP and hwnd == self.widget_hwnd:
                point = wintypes.POINT(
                    ctypes.c_short(lparam & 0xFFFF).value,
                    ctypes.c_short((lparam >> 16) & 0xFFFF).value,
                )
                user32.ClientToScreen(hwnd, ctypes.byref(point))
                self._show_menu(int(point.x), int(point.y))
                return 0
            if msg == WM_CONTEXTMENU and hwnd == self.widget_hwnd:
                x = ctypes.c_short(lparam & 0xFFFF).value
                y = ctypes.c_short((lparam >> 16) & 0xFFFF).value
                self._show_menu(x, y)
                return 0
            if msg == WM_COMMAND:
                return 0
            if msg == WM_DESTROY and hwnd == self.controller_hwnd:
                # The message loop is shared with the floating ball: never quit it here.
                self.running = False
                self._destroy_widget()
                _write_component_status(
                    {
                        "state": "stopped",
                        "visible": False,
                        "reason": "closed",
                        "taskbarHwnd": int(self.taskbar_hwnd or 0),
                        "widgetHwnd": 0,
                        "retrySeconds": None,
                    }
                )
                return 0
        except Exception as exc:
            self.reason = f"message-error:{type(exc).__name__}: {exc}"
            _write_component_status(
                {
                    "state": "error",
                    "visible": self.visible,
                    "reason": self.reason,
                    "taskbarHwnd": int(self.taskbar_hwnd or 0),
                    "widgetHwnd": int(self.widget_hwnd or 0),
                }
            )
        return int(user32.DefWindowProcW(hwnd, msg, wparam, lparam))

    def start(self) -> None:
        """Create windows on the calling (native UI) thread and embed."""
        _write_component_status({"state": "starting", "visible": False, "reason": "starting"})
        self._create_controller()
        self._attach(force=True)

    def reembed(self) -> None:
        self._destroy_widget()
        self.retry_seconds = 1.0
        self.next_retry_at = 0.0
        self._attach(force=True)

    def stop(self) -> None:
        global _UIA_NOTIFY_HWND
        _UIA_NOTIFY_HWND = 0
        if self.controller_hwnd and user32.IsWindow(self.controller_hwnd):
            user32.KillTimer(self.controller_hwnd, TIMER_MAINTENANCE)
            user32.DestroyWindow(self.controller_hwnd)
        if self.widget_hwnd and user32.IsWindow(self.widget_hwnd):
            user32.DestroyWindow(self.widget_hwnd)
        self.controller_hwnd = 0
        self.widget_hwnd = 0
        # The class captures this instance's WNDPROC; a new widget re-registers it.
        try:
            user32.UnregisterClassW(self.class_name, self.hinstance)
        except Exception:
            pass
        _write_component_status({"state": "stopped", "visible": False, "reason": "disabled"})
