from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cursor_usage_app import store


class StoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.root_patch = patch.object(store, "app_root", return_value=self.root)
        self.root_patch.start()

    def tearDown(self) -> None:
        self.root_patch.stop()
        self.temporary.cleanup()

    def test_corrupt_usage_recovers_last_valid_backup(self) -> None:
        store.save_usage({"generation": 1})
        store.save_usage({"generation": 2})
        store.usage_path().write_text("{broken", encoding="utf-8")

        self.assertEqual(store.load_usage(), {"generation": 1})
        self.assertEqual(
            json.loads(store.usage_path().read_text(encoding="utf-8")),
            {"generation": 1},
        )

    def test_corrupt_settings_and_meta_recover_from_backup(self) -> None:
        store.save_settings({"ballEnabled": True})
        store.save_settings({"ballEnabled": False})
        store.settings_path().write_text("not-json", encoding="utf-8")
        self.assertTrue(store.load_settings()["ballEnabled"])

        store.save_usage({"generation": 1, "fetchedAt": "a"})
        store.save_usage({"generation": 2, "fetchedAt": "b"})
        store.meta_path().write_text("[invalid", encoding="utf-8")
        self.assertEqual(store.load_meta()["fetchedAt"], "a")

    def test_corrupt_primary_never_replaces_valid_backup(self) -> None:
        store.save_usage({"generation": 1})
        store.save_usage({"generation": 2})
        backup = store.usage_path().with_suffix(".json.bak")
        expected = backup.read_bytes()
        store.usage_path().write_text("{bad", encoding="utf-8")

        store.save_usage({"generation": 3})

        self.assertEqual(backup.read_bytes(), expected)
        self.assertEqual(store.load_usage(), {"generation": 3})

    def test_legacy_settings_are_migrated_and_persisted(self) -> None:
        legacy = {
            "floatingBallEnabled": 1,
            "dockWidgetEnabled": True,
            "refreshInterval": "30",
            "pollInterval": 8,
        }
        store.settings_path().parent.mkdir(parents=True, exist_ok=True)
        store.settings_path().write_text(json.dumps(legacy), encoding="utf-8")

        settings = store.load_settings()

        self.assertEqual(settings["schemaVersion"], store.SETTINGS_SCHEMA_VERSION)
        self.assertTrue(settings["ballEnabled"])
        self.assertTrue(settings["dockEnabled"])
        self.assertEqual(settings["refreshSeconds"], 30)
        self.assertEqual(settings["uiPollSeconds"], 8)
        persisted = json.loads(store.settings_path().read_text(encoding="utf-8"))
        self.assertNotIn("floatingBallEnabled", persisted)
        self.assertEqual(persisted["schemaVersion"], store.SETTINGS_SCHEMA_VERSION)

    def test_alert_settings_are_validated(self) -> None:
        settings = store.save_settings({"alertThresholds": [95, "70", 0, 101, 70, "x"], "onDemandBudget": "123.456"})
        self.assertEqual(settings["alertThresholds"], [70, 95])
        self.assertEqual(settings["onDemandBudget"], 123.46)
        settings = store.save_settings({"alertThresholds": [], "onDemandBudget": -5})
        self.assertEqual(settings["alertThresholds"], [80, 95])  # empty resets to the defaults
        self.assertEqual(settings["onDemandBudget"], 0.0)

    def test_export_file_only_allows_known_types(self) -> None:
        with patch.object(store, "reveal_in_explorer"):
            path = store.export_file("报告", "json", '{"a":1}')
            self.assertEqual(path.suffix, ".json")
            self.assertEqual(path.read_text(encoding="utf-8"), '{"a":1}')
            with self.assertRaises(ValueError):
                store.export_file("x", "exe", "")

    def test_new_install_enables_native_taskbar_only(self) -> None:
        settings = store.load_settings()
        self.assertTrue(settings["dockEnabled"])
        self.assertFalse(settings["ballEnabled"])
        self.assertTrue(settings["startHidden"])

    def test_existing_install_without_dock_switch_is_not_forced_on(self) -> None:
        store.settings_path().parent.mkdir(parents=True, exist_ok=True)
        store.settings_path().write_text(
            json.dumps({"schemaVersion": 2, "refreshSeconds": 60}),
            encoding="utf-8",
        )
        settings = store.load_settings()
        self.assertFalse(settings["dockEnabled"])
        self.assertNotIn("dockX", settings)
        self.assertNotIn("dockOpacity", settings)

    def test_legacy_data_migrates_without_overwriting_user_data(self) -> None:
        legacy = self.root / "legacy"
        target = self.root / "new-data"
        legacy.mkdir()
        target.mkdir()
        (legacy / "usage.json").write_text('{"source":"legacy"}', encoding="utf-8")
        (legacy / "settings.json").write_text('{"source":"legacy"}', encoding="utf-8")
        (target / "settings.json").write_text('{"source":"current"}', encoding="utf-8")

        with patch.object(store, "_legacy_data_dirs", return_value=[legacy]):
            store._migrate_legacy_data(target)

        self.assertEqual(
            json.loads((target / "usage.json").read_text(encoding="utf-8"))["source"],
            "legacy",
        )
        self.assertEqual(
            json.loads((target / "settings.json").read_text(encoding="utf-8"))["source"],
            "current",
        )
        self.assertFalse(legacy.exists())


if __name__ == "__main__":
    unittest.main()
