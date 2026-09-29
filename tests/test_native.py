from __future__ import annotations

import sys
import unittest

from PIL import Image

from cursor_usage_app.native import taskbar
from cursor_usage_app.native.win import LayeredBitmap


class TaskbarGeometryTests(unittest.TestCase):
    def test_chooses_left_free_area_before_centered_tasks(self) -> None:
        x = taskbar._first_free_x(
            left=0,
            right=1920,
            top=1020,
            bottom=1080,
            width=240,
            margin=10,
            occupied=[{"rect": (630, 1020, 1180, 1080)}, {"rect": (1520, 1020, 1920, 1080)}],
        )
        self.assertEqual(x, 10)

    def test_moves_after_left_aligned_controls(self) -> None:
        x = taskbar._first_free_x(
            left=0, right=1500, top=1020, bottom=1080, width=220, margin=10, occupied=[{"rect": (0, 1020, 700, 1080)}]
        )
        self.assertEqual(x, 710)

    def test_hides_when_no_safe_gap_exists(self) -> None:
        x = taskbar._first_free_x(
            left=0,
            right=500,
            top=0,
            bottom=60,
            width=240,
            margin=10,
            occupied=[{"rect": (0, 0, 230, 60)}, {"rect": (250, 0, 500, 60)}],
        )
        self.assertIsNone(x)

    @unittest.skipUnless(sys.platform == "win32", "Windows taskbar probe")
    def test_live_probe_uses_uia_and_never_mutates_explorer(self) -> None:
        result = taskbar.probe()
        if not result["taskbarHwnd"]:
            self.skipTest("Explorer taskbar is being rebuilt")
        if result.get("reason") == "uia-pending":
            self.skipTest("Explorer UI Automation is still responding")
        self.assertEqual(result["class"], "Shell_TrayWnd")
        self.assertTrue(result["windowsVersion"]["isWindows11"])
        self.assertTrue(result["uia"]["available"])


class TaskbarStateTests(unittest.TestCase):
    def tearDown(self) -> None:
        taskbar._LAST_STATUS = None

    def test_reads_widget_summary_and_full_report(self) -> None:
        flat = {"individualUsedCents": 120, "individualLimitCents": 500}
        self.assertEqual(taskbar._summary_from_report(flat), (120.0, 500.0))
        self.assertEqual(taskbar._summary_from_report({"summary": flat}), (120.0, 500.0))
        self.assertIsNone(taskbar._summary_from_report(None))

    def test_status_is_kept_in_memory_and_deduplicated(self) -> None:
        taskbar._LAST_STATUS = None
        taskbar._write_component_status({"state": "running", "reason": "ok"})
        first = taskbar.component_status()["updatedAt"]
        taskbar._write_component_status({"state": "running", "reason": "ok"})
        self.assertEqual(taskbar.component_status()["updatedAt"], first)
        taskbar._write_component_status({"reason": "fullscreen"})
        self.assertEqual(taskbar.component_status()["reason"], "fullscreen")
        self.assertEqual(taskbar.component_status()["state"], "running")


class LayeredBitmapTests(unittest.TestCase):
    def test_premultiplied_bottom_up_bgra(self) -> None:
        image = Image.new("RGBA", (2, 1))
        image.putpixel((0, 0), (200, 100, 50, 128))
        image.putpixel((1, 0), (10, 20, 30, 0))
        raw = LayeredBitmap(image).raw
        # Same truncating premultiply as Windows expects: c * a // 255, in BGRA order.
        self.assertEqual(list(raw[:4]), [50 * 128 // 255, 100 * 128 // 255, 200 * 128 // 255, 128])
        self.assertEqual(list(raw[4:]), [0, 0, 0, 0])


if __name__ == "__main__":
    unittest.main()
