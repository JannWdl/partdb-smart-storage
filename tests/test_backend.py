import importlib.util
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class BackendTests(unittest.TestCase):
    def load_app_module(self):
        root = Path(__file__).resolve().parents[1]
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        os.environ["DATA_DIR"] = str(Path(temp.name) / "data")
        os.environ["CONFIG_DIR"] = str(root / "config")
        sys.path.insert(0, str(root / "app"))
        spec = importlib.util.spec_from_file_location("smart_storage_backend", root / "app" / "app.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_settings_are_saved_in_sqlite(self):
        backend = self.load_app_module()
        saved = backend.save_settings({
            "wled_url": "http://192.168.178.50/",
            "barcode_enabled": False,
            "scan_timeout_seconds": 12,
        })
        self.assertEqual(saved["wled_url"], "http://192.168.178.50")
        self.assertFalse(saved["barcode_enabled"])
        self.assertEqual(saved["scan_timeout_seconds"], 12)

    def test_scan_session_expires(self):
        backend = self.load_app_module()
        backend.save_session({"partdb_part_id": "123", "part_name": "Teil 123", "drawer_id": "main-1-1"})
        con = sqlite3.connect(backend.DB_PATH)
        try:
            con.execute("update scan_sessions set expires_at=1 where id='default'")
            con.commit()
        finally:
            con.close()
        session = backend.current_session()
        self.assertIsNone(session["partdb_part_id"])
        self.assertEqual(session["expires_at"], 0)

    def test_scan_action_requires_part_and_drawer(self):
        backend = self.load_app_module()
        with patch.object(backend, "call_wled", return_value={"ok": True}):
            result = backend.api_scan({"code": "ADD"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["kind"], "error")

    def test_wled_zones_can_be_created_by_drawer_or_cabinet(self):
        backend = self.load_app_module()
        drawer_zones = backend.wled_zones("drawers")
        cabinet_zones = backend.wled_zones("cabinets")
        self.assertEqual(len(drawer_zones), 21)
        self.assertEqual(len(cabinet_zones), 2)
        self.assertEqual(drawer_zones[0]["led_start"], 0)
        self.assertEqual(cabinet_zones[0]["led_stop"], 80)

    def test_wled_preview_payload_uses_segments_for_small_layouts(self):
        backend = self.load_app_module()
        zones = backend.wled_zones("drawers")
        payload = backend.wled_preview_payload_for_zones(zones)
        active_segments = [segment for segment in payload["seg"] if segment.get("on")]
        self.assertEqual(len(active_segments), 21)
        self.assertNotIn("i", active_segments[0])
        self.assertEqual(active_segments[0]["start"], 0)
        self.assertEqual(active_segments[20]["stop"], 96)

    def test_wled_preview_payload_uses_pixels_for_large_layouts(self):
        backend = self.load_app_module()
        zones = [{"led_start": i, "led_stop": i + 1, "color": [255, 0, 0]} for i in range(40)]
        payload = backend.wled_preview_payload_for_zones(zones)
        active_segments = [segment for segment in payload["seg"] if segment.get("id") == 0]
        self.assertEqual(len(active_segments), 1)
        self.assertIn("i", active_segments[0])


if __name__ == "__main__":
    unittest.main()
