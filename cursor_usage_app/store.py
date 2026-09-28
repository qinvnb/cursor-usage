"""Local on-disk usage store beside the executable / project root."""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_lock = threading.RLock()
SETTINGS_SCHEMA_VERSION = 5


def app_root() -> Path:
    """Directory that owns the ``data/`` folder."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _legacy_data_dirs() -> list[Path]:
    if not getattr(sys, "frozen", False):
        return []
    executable_dir = Path(sys.executable).resolve().parent
    local = os.environ.get("LOCALAPPDATA")
    local_base = Path(local) if local else Path.home() / "AppData" / "Local"
    candidates = [local_base / "CursorUsage" / "data"]
    if (executable_dir / "_internal").is_dir():
        candidates.append(executable_dir.parent / "data")
    return candidates


def _migrate_legacy_data(target: Path) -> None:
    marker = target / ".migrated-v1"
    if marker.exists():
        return
    migrated_source: Path | None = None
    migration_complete = True
    for source in _legacy_data_dirs():
        if not source.is_dir() or source.resolve() == target.resolve():
            continue
        migrated_source = source
        for item in source.iterdir():
            destination = target / item.name
            try:
                if item.is_dir():
                    for child in item.rglob("*"):
                        relative = child.relative_to(item)
                        child_destination = destination / relative
                        if child.is_dir():
                            child_destination.mkdir(parents=True, exist_ok=True)
                        elif not child_destination.exists():
                            child_destination.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(child, child_destination)
                elif not destination.exists():
                    shutil.copy2(item, destination)
            except OSError:
                migration_complete = False
                continue
        break
    if migrated_source is not None and migration_complete:
        try:
            shutil.rmtree(migrated_source)
        except OSError:
            return
    if migrated_source is not None and not migration_complete:
        return
    try:
        marker.touch(exist_ok=True)
    except OSError:
        pass


def data_dir() -> Path:
    path = app_root() / "data"
    path.mkdir(parents=True, exist_ok=True)
    _migrate_legacy_data(path)
    return path


def usage_path() -> Path:
    return data_dir() / "usage.json"


def meta_path() -> Path:
    return data_dir() / "meta.json"


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(payload, ensure_ascii=False, indent=2)
    fd, tmp_name = tempfile.mkstemp(prefix=path.stem + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(raw)
            f.flush()
            os.fsync(f.fileno())
        # Preserve only a known-good previous generation.  A corrupt primary
        # must never replace the last usable backup.
        existing = _read_json_file(path)
        if existing is not None:
            _replace_file_from_bytes(path.with_suffix(path.suffix + ".bak"), path.read_bytes())
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            try:
                os.remove(tmp_name)
            except OSError:
                pass


def _read_json_file(path: Path) -> dict[str, Any] | None:
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None


def _replace_file_from_bytes(path: Path, content: bytes) -> None:
    """Atomically replace *path* with already validated file content."""
    fd, tmp_name = tempfile.mkstemp(prefix=path.stem + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            try:
                os.remove(tmp_name)
            except OSError:
                pass


def read_json(path: Path) -> dict[str, Any] | None:
    """Read a JSON object, recovering a corrupt primary from ``.bak``."""
    data = _read_json_file(path)
    if data is not None:
        return data
    backup = path.with_suffix(path.suffix + ".bak")
    recovered = _read_json_file(backup)
    if recovered is None:
        return None
    try:
        _replace_file_from_bytes(path, backup.read_bytes())
    except OSError:
        # Recovery can still serve the valid backup on read-only media.
        pass
    return recovered


def load_usage() -> dict[str, Any] | None:
    with _lock:
        return read_json(usage_path())


def load_meta() -> dict[str, Any]:
    with _lock:
        meta = read_json(meta_path()) or {}
    return {
        "refreshing": bool(meta.get("refreshing")),
        "lastSuccessAt": meta.get("lastSuccessAt"),
        "lastAttemptAt": meta.get("lastAttemptAt"),
        "lastError": meta.get("lastError"),
        "updatedAt": meta.get("updatedAt"),
        "dataPath": str(usage_path()),
    }


def _write_meta(**fields: Any) -> dict[str, Any]:
    with _lock:
        meta = read_json(meta_path()) or {}
        meta.update(fields)
        meta["updatedAt"] = datetime.now(timezone.utc).isoformat()
        _atomic_write(meta_path(), meta)
        return dict(meta)


def save_usage(report: dict[str, Any]) -> None:
    with _lock:
        _atomic_write(usage_path(), report)
        meta = read_json(meta_path()) or {}
        now = datetime.now(timezone.utc).isoformat()
        meta.update(
            {
                "refreshing": False,
                "lastSuccessAt": now,
                "lastAttemptAt": now,
                "lastError": None,
                "updatedAt": now,
                "dataPath": str(usage_path()),
            }
        )
        _atomic_write(meta_path(), meta)


def mark_refreshing(active: bool, error: str | None = None) -> None:
    fields: dict[str, Any] = {
        "refreshing": bool(active),
        "lastAttemptAt": datetime.now(timezone.utc).isoformat(),
    }
    if error is not None:
        fields["lastError"] = error
        fields["refreshing"] = False
    _write_meta(**fields)


def clear_stale_refresh_flag() -> None:
    """If a previous process died mid-refresh, unstick meta.refreshing."""
    with _lock:
        meta = read_json(meta_path()) or {}
        if meta.get("refreshing"):
            meta["refreshing"] = False
            meta["updatedAt"] = datetime.now(timezone.utc).isoformat()
            if not meta.get("lastError"):
                meta["lastError"] = "上次刷新被中断"
            _atomic_write(meta_path(), meta)


def command_path() -> Path:
    return data_dir() / "command.json"


def write_command(payload: dict[str, Any]) -> None:
    with _lock:
        _atomic_write(command_path(), payload)


def consume_command() -> dict[str, Any] | None:
    path = command_path()
    with _lock:
        # Commands are ephemeral IPC migration data. Never recover them from
        # .bak, otherwise an already-consumed hide/toggle command repeats
        # forever after the primary file is deleted.
        data = _read_json_file(path)
        if data is None:
            return None
        for consumed in (path, path.with_suffix(path.suffix + ".bak")):
            try:
                consumed.unlink(missing_ok=True)
            except OSError:
                pass
        return data


def write_server_info(url: str, port: int) -> None:
    with _lock:
        _atomic_write(
            data_dir() / "server.json",
            {"url": url, "port": port, "updatedAt": datetime.now(timezone.utc).isoformat()},
        )


def age_seconds() -> float | None:
    path = usage_path()
    if not path.is_file():
        return None
    try:
        return max(0.0, time.time() - path.stat().st_mtime)
    except OSError:
        return None


def settings_path() -> Path:
    return data_dir() / "settings.json"


DEFAULT_SETTINGS: dict[str, Any] = {
    "schemaVersion": SETTINGS_SCHEMA_VERSION,
    "ballEnabled": False,
    # New installs start in tray with the native taskbar component enabled.
    "dockEnabled": True,
    "refreshSeconds": 60,
    "uiPollSeconds": 15,
    "windowWidth": 1360,
    "windowHeight": 900,
    "windowX": None,
    "windowY": None,
    "windowMaximized": False,
    "windowFullscreen": False,
    # auto = local Cursor session; manual = credentials.json
    "authSource": "auto",
    "launchAtStartup": False,
    # Start in tray without opening dashboard
    "startHidden": True,
    # Widget positions (None = use defaults)
    "ballX": None,
    "ballY": None,
    # Widget appearance / behavior
    "ballSize": 120,
    "ballOpacity": 100,
    "ballRefreshMs": 4000,
    "ballFontSize": 14,
    "ballRingWidth": 7,
    "dockWidth": 220,
    "dockCompact": False,
}


def _migrate_settings(raw: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Upgrade legacy settings without discarding unknown future fields."""
    migrated = dict(raw)
    had_existing_settings = bool(raw)
    try:
        version = int(migrated.get("schemaVersion", 0))
    except (TypeError, ValueError):
        version = 0
    original = dict(migrated)

    if version < 1:
        aliases = {
            "floatingBallEnabled": "ballEnabled",
            "dockWidgetEnabled": "dockEnabled",
            "refreshInterval": "refreshSeconds",
            "pollInterval": "uiPollSeconds",
        }
        for old, new in aliases.items():
            if new not in migrated and old in migrated:
                migrated[new] = migrated[old]
            migrated.pop(old, None)
        version = 1
    if version < 2:
        # Version 2 formalized the hidden-start default. Existing explicit
        # values remain untouched.
        migrated.setdefault("startHidden", DEFAULT_SETTINGS["startHidden"])
        version = 2
    if version < 3:
        # Native taskbar embedding replaces the movable transparent dock.
        # Existing users retain their explicit old switch; only genuinely new
        # installs receive the new enabled-by-default behavior.
        if had_existing_settings and "dockEnabled" not in migrated:
            migrated["dockEnabled"] = False
        migrated.setdefault("dockCompact", False)
        for obsolete in ("dockX", "dockY"):
            migrated.pop(obsolete, None)
        version = 3

    if version < 4:
        # The original native widget was an oversized text strip. Keep custom
        # widths, but migrate its old default to the compact card design.
        try:
            old_dock_width = int(migrated.get("dockWidth") or 290)
        except (TypeError, ValueError):
            old_dock_width = 290
        if old_dock_width == 290:
            migrated["dockWidth"] = 220
        version = 4

    if version < 5:
        try:
            old_window_width = int(migrated.get("windowWidth") or 1180)
        except (TypeError, ValueError):
            old_window_width = 1180
        if old_window_width == 1180:
            migrated["windowWidth"] = 1360
        version = 5

    if version <= SETTINGS_SCHEMA_VERSION:
        migrated["schemaVersion"] = SETTINGS_SCHEMA_VERSION
    return migrated, migrated != original


