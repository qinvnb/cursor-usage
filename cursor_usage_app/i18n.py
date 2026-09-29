"""Two-language text for the native parts (tray, floating ball, taskbar widget).

Mirrors packages/core/src/i18n.ts: each call site carries both strings,
``L("显示看板", "Show dashboard")``. The app calls ``set_language`` with the
shared ``language`` setting at startup and whenever settings change; "auto"
follows the Windows display language.
"""

from __future__ import annotations

import sys
from functools import lru_cache

APP_TITLES = ("Cursor 用量", "Cursor Usage")


@lru_cache(maxsize=1)
def system_lang() -> str:
    if sys.platform == "win32":
        try:
            import ctypes

            lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            return "zh" if (lang_id & 0x3FF) == 0x04 else "en"  # LANG_CHINESE
        except Exception:
            pass
    import locale

    code = (locale.getlocale()[0] or "").lower()
    return "zh" if code.startswith(("zh", "chinese")) else "en"


def resolve(pref: object) -> str:
    return pref if pref in ("zh", "en") else system_lang()  # type: ignore[return-value]


_lang = "zh"


def set_language(pref: object) -> str:
    global _lang
    _lang = resolve(pref)
    return _lang


def current() -> str:
    return _lang


def L(zh: str, en: str) -> str:
    return en if _lang == "en" else zh


def app_title() -> str:
    return L(*APP_TITLES)
