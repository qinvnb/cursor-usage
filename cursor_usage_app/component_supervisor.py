"""Small, bounded process supervisor for optional desktop components."""

from __future__ import annotations

import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable


Spawn = Callable[[], subprocess.Popen[Any] | None]
StateCallback = Callable[["ComponentState"], None]


@dataclass(frozen=True)
class ComponentState:
    name: str
    desired: bool
    running: bool
    status: str
    restart_count: int
    last_exit_code: int | None = None
    last_error: str | None = None
    updated_at: float = field(default_factory=time.time)


class ComponentSupervisor:
    """Supervise one helper with bounded exponential restart backoff."""

    def __init__(
        self,
        name: str,
        spawn: Spawn,
        *,
        on_state: StateCallback | None = None,
        backoff: tuple[float, ...] = (1.0, 2.0, 5.0),
        cooldown_seconds: float = 30.0,
        stable_seconds: float = 15.0,
    ) -> None:
        self.name = name
        self._spawn = spawn
        self._on_state = on_state
        self._backoff = backoff or (1.0,)
        self._cooldown = max(1.0, float(cooldown_seconds))
        self._stable_seconds = max(1.0, float(stable_seconds))
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._desired = False
        self._proc: subprocess.Popen[Any] | None = None
        self._restart_count = 0
        self._started_at = 0.0
        self._last_exit_code: int | None = None
        self._last_error: str | None = None
        self._last_emitted: tuple[Any, ...] | None = None
        self._thread = threading.Thread(
            target=self._run, name=f"supervisor-{name}", daemon=True
        )
        self._thread.start()
        self._emit("stopped")

    def set_desired(self, enabled: bool) -> None:
        with self._lock:
            self._desired = bool(enabled)
            if not self._desired:
                self._restart_count = 0
        self._wake.set()

    def restart(self) -> None:
        with self._lock:
            self._restart_count = 0
            self._terminate_locked()
        self._wake.set()

    def stop(self, timeout: float = 3.0) -> None:
        self._stop.set()
        self._wake.set()
        with self._lock:
            self._desired = False
            self._terminate_locked()
        if self._thread is not threading.current_thread():
            self._thread.join(timeout=max(0.0, timeout))
        self._emit("stopped")

    def process(self) -> subprocess.Popen[Any] | None:
        with self._lock:
            proc = self._proc
            return proc if proc is not None and proc.poll() is None else None

    def snapshot(self) -> ComponentState:
        with self._lock:
            running = self._proc is not None and self._proc.poll() is None
            status = "running" if running else ("waiting" if self._desired else "stopped")
            return ComponentState(
                name=self.name,
                desired=self._desired,
                running=running,
                status=status,
                restart_count=self._restart_count,
                last_exit_code=self._last_exit_code,
                last_error=self._last_error,
            )

    def _emit(self, status: str) -> None:
        callback = self._on_state
        if callback is None:
            return
        with self._lock:
            proc = self._proc
            state = ComponentState(
                name=self.name,
                desired=self._desired,
                running=proc is not None and proc.poll() is None,
                status=status,
                restart_count=self._restart_count,
                last_exit_code=self._last_exit_code,
                last_error=self._last_error,
            )
            signature = (
                state.status,
                state.desired,
                state.running,
                state.restart_count,
                state.last_exit_code,
                state.last_error,
            )
            if signature == self._last_emitted:
                return
            self._last_emitted = signature
        try:
            callback(state)
        except Exception:
            pass

    def _terminate_locked(self) -> None:
        proc = self._proc
        self._proc = None
        if proc is None:
            return
        try:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except Exception:
                    proc.kill()
        except Exception as exc:
            self._last_error = str(exc)

    def _start_once(self) -> bool:
        self._emit("starting")
        try:
            proc = self._spawn()
            if proc is None:
                raise RuntimeError("spawn returned no process")
        except Exception as exc:
            with self._lock:
                self._last_error = str(exc)
            self._emit("failed")
            return False
        with self._lock:
            if self._stop.is_set() or not self._desired:
                try:
                    proc.terminate()
                except Exception:
                    pass
                return False
            self._proc = proc
            self._started_at = time.monotonic()
            self._last_error = None
        self._emit("running")
        return True

    def _run(self) -> None:
        while not self._stop.is_set():
            with self._lock:
                desired = self._desired
                proc = self._proc

            if not desired:
                with self._lock:
                    self._terminate_locked()
                self._emit("stopped")
                self._wake.wait(1.0)
                self._wake.clear()
                continue

            if proc is None:
                if not self._start_once():
                    self._wait_backoff()
                continue

            code = proc.poll()
            if code is None:
                if time.monotonic() - self._started_at >= self._stable_seconds:
                    with self._lock:
                        self._restart_count = 0
                self._wake.wait(0.5)
                self._wake.clear()
                continue

            with self._lock:
                if proc is self._proc:
                    self._proc = None
                self._last_exit_code = int(code)
                self._restart_count += 1
            self._emit("crashed")
            self._wait_backoff()

    def _wait_backoff(self) -> None:
        with self._lock:
            failures = self._restart_count
            if failures == 0:
                self._restart_count = 1
                failures = 1
        if failures <= len(self._backoff):
            delay = self._backoff[failures - 1]
            self._emit("backoff")
        else:
            delay = self._cooldown
            self._emit("cooldown")
        self._wake.wait(delay)
        self._wake.clear()
