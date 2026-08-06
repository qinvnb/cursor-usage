from __future__ import annotations

import json
import logging
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from cursor_usage_app import diagnostics, logging_setup, store


class LoggingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.root_patch = patch.object(store, "app_root", return_value=self.root)
        self.root_patch.start()

    def tearDown(self) -> None:
        logger = logging.getLogger("cursor_usage_app")
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()
        self.root_patch.stop()
        self.temporary.cleanup()

    def test_jsonl_logging_redacts_tokens_cookies_and_jwt(self) -> None:
        logs = self.root / "logs"
        logger = logging_setup.setup_logging(logs)
        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1c2VyMTIzIn0.signature123456"
        logger.error(
            "authorization=Bearer super-secret cookie=session-value jwt=%s",
            jwt,
        )
        for handler in logger.handlers:
            handler.flush()

        raw = (logs / "app.jsonl").read_text(encoding="utf-8")
        event = json.loads(raw)
        self.assertNotIn("super-secret", raw)
        self.assertNotIn("session-value", raw)
        self.assertNotIn(jwt, raw)
        self.assertIn("[REDACTED", event["message"])

    def test_nested_sensitive_fields_are_redacted(self) -> None:
        sanitized = logging_setup.redact(
            {
                "accessToken": "token-value",
                "safe": {"cookie": "cookie-value", "count": 3},
                "message": "api_key=key-value",
            }
        )
        rendered = json.dumps(sanitized)
        self.assertNotIn("token-value", rendered)
        self.assertNotIn("cookie-value", rendered)
        self.assertNotIn("key-value", rendered)
        self.assertEqual(sanitized["safe"]["count"], 3)

    def test_user_profile_paths_are_redacted(self) -> None:
        windows = logging_setup.redact(
            r"failed at C:\Users\Alice\AppData\Local\CursorUsage\data\usage.json"
        )
        unix = logging_setup.redact("/home/alice/.config/cursor/state.json")
        self.assertNotIn("Alice", windows)
        self.assertIn("%USERPROFILE%", windows)
        self.assertNotIn("alice", unix)

    def test_diagnostic_zip_excludes_credentials_and_usage(self) -> None:
        store.save_settings({"authSource": "manual"})
        store.save_usage({"events": [{"accessToken": "usage-secret"}]})
        store.save_credentials({"accessToken": "credential-secret"})
        logs = self.root / "logs"
        logs.mkdir()
        (logs / "app.jsonl").write_text(
            '{"message":"cookie=log-secret"}\n',
            encoding="utf-8",
        )

        with patch.object(
            diagnostics,
            "load_meta",
            return_value={
                "dataPath": r"C:\Users\Alice\CursorUsage\data\usage.json"
            },
        ):
            archive_path = diagnostics.create_diagnostic_zip(
                self.root / "diagnostics.zip",
                logs,
            )

        with zipfile.ZipFile(archive_path) as archive:
            names = set(archive.namelist())
            combined = b"".join(archive.read(name) for name in names)
        self.assertIn("settings.json", names)
        self.assertIn("meta.json", names)
        self.assertIn("system.json", names)
        self.assertFalse(any("credential" in name for name in names))
        self.assertFalse(any("usage" in name for name in names))
        self.assertNotIn(b"credential-secret", combined)
        self.assertNotIn(b"usage-secret", combined)
        self.assertNotIn(b"log-secret", combined)
        self.assertNotIn(b"Alice", combined)


if __name__ == "__main__":
    unittest.main()
