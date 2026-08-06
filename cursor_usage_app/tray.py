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


def make_tray_image(size: int = 64) -> Image.Image:
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
) -> object:
    import pystray
    from pystray import MenuItem as Item

    icon_holder: dict[str, object] = {}

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
