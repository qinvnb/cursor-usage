from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from cursor_usage_app import store


def _report(cycle_start: str, used: float, *, fetched: str = "t0") -> dict:
    return {
        "fetchedAt": fetched,
        "account": {"email": "user@example.com"},
        "planInfo": {"planName": "Pro"},
        "summary": {
            "individualUsedCents": used,
            "individualLimitCents": 2000,
            "individualRemainingCents": 2000 - used,
            "includedUsedCents": 500,
            "includedLimitCents": 2000,
            "billingCycleStart": cycle_start,
            "billingCycleEnd": str(int(cycle_start) + 30 * 86_400_000),
        },
        "models": [{"model": "claude", "totalCostCents": used}],
    }


class SummaryFileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root_patch = patch.object(store, "app_root", return_value=Path(self.temporary.name))
        self.root_patch.start()

    def tearDown(self) -> None:
        self.root_patch.stop()
        self.temporary.cleanup()

    def test_save_writes_compact_widget_summary(self) -> None:
        store.save_usage(_report("1000", 123))
        summary = json.loads(store.summary_path().read_text(encoding="utf-8"))
        self.assertEqual(summary["individualUsedCents"], 123)
        self.assertEqual(summary["individualLimitCents"], 2000)
        self.assertNotIn("fetchedAt", summary)
        self.assertEqual(store.load_summary(), summary)

    def test_unchanged_report_skips_rewrite_but_stays_fresh(self) -> None:
        self.assertTrue(store.save_usage(_report("1000", 123, fetched="a")))
        before = store.usage_path().stat().st_mtime_ns
        time.sleep(0.02)
        self.assertFalse(store.save_usage(_report("1000", 123, fetched="b")))
        self.assertEqual(store.usage_path().stat().st_mtime_ns, before)
        self.assertEqual(store.load_meta()["fetchedAt"], "b")
        self.assertLess(store.age_seconds(), 5)

    def test_changed_report_is_rewritten(self) -> None:
        store.save_usage(_report("1000", 123))
        self.assertTrue(store.save_usage(_report("1000", 456)))
        self.assertEqual(store.load_usage()["summary"]["individualUsedCents"], 456)
        self.assertEqual(store.load_summary()["individualUsedCents"], 456)

    def test_summary_falls_back_to_usage_report(self) -> None:
        store.save_usage(_report("1000", 77))
        store.summary_path().unlink()
        self.assertEqual(store.load_summary()["individualUsedCents"], 77)

    def test_cycle_rollover_records_previous_cycle_once(self) -> None:
        store.save_usage(_report("1000", 100))
        store.save_usage(_report("1000", 900))
        store.save_usage(_report("5000", 10))
        store.save_usage(_report("5000", 20))
        cycles = store.load_history()["cycles"]
        self.assertEqual(len(cycles), 1)
        self.assertEqual(cycles[0]["cycleStart"], "1000")
        self.assertEqual(cycles[0]["individualUsedCents"], 900)
        self.assertEqual(cycles[0]["totalCents"], 1400)

    def test_history_is_capped(self) -> None:
        for i in range(store.HISTORY_LIMIT + 5):
            store.save_usage(_report(str(1000 + i), 1))
        self.assertEqual(len(store.load_history()["cycles"]), store.HISTORY_LIMIT)

    @unittest.skipUnless(sys.platform == "win32", "DPAPI is Windows-only")
    def test_credentials_are_encrypted_at_rest(self) -> None:
        store.save_credentials({"accessToken": "aaa.bbb.ccc", "refreshToken": "secret-r"})
        raw = store.credentials_path().read_text(encoding="utf-8")
        self.assertNotIn("aaa.bbb.ccc", raw)
        self.assertNotIn("secret-r", raw)
        self.assertEqual(store.load_credentials()["accessToken"], "aaa.bbb.ccc")

    @unittest.skipUnless(sys.platform == "win32", "DPAPI is Windows-only")
    def test_legacy_plaintext_credentials_migrate(self) -> None:
        path = store.credentials_path()
        path.write_text(json.dumps({"accessToken": "old.tok.en", "email": "a@b.c"}), encoding="utf-8")
        self.assertEqual(store.load_credentials()["accessToken"], "old.tok.en")
        self.assertNotIn("old.tok.en", path.read_text(encoding="utf-8"))
        self.assertFalse(path.with_suffix(".json.bak").exists())


if __name__ == "__main__":
    unittest.main()
