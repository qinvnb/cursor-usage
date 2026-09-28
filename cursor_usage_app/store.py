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


_ready_data_dirs: set[Path] = set()


def data_dir() -> Path:
    path = app_root() / "data"
    if path in _ready_data_dirs:
        return path
    path.mkdir(parents=True, exist_ok=True)
    _migrate_legacy_data(path)
    _ready_data_dirs.add(path)
    return path


def usage_path() -> Path:
    return data_dir() / "usage.json"


def summary_path() -> Path:
    return data_dir() / "summary.json"


def meta_path() -> Path:
    return data_dir() / "meta.json"


def _atomic_write(path: Path, payload: dict[str, Any], *, indent: int | None = 2) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if indent is None:
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    else:
        raw = json.dumps(payload, ensure_ascii=False, indent=indent)
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


_file_cache: dict[Path, tuple[tuple[int, int], dict[str, Any]]] = {}


def _stat_key(path: Path) -> tuple[int, int] | None:
    try:
        st = path.stat()
    except OSError:
        return None
    return st.st_mtime_ns, st.st_size


def read_json_cached(path: Path) -> dict[str, Any] | None:
    """Like read_json, but reuse the parsed object while mtime/size are unchanged.

    Callers must treat the returned dict as read-only.
    """
    key = _stat_key(path)
    if key is not None:
        hit = _file_cache.get(path)
        if hit is not None and hit[0] == key:
            return hit[1]
    data = read_json(path)
    key = _stat_key(path)
    if data is not None and key is not None:
        _file_cache[path] = (key, data)
    else:
        _file_cache.pop(path, None)
    return data


def load_usage() -> dict[str, Any] | None:
    with _lock:
        return read_json_cached(usage_path())


def summary_from_report(report: dict[str, Any]) -> dict[str, Any]:
    """Small, stable summary shared by the dashboard API and desktop widgets."""
    summary = report.get("summary") or {}
    account = report.get("account") or {}
    plan = report.get("planInfo") or {}
    individual_used = float(summary.get("individualUsedCents") or 0)
    individual_limit = float(summary.get("individualLimitCents") or 0)
    individual_left = float(summary.get("individualRemainingCents") or 0)
    used_pct = (
        min(100.0, individual_used / individual_limit * 100.0) if individual_limit > 0 else 0.0
    )
    return {
        "email": account.get("email"),
        "planName": plan.get("planName"),
        "unifiedUsedCents": summary.get("unifiedUsedCents"),
        "individualUsedCents": individual_used,
        "individualLimitCents": individual_limit,
        "individualRemainingCents": individual_left,
        "includedUsedCents": summary.get("includedUsedCents"),
        "includedLimitCents": summary.get("includedLimitCents"),
        "includedRemainingCents": summary.get("includedRemainingCents"),
        "usedPercent": round(used_pct, 1),
        "topOnDemandModel": summary.get("topOnDemandModel"),
        "billingCycleStart": summary.get("billingCycleStart"),
        "billingCycleEnd": summary.get("billingCycleEnd"),
    }


def load_summary() -> dict[str, Any] | None:
    """Read the widget summary; fall back to deriving it from usage.json."""
    data = read_json_cached(summary_path())
    if data is not None:
        return data
    report = load_usage()
    return summary_from_report(report) if report else None


