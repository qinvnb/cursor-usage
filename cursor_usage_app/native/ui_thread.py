"""One thread, one Win32 message loop, hosting the taskbar widget and the floating ball.

Other threads never touch the widgets directly: ``NativeUI.call(fn)`` queues
work and wakes the loop with a posted message, so every Win32 call happens on
the thread that owns the windows.
"""

from __future__ import annotations

import ctypes
import logging
import queue
import threading
import time
from ctypes import wintypes
from typing import Any, Callable

from .win import IS_WINDOWS, install_foreground_hook

logger = logging.getLogger("cursor_usage_app.native")

WM_APP_CALL = 0x8000 + 20
WM_TIMER = 0x0113
TIMER_FULLSCREEN = 7
FULLSCREEN_FALLBACK_MS = 2000
RESTART_BACKOFF = (1.0, 3.0, 10.0, 30.0)

if IS_WINDOWS:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.SetTimer.restype = ctypes.c_size_t
    user32.SetTimer.argtypes = [wintypes.HWND, ctypes.c_size_t, wintypes.UINT, ctypes.c_void_p]
    user32.KillTimer.argtypes = [wintypes.HWND, ctypes.c_size_t]


class NativeUI:
    """Owns the widgets' thread. Public methods are thread-safe."""

    def __init__(
        self,
        *,
        on_show: Callable[[], None],
        on_refresh: Callable[[], None],
        on_ball_closed: Callable[[], None],
        on_dock_closed: Callable[[], None],
        on_ball_moved: Callable[[int, int], None],
    ) -> None:
        self._callbacks = {
            "show": on_show,
            "refresh": on_refresh,
            "ball_closed": on_ball_closed,
            "dock_closed": on_dock_closed,
            "ball_moved": on_ball_moved,
        }
        self._queue: queue.Queue[Callable[[], None]] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._thread_id = 0
        self._ready = threading.Event()
        self._stopping = False
        self._ball: Any = None
        self._dock: Any = None
        self._want: dict[str, bool] = {"ball": False, "dock": False}
        self._settings: dict[str, Any] = {}
        self._summary: dict[str, Any] | None = None

    # --- public, any thread -------------------------------------------------

    def start(self) -> None:
        if not IS_WINDOWS or self._thread is not None:
            return
        self._thread = threading.Thread(target=self._supervise, name="native-ui", daemon=True)
        self._thread.start()
        self._ready.wait(5.0)

    def stop(self) -> None:
        self._stopping = True
        self.call(self._teardown)
        if self._thread_id:
            user32.PostThreadMessageW(self._thread_id, 0x0012, 0, 0)  # WM_QUIT
        if self._thread is not None:
            self._thread.join(timeout=3.0)

    def call(self, fn: Callable[[], None]) -> None:
        self._queue.put(fn)
        if self._thread_id:
            user32.PostThreadMessageW(self._thread_id, WM_APP_CALL, 0, 0)

    def configure(self, settings: dict[str, Any]) -> None:
        """Apply settings: toggles components and recreates them when their style changed."""
        settings = dict(settings)

        def apply() -> None:
            restyle = _style_keys(settings) != _style_keys(self._settings)
            self._settings = settings
            self._want = {"ball": bool(settings.get("ballEnabled")), "dock": bool(settings.get("dockEnabled"))}
            if restyle:
                self._stop_component("ball")
                self._stop_component("dock")
            self._sync_components()

        self.call(apply)

    def set_summary(self, summary: dict[str, Any] | None) -> None:
        def apply() -> None:
            self._summary = summary
            for component in (self._ball, self._dock):
                if component is not None:
                    component.set_summary(summary)

        self.call(apply)

    def reembed_dock(self) -> None:
        self.call(lambda: self._dock.reembed() if self._dock is not None else None)

    def reset_ball_position(self) -> None:
        self.call(lambda: self._ball.reset_position() if self._ball is not None else None)

    def running(self, name: str) -> bool:
        return (self._ball if name == "ball" else self._dock) is not None

    def dock_status(self) -> dict[str, Any]:
        from .taskbar import component_status

        return component_status()

    # --- native thread ------------------------------------------------------

    def _supervise(self) -> None:
        """Run the loop; if it dies unexpectedly, rebuild the widgets with backoff."""
        failures = 0
        while not self._stopping:
            started = time.monotonic()
            try:
                self._run_loop()
                return
            except Exception:
                logger.exception("native UI loop crashed")
            self._ball = self._dock = None
            failures = 0 if time.monotonic() - started > 60 else failures + 1
            time.sleep(RESTART_BACKOFF[min(failures, len(RESTART_BACKOFF) - 1)])

    def _run_loop(self) -> None:
        self._thread_id = int(kernel32.GetCurrentThreadId())
        msg = wintypes.MSG()
        # Force the thread message queue to exist before anyone posts to it.
        user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)
        install_foreground_hook(self._on_foreground)
        timer = user32.SetTimer(None, TIMER_FULLSCREEN, FULLSCREEN_FALLBACK_MS, None)
        self._sync_components()
        self._ready.set()
        try:
            while True:
                result = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if result == 0 or result == -1:
                    break
                if not msg.hWnd and msg.message == WM_APP_CALL:
                    self._drain()
                    continue
                if not msg.hWnd and msg.message == WM_TIMER and msg.wParam == timer:
                    self._on_foreground()
                    continue
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            user32.KillTimer(None, timer)
            self._teardown()

    def _drain(self) -> None:
        while True:
            try:
                fn = self._queue.get_nowait()
            except queue.Empty:
                return
            try:
                fn()
            except Exception:
                logger.exception("native UI task failed")

    def _on_foreground(self) -> None:
        if self._ball is not None:
            self._ball.check_fullscreen()

    def _sync_components(self) -> None:
        for name in ("ball", "dock"):
            current = self._ball if name == "ball" else self._dock
            if self._want[name] and current is None:
                self._start_component(name)
            elif not self._want[name] and current is not None:
                self._stop_component(name)

    def _start_component(self, name: str) -> None:
        cb = self._callbacks
        try:
            if name == "ball":
                from .ball import FloatingBall

                ball = FloatingBall(
                    self._settings,
                    on_show=cb["show"],
                    on_close=cb["ball_closed"],
                    on_moved=cb["ball_moved"],
                )
                ball.set_summary(self._summary)
                ball.start()
                self._ball = ball
            else:
                from .taskbar import TaskbarWidget

                dock = TaskbarWidget(
                    self._settings,
                    on_show=cb["show"],
                    on_refresh=cb["refresh"],
                    on_close=cb["dock_closed"],
                )
                dock.set_summary(self._summary)
                dock.start()
                self._dock = dock
        except Exception:
            logger.exception("failed to start %s", name)

    def _stop_component(self, name: str) -> None:
        component = self._ball if name == "ball" else self._dock
        if name == "ball":
            self._ball = None
        else:
            self._dock = None
        if component is not None:
            try:
                component.stop()
            except Exception:
                logger.exception("failed to stop %s", name)

    def _teardown(self) -> None:
        self._stop_component("ball")
        self._stop_component("dock")


STYLE_KEYS = ("ballSize", "ballOpacity", "ballFontSize", "ballRingWidth", "dockWidth", "dockCompact")


def _style_keys(settings: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(settings.get(k) for k in STYLE_KEYS)
