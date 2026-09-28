"""Local HTTP API: UI reads disk; background worker refreshes network data."""

from __future__ import annotations

import json
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from . import store
from .fetch import UsageError, fetch_report

DEFAULT_REFRESH_SECONDS = 60
FULL_REFRESH_SECONDS = 10 * 60
MAX_BODY_BYTES = 4 * 1024 * 1024
_LOCAL_HTTP_HOSTS = {"127.0.0.1", "localhost", "::1"}

_refresh_lock = threading.RLock()
_refresh_condition = threading.Condition(_refresh_lock)
_refresh_thread: threading.Thread | None = None
_refresh_pending = False
_refresh_pending_models = False
_refresh_running_models = False
_refresh_state = "success"
_refresh_error: str | None = None
_refresh_generation = 0
_refresh_completed_generation = 0
_scheduler_stop = threading.Event()
_scheduler_interval = DEFAULT_REFRESH_SECONDS
_scheduler_started = False
BACKOFF_BASE_SECONDS = 30
BACKOFF_MAX_SECONDS = 15 * 60
_consecutive_failures = 0
_next_auto_refresh_at = 0.0


def _backoff_remaining() -> float | None:
    """Seconds until automatic refreshes resume after failures (caller holds lock)."""
    remaining = _next_auto_refresh_at - time.monotonic()
    return remaining if _consecutive_failures and remaining > 0 else None


def is_trusted_local_request(host_header: str | None, origin_header: str | None) -> bool:
    """Reject DNS-rebinding and cross-origin requests to the local API."""
    try:
        host = urlparse(f"//{host_header or ''}").hostname
    except ValueError:
        return False
    if not host or host.lower() not in _LOCAL_HTTP_HOSTS:
        return False
    if not origin_header:
        return True
    try:
        origin = urlparse(origin_header)
    except ValueError:
        return False
    return (
        origin.scheme in {"http", "https"}
        and bool(origin.hostname)
        and origin.hostname.lower() in _LOCAL_HTTP_HOSTS
    )


def resource_dir() -> Path:
    import sys

    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "web"
    return Path(__file__).resolve().parent.parent / "web"


def export_csv(name: str, csv_text: str) -> Path:
    """Write a CSV (UTF-8 with BOM so Excel detects the encoding) and reveal it."""
    import re
    import subprocess
    import sys
    from datetime import datetime

    safe = re.sub(r'[\\/:*?"<>|\s]+', "_", name).strip("._") or "export"
    folder = store.data_dir() / "exports"
    folder.mkdir(parents=True, exist_ok=True)
    destination = folder / f"{safe[:60]}-{datetime.now():%Y%m%d-%H%M%S}.csv"
    destination.write_text(csv_text, encoding="utf-8-sig", newline="")
    if sys.platform == "win32":
        try:
            subprocess.Popen(["explorer.exe", f"/select,{destination}"])
        except OSError:
            pass
    return destination


def summary_from_report(report: dict[str, Any]) -> dict[str, Any]:
    return {"fetchedAt": report.get("fetchedAt"), **store.summary_from_report(report)}


def status_payload() -> dict[str, Any]:
    meta = store.load_meta()
    age = store.age_seconds()
    with _refresh_lock:
        state = _refresh_state
        pending = _refresh_pending
        running = _refresh_thread is not None
        running_models = _refresh_running_models
        error = _refresh_error
        retry_in = _backoff_remaining()
        failures = _consecutive_failures
    if not running and state == "success" and meta.get("lastError") and not meta.get("lastSuccessAt"):
        state = "error"
    return {
        **meta,
        "refreshing": running,
        "refreshState": state,
        "refreshPending": pending,
        "refreshIncludesModels": running_models if running else False,
        "lastError": error if state == "error" and error else meta.get("lastError"),
        "hasData": store.usage_path().is_file(),
        "ageSeconds": age,
        "stale": age is None or age >= get_refresh_seconds(),
        "dataDir": str(store.data_dir()),
        "consecutiveFailures": failures,
        "retryInSeconds": round(retry_in) if retry_in is not None and not running else None,
    }


