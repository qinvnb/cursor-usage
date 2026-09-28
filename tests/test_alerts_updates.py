from __future__ import annotations

import unittest

from cursor_usage_app import alerts, updates

DAY = alerts.DAY_MS


def _summary(ond_used: float, ond_limit: float = 1000, inc_used: float = 0, inc_limit: float = 0, **extra) -> dict:
    return {
        "individualUsedCents": ond_used,
        "individualLimitCents": ond_limit,
        "includedUsedCents": inc_used,
        "includedLimitCents": inc_limit,
        "billingCycleStart": str(extra.get("start", 0)),
        "billingCycleEnd": str(extra.get("end", 30 * DAY)),
    }


class AlertTests(unittest.TestCase):
    def test_highest_threshold_only(self) -> None:
        keys = [a.key for a in alerts.evaluate(_summary(960), now_ms=29 * DAY)]
        self.assertIn("ond-95", keys)
        self.assertNotIn("ond-80", keys)

    def test_alerts_fire_once_per_cycle(self) -> None:
        to_send, state = alerts.pending_alerts(_summary(850), {}, now_ms=29 * DAY)
        self.assertEqual([a.key for a in to_send], ["ond-80"])
        again, state = alerts.pending_alerts(_summary(860), state, now_ms=29 * DAY)
        self.assertEqual(again, [])
        higher, state = alerts.pending_alerts(_summary(970), state, now_ms=29 * DAY)
        self.assertEqual([a.key for a in higher], ["ond-95"])

    def test_crossing_95_suppresses_later_80(self) -> None:
        _, state = alerts.pending_alerts(_summary(990), {}, now_ms=29 * DAY)
        self.assertIn("ond-80", state["sent"])

    def test_new_cycle_resets_state(self) -> None:
        _, state = alerts.pending_alerts(_summary(850), {}, now_ms=29 * DAY)
        next_cycle = _summary(850, start=30 * DAY, end=60 * DAY)
        to_send, _ = alerts.pending_alerts(next_cycle, state, now_ms=59 * DAY)
        self.assertEqual([a.key for a in to_send], ["ond-80"])

    def test_pace_alert_when_running_out_early(self) -> None:
        # 500 of 1000 used after 2 days -> ~2 days left at this pace, 28 in cycle.
        keys = [a.key for a in alerts.evaluate(_summary(500), now_ms=2 * DAY)]
        self.assertIn("ond-pace", keys)

    def test_no_pace_alert_when_on_track(self) -> None:
        keys = [a.key for a in alerts.evaluate(_summary(300), now_ms=15 * DAY)]
        self.assertEqual(keys, [])

    def test_included_bucket(self) -> None:
        keys = [a.key for a in alerts.evaluate(_summary(0, 0, inc_used=1900, inc_limit=2000), now_ms=DAY)]
        self.assertEqual(keys, ["inc-95"])


class VersionTests(unittest.TestCase):
    def test_parse_version(self) -> None:
        self.assertEqual(updates.parse_version("v1.2.3"), (1, 2, 3))
        self.assertGreater(updates.parse_version("1.10.0"), updates.parse_version("1.9.9"))
        self.assertEqual(updates.parse_version(""), (0,))


if __name__ == "__main__":
    unittest.main()
