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
            "partdb_stock_write_enabled": False,
            "scan_timeout_seconds": 12,
        })
        self.assertEqual(saved["wled_url"], "http://192.168.178.50")
        self.assertFalse(saved["barcode_enabled"])
        self.assertFalse(saved["partdb_stock_write_enabled"])
        self.assertEqual(saved["scan_timeout_seconds"], 12)

    def test_empty_token_does_not_overwrite_existing_token(self):
        backend = self.load_app_module()
        backend.save_settings({"partdb_api_token": "abc123"})
        saved = backend.save_settings({"partdb_api_token": ""})
        self.assertEqual(saved["partdb_api_token"], "abc123")
        self.assertTrue(saved["partdb_api_token_configured"])

    def test_partdb_search_uses_jsonld_and_wildcard_name_filter(self):
        backend = self.load_app_module()
        paths = backend.partdb_search_paths("BC547")
        self.assertEqual(paths[0], "/parts.jsonld?itemsPerPage=50&name=%25BC547%25")
        self.assertIn("/parts.jsonld?itemsPerPage=50&name=BC547", paths)

    def test_empty_partdb_search_loads_first_parts_page(self):
        backend = self.load_app_module()
        self.assertEqual(backend.partdb_search_paths(""), ["/parts.jsonld?itemsPerPage=50&order[name]=asc"])

    def test_partdb_candidate_accepts_jsonld_id(self):
        backend = self.load_app_module()
        candidate = backend.part_candidate({"@id": "/api/parts/123", "name": "Widerstand", "description": "10k"})
        self.assertEqual(candidate["id"], "123")
        self.assertEqual(candidate["name"], "Widerstand")
        self.assertTrue(candidate["url"].endswith("/de/part/123"))

    def test_partdb_permission_message_explains_forbidden_api_access(self):
        backend = self.load_app_module()
        message = backend.partdb_permission_message(403)
        self.assertIn("API-Zugriff", message)
        self.assertIn("Miscellaneous/API", message)

    def test_partdb_http_status_preserves_permission_errors(self):
        backend = self.load_app_module()
        self.assertEqual(backend.partdb_status_for_http(401), 401)
        self.assertEqual(backend.partdb_status_for_http(403), 403)
        self.assertEqual(backend.partdb_status_for_http(500), 502)

    def test_scan_code_normalizes_german_keyboard_colon(self):
        backend = self.load_app_module()
        self.assertEqual(backend.normalize_scan_code("PARTÖ123"), "PART:123")
        self.assertEqual(backend.normalize_scan_code("drawerömagazin-1"), "DRAWER:magazin-1")
        self.assertEqual(backend.normalize_scan_code(" add\n"), "ADD")

    def test_openapi_uses_plain_json_accept_header(self):
        backend = self.load_app_module()
        with patch.object(backend, "partdb_get", return_value={"paths": {"/api/part_lots": {"patch": {}}}}) as get:
            backend.partdb_openapi()
        self.assertEqual(get.call_args.kwargs["headers"]["Accept"], "application/json")

    def test_stock_strategy_allows_direct_write_when_openapi_is_unavailable(self):
        backend = self.load_app_module()
        backend.save_settings({"partdb_api_token": "abc123"})
        with patch.object(backend, "partdb_openapi", side_effect=RuntimeError("406")):
            result = backend.partdb_stock_strategy()
        self.assertTrue(result["ok"])
        self.assertEqual(result["strategy"], "part_lot_patch_unverified")

    def test_write_partdb_stock_does_not_require_openapi(self):
        backend = self.load_app_module()
        backend.save_settings({"partdb_api_token": "abc123"})
        lot = {"@id": "/api/part_lots/7", "amount": 4, "part": "/api/parts/123"}
        with (
            patch.object(backend, "partdb_stock_strategy", side_effect=AssertionError("OpenAPI strategy should not be used")),
            patch.object(backend, "first_part_lot", return_value=lot),
            patch.object(backend, "partdb_patch", return_value={"ok": True}) as patch_lot,
        ):
            result = backend.write_partdb_stock("123", "ADD", 2)
        self.assertEqual(result["strategy"], "part_lot_patch_direct")
        self.assertEqual(result["old_amount"], 4)
        self.assertEqual(result["new_amount"], 6)
        patch_lot.assert_called_once_with("/api/part_lots/7", {"amount": 6.0})

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

    def test_drawer_scan_lights_the_whole_slot_range(self):
        backend = self.load_app_module()
        with patch.object(backend, "call_wled", return_value={"ok": True}) as wled:
            result = backend.api_scan({"code": "DRAWER:1"})
        self.assertTrue(result["ok"])
        self.assertIn("LED 0-3", result["message"])
        payload = wled.call_args.args[0]
        segment = payload["seg"][-1]
        self.assertEqual(segment["start"], 0)
        self.assertEqual(segment["stop"], 4)
        self.assertEqual(segment["i"][0::2], [0, 1, 2, 3])

    def test_scan_action_can_run_in_local_test_mode(self):
        backend = self.load_app_module()
        backend.save_settings({"partdb_stock_write_enabled": False})
        backend.save_session({"partdb_part_id": "123", "part_name": "Teil 123", "drawer_id": "main-1-1"})
        with patch.object(backend, "call_wled", return_value={"ok": True}), patch.object(backend, "write_partdb_stock") as write_stock:
            result = backend.api_scan({"code": "ADD"})
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "local")
        write_stock.assert_not_called()

    def test_scan_action_records_synced_partdb_write(self):
        backend = self.load_app_module()
        backend.save_session({"partdb_part_id": "123", "part_name": "Teil 123", "drawer_id": "main-1-1"})
        with patch.object(backend, "call_wled", return_value={"ok": True}), patch.object(backend, "write_partdb_stock", return_value={"old_amount": 1, "new_amount": 2}):
            result = backend.api_scan({"code": "ADD"})
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "synced")
        events = backend.api_stock_events(1)
        self.assertEqual(events[0]["status"], "synced")

    def test_scan_action_writes_stock_when_openapi_is_unavailable(self):
        backend = self.load_app_module()
        backend.save_settings({"partdb_api_token": "abc123", "partdb_stock_write_enabled": True})
        backend.save_session({"partdb_part_id": "123", "part_name": "Teil 123", "drawer_id": "main-1-1"})
        lot = {"@id": "/api/part_lots/7", "amount": 1, "part": "/api/parts/123"}
        with (
            patch.object(backend, "call_wled", return_value={"ok": True}),
            patch.object(backend, "partdb_stock_strategy", side_effect=RuntimeError("OpenAPI-Dokument nicht gefunden: 406")),
            patch.object(backend, "first_part_lot", return_value=lot),
            patch.object(backend, "partdb_patch", return_value={"ok": True}),
        ):
            result = backend.api_scan({"code": "ADD"})
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "synced")
        self.assertEqual(result["partdb"]["strategy"], "part_lot_patch_direct")

    def test_scan_action_records_failed_partdb_write(self):
        backend = self.load_app_module()
        backend.save_session({"partdb_part_id": "123", "part_name": "Teil 123", "drawer_id": "main-1-1"})
        with patch.object(backend, "call_wled", return_value={"ok": True}), patch.object(backend, "write_partdb_stock", side_effect=RuntimeError("kein Token")):
            result = backend.api_scan({"code": "REMOVE"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "failed")
        events = backend.api_stock_events(1)
        self.assertEqual(events[0]["status"], "failed")
        self.assertIn("kein Token", events[0]["sync_error"])

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

    def test_wled_matrix_effect_uses_full_layout_bounds(self):
        backend = self.load_app_module()
        payload = backend.wled_show_payload("matrix", 200)
        active_segments = [segment for segment in payload["seg"] if segment.get("id") == 0]
        self.assertEqual(len(active_segments), 1)
        self.assertEqual(active_segments[0]["start"], 0)
        self.assertEqual(active_segments[0]["stop"], 96)
        self.assertEqual(active_segments[0]["col"][0], [0, 255, 72])
        self.assertEqual(payload["bri"], 200)

    def test_wled_slot_cycle_runs_every_drawer(self):
        backend = self.load_app_module()
        with (
            patch.object(backend, "call_wled", return_value={"ok": True}) as wled,
            patch.object(backend.time, "sleep"),
        ):
            result = backend.run_wled_slot_cycle(step_ms=40, repeats=1)
        self.assertEqual(result["steps"], 21)
        self.assertEqual(wled.call_count, 21)
        first_payload = wled.call_args_list[0].args[0]
        self.assertEqual(first_payload["seg"][-1]["start"], 0)
        self.assertEqual(first_payload["seg"][-1]["stop"], 4)


if __name__ == "__main__":
    unittest.main()