def _report_digest(report: dict[str, Any]) -> str:
    import hashlib

    stable = {k: v for k, v in report.items() if k != "fetchedAt"}
    raw = json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def load_meta() -> dict[str, Any]:
    with _lock:
        meta = read_json_cached(meta_path()) or {}
    return {
        "refreshing": bool(meta.get("refreshing")),
        "lastSuccessAt": meta.get("lastSuccessAt"),
        "fetchedAt": meta.get("fetchedAt"),
        "usageDigest": meta.get("usageDigest"),
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


def save_usage(report: dict[str, Any]) -> bool:
    """Persist a fresh report. Returns False when only fetchedAt changed.

    Unchanged reports skip rewriting usage.json/summary.json; freshness is
    tracked through meta.lastSuccessAt instead of the file mtime.
    """
    with _lock:
        meta = read_json(meta_path()) or {}
        digest = _report_digest(report)
        previous = read_json_cached(usage_path())
        changed = digest != meta.get("usageDigest") or previous is None
        if changed:
            if previous is not None:
                _record_cycle_snapshot(previous, report)
            _atomic_write(usage_path(), report, indent=None)
            summary = summary_from_report(report)
            if summary != read_json(summary_path()):
                _atomic_write(summary_path(), summary, indent=None)
        now = datetime.now(timezone.utc).isoformat()
        meta.update(
            {
                "refreshing": False,
                "lastSuccessAt": now,
                "lastAttemptAt": now,
                "lastError": None,
                "updatedAt": now,
                "dataPath": str(usage_path()),
                "usageDigest": digest,
                "fetchedAt": report.get("fetchedAt"),
            }
        )
        _atomic_write(meta_path(), meta)
        return changed


HISTORY_LIMIT = 24


def history_path() -> Path:
    return data_dir() / "history.json"


def cycle_snapshot(report: dict[str, Any]) -> dict[str, Any] | None:
    """Compact per-cycle totals used by the history page."""
    summary = report.get("summary") or {}
    start = summary.get("billingCycleStart")
    if not start:
        return None
    models = report.get("models") or []
    included = float(summary.get("includedUsedCents") or 0)
    individual = float(summary.get("individualUsedCents") or 0)
    return {
        "cycleStart": str(start),
        "cycleEnd": str(summary.get("billingCycleEnd") or ""),
        "planName": (report.get("planInfo") or {}).get("planName"),
        "includedUsedCents": included,
        "includedLimitCents": float(summary.get("includedLimitCents") or 0),
        "individualUsedCents": individual,
        "individualLimitCents": float(summary.get("individualLimitCents") or 0),
        "totalCents": included + individual,
        "eventCount": summary.get("eventCount"),
        "topModels": [
            {"model": m.get("model"), "costCents": float(m.get("totalCostCents") or 0)}
            for m in models[:5]
        ],
        "capturedAt": report.get("fetchedAt"),
    }


def _record_cycle_snapshot(previous: dict[str, Any], current: dict[str, Any]) -> None:
    """When the billing cycle rolls over, keep the finished cycle's final numbers."""
    old = cycle_snapshot(previous)
    new_start = str((current.get("summary") or {}).get("billingCycleStart") or "")
    if old is None or not new_start or old["cycleStart"] == new_start:
        return
    history = load_history()
    cycles = [c for c in history.get("cycles", []) if c.get("cycleStart") != old["cycleStart"]]
    cycles.append(old)
    cycles.sort(key=lambda c: int(c.get("cycleStart") or 0))
    _atomic_write(history_path(), {"cycles": cycles[-HISTORY_LIMIT:]}, indent=None)


def load_history() -> dict[str, Any]:
    data = read_json(history_path()) or {}
    cycles = data.get("cycles")
    return {"cycles": cycles if isinstance(cycles, list) else []}


def alerts_state_path() -> Path:
    return data_dir() / "alerts.json"


def load_alerts_state() -> dict[str, Any]:
    return read_json(alerts_state_path()) or {}


def save_alerts_state(state: dict[str, Any]) -> None:
    with _lock:
        _atomic_write(alerts_state_path(), state, indent=None)


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
    meta = read_json_cached(meta_path()) or {}
    last = meta.get("lastSuccessAt")
    if last:
        try:
            ts = datetime.fromisoformat(str(last)).timestamp()
            return max(0.0, time.time() - ts)
        except ValueError:
            pass
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
    # Refresh an expired local Cursor token and write it back to state.vscdb.
    # Off by default: a rotating refresh token could otherwise sign Cursor out.
    "persistLocalRefresh": False,
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
    "lastView": "home",
    "alertsEnabled": True,
    # Off by default: contacting GitHub is the only non-Cursor network request.
    "checkUpdates": False,
}

