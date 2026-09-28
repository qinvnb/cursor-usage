"""Optional GitHub Releases update check (off by default; no usage data is sent)."""

from __future__ import annotations

import json
import re
import urllib.request
from typing import Any

from . import __version__

REPOSITORY = "qinvnb/cursor-usage"
RELEASES_API = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"

# Latest known newer release, shared with the HTTP API in the same process.
latest: dict[str, Any] | None = None


def parse_version(value: str) -> tuple[int, ...]:
    parts = re.findall(r"\d+", value or "")
    return tuple(int(p) for p in parts[:3]) or (0,)


def check_latest(current: str = __version__, *, timeout: float = 10.0) -> dict[str, Any] | None:
    """Return {"version", "url", "name"} when a newer release exists, else None."""
    global latest
    req = urllib.request.Request(
        RELEASES_API,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"cursor-usage/{current}",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    tag = str(data.get("tag_name") or "")
    if data.get("draft") or data.get("prerelease") or not tag:
        return None
    if parse_version(tag) <= parse_version(current):
        latest = None
        return None
    latest = {
        "version": tag.lstrip("vV"),
        "url": data.get("html_url") or f"https://github.com/{REPOSITORY}/releases/latest",
        "name": data.get("name") or tag,
    }
    return latest
