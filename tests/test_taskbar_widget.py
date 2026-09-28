from __future__ import annotations

import sys
import unittest
from unittest.mock import patch

from cursor_usage_app import taskbar_widget


class TaskbarGeometryTests(unittest.TestCase):
    def test_chooses_left_free_area_before_centered_tasks(self) -> None:
        x = taskbar_widget._first_free_x(
            left=0,
            right=1920,
            top=1020,
            bottom=1080,
            width=240,
            margin=10,
            occupied=[
                {"rect": (630, 1020, 1180, 1080)},
                {"rect": (1520, 1020, 1920, 1080)},
            ],
        )
        self.assertEqual(x, 10)

    def test_moves_after_left_aligned_controls(self) -> None:
        x = taskbar_widget._first_free_x(
            left=0,
            right=1500,
            top=1020,
            bottom=1080,
            width=220,
            margin=10,
            occupied=[{"rect": (0, 1020, 700, 1080)}],
        )
        self.assertEqual(x, 710)

    def test_hides_when_no_safe_gap_exists(self) -> None:
        x = taskbar_widget._first_free_x(
            left=0,
            right=500,
            top=0,
            bottom=60,
            width=240,
            margin=10,
            occupied=[
                {"rect": (0, 0, 230, 60)},
                {"rect": (250, 0, 500, 60)},
            ],
        )
        self.assertIsNone(x)

    def test_reads_flat_widget_summary_and_full_report(self) -> None:
        flat = {"individualUsedCents": 120, "individualLimitCents": 500}
        self.assertEqual(taskbar_widget._summary_from_report(flat), (120.0, 500.0))
        report = {"summary": flat}
        self.assertEqual(taskbar_widget._summary_from_report(report), (120.0, 500.0))
        self.assertIsNone(taskbar_widget._summary_from_report(None))

    def test_status_writes_are_deduplicated(self) -> None:
        writes: list[dict] = []
        taskbar_widget._LAST_STATUS = None
        with patch.object(taskbar_widget, "_atomic_json", side_effect=lambda _p, payload: writes.append(payload)), patch.object(
            taskbar_widget, "_store_module"
        ) as store_module:
            store_module.return_value.data_dir.return_value = "."
            store_module.return_value.read_json.return_value = {}
            status = {"state": "running", "visible": True, "reason": "ok"}
            taskbar_widget._write_component_status(dict(status))
            taskbar_widget._write_component_status(dict(status))
            taskbar_widget._write_component_status({**status, "reason": "fullscreen"})
        taskbar_widget._LAST_STATUS = None
        self.assertEqual(len(writes), 2)

    @unittest.skipUnless(sys.platform == "win32", "Windows taskbar probe")
    def test_live_probe_uses_uia_and_never_mutates_explorer(self) -> None:
        result = taskbar_widget.probe()
        if not result["taskbarHwnd"]:
            self.skipTest("Explorer taskbar is being rebuilt")
        if result.get("reason") == "uia-pending":
            self.skipTest("Explorer UI Automation is still responding")
        self.assertEqual(result["class"], "Shell_TrayWnd")
        self.assertTrue(result["windowsVersion"]["isWindows11"])
        self.assertIn("uia", result)
        self.assertTrue(result["uia"]["available"])
        self.assertIn("canEmbed", result)


if __name__ == "__main__":
    unittest.main()