def _normalize_settings(raw: dict[str, Any]) -> dict[str, Any]:
    out = dict(DEFAULT_SETTINGS)
    if "ballEnabled" in raw:
        out["ballEnabled"] = bool(raw["ballEnabled"])
    if "dockEnabled" in raw:
        out["dockEnabled"] = bool(raw["dockEnabled"])
    if "dockCompact" in raw:
        out["dockCompact"] = bool(raw["dockCompact"])
    if "refreshSeconds" in raw:
        try:
            out["refreshSeconds"] = max(15, min(3600, int(raw["refreshSeconds"])))
        except (TypeError, ValueError):
            pass
    if "uiPollSeconds" in raw:
        try:
            out["uiPollSeconds"] = max(5, min(120, int(raw["uiPollSeconds"])))
        except (TypeError, ValueError):
            pass

    for key, lo, hi in (("windowWidth", 640, 10000), ("windowHeight", 480, 10000)):
        if key in raw and raw[key] is not None:
            try:
                out[key] = max(lo, min(hi, int(raw[key])))
            except (TypeError, ValueError):
                pass
    for key in ("windowX", "windowY"):
        if key in raw:
            if raw[key] is None:
                out[key] = None
            else:
                try:
                    out[key] = int(raw[key])
                except (TypeError, ValueError):
                    out[key] = None
    if "windowMaximized" in raw:
        out["windowMaximized"] = bool(raw["windowMaximized"])
    if "windowFullscreen" in raw:
        out["windowFullscreen"] = bool(raw["windowFullscreen"])
    if "authSource" in raw:
        src = str(raw["authSource"] or "auto").lower()
        out["authSource"] = "manual" if src == "manual" else "auto"
    if "launchAtStartup" in raw:
        out["launchAtStartup"] = bool(raw["launchAtStartup"])
    if "startHidden" in raw:
        out["startHidden"] = bool(raw["startHidden"])
    for key in ("ballX", "ballY"):
        if key in raw:
            if raw[key] is None:
                out[key] = None
            else:
                try:
                    out[key] = int(raw[key])
                except (TypeError, ValueError):
                    out[key] = None
    for key, lo, hi in (
        ("ballSize", 72, 240),
        ("ballOpacity", 40, 100),
        ("ballRefreshMs", 2000, 30000),
        ("ballFontSize", 8, 28),
        ("ballRingWidth", 3, 18),
        ("dockWidth", 180, 520),
    ):
        if key in raw and raw[key] is not None:
            try:
                out[key] = max(lo, min(hi, int(raw[key])))
            except (TypeError, ValueError):
                pass
    return out