def _merge_lightweight_report(
    cached: dict[str, Any] | None, fresh: dict[str, Any]
) -> dict[str, Any]:
    """Keep expensive event/model data while replacing lightweight totals."""
    if not cached:
        return fresh
    merged = dict(cached)
    merged.update(fresh)
    for key in ("daily", "models", "onDemandModels", "includedModels"):
        if key not in fresh or not fresh.get(key):
            if key in cached:
                merged[key] = cached[key]
    # Nested objects: fresh totals win, but fields only a full refresh can
    # compute (event costs, top models, userId) are carried over.
    for key in ("account", "summary"):
        old, new = cached.get(key), fresh.get(key)
        if isinstance(old, dict) and isinstance(new, dict):
            combined = dict(old)
            combined.update({k: v for k, v in new.items() if v not in (None, "")})
            merged[key] = combined
    summary = merged.get("summary")
    old_summary = cached.get("summary") or {}
    if isinstance(summary, dict):
        for key in _EVENT_DERIVED_SUMMARY_KEYS:
            if key in old_summary:
                summary[key] = old_summary[key]
    return merged


_EVENT_DERIVED_SUMMARY_KEYS = (
    "onDemandEventCostCents",
    "onDemandEventCostDollars",
    "includedEventCostCents",
    "includedEventCostDollars",
    "modelCount",
    "topOnDemandModel",
    "topModel",
    "eventCount",
)


_report_listeners: list[Callable[[dict[str, Any]], None]] = []


def add_report_listener(listener: Callable[[dict[str, Any]], None]) -> None:
    """Call ``listener(report)`` after every successful refresh (refresh thread)."""
    _report_listeners.append(listener)


def _notify_report_listeners(report: dict[str, Any]) -> None:
    import logging

    for listener in list(_report_listeners):
        try:
            listener(report)
        except Exception:
            logging.getLogger("cursor_usage_app").exception("report listener failed")


def _do_refresh(*, include_models: bool = True) -> str | None:
    # fetch_report bounds the total network time with a per-refresh deadline.
    try:
        report = fetch_report(include_models=include_models)
        if not include_models:
            report = _merge_lightweight_report(store.load_usage(), report)
        store.save_usage(report)
        _notify_report_listeners(report)
        return None
    except UsageError as e:
        store.mark_refreshing(False, error=str(e))
        return str(e)
    except Exception as e:
        error = f"未知错误: {e}"
        store.mark_refreshing(False, error=error)
        return error


def get_refresh_seconds() -> int:
    return max(15, int(_scheduler_interval))


def set_refresh_seconds(seconds: int) -> int:
    global _scheduler_interval
    value = max(15, min(3600, int(seconds)))
    _scheduler_interval = value
    UsageHandler.refresh_seconds = value
    return value


def request_refresh(
    *, include_models: bool = True, wait: bool = False, auto: bool = False
) -> dict[str, Any]:
    """Merge refresh requests into one serialized lightweight/full queue.

    ``auto`` requests (scheduler, stale-data reads) are skipped while the
    failure backoff is active; user-initiated refreshes always run.
    """
    global _refresh_thread, _refresh_pending, _refresh_pending_models
    global _refresh_running_models, _refresh_state, _refresh_error
    global _refresh_generation, _refresh_completed_generation

    def runner() -> None:
        global _refresh_thread, _refresh_pending, _refresh_pending_models
        global _refresh_running_models, _refresh_state, _refresh_error
        global _refresh_completed_generation, _consecutive_failures, _next_auto_refresh_at
        while True:
            with _refresh_condition:
                run_models = _refresh_pending_models
                run_generation = _refresh_generation
                _refresh_pending = False
                _refresh_pending_models = False
                _refresh_running_models = run_models
                _refresh_state = "running"
            error = _do_refresh(include_models=run_models)
            with _refresh_condition:
                _refresh_completed_generation = max(
                    _refresh_completed_generation, run_generation
                )
                _refresh_error = error
                if error:
                    _consecutive_failures += 1
                    delay = min(
                        BACKOFF_MAX_SECONDS,
                        BACKOFF_BASE_SECONDS * 2 ** (_consecutive_failures - 1),
                    )
                    _next_auto_refresh_at = time.monotonic() + delay
                else:
                    _consecutive_failures = 0
                    _next_auto_refresh_at = 0.0
                if _refresh_pending:
                    _refresh_state = "pending"
                    _refresh_condition.notify_all()
                    continue
                _refresh_running_models = False
                _refresh_state = "error" if error else "success"
                _refresh_thread = None
                _refresh_condition.notify_all()
                return

    with _refresh_condition:
        active = _refresh_thread is not None
        if auto and not active and _backoff_remaining() is not None:
            return status_payload()
        # A running equal-or-stronger refresh satisfies a later request.
        satisfied_by_running = (
            active
            and _refresh_state == "running"
            and (_refresh_running_models or not include_models)
        )
        if not satisfied_by_running:
            _refresh_generation += 1
            target_generation = _refresh_generation
            _refresh_pending = True
            _refresh_pending_models = _refresh_pending_models or include_models
            _refresh_state = "pending"
        else:
            target_generation = _refresh_generation
        if not active:
            _refresh_thread = threading.Thread(target=runner, daemon=True, name="usage-refresh")
            _refresh_thread.start()

        if wait:
            deadline = time.monotonic() + 180
            while _refresh_completed_generation < target_generation:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                _refresh_condition.wait(remaining)

    return status_payload()


