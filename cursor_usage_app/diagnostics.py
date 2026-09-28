"""Build a privacy-safe diagnostic archive for support."""

from __future__ import annotations

import json
import platform
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import __version__
from .logging_setup import redact
from .store import data_dir, load_meta, load_settings


def _json_bytes(value: dict[str, Any]) -> bytes:
    return json.dumps(redact(value), ensure_ascii=False, indent=2).encode("utf-8")


def _sanitized_log_bytes(path: Path) -> bytes:
    lines: list[str] = []
    try:
        with path.open("r", encoding="utf-8", errors="replace") as source:
            for raw_line in source:
                raw_line = raw_line.rstrip("\r\n")
                try:
                    value = json.loads(raw_line)
                except json.JSONDecodeError:
                    value = {"message": raw_line}
                lines.append(json.dumps(redact(value), ensure_ascii=False, separators=(",", ":")))
    except OSError:
        return b""
    return (("\n".join(lines) + "\n") if lines else "").encode("utf-8")


def create_diagnostic_zip(
    destination: Path | str | None = None,
    log_directory: Path | str | None = None,
) -> Path:
    """Create a zip containing only support-safe metadata and sanitized logs."""
    if destination is None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        destination_path = data_dir() / f"diagnostics-{stamp}.zip"
    else:
        destination_path = Path(destination)
    destination_path.parent.mkdir(parents=True, exist_ok=True)

    logs = Path(log_directory) if log_directory is not None else data_dir() / "logs"
    system_info = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "appVersion": __version__,
        "pythonVersion": platform.python_version(),
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "executableMode": "frozen" if getattr(sys, "frozen", False) else "source",
    }

    # Write beside the destination and replace only after the zip is complete.
    fd, temporary_name = tempfile.mkstemp(
        prefix=destination_path.stem + ".",
        suffix=".tmp",
        dir=str(destination_path.parent),
    )
    try:
        # ZipFile opens the descriptor independently on Windows.
        import os

        os.close(fd)
        with zipfile.ZipFile(
            temporary_name, "w", compression=zipfile.ZIP_DEFLATED
        ) as archive:
            archive.writestr("settings.json", _json_bytes(load_settings()))
            archive.writestr("meta.json", _json_bytes(load_meta()))
            archive.writestr("system.json", _json_bytes(system_info))
            if logs.is_dir():
                for path in sorted(logs.glob("app.jsonl*")):
                    if path.is_file():
                        archive.writestr(
                            f"logs/{path.name}",
                            _sanitized_log_bytes(path),
                        )
        os.replace(temporary_name, destination_path)
    finally:
        Path(temporary_name).unlink(missing_ok=True)
    return destination_path