def load_settings() -> dict[str, Any]:
    with _lock:
        raw = read_json(settings_path()) or {}
        migrated, changed = _migrate_settings(raw)
        normalized = _normalize_settings(migrated)
        if changed or (raw and normalized != raw):
            _atomic_write(settings_path(), normalized)
    return normalized


def save_settings(patch: dict[str, Any]) -> dict[str, Any]:
    with _lock:
        cur = read_json(settings_path()) or {}
        cur.update(patch)
        migrated, _ = _migrate_settings(cur)
        merged = _normalize_settings(migrated)
        _atomic_write(settings_path(), merged)
        return merged


def credentials_path() -> Path:
    return data_dir() / "credentials.json"


def load_credentials() -> dict[str, Any]:
    with _lock:
        raw = read_json(credentials_path()) or {}
    return {
        "accessToken": str(raw.get("accessToken") or "").strip(),
        "refreshToken": str(raw.get("refreshToken") or "").strip(),
        "email": str(raw.get("email") or "").strip(),
        "updatedAt": raw.get("updatedAt"),
    }


def save_credentials(patch: dict[str, Any]) -> dict[str, Any]:
    with _lock:
        cur = read_json(credentials_path()) or {}
        for key in ("accessToken", "refreshToken", "email"):
            if key in patch and patch[key] is not None:
                cur[key] = str(patch[key]).strip()
        cur["updatedAt"] = datetime.now(timezone.utc).isoformat()
        _atomic_write(credentials_path(), cur)
        return {
            "accessToken": str(cur.get("accessToken") or "").strip(),
            "refreshToken": str(cur.get("refreshToken") or "").strip(),
            "email": str(cur.get("email") or "").strip(),
            "updatedAt": cur.get("updatedAt"),
        }


def clear_credentials() -> None:
    path = credentials_path()
    with _lock:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def credentials_public_info() -> dict[str, Any]:
    """Safe summary for UI — never return full tokens."""
    creds = load_credentials()
    access = creds.get("accessToken") or ""
    refresh = creds.get("refreshToken") or ""
    preview = ""
    if access:
        preview = ("…" + access[-8:]) if len(access) > 8 else "已设置"
    return {
        "hasManualCredentials": bool(access),
        "hasRefreshToken": bool(refresh),
        "manualEmail": creds.get("email") or "",
        "tokenPreview": preview,
        "credentialsUpdatedAt": creds.get("updatedAt"),
    }
