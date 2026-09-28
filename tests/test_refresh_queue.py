from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from cursor_usage_app import server


class RefreshQueueTests(unittest.TestCase):
    def setUp(self) -> None:
        with server._refresh_condition:
            self.assertIsNone(server._refresh_thread)
            server._refresh_pending = False
            server._refresh_pending_models = False
            server._refresh_running_models = False
            server._refresh_state = "success"
            server._refresh_error = None
            server._refresh_generation = 0
            server._refresh_completed_generation = 0
            server._consecutive_failures = 0
            server._next_auto_refresh_at = 0.0

        self.temp_dir = tempfile.TemporaryDirectory()
        data_dir = Path(self.temp_dir.name)
        usage_path = data_dir / "usage.json"
        usage_path.write_text("{}", encoding="utf-8")
        self.patchers = [
            patch.object(server.store, "load_meta", return_value={}),
            patch.object(server.store, "age_seconds", return_value=3.0),
            patch.object(server.store, "usage_path", return_value=usage_path),
            patch.object(server.store, "data_dir", return_value=data_dir),
        ]
        for patcher in self.patchers:
            patcher.start()

    def tearDown(self) -> None:
        thread = server._refresh_thread
        if thread is not None:
            thread.join(timeout=2)
        self.assertIsNone(server._refresh_thread)
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.temp_dir.cleanup()

    def test_concurrent_requests_merge_and_full_refresh_wins(self) -> None:
        started = threading.Event()
        release = threading.Event()
        calls: list[bool] = []
        active = 0
        max_active = 0
        calls_lock = threading.Lock()

        def fake_refresh(*, include_models: bool = True) -> None:
            nonlocal active, max_active
            with calls_lock:
                calls.append(include_models)
                active += 1
                max_active = max(max_active, active)
                call_number = len(calls)
            if call_number == 1:
                started.set()
                self.assertTrue(release.wait(2))
            with calls_lock:
                active -= 1
            return None

        with patch.object(server, "_do_refresh", side_effect=fake_refresh):
            server.request_refresh(include_models=False)
            self.assertTrue(started.wait(1))
            server.request_refresh(include_models=True)
            server.request_refresh(include_models=True)
            server.request_refresh(include_models=False)
            self.assertTrue(server._refresh_pending)
            self.assertTrue(server._refresh_pending_models)

            target_generation = server._refresh_generation
            release.set()
            with server._refresh_condition:
                completed = server._refresh_condition.wait_for(
                    lambda: server._refresh_completed_generation >= target_generation,
                    timeout=2,
                )
            self.assertTrue(completed)

        self.assertEqual(calls, [False, True])
        self.assertEqual(max_active, 1)
        self.assertEqual(server.status_payload()["refreshState"], "success")

    def test_running_full_refresh_satisfies_lightweight_request(self) -> None:
        started = threading.Event()
        release = threading.Event()
        calls: list[bool] = []

        def fake_refresh(*, include_models: bool = True) -> None:
            calls.append(include_models)
            started.set()
            self.assertTrue(release.wait(2))
            return None

        with patch.object(server, "_do_refresh", side_effect=fake_refresh):
            server.request_refresh(include_models=True)
            self.assertTrue(started.wait(1))
            server.request_refresh(include_models=False)
            self.assertFalse(server._refresh_pending)
            thread = server._refresh_thread
            release.set()
            self.assertIsNotNone(thread)
            thread.join(timeout=2)

        self.assertEqual(calls, [True])

    def test_lightweight_merge_preserves_expensive_event_data(self) -> None:
        cached = {
            "fetchedAt": "old",
            "summary": {"individualUsedCents": 10},
            "daily": [{"date": "2026-08-06"}],
            "models": [{"model": "cached"}],
            "onDemandModels": [{"model": "cached"}],
            "includedModels": [{"model": "cached"}],
        }
        fresh = {
            "fetchedAt": "new",
            "summary": {"individualUsedCents": 20},
            "models": [],
            "onDemandModels": [],
            "includedModels": [],
        }

        merged = server._merge_lightweight_report(cached, fresh)

        self.assertEqual(merged["fetchedAt"], "new")
        self.assertEqual(merged["summary"]["individualUsedCents"], 20)
        self.assertEqual(merged["daily"], cached["daily"])
        self.assertEqual(merged["models"], cached["models"])
        self.assertEqual(merged["onDemandModels"], cached["onDemandModels"])
        self.assertEqual(merged["includedModels"], cached["includedModels"])

    def test_lightweight_merge_keeps_event_derived_fields(self) -> None:
        cached = {
            "account": {"email": "a@b.c", "userId": 7, "authSource": "local"},
            "summary": {"individualUsedCents": 10, "eventCount": 42, "topOnDemandModel": "claude"},
        }
        fresh = {
            "account": {"email": "a@b.c", "membershipType": None, "authSource": "local"},
            "summary": {"individualUsedCents": 20, "eventCount": None, "topOnDemandModel": None},
        }
        merged = server._merge_lightweight_report(cached, fresh)
        self.assertEqual(merged["account"]["userId"], 7)
        self.assertEqual(merged["summary"]["individualUsedCents"], 20)
        self.assertEqual(merged["summary"]["eventCount"], 42)
        self.assertEqual(merged["summary"]["topOnDemandModel"], "claude")

    def test_failed_refresh_exposes_error_state_and_keeps_data_age(self) -> None:
        with patch.object(server, "_do_refresh", return_value="network unavailable"):
            payload = server.request_refresh(wait=True)

        self.assertEqual(payload["refreshState"], "error")
        self.assertEqual(payload["lastError"], "network unavailable")
        self.assertTrue(payload["hasData"])
        self.assertEqual(payload["ageSeconds"], 3.0)

    def test_failures_back_off_automatic_but_not_manual_refreshes(self) -> None:
        calls: list[bool] = []

        def failing(*, include_models: bool = True) -> str:
            calls.append(include_models)
            return "HTTP 503"

        with patch.object(server, "_do_refresh", side_effect=failing):
            first = server.request_refresh(wait=True)
            self.assertEqual(first["consecutiveFailures"], 1)
            self.assertGreater(first["retryInSeconds"], 0)

            skipped = server.request_refresh(include_models=False, auto=True)
            self.assertIsNone(server._refresh_thread)
            self.assertEqual(skipped["consecutiveFailures"], 1)

            server.request_refresh(wait=True)  # manual refresh still runs
        self.assertEqual(calls, [True, True])
        self.assertEqual(server._consecutive_failures, 2)

    def test_success_clears_backoff(self) -> None:
        server._consecutive_failures = 3
        server._next_auto_refresh_at = server.time.monotonic() + 999
        with patch.object(server, "_do_refresh", return_value=None):
            payload = server.request_refresh(wait=True)
        self.assertEqual(payload["consecutiveFailures"], 0)
        self.assertIsNone(payload["retryInSeconds"])


class LocalRequestSecurityTests(unittest.TestCase):
    def test_accepts_loopback_host_and_same_origin(self) -> None:
        self.assertTrue(
            server.is_trusted_local_request(
                "127.0.0.1:8765", "http://127.0.0.1:8765"
            )
        )
        self.assertTrue(server.is_trusted_local_request("localhost:8765", None))
        self.assertTrue(
            server.is_trusted_local_request("[::1]:8765", "http://[::1]:8765")
        )

    def test_rejects_cross_origin_and_dns_rebinding_hosts(self) -> None:
        self.assertFalse(
            server.is_trusted_local_request(
                "127.0.0.1:8765", "https://attacker.example"
            )
        )
        self.assertFalse(
            server.is_trusted_local_request("attacker.example:8765", None)
        )
        self.assertFalse(server.is_trusted_local_request("", "null"))


if __name__ == "__main__":
    unittest.main()
