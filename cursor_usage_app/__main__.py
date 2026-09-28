"""Cursor 用量桌面应用入口与组件控制器。"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import Any

from .component_supervisor import ComponentState, ComponentSupervisor

WIDGET_STYLE_KEYS = (
    "ballSize",
    "ballOpacity",
    "ballRefreshMs",
    "ballFontSize",
    "ballRingWidth",
    "dockWidth",
    "dockCompact",
)


def _widget_style_fp(settings: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(settings.get(k) for k in WIDGET_STYLE_KEYS)


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


def _keep_alive() -> None:
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        return


def _spawn_helper(flag: str) -> subprocess.Popen[Any] | None:
    try:
        if getattr(sys, "frozen", False):
            cmd = [sys.executable, flag]
            cwd = str(Path(sys.executable).resolve().parent)
            env = os.environ.copy()
            # A helper is a new application instance, not a PyInstaller
            # onefile worker for the already-running parent.
            env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
        else:
            mod = (
                "cursor_usage_app.ball_tk"
                if flag == "--ball"
                else "cursor_usage_app.taskbar_widget"
            )
            cmd = [sys.executable, "-m", mod]
            cwd = None
            env = None
        return subprocess.Popen(cmd, cwd=cwd, env=env, close_fds=False)
    except Exception as e:
        print(f"辅助窗口启动失败({flag}): {e}", file=sys.stderr)
        return None


def _stop_proc(proc: subprocess.Popen[Any] | None) -> None:
    if proc is None:
        return
    try:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except Exception:
                proc.kill()
    except Exception:
        pass


class AppController:
    """Own optional component lifecycles and expose their real health."""

    def __init__(self, logger: Any) -> None:
        self.logger = logger
        self.components: dict[str, ComponentSupervisor] = {}
        self.states: dict[str, ComponentState] = {}

    def add(self, name: str, flag: str) -> None:
        def on_state(value: ComponentState) -> None:
            self.states[name] = value
            self.logger.info(
                "component state",
                extra={
                    "component": name,
                    "status": value.status,
                    "exitCode": value.last_exit_code,
                    "error": value.last_error,
                },
            )

        self.components[name] = ComponentSupervisor(
            name, lambda: _spawn_helper(flag), on_state=on_state
        )

    def enable(self, name: str, enabled: bool) -> None:
        self.components[name].set_desired(enabled)

    def restart(self, name: str) -> None:
        self.components[name].restart()

    def running(self, name: str) -> bool:
        return self.components[name].process() is not None

    def status(self, name: str) -> str:
        state = self.states.get(name)
        return state.status if state else "stopped"

    def stop(self) -> None:
        for component in self.components.values():
            component.stop()


def _read_window_geometry(window: Any) -> dict[str, Any]:
    """Snapshot current window geometry for persistence."""
    payload: dict[str, Any] = {}
    try:
        w = int(getattr(window, "width", 0) or 0)
        h = int(getattr(window, "height", 0) or 0)
        if w >= 640:
            payload["windowWidth"] = w
        if h >= 480:
            payload["windowHeight"] = h
    except Exception:
        pass
    try:
        x = getattr(window, "x", None)
        y = getattr(window, "y", None)
        if x is not None:
            payload["windowX"] = int(x)
        if y is not None:
            payload["windowY"] = int(y)
    except Exception:
        pass
    return payload


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    if "--ball" in argv:
        from .ball_tk import main as ball_main

        return ball_main([a for a in argv if a != "--ball"])
    if "--dock" in argv:
        from .taskbar_widget import main as dock_main

        return dock_main([a for a in argv if a != "--dock"])

    parser = argparse.ArgumentParser(description="Cursor 用量本地看板")
    parser.add_argument("--refresh", type=int, default=0, help="覆盖设置中的刷新秒数；0=用设置")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--browser", action="store_true")
    parser.add_argument("--no-window", action="store_true")
    parser.add_argument("--no-tray", action="store_true")
    parser.add_argument("--start-hidden", action="store_true", help="启动时隐藏看板（默认行为）")
    parser.add_argument("--show-window", action="store_true", help="启动时显示看板")
    args = parser.parse_args(argv)

    from . import store
    from .instance import SingleInstance
    from .logging_setup import install_exception_hooks, setup_logging
    from .server import request_refresh, set_refresh_seconds, start_server, stop_background_scheduler

    logger = setup_logging()
    uninstall_exception_hooks = install_exception_hooks(logger)
    instance = SingleInstance()
    if not instance.acquire():
        instance.send("show-main", timeout=2.0)
        instance.close()
        return 0
    pending_ipc: list[tuple[str, dict[str, Any]]] = []
    pending_ipc_lock = threading.Lock()

    def queue_ipc(action: str, payload: dict[str, Any]) -> None:
        with pending_ipc_lock:
            pending_ipc.append((action, payload))

    instance.start(queue_ipc)

    settings = store.load_settings()
    refresh = max(15, int(args.refresh or settings.get("refreshSeconds") or 60))
    store.save_settings({"refreshSeconds": refresh})
    # Keep registry autostart in sync with saved preference
    try:
        from .autostart import is_launch_at_startup, set_launch_at_startup

        want = bool(settings.get("launchAtStartup"))
        if want != is_launch_at_startup():
            set_launch_at_startup(want)
    except Exception:
        pass
    server, url = start_server(port=args.port, refresh_seconds=refresh)
    store.write_server_info(url, server.server_address[1])

    if args.no_window:
        print(f"Cursor 用量看板: {url}")
        _keep_alive()
        stop_background_scheduler()
        server.shutdown()
        instance.close()
        uninstall_exception_hooks()
        return 0

    if args.browser:
        webbrowser.open(url)
        _keep_alive()
        stop_background_scheduler()
        server.shutdown()
        instance.close()
        uninstall_exception_hooks()
        return 0

    try:
        import webview
    except ImportError:
        webbrowser.open(url)
        _keep_alive()
        stop_background_scheduler()
        server.shutdown()
        instance.close()
        uninstall_exception_hooks()
        return 0

    state: dict[str, Any] = {
        "quitting": False,
        "tray_icon": None,
        "win_maximized": bool(settings.get("windowMaximized")),
        "win_fullscreen": bool(settings.get("windowFullscreen")),
        "save_timer": None,
    }
    window_visible = threading.Event()
    stop_event = threading.Event()
    controller = AppController(logger)
    controller.add("ball", "--ball")
    controller.add("dock", "--dock")

    win_w = int(settings.get("windowWidth") or 1360)
    win_h = int(settings.get("windowHeight") or 900)
    win_x = settings.get("windowX")
    win_y = settings.get("windowY")
    # Default: start in tray without opening dashboard.
    start_hidden = True
    if args.show_window:
        start_hidden = False
    elif args.start_hidden:
        start_hidden = True
    elif settings.get("startHidden") is False:
        start_hidden = False

    win_kwargs: dict[str, Any] = {
        "width": max(640, win_w),
        "height": max(480, win_h),
        "min_size": (640, 480),
        "hidden": start_hidden,
        "background_color": "#0B1120" if _system_prefers_dark() else "#F4F6F9",
        "fullscreen": bool(settings.get("windowFullscreen")) and not start_hidden,
        "maximized": bool(settings.get("windowMaximized"))
        and not bool(settings.get("windowFullscreen"))
        and not start_hidden,
    }
    if (
        win_x is not None
        and win_y is not None
        and not win_kwargs["fullscreen"]
        and not win_kwargs["maximized"]
    ):
        win_kwargs["x"] = int(win_x)
        win_kwargs["y"] = int(win_y)

    main_window = webview.create_window("Cursor 用量", url, **win_kwargs)
    if not start_hidden:
        window_visible.set()

    def set_page_active(active: bool) -> None:
        """Pause dashboard polling/animations while the window sits in the tray."""
        if active:
            window_visible.set()
        else:
            window_visible.clear()
        script = f"typeof setActive==='function'&&setActive({'true' if active else 'false'});"

        def _run() -> None:
            try:
                main_window.evaluate_js(script)
            except Exception:
                pass

        # evaluate_js blocks until the GUI thread runs the script; never call
        # it inline from GUI-thread event handlers such as ``closing``.
        threading.Thread(target=_run, daemon=True, name="page-active").start()

    def persist_window(extra: dict[str, Any] | None = None) -> None:
        patch = _read_window_geometry(main_window)
        patch["windowMaximized"] = bool(state.get("win_maximized"))
        patch["windowFullscreen"] = bool(state.get("win_fullscreen"))
        if extra:
            patch.update(extra)
        try:
            store.save_settings(patch)
        except Exception:
            pass

    def schedule_persist() -> None:
        timer = state.get("save_timer")
        if timer is not None:
            try:
                timer.cancel()
            except Exception:
                pass

        def _job() -> None:
            if not state["quitting"]:
                persist_window()

        t = threading.Timer(0.4, _job)
        t.daemon = True
        state["save_timer"] = t
        t.start()

    def show_main() -> None:
        """Show dashboard; safe to call from tray / helper threads."""
        try:
            main_window.show()
        except Exception:
            pass
        set_page_active(True)
        # Prefer restoring maximized/fullscreen state without collapsing them.
        if state.get("win_fullscreen"):
            try:
                if not bool(getattr(main_window, "fullscreen", False)):
                    main_window.toggle_fullscreen()
            except Exception:
                pass
        elif state.get("win_maximized"):
            try:
                main_window.maximize()
            except Exception:
                pass
        else:
            try:
                main_window.restore()
            except Exception:
                pass
        try:
            main_window.on_top = True
            main_window.on_top = False
        except Exception:
            pass
        # Win32 foreground — tray click often runs off the GUI thread.
        if sys.platform == "win32":
            try:
                import ctypes

                user32 = ctypes.windll.user32
                hwnd = user32.FindWindowW(None, "Cursor 用量")
                if hwnd:
                    SW_RESTORE = 9
                    SW_SHOW = 5
                    if user32.IsIconic(hwnd):
                        user32.ShowWindow(hwnd, SW_RESTORE)
                    else:
                        user32.ShowWindow(hwnd, SW_SHOW)
                    user32.SetForegroundWindow(hwnd)
                    user32.BringWindowToTop(hwnd)
            except Exception:
                pass

    def start_ball(*, persist: bool = True) -> None:
        controller.enable("ball", True)
        if persist:
            store.save_settings({"ballEnabled": True})

    def stop_ball(*, persist: bool = True) -> None:
        controller.enable("ball", False)
        if persist:
            store.save_settings({"ballEnabled": False})

    def toggle_ball() -> None:
        if controller.running("ball"):
            stop_ball()
        else:
            start_ball()

    def start_dock(*, persist: bool = True) -> None:
        controller.enable("dock", True)
        if persist:
            store.save_settings({"dockEnabled": True})

    def stop_dock(*, persist: bool = True) -> None:
        controller.enable("dock", False)
        if persist:
            store.save_settings({"dockEnabled": False})

    def toggle_dock() -> None:
        if controller.running("dock"):
            stop_dock()
        else:
            start_dock()

    def apply_settings_live() -> None:
        s = store.load_settings()
        set_refresh_seconds(int(s.get("refreshSeconds") or 60))
        want_ball = bool(s.get("ballEnabled"))
        want_dock = bool(s.get("dockEnabled"))
        fp = _widget_style_fp(s)
        style_changed = state.get("widget_fp") != fp
        state["widget_fp"] = fp
        ball_on = controller.running("ball")
        dock_on = controller.running("dock")
        # Only restart when toggled or appearance params changed (avoids flash on every save).
        if want_ball:
            if (not ball_on) or style_changed:
                if ball_on:
                    controller.restart("ball")
                else:
                    start_ball(persist=False)
        elif ball_on:
            stop_ball(persist=False)
        if want_dock:
            if (not dock_on) or style_changed:
                if dock_on:
                    controller.restart("dock")
                else:
                    start_dock(persist=False)
        elif dock_on:
            stop_dock(persist=False)
        try:
            main_window.evaluate_js("typeof onSettingsApplied==='function'&&onSettingsApplied();")
        except Exception:
            pass

    def do_refresh() -> None:
        def _job() -> None:
            try:
                request_refresh(include_models=True, wait=True)
                try:
                    main_window.evaluate_js("typeof loadUsage==='function'&&loadUsage();")
                except Exception:
                    pass
            except Exception:
                pass

        threading.Thread(target=_job, daemon=True).start()

    def _widget_flags() -> tuple[bool, bool]:
        return controller.running("ball"), controller.running("dock")

    def quit_app() -> None:
        state["quitting"] = True
        stop_event.set()
        window_visible.set()
        persist_window()
        controller.stop()
        icon = state.get("tray_icon")
        if icon is not None:
            try:
                icon.stop()
            except Exception:
                pass
        try:
            main_window.destroy()
        except Exception:
            pass

    def on_main_closing() -> bool:
        persist_window()
        if state["quitting"] or args.no_tray:
            return True
        try:
            main_window.hide()
        except Exception:
            return True
        set_page_active(False)
        return False

    def on_resized(*_a: Any) -> None:
        if state.get("win_fullscreen") or state.get("win_maximized"):
            return
        schedule_persist()

    def on_moved(*_a: Any) -> None:
        if state.get("win_fullscreen") or state.get("win_maximized"):
            return
        schedule_persist()

    def on_maximized(*_a: Any) -> None:
        state["win_maximized"] = True
        state["win_fullscreen"] = False
        schedule_persist()

    def on_restored(*_a: Any) -> None:
        state["win_maximized"] = False
        schedule_persist()

    def poll_commands() -> None:
        # command.json is only a fallback when the named-pipe IPC is
        # unavailable, so a slow cadence is enough.
        while not state["quitting"]:
            try:
                cmd = store.consume_command()
                if not cmd:
                    stop_event.wait(5.0)
                    continue
                action = cmd.get("action")
                if action == "show-main":
                    show_main()
                elif action == "apply-settings":
                    apply_settings_live()
                elif action == "hide-ball":
                    stop_ball(persist=True)
                elif action == "hide-dock":
                    stop_dock(persist=True)
                elif action == "reset-widget-positions":
                    store.save_settings(
                        {"ballX": None, "ballY": None}
                    )
                    # Restart running widgets so they pick up defaults
                    ball_on = controller.running("ball")
                    dock_on = controller.running("dock")
                    if ball_on:
                        start_ball(persist=False)
                    if dock_on:
                        start_dock(persist=False)
                elif action == "quit":
                    quit_app()
                    break
            except Exception:
                pass
            stop_event.wait(0.35)

    def track_fullscreen() -> None:
        while not state["quitting"]:
            window_visible.wait()
            if state["quitting"]:
                break
            try:
                fs = bool(getattr(main_window, "fullscreen", False))
                if fs != bool(state.get("win_fullscreen")):
                    state["win_fullscreen"] = fs
                    if fs:
                        state["win_maximized"] = False
                    persist_window()
            except Exception:
                pass
            stop_event.wait(1.0)

    def on_loaded(*_a: Any) -> None:
        set_page_active(window_visible.is_set())

    main_window.events.closing += on_main_closing
    main_window.events.loaded += on_loaded
    try:
        main_window.events.resized += on_resized
        main_window.events.moved += on_moved
        main_window.events.maximized += on_maximized
        main_window.events.restored += on_restored
    except Exception:
        pass

    state["widget_fp"] = _widget_style_fp(settings)
    if settings.get("ballEnabled"):
        start_ball(persist=False)
    if settings.get("dockEnabled"):
        start_dock(persist=False)

    def is_ball_on() -> bool:
        return controller.running("ball")

    def is_dock_on() -> bool:
        return controller.running("dock")

    def dock_status() -> str:
        try:
            payload = store.read_json(store.data_dir() / "component_status.json") or {}
            taskbar = payload.get("taskbarWidget") or {}
            if is_dock_on():
                return str(taskbar.get("state") or controller.status("dock"))
        except Exception:
            pass
        return controller.status("dock")

    def export_diagnostics() -> None:
        try:
            from .diagnostics import create_diagnostic_zip

            path = create_diagnostic_zip()
            logger.info("diagnostic archive created: %s", path.name)
            if sys.platform == "win32":
                subprocess.Popen(["explorer.exe", f"/select,{path}"])
        except Exception:
            logger.exception("diagnostic export failed")

    def on_ipc_command(action: str, _payload: dict[str, Any]) -> None:
        if action == "show-main":
            show_main()
        elif action == "refresh":
            do_refresh()
        elif action == "hide-ball":
            stop_ball(persist=True)
        elif action == "hide-dock":
            stop_dock(persist=True)
        elif action == "apply-settings":
            apply_settings_live()
        elif action == "reset-widget-positions":
            store.save_settings({"ballX": None, "ballY": None})
            if controller.running("ball"):
                controller.restart("ball")
        elif action == "reembed-dock":
            controller.restart("dock")
        elif action == "quit":
            quit_app()

    from . import alerts, updates
    from .server import add_report_listener
    from .tray import format_usage_lines, update_tray

    if not args.no_tray:
        try:
            from .tray import start_tray

            state["tray_icon"] = start_tray(
                on_show_main=show_main,
                on_toggle_ball=toggle_ball,
                on_toggle_dock=toggle_dock,
                on_refresh=do_refresh,
                on_quit=quit_app,
                is_ball_on=is_ball_on,
                is_dock_on=is_dock_on,
                dock_status=dock_status,
                on_reembed=lambda: controller.restart("dock"),
                on_export_diagnostics=export_diagnostics,
                usage_lines=lambda: format_usage_lines(state.get("summary")),
                update_info=lambda: updates.latest,
                on_open_update=lambda: webbrowser.open(
                    (updates.latest or {}).get("url") or updates.RELEASES_API
                ),
            )
        except Exception as e:
            logger.warning("tray start failed: %s", e)

    def notify(title: str, message: str) -> None:
        icon = state.get("tray_icon")
        if icon is None:
            return
        try:
            icon.notify(message, title)
        except Exception:
            logger.warning("tray notification failed", exc_info=True)

    def on_report(report: dict[str, Any]) -> None:
        summary = store.summary_from_report(report)
        if summary != state.get("summary"):
            state["summary"] = summary
            if state.get("tray_icon") is not None:
                update_tray(state["tray_icon"], summary)
        if not store.load_settings().get("alertsEnabled", True):
            return
        previous_state = store.load_alerts_state()
        to_send, new_state = alerts.pending_alerts(summary, previous_state)
        if new_state.get("cycle") != previous_state.get("cycle") or to_send:
            store.save_alerts_state({**previous_state, **new_state})
        for alert in to_send:
            notify(alert.title, alert.message)

    state["summary"] = store.load_summary()
    if state.get("tray_icon") is not None:
        update_tray(state["tray_icon"], state["summary"])
    add_report_listener(on_report)

    def update_checker() -> None:
        last_check = 0.0
        if stop_event.wait(30.0):
            return
        while not state["quitting"]:
            if (
                store.load_settings().get("checkUpdates")
                and time.monotonic() - last_check >= 24 * 3600
            ):
                last_check = time.monotonic()
                try:
                    found = updates.check_latest()
                except Exception as exc:
                    logger.info("update check failed: %s", exc)
                    found = None
                if found:
                    alert_state = store.load_alerts_state()
                    if alert_state.get("updateNotified") != found["version"]:
                        store.save_alerts_state({**alert_state, "updateNotified": found["version"]})
                        notify("Cursor 用量有新版本", f"v{found['version']} 已发布，可在托盘菜单打开下载页")
                    if state.get("tray_icon") is not None:
                        update_tray(state["tray_icon"], state.get("summary"))
            if stop_event.wait(3600.0):
                return

    threading.Thread(target=update_checker, daemon=True, name="update-check").start()

    instance.register_callback(on_ipc_command)
    with pending_ipc_lock:
        queued_ipc = list(pending_ipc)
        pending_ipc.clear()
    for queued_action, queued_payload in queued_ipc:
        on_ipc_command(queued_action, queued_payload)
    # One-release compatibility: consume legacy command.json while all helpers
    # and duplicate launches use the named pipe.
    threading.Thread(target=poll_commands, daemon=True, name="legacy-cmd").start()
    threading.Thread(target=track_fullscreen, daemon=True, name="fs-track").start()
    webview.start()

    state["quitting"] = True
    stop_event.set()
    window_visible.set()
    persist_window()
    controller.stop()
    stop_background_scheduler()
    server.shutdown()
    icon = state.get("tray_icon")
    if icon is not None:
        try:
            icon.stop()
        except Exception:
            pass
    instance.close()
    uninstall_exception_hooks()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
