"""pywebview js_api: the I/O surface the TypeScript core and UI run on.

Every public method is callable from the page as ``window.pywebview.api.<name>``
and runs on a pywebview worker thread. Names starting with ``_`` are not exposed.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse

from . import __version__, store
from .i18n import L

logger = logging.getLogger("cursor_usage_app.bridge")

ALLOWED_HOSTS = {"api2.cursor.sh", "cursor.com", "www.cursor.com"}
AUTH_PREFIX = "cursorAuth/"
MAX_RESPONSE_BYTES = 32 * 1024 * 1024


class AppHooks(Protocol):
    def on_summary(self, summary: dict[str, Any]) -> None: ...
    def notify(self, title: str, message: str) -> None: ...
    def apply_settings(self, settings: dict[str, Any]) -> None: ...
    def component_status(self) -> dict[str, Any]: ...
    def reembed_dock(self) -> None: ...
    def update_info(self) -> dict[str, Any] | None: ...


def state_db_path() -> Path:
    override = os.environ.get("CURSOR_STATE_DB")
    if override:
        return Path(override)
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Cursor" / "User" / "globalStorage" / "state.vscdb"
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", "")) / "Cursor" / "User" / "globalStorage" / "state.vscdb"
    return Path.home() / ".config" / "Cursor" / "User" / "globalStorage" / "state.vscdb"


def read_local_auth(db_path: Path | None = None) -> dict[str, str]:
    """Read cursorAuth/* keys from Cursor's state.vscdb (read-only)."""
    path = db_path or state_db_path()
    if not path.is_file():
        raise RuntimeError(
            L(f"找不到 Cursor 登录数据：{path}。请先在 Cursor 中登录。", f"Cursor sign-in data not found: {path}. Sign in to Cursor first.")
        )
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=5)
    try:
        rows = conn.execute("SELECT key, value FROM ItemTable WHERE key LIKE 'cursorAuth/%'").fetchall()
    finally:
        conn.close()
    return {k[len(AUTH_PREFIX):]: v for k, v in rows if isinstance(v, str)}


def write_local_auth(patch: dict[str, str], db_path: Path | None = None) -> None:
    path = db_path or state_db_path()
    conn = sqlite3.connect(str(path), timeout=5)
    try:
        for key in ("accessToken", "refreshToken"):
            value = patch.get(key)
            if value:
                conn.execute(
                    "INSERT INTO ItemTable(key, value) VALUES(?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (AUTH_PREFIX + key, value),
                )
        conn.commit()
    finally:
        conn.close()


def env_token() -> str | None:
    env = os.environ.get("CURSOR_SESSION_TOKEN") or os.environ.get("CURSOR_ACCESS_TOKEN")
    if not env:
        return None
    return env.replace("%3A%3A", "::").split("::", 1)[-1].strip() or None


def http_request(req: dict[str, Any]) -> dict[str, Any]:
    """One HTTP exchange. Any status is returned; only transport errors raise."""
    url = str(req.get("url") or "")
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
        raise PermissionError(f"blocked request to {parsed.hostname or url}")
    body = req.get("body")
    request = urllib.request.Request(
        url,
        data=body.encode("utf-8") if isinstance(body, str) else None,
        headers={str(k): str(v) for k, v in (req.get("headers") or {}).items()},
        method=str(req.get("method") or "GET"),
    )
    timeout = max(1.0, float(req.get("timeoutMs") or 30000) / 1000.0)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            raw = resp.read(MAX_RESPONSE_BYTES)
            return {
                "status": resp.status,
                "headers": {k.lower(): v for k, v in resp.headers.items()},
                "body": raw.decode("utf-8", errors="replace"),
            }
    except urllib.error.HTTPError as exc:
        raw = exc.read(MAX_RESPONSE_BYTES) if exc.fp else b""
        return {
            "status": exc.code,
            "headers": {k.lower(): v for k, v in (exc.headers or {}).items()},
            "body": raw.decode("utf-8", errors="replace"),
        }
    except urllib.error.URLError as exc:
        raise ConnectionError(str(exc.reason)) from exc


class Bridge:
    def __init__(self, app: AppHooks) -> None:
        self._app = app

    # --- network & Cursor auth -------------------------------------------

    def http(self, req: dict[str, Any]) -> dict[str, Any]:
        return http_request(req)

    def envToken(self) -> str | None:  # noqa: N802 - JS naming
        return env_token()

    def readLocalAuth(self) -> dict[str, str]:  # noqa: N802
        return read_local_auth()

    def writeLocalAuth(self, patch: dict[str, str]) -> None:  # noqa: N802
        write_local_auth(patch)

    def getCredentials(self) -> dict[str, str] | None:  # noqa: N802
        creds = store.load_credentials()
        if not creds.get("accessToken"):
            return None
        return {k: creds.get(k) or "" for k in ("accessToken", "refreshToken", "email")}

    def saveCredentials(self, patch: dict[str, Any]) -> None:  # noqa: N802
        store.save_credentials(patch or {})

    def clearCredentials(self) -> dict[str, Any]:  # noqa: N802
        store.clear_credentials()
        return self.saveSettings({"authSource": "auto"})

    # --- settings & persisted state ---------------------------------------

    def loadSettings(self) -> dict[str, Any]:  # noqa: N802
        settings = store.load_settings()
        try:
            from .autostart import is_launch_at_startup

            settings["launchAtStartup"] = is_launch_at_startup()
        except Exception:
            pass
        return settings

    def saveSettings(self, patch: dict[str, Any]) -> dict[str, Any]:  # noqa: N802
        patch = dict(patch or {})
        if "launchAtStartup" in patch:
            from .autostart import set_launch_at_startup

            patch["launchAtStartup"] = set_launch_at_startup(bool(patch["launchAtStartup"]))
        settings = store.save_settings(patch)
        if set(patch) - {"lastView"}:
            self._app.apply_settings(settings)
        return self.loadSettings()

    def loadState(self) -> dict[str, Any]:  # noqa: N802
        return {
            "report": store.load_usage(),
            "history": store.load_history()["cycles"],
            "alerts": store.load_alerts_state(),
        }

    def saveReport(self, report: dict[str, Any], summary: dict[str, Any]) -> None:  # noqa: N802
        store.save_usage(report, summary)
        self._app.on_summary(summary)

    def saveHistory(self, cycles: list[dict[str, Any]]) -> None:  # noqa: N802
        store.save_history(cycles)

    def saveAlertsState(self, state: dict[str, Any]) -> None:  # noqa: N802
        store.save_alerts_state({**store.load_alerts_state(), **(state or {})})

    def notify(self, title: str, message: str) -> None:
        self._app.notify(str(title), str(message))

    # --- desktop features ---------------------------------------------------

    def appInfo(self) -> dict[str, Any]:  # noqa: N802
        return {
            "version": __version__,
            "dataDir": str(store.data_dir()),
            "platform": sys.platform,
            "update": self._app.update_info(),
            **store.credentials_public_info(),
        }

    def componentStatus(self) -> dict[str, Any]:  # noqa: N802
        return self._app.component_status()

    def reembedDock(self) -> None:  # noqa: N802
        self._app.reembed_dock()

    def exportCsv(self, name: str, csv: str) -> str:  # noqa: N802
        return str(store.export_csv(str(name or "export"), str(csv or "")))

    def exportFile(self, name: str, extension: str, content: str) -> str:  # noqa: N802
        return str(store.export_file(str(name or "export"), str(extension or ""), str(content or "")))

    def exportDiagnostics(self) -> str:  # noqa: N802
        from .diagnostics import create_diagnostic_zip

        path = create_diagnostic_zip()
        store.reveal_in_explorer(path)
        return str(path)

    def openUrl(self, url: str) -> None:  # noqa: N802
        parsed = urlparse(str(url))
        if parsed.scheme == "https" and parsed.hostname in {"github.com", "cursor.com", "www.cursor.com"}:
            import webbrowser

            webbrowser.open(str(url))

    def log(self, level: str, message: str) -> None:
        getattr(logger, level if level in {"debug", "info", "warning", "error"} else "info")(
            "%s", str(message)[:2000]
        )