def start_background_scheduler(refresh_seconds: int) -> None:
    """Periodically refresh disk data. UI only reads files."""
    global _scheduler_started, _scheduler_interval
    _scheduler_interval = max(15, int(refresh_seconds))
    if _scheduler_started:
        return
    _scheduler_started = True
    _scheduler_stop.clear()

    def loop() -> None:
        request_refresh(include_models=True)
        last_full = time.monotonic()
        while not _scheduler_stop.is_set():
            if _scheduler_stop.wait(max(15, int(_scheduler_interval))):
                break
            now = time.monotonic()
            include_models = now - last_full >= max(
                FULL_REFRESH_SECONDS, int(_scheduler_interval)
            )
            request_refresh(include_models=include_models, auto=True)
            if include_models:
                last_full = now

    threading.Thread(target=loop, daemon=True, name="usage-scheduler").start()


def stop_background_scheduler() -> None:
    global _scheduler_started
    _scheduler_stop.set()
    _scheduler_started = False


class UsageHandler(SimpleHTTPRequestHandler):
    refresh_seconds: int = DEFAULT_REFRESH_SECONDS

    def __init__(self, *args: Any, directory: str, **kwargs: Any) -> None:
        super().__init__(*args, directory=directory, **kwargs)

    def log_message(self, format: str, *args: Any) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path.startswith("/api/") and not is_trusted_local_request(
            self.headers.get("Host"), self.headers.get("Origin")
        ):
            self._send_json(403, {"ok": False, "error": "untrusted local request"})
            return
        if path == "/api/usage":
            self._serve_usage()
            return
        if path == "/api/summary":
            self._serve_summary()
            return
        if path == "/api/status":
            self._send_json(200, status_payload())
            return
        if path == "/api/health":
            components = store.read_json(store.data_dir() / "component_status.json") or {}
            self._send_json(
                200,
                {
                    "ok": True,
                    "refresh": status_payload(),
                    "components": components,
                },
            )
            return
        if path == "/api/history":
            report = store.load_usage()
            current = store.cycle_snapshot(report) if report else None
            self._send_json(200, {**store.load_history(), "current": current})
            return
        if path == "/api/refresh":
            payload = request_refresh(include_models=True, wait=False)
            self._send_json(202, {"ok": True, "message": "刷新请求已进入队列", **payload})
            return
        if path == "/api/settings":
            settings = store.load_settings()
            # Reflect real registry state for startup
            try:
                from .autostart import is_launch_at_startup

                settings["launchAtStartup"] = is_launch_at_startup()
            except Exception:
                pass
            from . import __version__, updates

            self._send_json(
                200,
                {
                    **settings,
                    "refreshSeconds": get_refresh_seconds(),
                    "dataDir": str(store.data_dir()),
                    "version": __version__,
                    "update": updates.latest,
                    **store.credentials_public_info(),
                },
            )
            return
        if path == "/api/config":
            settings = store.load_settings()
            self._send_json(
                200,
                {
                    "refreshSeconds": get_refresh_seconds(),
                    "uiPollSeconds": settings.get("uiPollSeconds", 15),
                    "authSource": settings.get("authSource", "auto"),
                    "lastView": settings.get("lastView", "home"),
                    "title": "Cursor 用量",
                    "features": {
                        "tray": True,
                        "ball": True,
                        "dock": True,
                        "diskStore": True,
                        "manualAuth": True,
                        "autostart": True,
                    },
                    "dataDir": str(store.data_dir()),
                    **store.credentials_public_info(),
                },
            )
            return
        if path in ("/", "/index.html"):
            self.path = "/index.html"
        return super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if not is_trusted_local_request(
            self.headers.get("Host"), self.headers.get("Origin")
        ):
            self._send_json(403, {"ok": False, "error": "untrusted local request"})
            return
        if path == "/api/diagnostics/export":
            try:
                from .diagnostics import create_diagnostic_zip

                destination = create_diagnostic_zip()
                self._send_json(200, {"ok": True, "path": str(destination)})
            except Exception as exc:
                self._send_json(500, {"ok": False, "error": str(exc)})
            return
        if path == "/api/export/csv":
            payload = self._read_json_body()
            if payload is None:
                return
            try:
                destination = export_csv(str(payload.get("name") or "export"), str(payload.get("csv") or ""))
                self._send_json(200, {"ok": True, "path": str(destination)})
            except Exception as exc:
                self._send_json(500, {"ok": False, "error": str(exc)})
            return
        if path == "/api/taskbar/reembed":
            try:
                from .instance import send_command

                ok = send_command("reembed-dock", timeout=1.5)
            except Exception:
                ok = False
            self._send_json(202 if ok else 503, {"ok": ok})
            return
        if path != "/api/settings":
            self.send_error(404)
            return
        payload = self._read_json_body()
        if payload is None:
            return
        if set(payload) == {"lastView"}:
            # UI navigation state only: no need to notify components.
            store.save_settings({"lastView": payload["lastView"]})
            self._send_json(200, {"ok": True})
            return

        patch: dict[str, Any] = {}
        if "ballEnabled" in payload:
            patch["ballEnabled"] = bool(payload["ballEnabled"])
        if "dockEnabled" in payload:
            patch["dockEnabled"] = bool(payload["dockEnabled"])
        if "dockCompact" in payload:
            patch["dockCompact"] = bool(payload["dockCompact"])
        if "refreshSeconds" in payload:
            patch["refreshSeconds"] = payload["refreshSeconds"]
        if "uiPollSeconds" in payload:
            patch["uiPollSeconds"] = payload["uiPollSeconds"]
        if "authSource" in payload:
            patch["authSource"] = payload["authSource"]
        if "startHidden" in payload:
            patch["startHidden"] = bool(payload["startHidden"])
        for key in ("persistLocalRefresh", "alertsEnabled", "checkUpdates"):
            if key in payload:
                patch[key] = bool(payload[key])
        for key in (
            "ballSize",
            "ballOpacity",
            "ballRefreshMs",
            "ballFontSize",
            "ballRingWidth",
            "dockWidth",
        ):
            if key in payload and payload[key] is not None:
                patch[key] = payload[key]

        # Credentials
        cred_error: str | None = None
        token_raw = None
        if payload.get("clearCredentials"):
            store.clear_credentials()
            patch["authSource"] = "auto"
        else:
            token_raw = payload.get("sessionToken") or payload.get("accessToken")
            refresh_raw = payload.get("refreshToken")
            email_raw = payload.get("email")
            if token_raw:
                try:
                    from .fetch import parse_session_input

                    parsed = parse_session_input(str(token_raw))
                    cred_patch: dict[str, Any] = {"accessToken": parsed["accessToken"]}
                    if refresh_raw:
                        cred_patch["refreshToken"] = str(refresh_raw).strip()
                    email = str(email_raw or "").strip() or parsed.get("emailHint") or ""
                    if email:
                        cred_patch["email"] = email
                    store.save_credentials(cred_patch)
                    patch["authSource"] = "manual"
                except Exception as e:
                    cred_error = str(e)

        # Autostart
        if "launchAtStartup" in payload:
            try:
                from .autostart import set_launch_at_startup

                enabled = set_launch_at_startup(bool(payload["launchAtStartup"]))
                patch["launchAtStartup"] = enabled
            except Exception as e:
                self._send_json(500, {"error": f"设置开机自启失败: {e}"})
                return

        if payload.get("resetWidgetPositions"):
            patch.update({"ballX": None, "ballY": None})

        settings = store.save_settings(patch) if patch else store.load_settings()
        if "refreshSeconds" in settings:
            set_refresh_seconds(int(settings["refreshSeconds"]))

        action = (
            "reset-widget-positions"
            if payload.get("resetWidgetPositions")
            else "apply-settings"
        )
        try:
            from .instance import send_command

            delivered = send_command(action, timeout=1.5)
        except Exception:
            delivered = False
        if not delivered:
            # One-release migration compatibility with a previously running
            # main process.
            store.write_command({"action": action})

        # Saving credentials should force a refresh soon
        if token_raw and not cred_error:
            request_refresh(include_models=True, wait=False)

        try:
            from .autostart import is_launch_at_startup

            settings["launchAtStartup"] = is_launch_at_startup()
        except Exception:
            pass

        out = {
            "ok": not bool(cred_error),
            "settings": {
                **settings,
                **store.credentials_public_info(),
            },
        }
        if cred_error:
            out["error"] = cred_error
            self._send_json(400, out)
            return
        self._send_json(200, out)

    def _read_json_body(self) -> dict[str, Any] | None:
        """Parse a JSON object body, replying 400/413 and returning None on failure."""
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY_BYTES:
            self._send_json(413, {"error": "请求体过大"})
            return None
        raw = self.rfile.read(max(0, length)) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
            if not isinstance(payload, dict):
                raise ValueError("body must be object")
        except Exception as e:
            self._send_json(400, {"error": f"无效 JSON: {e}"})
            return None
        return payload

    def _cached_report(self) -> dict[str, Any] | None:
        """Return cached data (kicking a background refresh if stale) or send 404."""
        report = store.load_usage()
        if report is None:
            # Trigger fetch but return immediately so UI never hangs.
            request_refresh(include_models=True, wait=False, auto=True)
            self._send_json(
                404,
                {
                    "error": "本地暂无数据，正在后台拉取",
                    "status": status_payload(),
                },
            )
            return None
        age = store.age_seconds()
        if age is None or age >= max(15, self.refresh_seconds):
            request_refresh(include_models=False, wait=False, auto=True)
        return report

    def _serve_usage(self) -> None:
        report = self._cached_report()
        if report is None:
            return
        status = status_payload()
        digest = str(status.get("usageDigest") or "")
        fetched_at = status.get("fetchedAt") or report.get("fetchedAt")
        cache = self._cache_info(status)
        query = parse_qs(urlparse(self.path).query)
        if digest and query.get("digest", [""])[0] == digest:
            self._send_json(
                200,
                {
                    "unchanged": True,
                    "digest": digest,
                    "fetchedAt": fetched_at,
                    "cache": cache,
                    "status": status,
                },
            )
            return
        out = dict(report)
        out.update({"digest": digest, "fetchedAt": fetched_at, "cache": cache, "status": status})
        self._send_json(200, out)

    def _serve_summary(self) -> None:
        report = self._cached_report()
        if report is None:
            return
        status = status_payload()
        summary = summary_from_report(report)
        summary["fetchedAt"] = status.get("fetchedAt") or summary.get("fetchedAt")
        summary["cache"] = self._cache_info(status)
        self._send_json(200, summary)

    def _cache_info(self, status: dict[str, Any] | None = None) -> dict[str, Any]:
        status = status or status_payload()
        return {
            "ageSeconds": status["ageSeconds"],
            "stale": status["stale"],
            "refreshState": status["refreshState"],
            "lastError": status["lastError"],
        }

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def start_server(
    host: str = "127.0.0.1",
    port: int = 0,
    refresh_seconds: int = DEFAULT_REFRESH_SECONDS,
) -> tuple[ThreadingHTTPServer, str]:
    web = resource_dir()
    if not web.is_dir():
        raise FileNotFoundError(f"找不到前端目录: {web}")

    # Ensure data dir exists next to exe / project.
    store.data_dir()
    store.clear_stale_refresh_flag()

    handler = partial(UsageHandler, directory=str(web))
    UsageHandler.refresh_seconds = refresh_seconds
    set_refresh_seconds(refresh_seconds)
    server = ThreadingHTTPServer((host, port), handler)
    actual_port = server.server_address[1]
    url = f"http://{host}:{actual_port}/"
    store.write_server_info(url, actual_port)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    start_background_scheduler(refresh_seconds)
    return server, url


# Back-compat aliases used by tray / main.
def refresh_usage(*, include_models: bool = True, force: bool = True) -> dict[str, Any]:
    """Compatibility wrapper: schedule refresh; return current disk data if any."""
    request_refresh(include_models=include_models, wait=False)
    report = store.load_usage()
    if report is not None:
        return report
    # If caller really needs data and none exists, do a short wait once.
    if force:
        request_refresh(include_models=include_models, wait=True)
        report = store.load_usage()
        if report is not None:
            return report
    raise UsageError("本地暂无数据，后台刷新尚未完成")
