"""Windows launch-at-startup (HKCU Run)."""

from __future__ import annotations

import sys
from pathlib import Path


RUN_VALUE_NAME = "CursorUsage"


def launch_command() -> str:
    """Command line written to the Run key."""
    if getattr(sys, "frozen", False):
        exe = str(Path(sys.executable).resolve())
        return f'"{exe}" --start-hidden'
    # Dev: run module from project root
    py = str(Path(sys.executable).resolve())
    root = Path(__file__).resolve().parent.parent
    return f'"{py}" -m cursor_usage_app --start-hidden'


def is_launch_at_startup() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_READ,
        ) as key:
            try:
                winreg.QueryValueEx(key, RUN_VALUE_NAME)
                return True
            except FileNotFoundError:
                return False
    except Exception:
        return False


def set_launch_at_startup(enabled: bool) -> bool:
    """Enable/disable login startup. Returns final state."""
    if sys.platform != "win32":
        return False
    import winreg

    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        r"Software\Microsoft\Windows\CurrentVersion\Run",
        0,
        winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE,
    ) as key:
        if enabled:
            winreg.SetValueEx(key, RUN_VALUE_NAME, 0, winreg.REG_SZ, launch_command())
        else:
            try:
                winreg.DeleteValue(key, RUN_VALUE_NAME)
            except FileNotFoundError:
                pass
    return is_launch_at_startup()
