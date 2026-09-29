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

    def test_widget_summary_carries_included_pools(self) -> None:
        legacy = json.loads(json.dumps(_report("1000", 123)))
        store.save_usage(legacy)
        summary = store.load_summary()
        self.assertIsNone(summary["autoPercentUsed"])
        self.assertIsNone(summary["apiPercentUsed"])

        split = _report("1000", 456)
        split["periodUsage"] = {"planUsage": {"autoPercentUsed": 10.37, "apiPercentUsed": 100}}
        split["summary"].update(autoPercentUsed=10.37, apiPercentUsed=100)
        store.save_usage(split)
        summary = store.load_summary()
        self.assertEqual((summary["autoPercentUsed"], summary["apiPercentUsed"]), (10.4, 100.0))

        from cursor_usage_app import i18n
        from cursor_usage_app.tray import format_usage_lines

        try:
            i18n.set_language("zh")
            self.assertEqual(
                format_usage_lines(summary)[1:],
                ["套餐内 Cursor 模型（Auto）已用 10%", "套餐内其他模型（API）已用 100%"],
            )
            i18n.set_language("en")
            self.assertEqual(
                format_usage_lines(summary)[1:],
                ["Included Cursor models (Auto): 10% used", "Included other models (API): 100% used"],
            )
            with_tokens = {**summary, "tokens": {"total": 259_876_000}}
            self.assertEqual(format_usage_lines(with_tokens)[-1], "Tokens this cycle: 259.9M")
        finally:
            i18n.set_language("zh")

    def test_language_setting_is_validated(self) -> None:
        self.assertEqual(store.load_settings()["language"], "auto")
        self.assertEqual(store.save_settings({"language": "en"})["language"], "en")
        self.assertEqual(store.save_settings({"language": "fr"})["language"], "auto")

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

    def test_summary_from_core_is_stored_as_given(self) -> None:
        summary = {"individualUsedCents": 5, "individualLimitCents": 9, "fromCore": True}
        store.save_usage(_report("1000", 5), summary)
        self.assertEqual(store.load_summary(), summary)

    def test_history_is_stored_and_capped(self) -> None:
        cycles = [{"cycleStart": str(i), "totalCents": i} for i in range(store.HISTORY_LIMIT + 5)]
        store.save_history(cycles)
        stored = store.load_history()["cycles"]
        self.assertEqual(len(stored), store.HISTORY_LIMIT)
        self.assertEqual(stored[-1]["cycleStart"], str(store.HISTORY_LIMIT + 4))

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
