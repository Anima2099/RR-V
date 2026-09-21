from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app import settings_backup


class FakeSettings:
    def __init__(self, values: dict[str, object]) -> None:
        self.values = dict(values)
        self.clear_count = 0
        self.sync_count = 0

    def allKeys(self) -> list[str]:
        return list(self.values)

    def value(self, key: str) -> object:
        return self.values.get(key)

    def clear(self) -> None:
        self.clear_count += 1
        self.values.clear()

    def setValue(self, key: str, value: object) -> None:
        self.values[key] = value

    def sync(self) -> None:
        self.sync_count += 1


class SettingsBackupSafetyTests(unittest.TestCase):
    def test_corrupt_encoded_value_is_rejected_before_current_settings_change(self) -> None:
        payload = {
            "format": settings_backup.BACKUP_FORMAT,
            "version": settings_backup.BACKUP_VERSION,
            "settings": {
                "window/geometry": {
                    "__type__": "QByteArray",
                    "base64": "%%%invalid-base64%%%",
                }
            },
        }
        current = FakeSettings({"window/sidebar_collapsed": True})

        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "corrupt.json"
            source.write_text(
                json.dumps(payload, ensure_ascii=False),
                encoding="utf-8",
            )
            with patch("app.settings_backup._settings", return_value=current):
                with self.assertRaises(Exception):
                    settings_backup.restore_backup(source)

        self.assertEqual(
            current.values,
            {"window/sidebar_collapsed": True},
        )
        self.assertEqual(current.clear_count, 0)

    def test_invalid_preset_payload_is_rejected_before_current_settings_change(self) -> None:
        payload = {
            "format": settings_backup.BACKUP_FORMAT,
            "version": settings_backup.BACKUP_VERSION,
            "settings": {"window/current_page": 2},
            "download_presets": {"broken": True},
        }
        current = FakeSettings({"window/current_page": 1})

        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "invalid-presets.json"
            source.write_text(
                json.dumps(payload, ensure_ascii=False),
                encoding="utf-8",
            )
            with (
                patch("app.settings_backup._settings", return_value=current),
                patch.object(
                    settings_backup.PresetLibrary,
                    "from_payload",
                    side_effect=ValueError("invalid preset payload"),
                ),
            ):
                with self.assertRaises(ValueError):
                    settings_backup.restore_backup(source)

        self.assertEqual(current.values, {"window/current_page": 1})
        self.assertEqual(current.clear_count, 0)

    def test_restore_rolls_back_settings_if_preset_apply_fails(self) -> None:
        current = FakeSettings(
            {
                "window/current_page": 1,
                "downloads/default_path": "D:/old",
            }
        )
        previous_presets = {"previous": "preset"}

        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "valid.json"
            source.write_text("{}", encoding="utf-8")

            with (
                patch("app.settings_backup._settings", return_value=current),
                patch(
                    "app.settings_backup._prepare_restore_payload",
                    return_value=(
                        {
                            "window/current_page": 3,
                            "downloads/default_path": "D:/new",
                        },
                        {"incoming": "preset"},
                    ),
                ),
                patch(
                    "app.settings_backup.export_preset_payload",
                    return_value=previous_presets,
                ),
                patch(
                    "app.settings_backup.import_preset_payload",
                    side_effect=[OSError("preset write failed"), object()],
                ) as import_presets,
            ):
                with self.assertRaises(OSError):
                    settings_backup.restore_backup(source)

        self.assertEqual(
            current.values,
            {
                "window/current_page": 1,
                "downloads/default_path": "D:/old",
            },
        )
        self.assertEqual(import_presets.call_count, 2)
        self.assertEqual(
            import_presets.call_args_list[1].args[0],
            previous_presets,
        )

    def test_backup_write_failure_keeps_existing_file_and_removes_temp(self) -> None:
        current = FakeSettings({"window/current_page": 1})

        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "RR-V_settings.json"
            destination.write_text("existing backup", encoding="utf-8")
            temp_path = destination.with_name(destination.name + ".tmp")

            with (
                patch("app.settings_backup._settings", return_value=current),
                patch(
                    "app.settings_backup.export_preset_payload",
                    return_value={"placeholder": True},
                ),
                patch(
                    "app.settings_backup._prepare_restore_payload",
                    return_value=({}, None),
                ),
                patch(
                    "app.settings_backup.os.replace",
                    side_effect=OSError("replace failed"),
                ),
            ):
                with self.assertRaises(OSError):
                    settings_backup.create_backup(destination)

            self.assertEqual(
                destination.read_text(encoding="utf-8"),
                "existing backup",
            )
            self.assertFalse(temp_path.exists())


if __name__ == "__main__":
    unittest.main()