DASHBOARD_VIEWS = ("home", "ondemand", "included", "daily", "models", "history", "settings")


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
    if raw.get("lastView") in DASHBOARD_VIEWS:
        out["lastView"] = raw["lastView"]
    for key in ("alertsEnabled", "checkUpdates"):
        if key in raw:
            out[key] = bool(raw[key])
    if "persistLocalRefresh" in raw:
        out["persistLocalRefresh"] = bool(raw["persistLocalRefresh"])
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


_CRED_FIELDS = ("accessToken", "refreshToken", "email")


def _dpapi(data: bytes, *, protect: bool) -> bytes | None:
    """Encrypt/decrypt with Windows DPAPI (current user scope). None if unavailable."""
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    buffer = ctypes.create_string_buffer(data, len(data))
    blob_in = DATA_BLOB(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    blob_out = DATA_BLOB()
    CRYPTPROTECT_UI_FORBIDDEN = 0x1
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    ok = fn(
        ctypes.byref(blob_in),
        None,
        None,
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(blob_out),
    )
    if not ok:
        return None
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(blob_out.pbData, ctypes.c_void_p))


def _decode_credentials(raw: dict[str, Any]) -> dict[str, Any]:
    """Accept the DPAPI format ({"protected": base64}) and legacy plaintext."""
    import base64

    protected = raw.get("protected")
    if not protected:
        return raw
    try:
        plain = _dpapi(base64.b64decode(protected), protect=False)
        secrets = json.loads(plain.decode("utf-8")) if plain else {}
    except (ValueError, UnicodeError):
        secrets = {}
    return {**secrets, "updatedAt": raw.get("updatedAt")}


def _encode_credentials(values: dict[str, Any]) -> dict[str, Any]:
    import base64

    secrets = {k: values.get(k, "") for k in _CRED_FIELDS}
    sealed = _dpapi(json.dumps(secrets).encode("utf-8"), protect=True)
    if sealed is None:
        # Non-Windows development fallback.
        return {**secrets, "updatedAt": values.get("updatedAt")}
    return {
        "format": "dpapi-v1",
        "protected": base64.b64encode(sealed).decode("ascii"),
        "updatedAt": values.get("updatedAt"),
    }


def load_credentials() -> dict[str, Any]:
    with _lock:
        stored = read_json(credentials_path()) or {}
        raw = _decode_credentials(stored)
        if stored and not stored.get("protected") and sys.platform == "win32":
            # Migrate legacy plaintext credentials in place.
            try:
                _atomic_write(credentials_path(), _encode_credentials(raw))
                _remove_backup(credentials_path())
            except OSError:
                pass
    return {
        "accessToken": str(raw.get("accessToken") or "").strip(),
        "refreshToken": str(raw.get("refreshToken") or "").strip(),
        "email": str(raw.get("email") or "").strip(),
        "updatedAt": raw.get("updatedAt"),
    }


def _remove_backup(path: Path) -> None:
    """Drop the .bak copy so a plaintext generation does not linger on disk."""
    try:
        path.with_suffix(path.suffix + ".bak").unlink(missing_ok=True)
    except OSError:
        pass


def save_credentials(patch: dict[str, Any]) -> dict[str, Any]:
    with _lock:
        stored = read_json(credentials_path()) or {}
        cur = _decode_credentials(stored)
        for key in _CRED_FIELDS:
            if key in patch and patch[key] is not None:
                cur[key] = str(patch[key]).strip()
        cur["updatedAt"] = datetime.now(timezone.utc).isoformat()
        _atomic_write(credentials_path(), _encode_credentials(cur))
        if stored and not stored.get("protected"):
            _remove_backup(credentials_path())
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
        _remove_backup(path)


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
