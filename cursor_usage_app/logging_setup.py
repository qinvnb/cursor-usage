"""Privacy-safe JSONL application logging."""

from __future__ import annotations

import json
import logging
import re
import sys
import threading
from datetime import datetime, timedelta, timezone
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from types import TracebackType
from typing import Any, Callable

from .store import data_dir

LOG_RETENTION_DAYS = 7
_SENSITIVE_KEY = re.compile(
    r"(?i)(access[\s_-]?token|refresh[\s_-]?token|authorization|cookie|set-cookie|"
    r"password|passwd|secret|api[_-]?key|session[_-]?id)"
)
_KEY_VALUE = re.compile(
    r"""(?ix)
    (["']?(?:access[\s_-]?token|refresh[\s_-]?token|authorization|cookie|set-cookie|
       password|passwd|secret|api[_-]?key|session[_-]?id)["']?
       (?:\s*[:=]\s*|\s+))
    (?:"[^"]*"|'[^']*'|[^\s,;}]+)
    """
)
_BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")
_WINDOWS_PROFILE = re.compile(r"(?i)\b[A-Z]:\\Users\\[^\\/\s\"']+")
_UNIX_PROFILE = re.compile(r"(?<![\w])/(?:home|Users)/[^/\s\"']+")


def redact(value: Any, key: str | None = None) -> Any:
    """Return a JSON-safe copy with credentials and token-like text removed."""
    if key and _SENSITIVE_KEY.search(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(k): redact(v, str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [redact(item) for item in value]
    if isinstance(value, str):
        text = _BEARER.sub("Bearer [REDACTED]", value)
        text = _JWT.sub("[REDACTED_JWT]", text)
        text = _KEY_VALUE.sub(r"\1[REDACTED]", text)
        text = _WINDOWS_PROFILE.sub("%USERPROFILE%", text)
        return _UNIX_PROFILE.sub("~", text)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return redact(str(value))


class JsonlFormatter(logging.Formatter):
    """One JSON object per log record, with defense-in-depth redaction."""

    def format(self, record: logging.LogRecord) -> str:
        try:
            message = record.getMessage()
        except Exception:
            message = str(record.msg)
        item: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact(message),
        }
        if record.exc_info:
            item["exception"] = redact(self.formatException(record.exc_info))
        for key in ("component", "status", "exitCode", "error"):
            value = getattr(record, key, None)
            if value is not None:
                item[key] = redact(value)
        return json.dumps(item, ensure_ascii=False, separators=(",", ":"))


def cleanup_old_logs(directory: Path, retention_days: int = LOG_RETENTION_DAYS) -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, retention_days))
    for path in directory.glob("app.jsonl*"):
        try:
            modified = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
            if modified < cutoff:
                path.unlink()
        except OSError:
            continue


def setup_logging(
    log_directory: Path | str | None = None,
    level: int = logging.INFO,
) -> logging.Logger:
    """Configure and return the application logger."""
    directory = Path(log_directory) if log_directory is not None else data_dir() / "logs"
    directory.mkdir(parents=True, exist_ok=True)
    cleanup_old_logs(directory)

    logger = logging.getLogger("cursor_usage_app")
    logger.setLevel(level)
    logger.propagate = False
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            pass

    handler = TimedRotatingFileHandler(
        directory / "app.jsonl",
        when="midnight",
        interval=1,
        backupCount=LOG_RETENTION_DAYS,
        encoding="utf-8",
        utc=True,
    )
    handler.setFormatter(JsonlFormatter())
    logger.addHandler(handler)
    return logger


def install_exception_hooks(logger: logging.Logger | None = None) -> Callable[[], None]:
    """Install process and thread exception hooks; return an uninstall function."""
    target = logger or logging.getLogger("cursor_usage_app")
    old_sys_hook = sys.excepthook
    old_thread_hook = getattr(threading, "excepthook", None)

    def system_hook(
        exc_type: type[BaseException],
        exc_value: BaseException,
        traceback: TracebackType | None,
    ) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            old_sys_hook(exc_type, exc_value, traceback)
            return
        target.critical("Uncaught exception", exc_info=(exc_type, exc_value, traceback))

    def thread_hook(args: threading.ExceptHookArgs) -> None:
        if args.exc_type is SystemExit:
            return
        target.critical(
            "Uncaught thread exception in %s",
            getattr(args.thread, "name", "unknown"),
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    sys.excepthook = system_hook
    if old_thread_hook is not None:
        threading.excepthook = thread_hook

    def uninstall() -> None:
        sys.excepthook = old_sys_hook
        if old_thread_hook is not None:
            threading.excepthook = old_thread_hook

    return uninstall
