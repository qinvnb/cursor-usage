"""System tray for Cursor usage desktop app."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable

from PIL import Image, ImageDraw

from .i18n import L, app_title


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


def make_tray_image(size: int = 64, progress: float | None = None) -> Image.Image:
    """App icon; with ``progress`` (0–1) the gauge shows on-demand usage and the tile warns near the limit."""
    if progress is None:
        return _base_icon(size)
    try:
        from .icon_art import make_icon_image, palette_for

        value = max(0.0, min(1.0, progress))
        return make_icon_image(size, progress=value, palette=palette_for(value), supersample=8)
    except Exception:
        return _base_icon(size)


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
        if not info:
            return ""
        return L(f"发现新版本 v{info['version']}（打开下载页）", f"Update v{info['version']} available (open download page)")

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
            "embedded": ("已嵌入", "embedded"),
            "running": ("已启动", "running"),
            "waiting": ("等待 Explorer", "waiting for Explorer"),
            "retrying": ("重试中", "retrying"),
            "backoff": ("重试中", "retrying"),
            "cooldown": ("已暂停", "paused"),
            "failed": ("异常", "error"),
            "disabled": ("已关闭", "off"),
            "stopped": ("已关闭", "off"),
        }
        pair = labels.get(value)
        label = L(*pair) if pair else (value or L("未知", "unknown"))
        return L(f"任务栏状态：{label}", f"Taskbar widget: {label}")

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
    def tr(zh: str, en: str) -> Callable[[object], str]:
        # Menu texts are callables so a language switch shows up on the next open.
        return lambda _item: L(zh, en)

    # default=True → Windows left-click runs "show dashboard" instead of only opening the menu.
    menu = pystray.Menu(
        Item(tr("显示看板", "Show dashboard"), do_show, default=True),
        Item(usage_line(0), None, enabled=False, visible=usage_line_visible(0)),
        Item(usage_line(1), None, enabled=False, visible=usage_line_visible(1)),
        Item(usage_line(2), None, enabled=False, visible=usage_line_visible(2)),
        Item(usage_line(3), None, enabled=False, visible=usage_line_visible(3)),
        Item(update_text, do_open_update, visible=lambda _item: bool(update_text())),
        pystray.Menu.SEPARATOR,
        Item(tr("悬浮球", "Floating ball"), do_ball, checked=ball_checked),
        Item(tr("嵌入任务栏", "Taskbar widget"), do_dock, checked=dock_checked),
        Item(dock_status_text, None, enabled=False),
        Item(tr("重新嵌入", "Re-embed"), do_reembed, enabled=lambda _item: bool(dock_checked())),
        Item(tr("立即刷新", "Refresh now"), do_refresh),
        Item(tr("导出诊断包", "Export diagnostics"), do_export, enabled=bool(on_export_diagnostics)),
        pystray.Menu.SEPARATOR,
        Item(tr("退出", "Quit"), do_quit),
    )
    icon = pystray.Icon("cursor_usage", image, app_title(), menu)
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
        used = usd(summary.get("individualUsedCents"))
        limit = usd(summary.get("individualLimitCents"))
        left = usd(summary.get("individualRemainingCents"))
        lines.append(L(f"按需 {used} / {limit}，剩余 {left}", f"On-demand {used} / {limit}, {left} left"))
    auto_pct = summary.get("autoPercentUsed")
    api_pct = summary.get("apiPercentUsed")
    if auto_pct is not None or api_pct is not None:
        auto = f"{float(auto_pct or 0):.0f}%"
        api = f"{float(api_pct or 0):.0f}%"
        lines.append(L(f"套餐内 Cursor 模型（Auto）已用 {auto}", f"Included Cursor models (Auto): {auto} used"))
        lines.append(L(f"套餐内其他模型（API）已用 {api}", f"Included other models (API): {api} used"))
    elif float(summary.get("includedLimitCents") or 0) > 0:
        used = usd(summary.get("includedUsedCents"))
        limit = usd(summary.get("includedLimitCents"))
        lines.append(L(f"套餐内 {used} / {limit}", f"Included {used} / {limit}"))
    token_info = summary.get("tokens")
    if isinstance(token_info, dict) and token_info.get("total"):
        total = format_tokens(token_info.get("total"))
        lines.append(L(f"本周期 Token {total}", f"Tokens this cycle: {total}"))
    return lines


def format_tokens(value: object) -> str:
    try:
        n = float(value or 0)
    except (TypeError, ValueError):
        return "0"
    if n >= 1e9:
        return f"{n / 1e9:.2f}B"
    if n >= 1e6:
        return f"{n / 1e6:.1f}M"
    if n >= 1e3:
        return f"{n / 1e3:.1f}K"
    return str(round(n))


def update_tray(icon: object, summary: dict | None) -> None:
    """Refresh the tray ring, tooltip and menu after new usage data arrives."""
    try:
        progress = usage_progress(summary)
        icon.icon = make_tray_image(progress=progress)  # type: ignore[attr-defined]
        lines = format_usage_lines(summary)
        icon.title = app_title() + (f"\n{lines[0]}" if lines else "")  # type: ignore[attr-defined]
        icon.update_menu()  # type: ignore[attr-defined]
    except Exception:
        pass
