import importlib.util
import os
import socket
import sqlite3
import sys
import tempfile
import threading
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
            "zvt_host": "192.168.178.44",
            "zvt_port": 20007,
            "zvt_enabled": True,
        })
        self.assertEqual(saved["wled_url"], "http://192.168.178.50")
        self.assertFalse(saved["barcode_enabled"])
        self.assertFalse(saved["partdb_stock_write_enabled"])
        self.assertEqual(saved["scan_timeout_seconds"], 12)
        self.assertEqual(saved["zvt_host"], "192.168.178.44")
        self.assertEqual(saved["zvt_port"], 20007)
        self.assertTrue(saved["zvt_enabled"])

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

    def test_stock_error_explains_missing_part_lot(self):
        backend = self.load_app_module()
        message = backend.partdb_stock_error_message(RuntimeError("Kein Part-DB-Lagerlos für dieses Teil gefunden."), "123", "Relais")
        self.assertIn("Relais", message)
        self.assertIn("Bestandseintrag", message)
        self.assertIn("Lagerlos", message)

    def test_voice_add_reports_missing_part_lot_clearly(self):
        backend = self.load_app_module()
        with patch.object(backend, "call_wled", return_value={"ok": True}):
            backend.api_assign({"part_id": "123", "part_name": "Relais", "drawer_id": "1"})
        with patch.object(backend, "call_wled", return_value={"ok": True}), patch.object(backend, "write_partdb_stock", side_effect=RuntimeError("Kein Part-DB-Lagerlos für dieses Teil gefunden.")):
            result = backend.api_voice_command({"text": "buche 3 von Relais"})
        self.assertFalse(result["ok"])
        self.assertIn("Bestandseintrag", result["reply"])
        self.assertIn("Relais", result["reply"])

    def test_zvt_frames_use_registration_and_display_input_only(self):
        backend = self.load_app_module()
        self.assertEqual(backend.zvt_registration_frame(), bytes.fromhex("06 00 06 00 00 00 00 09 78"))
        display = backend.zvt_display_input_frame(["1 Entnehmen", "2 Einlagern"])
        self.assertEqual(display[:2], b"\x06\xe1")
        for command in ("06 01", "06 93", "06 E1", "06 00 00 06 93 00", "invalid"):
            backend.save_settings({"zvt_registration_command": command})
            with self.assertRaises(ValueError):
                backend.zvt_registration_frame()
        backend.save_settings({"zvt_display_input_command": "06 22"})
        with self.assertRaises(ValueError):
            backend.zvt_display_input_frame(["Payment darf nicht raus"])

    def test_zvt_key_parser_only_accepts_complete_key_responses(self):
        backend = self.load_app_module()
        self.assertEqual(backend.zvt_parse_key(bytes.fromhex("80 00 01 31")), "1")
        self.assertEqual(backend.zvt_parse_key(bytes.fromhex("80 00 01 0D")), "OK")
        self.assertEqual(backend.zvt_parse_key(bytes.fromhex("80 00 01 1B")), "CANCEL")
        self.assertEqual(backend.zvt_parse_key(bytes.fromhex("80 00 01 6C")), "TIMEOUT")
        for response in (b"1", b"OK", b"\x80\x00\x01", bytes.fromhex("06 0F 0A 19 03 29 69 22 56 31 49 09 78")):
            self.assertIsNone(backend.zvt_parse_key(response))

    def test_zvt_display_matches_working_ccv_capture(self):
        self.load_app_module()
        from zvt import display_frame
        expected = bytes.fromhex("06 E1 20 F0 00 F1 F1 F0 4C 41 47 45 52 20 54 45 53 54 F2 F1 F4 54 61 73 74 65 20 64 72 75 65 63 6B 65 6E")
        self.assertEqual(display_frame(["LAGER TEST", "Taste druecken"], duration=0), expected)

    def test_zvt_stream_reassembles_fragmented_and_coalesced_responses(self):
        self.load_app_module()
        from zvt import Connection, ACK, frame, pop_frame, validate_outbound
        from unittest.mock import Mock
        sock = Mock()
        completion = bytes.fromhex("06 0F 0A 19 03 29 69 22 56 31 49 09 78")
        sock.recv.side_effect = [b"\x80", b"\x00\x00" + completion[:4], completion[4:] + bytes.fromhex("80 00 01 0D")]
        connection = Connection(sock, threading.Event())
        registration = bytes.fromhex("06 00 06 00 00 00 00 09 78")
        connection.register(registration)
        self.assertEqual([call.args[0] for call in sock.sendall.call_args_list], [registration, ACK])
        self.assertEqual(connection.receive(1), bytes.fromhex("80 00 01 0D"))
        long_frame = frame(b"\x06\xe1", b"a" * 300)
        self.assertEqual(long_frame[2:5], bytes.fromhex("FF 2C 01"))
        buffer = bytearray(long_frame + ACK)
        self.assertEqual(pop_frame(buffer), long_frame)
        self.assertEqual(pop_frame(buffer), ACK)
        for invalid in (b"\x06\x00", bytes.fromhex("06 93 00"), registration + bytes.fromhex("06 93 00")):
            with self.assertRaises(ValueError):
                validate_outbound(invalid)

    def test_zvt_rejected_registration_never_sends_display(self):
        backend = self.load_app_module()
        from unittest.mock import Mock
        sock = Mock()
        sock.recv.return_value = bytes.fromhex("84 9A 00")
        controller = backend.ZvtStorageController()
        with self.assertRaisesRegex(RuntimeError, "84 9A"):
            controller.run_connection(sock, backend.settings())
        self.assertFalse(controller.registered)
        self.assertEqual(sock.sendall.call_count, 1)

    def test_zvt_start_stop_restart_while_waiting_for_input(self):
        backend = self.load_app_module()
        controller = backend.ZvtStorageController()
        self.addCleanup(controller.stop)
        for _ in range(3):
            client, terminal = socket.socketpair()
            terminal.settimeout(3)
            with terminal, patch.object(backend.socket, "create_connection", return_value=client):
                controller.start()

                def receive(size):
                    result = b""
                    while len(result) < size:
                        chunk = terminal.recv(size - len(result))
                        if not chunk:
                            raise AssertionError("Unexpected EOF")
                        result += chunk
                    return result

                self.assertEqual(receive(9), bytes.fromhex("06 00 06 00 00 00 00 09 78"))
                self.assertEqual(controller.status, "registering")
                terminal.sendall(bytes.fromhex("80 00 00 06 0F 00"))
                self.assertEqual(receive(3), bytes.fromhex("80 00 00"))
                header = receive(3)
                self.assertEqual(header[:2], bytes.fromhex("06 E1"))
                self.assertIn(b"F1 Raus", receive(header[2]))
                self.assertTrue(controller.registered)
                self.assertFalse(controller.display_confirmed)
                # A timeout is a positive display response, not a stock action.
                terminal.sendall(bytes.fromhex("80 00 01 6C"))
                header = receive(3)
                receive(header[2])
                self.assertEqual(controller.status, "ready")
                controller.stop()
                self.assertFalse(controller.thread.is_alive())
                self.assertIsNone(controller.sock)
                self.assertIsNone(controller.last_error)
                self.assertEqual(controller.status, "stopped")

    def test_zvt_number_keys_book_quantity_through_partdb_flow(self):
        backend = self.load_app_module()
        backend.save_session({"partdb_part_id": "123", "part_name": "Teil 123", "drawer_id": "main-1-1"})
        controller = backend.ZvtStorageController()
        with (
            patch.object(backend, "partdb_get", return_value={"name": "Widerstand"}),
            patch.object(backend, "first_part_lot", return_value={"amount": 5}),
            patch.object(backend, "call_wled", return_value={"ok": True}),
            patch.object(backend, "write_partdb_stock", return_value={"old_amount": 5, "new_amount": 7}) as write_stock,
        ):
            controller.apply_key("2")
            controller.apply_key("2")
            result = controller.apply_key("OK")
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "synced")
        write_stock.assert_called_once_with("123", "ADD", 2)
        events = backend.api_stock_events(1)
        self.assertEqual(events[0]["quantity"], 2)
        self.assertEqual(events[0]["event_type"], "add")
        self.assertEqual(controller.display_lines, ["Widerstand", "2 eingelagert", "Bestand: 5 -> 7", "OK/STOP zurueck"])
        self.assertEqual(controller.mode, "result")

    def test_zvt_context_uses_partdb_name_stock_and_friendly_drawer_label(self):
        backend = self.load_app_module()
        backend.save_session({"partdb_part_id": "123", "part_name": "Alter Name", "drawer_id": "main-1-1"})
        controller = backend.ZvtStorageController()
        with (
            patch.object(backend, "partdb_get", return_value={"name": "Widerstand 10k"}) as get,
            patch.object(backend, "first_part_lot", return_value={"amount": 12.5}) as lot,
        ):
            controller.show_menu()
            controller.show_menu()
            self.assertEqual(get.call_count, 1)
            self.assertEqual(lot.call_count, 1)
            self.assertEqual(controller.display_lines[:2], ["Widerstand 10k", "Best. 12.5 / Fach 1"])
            controller.apply_key("F3")
            self.assertEqual(get.call_count, 2)
        self.assertEqual(controller.mode, "info")
        self.assertEqual(controller.display_lines[1], "Buchungsbestand: 12.5")

    def test_zvt_unavailable_stock_never_appears_as_zero(self):
        backend = self.load_app_module()
        backend.save_session({"partdb_part_id": "123", "part_name": "Widerstand", "drawer_id": "main-1-1"})
        controller = backend.ZvtStorageController()
        with patch.object(backend, "partdb_get", side_effect=RuntimeError("offline")):
            controller.show_menu()
            self.assertIn("Best. ?", controller.display_lines[1])
            controller.apply_key("F3")
            self.assertEqual(controller.display_lines[1], "Bestand nicht abrufbar")

    def test_zvt_selection_change_does_not_book_another_part(self):
        backend = self.load_app_module()
        backend.save_session({"partdb_part_id": "123", "part_name": "Erstes Teil", "drawer_id": "main-1-1"})
        controller = backend.ZvtStorageController()
        with (
            patch.object(backend, "partdb_get", return_value={"name": "Erstes Teil"}),
            patch.object(backend, "first_part_lot", return_value={"amount": 12}),
            patch.object(backend, "write_partdb_stock") as write,
        ):
            controller.show_menu()
            controller.apply_key("F1")
            backend.save_session({"partdb_part_id": "456", "part_name": "Zweites Teil", "drawer_id": "main-1-2"})
            controller.apply_key("F2")
            self.assertEqual(controller.display_lines[0], "Erstes Teil")
            result = controller.apply_key("OK")
        write.assert_not_called()
        self.assertFalse(result["ok"])
        self.assertEqual(controller.display_lines[0], "NICHT GEBUCHT")

    def test_zvt_test_mode_and_failed_booking_have_distinct_result_screens(self):
        for test_mode in (True, False):
            backend = self.load_app_module()
            backend.save_settings({"partdb_stock_write_enabled": not test_mode})
            backend.save_session({"partdb_part_id": "123", "part_name": "Widerstand", "drawer_id": "main-1-1"})
            controller = backend.ZvtStorageController()
            with (
                patch.object(backend, "partdb_get", return_value={"name": "Widerstand"}),
                patch.object(backend, "first_part_lot", return_value={"amount": 12}),
                patch.object(backend, "call_wled"),
                patch.object(backend, "write_partdb_stock", side_effect=RuntimeError("offline")) as write,
            ):
                controller.apply_key("F1")
                controller.apply_key("OK")
                if test_mode:
                    write.assert_not_called()
                    self.assertEqual(controller.display_lines[0], "TEST: NICHT GEBUCHT")
                else:
                    self.assertEqual(controller.display_lines[0], "BUCHUNG FEHLGESCHLAGEN")
                self.assertEqual(controller.mode, "result")
                controller.apply_key("F1")
                self.assertEqual(controller.mode, "result")

    def test_zvt_result_needs_acknowledgement_and_refreshes_stock(self):
        backend = self.load_app_module()
        backend.save_session({"partdb_part_id": "123", "part_name": "Widerstand", "drawer_id": "main-1-1"})
        controller = backend.ZvtStorageController()
        with (
            patch.object(backend, "partdb_get", return_value={"name": "Widerstand"}),
            patch.object(backend, "first_part_lot", side_effect=[{"amount": 12}, {"amount": 10}]),
            patch.object(backend, "call_wled"),
            patch.object(backend, "write_partdb_stock", return_value={"old_amount": 12, "new_amount": 10}) as write,
        ):
            controller.apply_key("F1")
            controller.apply_key("F2")
            controller.apply_key("OK")
            self.assertEqual(controller.display_lines[1:3], ["2 entnommen", "Bestand: 12 -> 10"])
            controller.apply_key("TIMEOUT")
            self.assertEqual(controller.mode, "result")
            controller.apply_key("OK")
            self.assertEqual(controller.mode, "menu")
            self.assertIn("Best. 10", controller.display_lines[1])
            write.assert_called_once_with("123", "REMOVE", 2)

    def test_zvt_lines_fit_four_line_display_and_zero_stock_is_visible(self):
        backend = self.load_app_module()
        context = {"partdb_part_id": "123", "part_name": "A" * 100, "drawer_label": "Fach " * 30, "amount": 0}
        controller = backend.ZvtStorageController()
        controller.show(backend.zvt_menu_lines(context))
        self.assertIn("Best. 0", controller.display_lines[1])
        self.assertTrue(controller.display_lines[0].endswith("..."))
        self.assertEqual(len(controller.display_lines), 4)
        self.assertTrue(all(len(line) <= 22 for line in controller.display_lines))

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

    def test_telegram_help_lists_stock_commands(self):
        backend = self.load_app_module()
        result = backend.api_telegram_command({"text": "/help"})
        self.assertTrue(result["ok"])
        self.assertIn("/add", result["reply"])
        self.assertIn("/find", result["reply"])

    def test_telegram_drawer_command_lights_slot(self):
        backend = self.load_app_module()
        with patch.object(backend, "call_wled", return_value={"ok": True}) as wled:
            result = backend.api_telegram_command({"text": "/fach 1"})
        self.assertTrue(result["ok"])
        self.assertIn("LED 0-3", result["reply"])
        payload = wled.call_args.args[0]
        self.assertEqual(payload["seg"][-1]["i"][0::2], [0, 1, 2, 3])

    def test_telegram_add_uses_assignment_and_quantity(self):
        backend = self.load_app_module()
        with patch.object(backend, "call_wled", return_value={"ok": True}):
            backend.api_assign({"part_id": "123", "part_name": "Widerstand 10k", "drawer_id": "1"})
        with patch.object(backend, "call_wled", return_value={"ok": True}), patch.object(backend, "write_partdb_stock", return_value={"old_amount": 1, "new_amount": 3}) as write_stock:
            result = backend.api_telegram_command({"text": "/add 123 2"})
        self.assertTrue(result["ok"])
        self.assertIn("2 Zugang", result["reply"])
        write_stock.assert_called_once_with("123", "ADD", 2)
        events = backend.api_stock_events(1)
        self.assertEqual(events[0]["quantity"], 2)
        self.assertEqual(events[0]["status"], "synced")

    def test_telegram_stock_reads_partdb_amount(self):
        backend = self.load_app_module()
        part = {"@id": "/api/parts/123", "name": "Widerstand 10k"}
        lot = {"@id": "/api/part_lots/7", "amount": 12, "part": "/api/parts/123"}
        with patch.object(backend, "partdb_get", return_value=part), patch.object(backend, "first_part_lot", return_value=lot):
            result = backend.api_telegram_command({"text": "/stock 123"})
        self.assertTrue(result["ok"])
        self.assertIn("Bestand: 12", result["reply"])
        self.assertIn("Widerstand 10k", result["reply"])

    def test_telegram_assign_maps_part_to_drawer(self):
        backend = self.load_app_module()
        with patch.object(backend, "call_wled", return_value={"ok": True}):
            result = backend.api_telegram_command({"text": "/assign 123 1 Widerstand 10k"})
        self.assertTrue(result["ok"])
        self.assertIn("Zuordnung gespeichert", result["reply"])
        assignment = backend.find_assignment_by_part("123")
        self.assertEqual(assignment["drawer_id"], "main-1-1")

    def test_telegram_off_turns_wled_off(self):
        backend = self.load_app_module()
        with patch.object(backend, "call_wled", return_value={"ok": True}) as wled:
            result = backend.api_telegram_command({"text": "/off"})
        self.assertTrue(result["ok"])
        wled.assert_called_once_with({"on": False})

    def test_voice_command_maps_german_stock_sentence(self):
        backend = self.load_app_module()
        self.assertEqual(backend.voice_to_telegram_command("Bestand von Teil 123"), "/stock 123")

    def test_voice_command_maps_german_add_sentence(self):
        backend = self.load_app_module()
        self.assertEqual(backend.voice_to_telegram_command("Buche fünf Stück von Teil 123 ein"), "/add 123 5")

    def test_voice_command_endpoint_uses_same_command_logic(self):
        backend = self.load_app_module()
        with patch.object(backend, "direct_stock_action", return_value={"ok": True, "message": "5 Zugang in Part-DB gebucht."}) as action:
            result = backend.api_voice_command({"text": "Buche 5 von Teil 123 ein"})
        self.assertTrue(result["ok"])
        self.assertEqual(result["command"], "/add 123 5")
        self.assertEqual(result["reply"], "5 Zugang in Part-DB gebucht.")
        action.assert_called_once_with("ADD", "123", 5)


if __name__ == "__main__":
    unittest.main()
