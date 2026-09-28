from __future__ import annotations

import io
import time
import unittest
import urllib.error
from unittest.mock import patch

from cursor_usage_app import usage


def _event(ts: int, cents: float = 1.0, model: str = "m") -> dict:
    return {"timestamp": str(ts), "kind": "USAGE_BASED", "model": model, "chargedCents": cents}


class EventCacheTests(unittest.TestCase):
    def test_incremental_refresh_replaces_overlap_window(self) -> None:
        hour = 3_600_000
        calls: list[int] = []
        server_events = [_event(10 * hour), _event(20 * hour), _event(29 * hour)]

        def fetcher(_token, _uid, start, _end):
            calls.append(int(start))
            return [e for e in server_events if int(e["timestamp"]) >= int(start)]

        cache = usage.UsageEventCache(fetcher)
        first = cache.events("t", 1, 0, 100 * hour)
        self.assertEqual(len(first), 3)

        # A late cost correction to a recent event and one brand-new event.
        server_events[2] = _event(29 * hour, cents=5.0)
        server_events.append(_event(30 * hour))
        second = cache.events("t", 1, 0, 100 * hour)

        self.assertEqual(calls, [0, 29 * hour - cache.OVERLAP_MS])
        self.assertEqual([int(e["timestamp"]) for e in second], [10 * hour, 20 * hour, 29 * hour, 30 * hour])
        self.assertEqual(second[2]["chargedCents"], 5.0)

    def test_cycle_change_forces_full_download(self) -> None:
        calls: list[int] = []

        def fetcher(_token, _uid, start, _end):
            calls.append(int(start))
            return [_event(int(start) + 1)]

        cache = usage.UsageEventCache(fetcher)
        cache.events("t", 1, 100, 1000)
        cache.events("t", 1, 5000, 9000)
        self.assertEqual(calls, [100, 5000])

    def test_events_are_slimmed(self) -> None:
        cache = usage.UsageEventCache(
            lambda *_: [{**_event(1), "tokenUsage": {"inputTokens": 3, "junk": 1}, "extra": "x"}]
        )
        event = cache.events("t", 1, 0, 10)[0]
        self.assertNotIn("extra", event)
        self.assertEqual(event["tokenUsage"], {"inputTokens": 3})


class HttpClientTests(unittest.TestCase):
    def _http_error(self, code: int) -> urllib.error.HTTPError:
        return urllib.error.HTTPError("https://x", code, "err", {}, io.BytesIO(b"busy"))

    def test_retries_transient_errors_then_succeeds(self) -> None:
        response = io.BytesIO(b'{"ok": true}')
        response.__enter__ = lambda self=response: self  # type: ignore[method-assign]
        response.__exit__ = lambda *a: None  # type: ignore[method-assign]
        side_effects = [self._http_error(503), response]
        with patch.object(usage.urllib.request, "urlopen", side_effect=side_effects), patch.object(
            usage.time, "sleep"
        ) as sleep:
            result = usage._open_json(usage.urllib.request.Request("https://x"), timeout=5, label="x")
        self.assertEqual(result, {"ok": True})
        sleep.assert_called_once()

    def test_client_errors_are_not_retried(self) -> None:
        with patch.object(usage.urllib.request, "urlopen", side_effect=[self._http_error(401)]) as opener:
            with self.assertRaises(usage.CursorApiError) as ctx:
                usage._open_json(usage.urllib.request.Request("https://x"), timeout=5, label="x")
        self.assertEqual(ctx.exception.status, 401)
        self.assertEqual(opener.call_count, 1)

    def test_deadline_bounds_timeouts(self) -> None:
        with usage.request_deadline(2.0):
            self.assertLessEqual(usage._timeout(30), 2.0)
        with usage.request_deadline(0.01):
            time.sleep(0.02)
            with self.assertRaises(usage.CursorApiError):
                usage._timeout(30)
        self.assertEqual(usage._timeout(30), 30)

    def test_expired_local_token_is_not_refreshed_without_persist(self) -> None:
        auth = {"cursorAuth/accessToken": "a.b.c", "cursorAuth/refreshToken": "r"}
        with patch.object(usage, "token_expired", return_value=True), patch.object(
            usage, "refresh_access_token"
        ) as refresh, patch.dict(usage.os.environ, {}, clear=False):
            usage.os.environ.pop("CURSOR_SESSION_TOKEN", None)
            usage.os.environ.pop("CURSOR_ACCESS_TOKEN", None)
            with self.assertRaises(usage.CursorApiError):
                usage.resolve_token(auth, usage.Path("unused"), persist=False)
        refresh.assert_not_called()


if __name__ == "__main__":
    unittest.main()
