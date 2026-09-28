"""System tray for Cursor usage desktop app."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable

from PIL import Image, ImageDraw


def _assets_icon() -> Path | None:
    here = Path(__file__).resolve().parent.parent / "assets" / "app.png"
    if here.is_file():
        return here
    import sys

    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        p = Path(sys._MEIPASS) / "assets" / "app.png"
        if p.is_file():
            return p
    return None


def _ring_color(progress: float) -> tuple[int, int, int, int]:
    # Same thresholds as the floating ball and taskbar widget.
    if progress >= 0.9:
        return (220, 38, 38, 255)
    if progress >= 0.7:
        return (217, 119, 6, 255)
    return (37, 99, 235, 255)


def make_tray_image(size: int = 64, progress: float | None = None) -> Image.Image:
    """App icon; with ``progress`` (0–1) a usage ring is drawn around it."""
    base = _base_icon(size)
    if progress is None:
        return base
    ss = 4
    big = size * ss
    ring_w = max(6 * ss, big // 9)
    canvas = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    inner = big - 2 * ring_w - 2 * ss
    canvas.alpha_composite(
        base.resize((inner, inner), Image.Resampling.LANCZOS), (ring_w + ss, ring_w + ss)
    )
    draw = ImageDraw.Draw(canvas)
    box = (ring_w // 2, ring_w // 2, big - ring_w // 2 - 1, big - ring_w // 2 - 1)
    draw.arc(box, 0, 360, fill=(148, 163, 184, 200), width=ring_w)
    value = max(0.0, min(1.0, progress))
    if value > 0.005:
        draw.arc(box, -90, -90 + value * 360, fill=_ring_color(value), width=ring_w)
    return canvas.resize((size, size), Image.Resampling.LANCZOS)


def _base_icon(size: int) -> Image.Image:
    icon = _assets_icon()
    if icon is not None:
        try:
            return Image.open(icon).convert("RGBA").resize((size, size), Image.Resampling.LANCZOS)
        except Exception:
            pass
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    margin = 4
    draw.ellipse(
        (margin, margin, size - margin - 1, size - margin - 1),
        fill=(37, 99, 235, 255),
    )
    draw.ellipse(
        (size * 0.28, size * 0.28, size * 0.72, size * 0.72),
        outline=(255, 255, 255, 230),
        width=max(2, size // 18),
    )
    return img


def start_tray(
    *,
    on_show_main: Callable[[], None],
    on_toggle_ball: Callable[[], None],
    on_toggle_dock: Callable[[], None],
    on_refresh: Callable[[], None],
    on_quit: Callable[[], None],
    is_ball_on: Callable[[], bool] | None = None,
    is_dock_on: Callable[[], bool] | None = None,
    dock_status: Callable[[], str] | None = None,
    on_reembed: Callable[[], None] | None = None,
    on_export_diagnostics: Callable[[], None] | None = None,
    usage_lines: Callable[[], list[str]] | None = None,
    update_info: Callable[[], dict | None] | None = None,
    on_open_update: Callable[[], None] | None = None,
) -> object:
    import pystray
    from pystray import MenuItem as Item

    icon_holder: dict[str, object] = {}

    def usage_line(index: int) -> Callable[[object], str]:
        def text(_item: object = None) -> str:
            try:
                lines = usage_lines() if usage_lines else []
            except Exception:
                lines = []
            return lines[index] if index < len(lines) else ""

        return text

    def usage_line_visible(index: int) -> Callable[[object], bool]:
        return lambda _item: bool(usage_line(index)(None))

    def update_text(_item: object = None) -> str:
        info = update_info() if update_info else None
        return f"发现新版本 v{info['version']}（打开下载页）" if info else ""

    def do_open_update(_icon: object = None, _item: object = None) -> None:
        if on_open_update:
            on_open_update()

    def ball_checked(_item: object = None) -> bool:
        try:
            return bool(is_ball_on and is_ball_on())
        except Exception:
            return False

    def dock_checked(_item: object = None) -> bool:
        try:
            return bool(is_dock_on and is_dock_on())
        except Exception:
            return False

    def dock_status_text(_item: object = None) -> str:
        try:
            value = str(dock_status() if dock_status else "").strip()
        except Exception:
            value = ""
        labels = {
            "embedded": "已嵌入",
            "running": "已启动",
            "waiting": "等待 Explorer",
            "retrying": "重试中",
            "backoff": "重试中",
            "cooldown": "已暂停",
            "failed": "异常",
            "disabled": "已关闭",
            "stopped": "已关闭",
        }
        return f"任务栏状态：{labels.get(value, value or '未知')}"

    def refresh_menu() -> None:
        ic = icon_holder.get("icon")
        if ic is None:
            return
        try:
            ic.update_menu()  # type: ignore[attr-defined]
        except Exception:
            pass

    def do_show(_icon: object = None, _item: object = None) -> None:
        on_show_main()

    def do_ball(_icon: object = None, _item: object = None) -> None:
        on_toggle_ball()
        refresh_menu()

    def do_dock(_icon: object = None, _item: object = None) -> None:
        on_toggle_dock()
        refresh_menu()

    def do_refresh(_icon: object = None, _item: object = None) -> None:
        on_refresh()

    def do_reembed(_icon: object = None, _item: object = None) -> None:
        if on_reembed:
            on_reembed()
        refresh_menu()

    def do_export(_icon: object = None, _item: object = None) -> None:
        if on_export_diagnostics:
            on_export_diagnostics()

    def do_quit(_icon: object = None, _item: object = None) -> None:
        on_quit()

    image = make_tray_image()
    # default=True → Windows left-click runs「显示看板」instead of only opening menu.
    menu = pystray.Menu(
        Item("显示看板", do_show, default=True),
        Item(usage_line(0), None, enabled=False, visible=usage_line_visible(0)),
        Item(usage_line(1), None, enabled=False, visible=usage_line_visible(1)),
        Item(update_text, do_open_update, visible=lambda _item: bool(update_text())),
        pystray.Menu.SEPARATOR,
        Item("悬浮球", do_ball, checked=ball_checked),
        Item("嵌入任务栏", do_dock, checked=dock_checked),
        Item(dock_status_text, None, enabled=False),
        Item("重新嵌入", do_reembed, enabled=lambda _item: bool(dock_checked())),
        Item("立即刷新", do_refresh),
        Item("导出诊断包", do_export, enabled=bool(on_export_diagnostics)),
        pystray.Menu.SEPARATOR,
        Item("退出", do_quit),
    )
    icon = pystray.Icon("cursor_usage", image, "Cursor 用量", menu)
    icon_holder["icon"] = icon

    thread = threading.Thread(target=icon.run, daemon=True, name="tray")
    thread.start()
    return icon


def usage_progress(summary: dict | None) -> float | None:
    if not summary:
        return None
    try:
        limit = float(summary.get("individualLimitCents") or 0)
        used = float(summary.get("individualUsedCents") or 0)
    except (TypeError, ValueError):
        return None
    return used / limit if limit > 0 else None


def format_usage_lines(summary: dict | None) -> list[str]:
    if not summary:
        return []

    def usd(value: object) -> str:
        try:
            return f"${float(value or 0) / 100:.2f}"
        except (TypeError, ValueError):
            return "$0.00"

    lines = []
    if float(summary.get("individualLimitCents") or 0) > 0:
        lines.append(
            f"按需 {usd(summary.get('individualUsedCents'))} / {usd(summary.get('individualLimitCents'))}"
            f"，剩余 {usd(summary.get('individualRemainingCents'))}"
        )
    if float(summary.get("includedLimitCents") or 0) > 0:
        lines.append(
            f"套餐内 {usd(summary.get('includedUsedCents'))} / {usd(summary.get('includedLimitCents'))}"
        )
    return lines


def update_tray(icon: object, summary: dict | None) -> None:
    """Refresh the tray ring, tooltip and menu after new usage data arrives."""
    try:
        progress = usage_progress(summary)
        icon.icon = make_tray_image(progress=progress)  # type: ignore[attr-defined]
        lines = format_usage_lines(summary)
        icon.title = "Cursor 用量" + (f"\n{lines[0]}" if lines else "")  # type: ignore[attr-defined]
        icon.update_menu()  # type: ignore[attr-defined]
    except Exception:
        pass
