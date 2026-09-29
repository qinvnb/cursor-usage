"""Cursor 用量桌面应用：单进程（看板 WebView + 原生组件线程 + 托盘）。"""

from __future__ import annotations

import argparse
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import Any

from . import i18n


def _system_prefers_dark() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import winreg

        key = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as handle:
            value, _kind = winreg.QueryValueEx(handle, "AppsUseLightTheme")
        return int(value) == 0
    except OSError:
        return False


def _dashboard_html() -> str:
    """The built single-file dashboard (packages/ui -> web/dist/index.html)."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        base = Path(sys._MEIPASS)
    else:
        base = Path(__file__).resolve().parent.parent
    path = base / "web" / "dist" / "index.html"
    if not path.is_file():
        raise FileNotFoundError(f"Dashboard page not found: {path}. Run `npm run build` first.")
    return path.read_text(encoding="utf-8")


class App:
    """Glue between the WebView (TS core), native widgets, tray and settings."""

    def __init__(self, args: argparse.Namespace, logger: Any) -> None:
        from . import store
        from .native.ui_thread import NativeUI

        self.args = args
        self.logger = logger
        self.store = store
        self.settings = store.load_settings()
        i18n.set_language(self.settings.get("language"))
        self.window: Any = None
        self.tray: Any = None
        self.summary: dict[str, Any] | None = store.load_summary()
        self.page_ready = threading.Event()
        self.window_visible = threading.Event()
        self.stop_event = threading.Event()
        self.quitting = False
        self.win_maximized = bool(self.settings.get("windowMaximized"))
        self.win_fullscreen = bool(self.settings.get("windowFullscreen"))
        self._save_timer: threading.Timer | None = None
        self.native = NativeUI(
            on_show=self.show_main,
            on_refresh=lambda: self.refresh(full=True),
            on_ball_closed=lambda: self.set_component("ballEnabled", False),
            on_dock_closed=lambda: self.set_component("dockEnabled", False),
            on_ball_moved=lambda x, y: store.save_settings({"ballX": x, "ballY": y}),
        )

    # --- AppHooks (called by the bridge) ------------------------------------

    def on_summary(self, summary: dict[str, Any]) -> None:
        if summary == self.summary:
            return
        self.summary = summary
        self.native.set_summary(summary)
        if self.tray is not None:
            from .tray import update_tray

            update_tray(self.tray, summary)

    def notify(self, title: str, message: str) -> None:
        if self.tray is None:
            return
        try:
            self.tray.notify(message, title)
        except Exception:
            self.logger.warning("tray notification failed", exc_info=True)

    def apply_settings(self, settings: dict[str, Any]) -> None:
        self.settings = dict(settings)
        previous = i18n.current()
        i18n.set_language(self.settings.get("language"))
        self.native.configure(self.settings)
        if i18n.current() != previous and self.window is not None:
            try:
                self.window.set_title(i18n.app_title())
            except Exception:
                pass
        if self.tray is not None:
            from .tray import update_tray

            update_tray(self.tray, self.summary)

    def component_status(self) -> dict[str, Any]:
        return {
            "ball": {"running": self.native.running("ball")},
            "taskbarWidget": self.native.dock_status() if self.native.running("dock") else {"state": "stopped"},
        }

    def reembed_dock(self) -> None:
        self.native.reembed_dock()

    def update_info(self) -> dict[str, Any] | None:
        from . import updates

        return updates.latest

    # --- actions --------------------------------------------------------------

    def run_js(self, script: str) -> None:
        """Fire-and-forget script; never call evaluate_js inline on the GUI thread."""
        if self.window is None or not self.page_ready.is_set():
            return

        def _run() -> None:
            try:
                self.window.evaluate_js(script)
            except Exception:
                pass

        threading.Thread(target=_run, daemon=True, name="evaluate-js").start()

    def refresh(self, *, full: bool | None = None, auto: bool = False) -> None:
        opts = []
        if full is not None:
            opts.append(f"full:{'true' if full else 'false'}")
        if auto:
            opts.append("auto:true")
        self.run_js(f"void (window.cursorUsage && window.cursorUsage.refresh({{{','.join(opts)}}}))")

    def set_page_active(self, active: bool) -> None:
        if active:
            self.window_visible.set()
        else:
            self.window_visible.clear()
        self.run_js(f"void (window.cursorUsage && window.cursorUsage.setActive({'true' if active else 'false'}))")

    def show_main(self) -> None:
        window = self.window
        if window is None:
            return
        try:
            window.show()
            if self.win_fullscreen and not getattr(window, "fullscreen", False):
                window.toggle_fullscreen()
            elif self.win_maximized:
                window.maximize()
            else:
                window.restore()
        except Exception:
            pass
        if sys.platform == "win32":
            try:
                import ctypes

                user32 = ctypes.windll.user32
                hwnd = 0
                for title in (i18n.app_title(), *i18n.APP_TITLES):
                    hwnd = user32.FindWindowW(None, title)
                    if hwnd:
                        break
                if hwnd:
                    user32.ShowWindow(hwnd, 9 if user32.IsIconic(hwnd) else 5)
                    user32.SetForegroundWindow(hwnd)
            except Exception:
                pass
        self.set_page_active(True)

    def set_component(self, key: str, enabled: bool) -> None:
        self.apply_settings(self.store.save_settings({key: bool(enabled)}))
        self.run_js("void (window.cursorUsage && window.cursorUsage.reloadSettings())")

    def toggle_component(self, key: str) -> None:
        self.set_component(key, not bool(self.settings.get(key)))

    def export_diagnostics(self) -> None:
        try:
            from .diagnostics import create_diagnostic_zip

            path = create_diagnostic_zip()
            self.store.reveal_in_explorer(path)
        except Exception:
            self.logger.exception("diagnostic export failed")

    def quit(self) -> None:
        self.quitting = True
        self.stop_event.set()
        self.window_visible.set()
        self.persist_window()
        if self.tray is not None:
            try:
                self.tray.stop()
            except Exception:
                pass
        try:
            self.window.destroy()
        except Exception:
            pass

    # --- window geometry --------------------------------------------------------

    def persist_window(self) -> None:
        window = self.window
        if window is None:
            return
        patch: dict[str, Any] = {
            "windowMaximized": self.win_maximized,
            "windowFullscreen": self.win_fullscreen,
        }
        try:
            w, h = int(window.width or 0), int(window.height or 0)
            if w >= 640 and h >= 480 and not (self.win_maximized or self.win_fullscreen):
                patch.update({"windowWidth": w, "windowHeight": h, "windowX": int(window.x), "windowY": int(window.y)})
        except Exception:
            pass
        try:
            self.store.save_settings(patch)
        except Exception:
            pass

    def schedule_persist(self, *_a: Any) -> None:
        if self._save_timer is not None:
            self._save_timer.cancel()
        self._save_timer = threading.Timer(0.5, lambda: None if self.quitting else self.persist_window())
        self._save_timer.daemon = True
        self._save_timer.start()

    # --- background threads -------------------------------------------------------

    def scheduler(self) -> None:
        """Trigger core refreshes; the core itself decides full vs lightweight."""
        while not self.stop_event.wait(max(15, int(self.settings.get("refreshSeconds") or 60))):
            self.refresh(auto=True)

    def track_fullscreen(self) -> None:
        while not self.quitting:
            self.window_visible.wait()
            if self.stop_event.wait(1.0):
                return
            try:
                fs = bool(getattr(self.window, "fullscreen", False))
                if fs != self.win_fullscreen:
                    self.win_fullscreen = fs
                    if fs:
                        self.win_maximized = False
                    self.persist_window()
            except Exception:
                pass

    def update_checker(self) -> None:
        from . import updates

        last_check = 0.0
        if self.stop_event.wait(30.0):
            return
        while not self.quitting:
            if self.settings.get("checkUpdates") and time.monotonic() - last_check >= 24 * 3600:
                last_check = time.monotonic()
                try:
                    found = updates.check_latest()
                except Exception as exc:
                    self.logger.info("update check failed: %s", exc)
                    found = None
                if found:
                    state = self.store.load_alerts_state()
                    if state.get("updateNotified") != found["version"]:
                        self.store.save_alerts_state({**state, "updateNotified": found["version"]})
                        self.notify(
                            i18n.L("Cursor 用量有新版本", "Cursor Usage update available"),
                            i18n.L(
                                f"v{found['version']} 已发布，可在托盘菜单打开下载页",
                                f"v{found['version']} is out; open the download page from the tray menu",
                            ),
                        )
                    if self.tray is not None:
                        self.tray.update_menu()
            if self.stop_event.wait(3600.0):
                return

    # --- tray ---------------------------------------------------------------------

    def start_tray(self) -> None:
        from . import updates
        from .tray import format_usage_lines, start_tray, update_tray

        try:
            self.tray = start_tray(
                on_show_main=self.show_main,
                on_toggle_ball=lambda: self.toggle_component("ballEnabled"),
                on_toggle_dock=lambda: self.toggle_component("dockEnabled"),
                on_refresh=lambda: self.refresh(full=True),
                on_quit=self.quit,
                is_ball_on=lambda: bool(self.settings.get("ballEnabled")),
                is_dock_on=lambda: bool(self.settings.get("dockEnabled")),
                dock_status=lambda: str(self.native.dock_status().get("state") or "stopped"),
                on_reembed=self.reembed_dock,
                on_export_diagnostics=self.export_diagnostics,
                usage_lines=lambda: format_usage_lines(self.summary),
                update_info=lambda: updates.latest,
                on_open_update=lambda: webbrowser.open((updates.latest or {}).get("url") or updates.RELEASES_API),
            )
            update_tray(self.tray, self.summary)
        except Exception as exc:
            self.logger.warning("tray start failed: %s", exc)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Cursor Usage local dashboard")
    parser.add_argument("--refresh", type=int, default=0, help="override the refresh interval in seconds; 0 = use settings")
    parser.add_argument("--no-tray", action="store_true")
    parser.add_argument("--start-hidden", action="store_true", help="start with the dashboard hidden (default)")
    parser.add_argument("--show-window", action="store_true", help="show the dashboard on start")
    parser.add_argument("--debug", action="store_true", help="open the WebView developer tools")
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))

    from . import store
    from .bridge import Bridge
    from .instance import SingleInstance
    from .logging_setup import install_exception_hooks, setup_logging
    from .native.win import enable_dpi_awareness

    enable_dpi_awareness()
    logger = setup_logging()
    uninstall_exception_hooks = install_exception_hooks(logger)
    instance = SingleInstance()
    if not instance.acquire():
        instance.send("show-main", timeout=2.0)
        instance.close()
        return 0

    import webview

    if args.refresh:
        store.save_settings({"refreshSeconds": max(15, int(args.refresh))})
    app = App(args, logger)
    settings = app.settings
    try:
        from .autostart import is_launch_at_startup, set_launch_at_startup

        want = bool(settings.get("launchAtStartup"))
        if want != is_launch_at_startup():
            set_launch_at_startup(want)
    except Exception:
        pass

    start_hidden = not args.show_window and (args.start_hidden or settings.get("startHidden", True) is not False)
    win_kwargs: dict[str, Any] = {
        "width": max(640, int(settings.get("windowWidth") or 1280)),
        "height": max(480, int(settings.get("windowHeight") or 860)),
        "min_size": (560, 480),
        "hidden": start_hidden,
        "background_color": "#0E1014" if _system_prefers_dark() else "#FAFAFA",
        "fullscreen": app.win_fullscreen and not start_hidden,
        "maximized": app.win_maximized and not app.win_fullscreen and not start_hidden,
    }
    if settings.get("windowX") is not None and settings.get("windowY") is not None and not (
        win_kwargs["fullscreen"] or win_kwargs["maximized"]
    ):
        win_kwargs["x"], win_kwargs["y"] = int(settings["windowX"]), int(settings["windowY"])

    app.window = webview.create_window(i18n.app_title(), html=_dashboard_html(), js_api=Bridge(app), **win_kwargs)
    if not start_hidden:
        app.window_visible.set()

    def on_loaded(*_a: Any) -> None:
        app.page_ready.set()
        app.set_page_active(app.window_visible.is_set())

    def on_closing() -> bool:
        app.persist_window()
        if app.quitting or args.no_tray:
            return True
        try:
            app.window.hide()
        except Exception:
            return True
        app.set_page_active(False)
        return False

    def on_maximized(*_a: Any) -> None:
        app.win_maximized, app.win_fullscreen = True, False
        app.schedule_persist()

    def on_restored(*_a: Any) -> None:
        app.win_maximized = False
        app.schedule_persist()

    events = app.window.events
    events.loaded += on_loaded
    events.closing += on_closing
    events.maximized += on_maximized
    events.restored += on_restored
    events.resized += lambda *_a: None if (app.win_maximized or app.win_fullscreen) else app.schedule_persist()
    events.moved += lambda *_a: None if (app.win_maximized or app.win_fullscreen) else app.schedule_persist()

    app.native.start()
    app.native.set_summary(app.summary)
    app.native.configure(settings)
    if not args.no_tray:
        app.start_tray()

    def on_ipc(action: str, _payload: dict[str, Any]) -> None:
        if action == "show-main":
            app.show_main()
        elif action == "refresh":
            app.refresh(full=True)
        elif action == "quit":
            app.quit()

    instance.start(on_ipc)
    for target, name in ((app.scheduler, "scheduler"), (app.track_fullscreen, "fs-track"), (app.update_checker, "update-check")):
        threading.Thread(target=target, daemon=True, name=name).start()

    webview.start(debug=args.debug)

    app.quitting = True
    app.stop_event.set()
    app.window_visible.set()
    app.native.stop()
    if app.tray is not None:
        try:
            app.tray.stop()
        except Exception:
            pass
    instance.close()
    uninstall_exception_hooks()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
