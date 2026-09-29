from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from cursor_usage_app import bridge, store


class FakeApp:
    def __init__(self) -> None:
        self.summaries: list[dict[str, Any]] = []
        self.applied: list[dict[str, Any]] = []
        self.notified: list[tuple[str, str]] = []

    def on_summary(self, summary: dict[str, Any]) -> None:
        self.summaries.append(summary)

    def notify(self, title: str, message: str) -> None:
        self.notified.append((title, message))

    def apply_settings(self, settings: dict[str, Any]) -> None:
        self.applied.append(settings)

    def component_status(self) -> dict[str, Any]:
        return {}

    def reembed_dock(self) -> None:
        pass

    def update_info(self) -> None:
        return None


class BridgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.patch = patch.object(store, "app_root", return_value=self.root)
        self.patch.start()
        self.app = FakeApp()
        self.bridge = bridge.Bridge(self.app)

    def tearDown(self) -> None:
        self.patch.stop()
        self.tmp.cleanup()

    def test_http_only_reaches_cursor_hosts(self) -> None:
        for url in ("https://example.com/x", "http://api2.cursor.sh/x", "file:///etc/passwd", "https://cursor.com.evil.io/"):
            with self.assertRaises(PermissionError, msg=url):
                self.bridge.http({"url": url, "method": "GET"})

    def test_private_members_are_not_exposed(self) -> None:
        public = [n for n in dir(self.bridge) if not n.startswith("_")]
        self.assertNotIn("app", public)
        self.assertIn("saveReport", public)

    def test_local_auth_read_and_write(self) -> None:
        db = self.root / "state.vscdb"
        conn = sqlite3.connect(db)
        conn.execute("CREATE TABLE ItemTable (key TEXT UNIQUE ON CONFLICT REPLACE, value BLOB)")
        conn.executemany(
            "INSERT INTO ItemTable VALUES (?, ?)",
            [("cursorAuth/accessToken", "a.b.c"), ("cursorAuth/cachedEmail", "me@x.y"), ("other", "x")],
        )
        conn.commit()
        conn.close()
        with patch.dict("os.environ", {"CURSOR_STATE_DB": str(db)}):
            self.assertEqual(self.bridge.readLocalAuth(), {"accessToken": "a.b.c", "cachedEmail": "me@x.y"})
            self.bridge.writeLocalAuth({"accessToken": "new.t.k", "refreshToken": "r"})
            self.assertEqual(self.bridge.readLocalAuth()["accessToken"], "new.t.k")
            self.assertEqual(self.bridge.readLocalAuth()["refreshToken"], "r")

    def test_missing_state_db_raises_readable_error(self) -> None:
        with patch.dict("os.environ", {"CURSOR_STATE_DB": str(self.root / "missing.vscdb")}):
            with self.assertRaises(RuntimeError):
                self.bridge.readLocalAuth()

    def test_save_report_persists_and_notifies_app(self) -> None:
        summary = {"individualUsedCents": 1, "individualLimitCents": 2}
        self.bridge.saveReport({"fetchedAt": "t", "summary": {}}, summary)
        self.assertEqual(store.load_summary(), summary)
        self.assertEqual(self.app.summaries, [summary])
        state = self.bridge.loadState()
        self.assertEqual(state["report"]["fetchedAt"], "t")
        self.assertEqual(state["history"], [])

    def test_ui_only_settings_do_not_reconfigure_components(self) -> None:
        with patch("cursor_usage_app.autostart.is_launch_at_startup", return_value=False):
            self.bridge.saveSettings({"lastView": "home"})
            self.assertEqual(self.app.applied, [])
            self.bridge.saveSettings({"ballEnabled": True})
        self.assertTrue(self.app.applied[-1]["ballEnabled"])

    def test_env_token_parsing(self) -> None:
        with patch.dict("os.environ", {"CURSOR_SESSION_TOKEN": "user%3A%3Aa.b.c"}, clear=False):
            self.assertEqual(bridge.env_token(), "a.b.c")


if __name__ == "__main__":
    unittest.main()
