import json
import os
import re
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote

import requests
import uvicorn
from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from core import DEFAULT_LAYOUT, computed_slots as build_slots, validate_layout

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
CONFIG_DIR = Path(os.environ.get("CONFIG_DIR", "/config"))
DB_PATH = DATA_DIR / "smart-storage.db"
LAYOUT_PATH = DATA_DIR / "layout.json"
STATIC_DIR = Path(__file__).parent / "static"

ENV_DEFAULTS = {
    "partdb_url": os.environ.get("PARTDB_PUBLIC_URL", "http://partdb.local:8080").rstrip("/"),
    "partdb_internal_url": os.environ.get("PARTDB_INTERNAL_URL", "http://partdb:80").rstrip("/"),
    "partdb_api_token": os.environ.get("PARTDB_API_TOKEN", ""),
    "wled_url": os.environ.get("WLED_BASE_URL", "http://192.168.178.220").rstrip("/"),
    "barcode_enabled": os.environ.get("BARCODE_ENABLED", "true").lower() in ("1", "true", "yes", "on"),
    "barcode_camera_enabled": os.environ.get("BARCODE_CAMERA_ENABLED", "true").lower() in ("1", "true", "yes", "on"),
    "partdb_stock_write_enabled": os.environ.get("PARTDB_STOCK_WRITE_ENABLED", "true").lower() in ("1", "true", "yes", "on"),
    "scan_timeout_seconds": int(os.environ.get("SCAN_TIMEOUT_SECONDS", "30")),
}

DEFAULT_COLORS = {
    "locate": [255, 185, 0],
    "assign": [0, 255, 120],
    "success": [0, 255, 120],
    "missing": [255, 0, 0],
    "error": [255, 0, 0],
    "wishlist": [0, 140, 255],
    "test": [0, 140, 255],
}

ZONE_PALETTE = [
    [255, 185, 0],
    [0, 180, 255],
    [0, 255, 120],
    [255, 0, 180],
    [255, 90, 0],
    [130, 90, 255],
    [255, 255, 90],
    [0, 255, 210],
]

app = FastAPI(title="Part-DB Smart Storage", version="0.2.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def add_column(con, table, name, definition):
    columns = {row[1] for row in con.execute(f"pragma table_info({table})").fetchall()}
    if name not in columns:
        con.execute(f"alter table {table} add column {name} {definition}")


def ensure_data():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not LAYOUT_PATH.exists():
        example = CONFIG_DIR / "example-layout.json"
        content = example.read_text(encoding="utf-8") if example.exists() else json.dumps(DEFAULT_LAYOUT, indent=2)
        LAYOUT_PATH.write_text(content, encoding="utf-8")
    con = sqlite3.connect(DB_PATH)
    try:
        con.execute(
            """
            create table if not exists assignments (
                id integer primary key autoincrement,
                part_id text not null,
                part_name text not null,
                slot_id text not null,
                notes text not null default '',
                created_at integer not null,
                updated_at integer not null,
                unique(part_id)
            )
            """
        )
        add_column(con, "assignments", "drawer_id", "text")
        add_column(con, "assignments", "partdb_part_id", "text")
        add_column(con, "assignments", "led_start", "integer")
        add_column(con, "assignments", "led_end", "integer")
        con.execute("update assignments set drawer_id=slot_id where drawer_id is null")
        con.execute("update assignments set partdb_part_id=part_id where partdb_part_id is null")
        con.execute(
            """
            create table if not exists settings (
                key text primary key,
                value text not null,
                updated_at integer not null
            )
            """
        )
        con.execute(
            """
            create table if not exists stock_events (
                id integer primary key autoincrement,
                event_type text not null,
                partdb_part_id text,
                part_name text,
                drawer_id text,
                quantity integer not null default 1,
                code text,
                message text not null default '',
                created_at integer not null
            )
            """
        )
        add_column(con, "stock_events", "status", "text not null default 'local'")
        add_column(con, "stock_events", "sync_error", "text")
        add_column(con, "stock_events", "partdb_result", "text")
        con.execute(
            """
            create table if not exists scan_sessions (
                id text primary key,
                partdb_part_id text,
                part_name text,
                drawer_id text,
                expires_at integer not null,
                updated_at integer not null
            )
            """
        )
        now = int(time.time())
        for key, value in ENV_DEFAULTS.items():
            con.execute(
                "insert or ignore into settings (key, value, updated_at) values (?, ?, ?)",
                (key, json.dumps(value), now),
            )
        con.commit()
    finally:
        con.close()


@contextmanager
def db():
    ensure_data()
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()


def read_layout():
    ensure_data()
    return json.loads(LAYOUT_PATH.read_text(encoding="utf-8"))


def write_layout(layout):
    validate_layout(layout)
    LAYOUT_PATH.write_text(json.dumps(layout, indent=2), encoding="utf-8")


def computed_slots(layout=None):
    return build_slots(layout or read_layout())


def slot_by_id(slot_id):
    for slot in computed_slots():
        if slot["id"] == slot_id or str(slot["global_index"]) == str(slot_id):
            return slot
    return None


def settings():
    with db() as con:
        values = {row["key"]: json.loads(row["value"]) for row in con.execute("select key, value from settings")}
    result = ENV_DEFAULTS.copy()
    result.update(values)
    for key in ("partdb_url", "partdb_internal_url", "wled_url"):
        result[key] = str(result[key]).rstrip("/")
    result["scan_timeout_seconds"] = int(result["scan_timeout_seconds"] or 30)
    result["barcode_enabled"] = bool(result["barcode_enabled"])
    result["barcode_camera_enabled"] = bool(result["barcode_camera_enabled"])
    result["partdb_stock_write_enabled"] = bool(result["partdb_stock_write_enabled"])
    result["partdb_api_token_configured"] = bool(result.get("partdb_api_token"))
    return result


def save_settings(payload):
    now = int(time.time())
    with db() as con:
        for key, value in payload.items():
            if key not in ENV_DEFAULTS:
                continue
            if key == "partdb_api_token" and not str(value or "").strip():
                continue
            if key in ("partdb_url", "partdb_internal_url", "wled_url"):
                value = str(value).strip().rstrip("/")
            if key == "partdb_api_token":
                value = str(value).strip()
            if key == "scan_timeout_seconds":
                value = max(5, min(300, int(value or 30)))
            if key in ("barcode_enabled", "barcode_camera_enabled", "partdb_stock_write_enabled"):
                value = bool(value)
            con.execute(
                """
                insert into settings (key, value, updated_at)
                values (?, ?, ?)
                on conflict(key) do update set value=excluded.value, updated_at=excluded.updated_at
                """,
                (key, json.dumps(value), now),
            )
    return settings()


def auth_headers():
    cfg = settings()
    headers = {"Accept": "application/ld+json, application/json"}
    if cfg["partdb_api_token"]:
        headers["Authorization"] = f"Bearer {cfg['partdb_api_token']}"
    return headers


def partdb_api_url(path):
    path = str(path or "").strip()
    if path.startswith("http://") or path.startswith("https://"):
        return path
    if not path.startswith("/"):
        path = "/" + path
    if path.startswith("/api/"):
        return f"{settings()['partdb_internal_url']}{path}"
    return f"{settings()['partdb_internal_url']}/api{path}"


def partdb_request(method, path, **kwargs):
    timeout = kwargs.pop("timeout", 12)
    attempts = kwargs.pop("attempts", 3)
    headers = kwargs.pop("headers", auth_headers())
    last_error = None
    for attempt in range(attempts):
        try:
            response = requests.request(method, partdb_api_url(path), headers=headers, timeout=timeout, **kwargs)
            if response.status_code in (502, 503, 504) and attempt + 1 < attempts:
                time.sleep(1 + attempt)
                continue
            return response
        except requests.RequestException as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(1 + attempt)
                continue
    raise RuntimeError(f"Part-DB antwortet nicht: {last_error}")


def partdb_permission_message(status_code):
    if status_code == 401:
        return "Part-DB API-Token fehlt, ist falsch oder abgelaufen."
    if status_code == 403:
        return "Part-DB verweigert den API-Zugriff. Token-Scope und Benutzerrecht Miscellaneous/API in Part-DB pruefen."
    return f"Part-DB HTTP {status_code}"


def partdb_status_for_http(status_code):
    if status_code in (401, 403):
        return status_code
    if status_code == 404:
        return 404
    return 502


def partdb_get(path, timeout=12, headers=None):
    response = partdb_request("GET", path, timeout=timeout, headers=headers or auth_headers())
    response.raise_for_status()
    return response.json()


def partdb_patch(path, payload):
    headers = auth_headers()
    headers["Content-Type"] = "application/merge-patch+json"
    response = partdb_request("PATCH", path, headers=headers, json=payload, timeout=12)
    response.raise_for_status()
    try:
        return response.json()
    except Exception:
        return {"ok": True}


def collection_items(payload):
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    return payload.get("hydra:member") or payload.get("member") or payload.get("items") or payload.get("data") or []


def entity_id(value):
    text = str(value or "").strip().rstrip("/")
    return text.split("/")[-1] if text else ""


def partdb_openapi():
    last_error = None
    headers = auth_headers()
    headers["Accept"] = "application/json"
    for path in ("/docs.jsonopenapi", "/docs.json"):
        try:
            docs = partdb_get(path, headers=headers)
            if isinstance(docs, dict) and docs.get("paths"):
                return docs
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f"OpenAPI-Dokument nicht gefunden: {last_error}")


def partdb_stock_strategy():
    cfg = settings()
    if not cfg["partdb_api_token"]:
        return {"ok": False, "message": "Part-DB API-Token fehlt."}
    try:
        docs = partdb_openapi()
    except Exception as exc:
        return {
            "ok": True,
            "strategy": "part_lot_patch_unverified",
            "message": f"Part-DB OpenAPI nicht verfügbar, Bestandsschreiben wird direkt versucht: {exc}",
        }
    paths = docs.get("paths", {}) if isinstance(docs, dict) else {}
    part_lot_patch = any("part_lots" in path and "patch" in {method.lower() for method in methods} for path, methods in paths.items() if isinstance(methods, dict))
    if not part_lot_patch:
        return {
            "ok": True,
            "strategy": "part_lot_patch_unverified",
            "message": "Part-DB OpenAPI nennt keinen Part-Lot-PATCH-Endpunkt, Bestandsschreiben wird direkt versucht.",
        }
    return {"ok": True, "strategy": "part_lot_patch", "message": "Part-DB Bestandsschreiben ist bereit."}


def first_part_lot(part_id):
    candidates = []
    part = partdb_get(f"/parts/{entity_id(part_id)}")
    for key in ("part_lots", "partLots", "lots", "part_lot"):
        value = part.get(key) if isinstance(part, dict) else None
        if isinstance(value, list):
            candidates.extend(value)
        elif value:
            candidates.append(value)
    for query in (
        f"/part_lots?part=/api/parts/{entity_id(part_id)}",
        f"/part_lots?part={entity_id(part_id)}",
        f"/part_lots?part.id={entity_id(part_id)}",
    ):
        try:
            candidates.extend(collection_items(partdb_get(query)))
        except Exception:
            continue
    for candidate in candidates:
        lot_path = candidate.get("@id") if isinstance(candidate, dict) else candidate
        if lot_path:
            lot = candidate if isinstance(candidate, dict) and "amount" in candidate else partdb_get(lot_path)
            lot_part = lot.get("part") if isinstance(lot, dict) else ""
            if isinstance(lot_part, dict):
                lot_part = lot_part.get("@id") or lot_part.get("id")
            if str(entity_id(lot_part)) in ("", str(entity_id(part_id))):
                return lot
    raise RuntimeError("Kein Part-DB-Lagerlos fuer dieses Teil gefunden.")


def lot_amount(lot):
    for key in ("amount", "instock", "instock_amount", "stock"):
        if isinstance(lot, dict) and lot.get(key) is not None:
            return float(lot[key])
    raise RuntimeError("Part-DB-Lagerlos enthaelt keinen lesbaren Bestand.")


def write_partdb_stock(part_id, action, quantity=1):
    strategy = partdb_stock_strategy()
    if not strategy["ok"]:
        raise RuntimeError(strategy["message"])
    lot = first_part_lot(part_id)
    old_amount = lot_amount(lot)
    delta = float(quantity or 1) * (1 if action == "ADD" else -1)
    new_amount = old_amount + delta
    if new_amount < 0:
        raise RuntimeError("Nicht genug Bestand in Part-DB.")
    lot_path = lot.get("@id") or f"/part_lots/{entity_id(lot.get('id'))}"
    result = partdb_patch(lot_path, {"amount": new_amount})
    return {
        "strategy": strategy["strategy"],
        "lot": lot_path,
        "old_amount": old_amount,
        "new_amount": new_amount,
        "result": result,
    }


def normalize(text):
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def normalize_scan_code(raw_code):
    code = re.sub(r"[\s]+", "", str(raw_code or "").strip())
    code = code.replace("：", ":").replace(";", ":").replace("Ö", ":").replace("ö", ":")
    upper = code.upper()
    for prefix in ("PART", "DRAWER"):
        if upper.startswith(prefix):
            rest = code[len(prefix):]
            if rest.startswith(":"):
                rest = rest[1:]
            return f"{prefix}:{rest}"
    if upper in ("ADD", "REMOVE", "WISHLIST", "CANCEL"):
        return upper
    return code


def part_url(part_id):
    return f"{settings()['partdb_url']}/de/part/{entity_id(part_id)}"


def partdb_search(query):
    candidates = []
    last_error = None
    last_status = None
    for path in partdb_search_paths(query):
        try:
            response = partdb_request("GET", path, timeout=12)
            if response.status_code >= 400:
                last_status = response.status_code
                last_error = partdb_permission_message(response.status_code)
                if response.status_code in (401, 403):
                    break
                continue
            payload = response.json() if "json" in response.headers.get("content-type", "") else {}
            for item in collection_items(payload):
                candidate = part_candidate(item)
                if candidate:
                    candidates.append(candidate)
            if candidates:
                return unique_parts(candidates)[:50]
        except Exception as exc:
            last_error = str(exc)
            last_status = 502
            continue
    local = local_assignment_search(query)
    if local:
        return local
    if last_error:
        raise HTTPException(status_code=partdb_status_for_http(last_status), detail=f"Part-DB Suche fehlgeschlagen: {last_error}")
    return []


def partdb_search_paths(query):
    text = str(query or "").strip()
    if not text:
        return ["/parts.jsonld?itemsPerPage=50&order[name]=asc"]
    exact = quote(text)
    wildcard = quote(f"%{text}%")
    return [
        f"/parts.jsonld?itemsPerPage=50&name={wildcard}",
        f"/parts.jsonld?itemsPerPage=50&name={exact}",
        f"/parts?itemsPerPage=50&name={wildcard}",
        f"/parts?itemsPerPage=50&name={exact}",
    ]


def part_candidate(item):
    if not isinstance(item, dict):
        return None
    part_id = item.get("id") or entity_id(item.get("@id"))
    if not part_id:
        return None
    name = item.get("name") or item.get("full_name") or item.get("fullName") or f"Teil {part_id}"
    if isinstance(name, dict):
        name = name.get("text") or name.get("value") or next(iter(name.values()), f"Teil {part_id}")
    description = item.get("description") or item.get("comment") or ""
    if isinstance(description, dict):
        description = description.get("text") or description.get("value") or ""
    return {"id": str(entity_id(part_id)), "name": str(name), "description": str(description), "url": part_url(part_id)}


def unique_parts(items):
    seen = set()
    result = []
    for item in items:
        if item["id"] in seen:
            continue
        seen.add(item["id"])
        result.append(item)
    return result


def local_assignment_search(query):
    q = normalize(query)
    with db() as con:
        rows = con.execute("select partdb_part_id, part_name from assignments order by part_name").fetchall()
    return [
        {"id": row["partdb_part_id"], "name": row["part_name"], "description": "", "url": part_url(row["partdb_part_id"])}
        for row in rows
        if q in normalize(row["part_name"])
    ][:30]


def wled_state_for_slot(slot, color_name="locate"):
    color = DEFAULT_COLORS.get(color_name, DEFAULT_COLORS["locate"])
    led_start = int(slot["led_start"])
    led_stop = int(slot["led_stop"])
    pixels = []
    for led in range(led_start, led_stop):
        pixels.extend([led, color])
    return {
        "on": True,
        "bri": 220,
        "transition": 0,
        "mainseg": 0,
        "seg": wled_clear_segments() + [{
            "id": 0,
            "start": 0,
            "stop": led_stop,
            "on": True,
            "bri": 255,
            "col": [color, [0, 0, 0], [0, 0, 0]],
            "fx": 0,
            "sx": 140,
            "ix": 180,
            "pal": 0,
            "i": pixels,
        }],
    }


def wled_clear_segments():
    return [{"id": segment_id, "stop": 0} for segment_id in range(1, 32)]


def wled_zones(mode="drawers"):
    layout = read_layout()
    slots = computed_slots(layout)
    zones = []
    if mode == "cabinets":
        for index, cabinet in enumerate(layout["cabinets"]):
            cabinet_slots = [slot for slot in slots if slot["cabinet_id"] == cabinet["id"]]
            if not cabinet_slots:
                continue
            start = min(slot["led_start"] for slot in cabinet_slots)
            stop = max(slot["led_stop"] for slot in cabinet_slots)
            zones.append({
                "id": cabinet["id"],
                "label": cabinet["name"],
                "type": "cabinet",
                "cabinet_id": cabinet["id"],
                "led_start": start,
                "led_stop": stop,
                "color": ZONE_PALETTE[index % len(ZONE_PALETTE)],
                "slots": len(cabinet_slots),
            })
        return zones
    for index, slot in enumerate(slots):
        zones.append({
            "id": slot["id"],
            "label": slot["label"],
            "type": "drawer",
            "cabinet_id": slot["cabinet_id"],
            "cabinet_name": slot["cabinet_name"],
            "row": slot["row"],
            "column": slot["column"],
            "led_start": slot["led_start"],
            "led_stop": slot["led_stop"],
            "color": ZONE_PALETTE[index % len(ZONE_PALETTE)],
            "slots": 1,
        })
    return zones


def wled_segments_for_zones(zones, brightness=180):
    return [{
        "id": index,
        "start": zone["led_start"],
        "stop": zone["led_stop"],
        "on": True,
        "bri": int(brightness),
        "col": [zone["color"], [0, 0, 0], [0, 0, 0]],
        "fx": 0,
        "sx": 128,
        "ix": 128,
        "pal": 0,
    } for index, zone in enumerate(zones)]


def wled_segment_payload_for_zones(zones, brightness=180):
    active_segments = wled_segments_for_zones(zones[:31], brightness)
    clear_segments = [{"id": segment_id, "stop": 0} for segment_id in range(len(active_segments), 32)]
    return {
        "on": True,
        "bri": max(1, min(255, int(brightness))),
        "transition": 0,
        "mainseg": 0,
        "seg": active_segments + clear_segments,
    }


def wled_pixel_payload_for_zones(zones, brightness=180):
    if not zones:
        return {"on": True, "bri": int(brightness), "seg": []}
    total_stop = max(zone["led_stop"] for zone in zones)
    pixels = []
    colors = {}
    for zone in zones:
        for led in range(zone["led_start"], zone["led_stop"]):
            colors[led] = zone["color"]
    for led in range(total_stop):
        pixels.extend([led, colors.get(led, [0, 0, 0])])
    return {
        "on": True,
        "bri": max(1, min(255, int(brightness))),
        "transition": 0,
        "mainseg": 0,
        "seg": wled_clear_segments() + [{
            "id": 0,
            "start": 0,
            "stop": total_stop,
            "on": True,
            "bri": max(1, min(255, int(brightness))),
            "fx": 0,
            "sx": 128,
            "ix": 128,
            "pal": 0,
            "i": pixels,
        }],
    }


def wled_preview_payload_for_zones(zones, brightness=180):
    if len(zones) <= 31:
        return wled_segment_payload_for_zones(zones, brightness)
    return wled_pixel_payload_for_zones(zones, brightness)


def call_wled(payload):
    response = requests.post(f"{settings()['wled_url']}/json/state", json=payload, timeout=2)
    response.raise_for_status()
    try:
        return response.json()
    except Exception:
        return {"ok": True}


def assignments():
    slots = {slot["id"]: slot for slot in computed_slots()}
    with db() as con:
        rows = con.execute("select * from assignments order by part_name").fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["part_id"] = item.get("part_id") or item.get("partdb_part_id")
        item["partdb_part_id"] = item.get("partdb_part_id") or item["part_id"]
        item["slot_id"] = item.get("slot_id") or item.get("drawer_id")
        item["drawer_id"] = item.get("drawer_id") or item["slot_id"]
        item["slot"] = slots.get(item["drawer_id"]) or slots.get(item["slot_id"])
        item["partdb_url"] = part_url(item["partdb_part_id"])
        result.append(item)
    return result


def record_stock_event(event_type, partdb_part_id=None, part_name=None, drawer_id=None, quantity=1, code=None, message="", status="local", sync_error=None, partdb_result=None):
    with db() as con:
        cursor = con.execute(
            """
            insert into stock_events
                (event_type, partdb_part_id, part_name, drawer_id, quantity, code, message, created_at, status, sync_error, partdb_result)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (event_type, partdb_part_id, part_name, drawer_id, int(quantity or 1), code, message, int(time.time()), status, sync_error, json.dumps(partdb_result) if partdb_result is not None else None),
        )
        return cursor.lastrowid


def current_session():
    now = int(time.time())
    with db() as con:
        row = con.execute("select * from scan_sessions where id='default'").fetchone()
        if not row or int(row["expires_at"]) < now:
            con.execute("delete from scan_sessions where id='default'")
            return {"partdb_part_id": None, "part_name": None, "drawer_id": None, "expires_at": 0}
        return dict(row)


def save_session(session):
    now = int(time.time())
    expires_at = now + settings()["scan_timeout_seconds"]
    with db() as con:
        con.execute(
            """
            insert into scan_sessions (id, partdb_part_id, part_name, drawer_id, expires_at, updated_at)
            values ('default', ?, ?, ?, ?, ?)
            on conflict(id) do update set
                partdb_part_id=excluded.partdb_part_id,
                part_name=excluded.part_name,
                drawer_id=excluded.drawer_id,
                expires_at=excluded.expires_at,
                updated_at=excluded.updated_at
            """,
            (session.get("partdb_part_id"), session.get("part_name"), session.get("drawer_id"), expires_at, now),
        )
    session["expires_at"] = expires_at
    return session


def clear_session():
    with db() as con:
        con.execute("delete from scan_sessions where id='default'")


def feedback(kind, message, slot=None):
    payload = {"kind": kind, "message": message, "audio": kind}
    try:
        if slot:
            call_wled(wled_state_for_slot(slot, kind))
        elif kind in ("success", "error", "wishlist"):
            call_wled({"on": True, "bri": 180, "seg": [{"start": 0, "stop": 1, "col": [DEFAULT_COLORS[kind]], "fx": 2}]})
    except Exception:
        payload["wled_error"] = True
    return payload


def find_assignment_by_part(part_id):
    for item in assignments():
        if str(item["partdb_part_id"]) == str(part_id):
            return item
    return None


def find_assignment_by_drawer(drawer_id):
    for item in assignments():
        if item["drawer_id"] == drawer_id or item["slot_id"] == drawer_id:
            return item
    return None


def handle_action(action, code):
    cfg = settings()
    session = current_session()
    part_id = session.get("partdb_part_id")
    drawer_id = session.get("drawer_id")
    assignment = find_assignment_by_part(part_id) if part_id else None
    if assignment and not drawer_id:
        drawer_id = assignment["drawer_id"]
    slot = slot_by_id(drawer_id) if drawer_id else None
    if not part_id or not drawer_id:
        record_stock_event("scan_error", part_id, session.get("part_name"), drawer_id, 1, code, "Teil oder Fach fehlt.", status="failed")
        return {"ok": False, "session": session, **feedback("error", "Erst Teil und Fach scannen.")}
    event_type = {"ADD": "add", "REMOVE": "remove", "WISHLIST": "wishlist"}[action]
    if action == "WISHLIST":
        message = "Wunschliste lokal markiert."
        record_stock_event(event_type, part_id, session.get("part_name"), drawer_id, 1, code, message, status="local")
        return {"ok": True, "event_type": event_type, "session": save_session(session), "status": "local", **feedback("wishlist", message, slot)}
    if not cfg["partdb_stock_write_enabled"]:
        message = "Testmodus: Bestand nicht in Part-DB geaendert."
        record_stock_event(event_type, part_id, session.get("part_name"), drawer_id, 1, code, message, status="local")
        return {"ok": True, "event_type": event_type, "session": save_session(session), "status": "local", **feedback("success", message, slot)}
    try:
        partdb_result = write_partdb_stock(part_id, action, 1)
    except Exception as exc:
        message = f"Part-DB Buchung fehlgeschlagen: {exc}"
        record_stock_event(event_type, part_id, session.get("part_name"), drawer_id, 1, code, message, status="failed", sync_error=str(exc))
        return {"ok": False, "event_type": event_type, "session": session, "status": "failed", **feedback("error", message, slot)}
    message = {"ADD": "Zugang in Part-DB gebucht.", "REMOVE": "Abgang in Part-DB gebucht."}[action]
    record_stock_event(event_type, part_id, session.get("part_name"), drawer_id, 1, code, message, status="synced", partdb_result=partdb_result)
    return {"ok": True, "event_type": event_type, "session": save_session(session), "status": "synced", "partdb": partdb_result, **feedback("success", message, slot)}


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health():
    cfg = settings()
    partdb_ok = False
    wled_ok = False
    try:
        partdb_ok = requests.get(cfg["partdb_internal_url"], timeout=2).status_code < 500
    except Exception:
        pass
    try:
        wled_ok = requests.get(f"{cfg['wled_url']}/json/info", timeout=2).status_code == 200
    except Exception:
        pass
    return {"ok": True, "partdb": partdb_ok, "wled": wled_ok}


@app.get("/api/settings")
def api_get_settings():
    return settings()


@app.put("/api/settings")
def api_save_settings(payload: dict = Body(...)):
    return save_settings(payload)


@app.get("/api/partdb/stock/test")
def api_partdb_stock_test():
    return partdb_stock_strategy()


@app.get("/api/layout")
def api_layout():
    layout = read_layout()
    return {"layout": layout, "slots": computed_slots(layout)}


@app.put("/api/layout")
def api_save_layout(payload: dict = Body(...)):
    layout = payload.get("layout", payload)
    write_layout(layout)
    return {"saved": True, "slots": computed_slots(layout)}


@app.get("/api/assignments")
def api_assignments():
    return assignments()


@app.post("/api/assignments")
def api_assign(data: dict = Body(...)):
    part_id = str(data.get("part_id") or data.get("partdb_part_id") or "").strip()
    part_name = str(data.get("part_name", "")).strip()
    drawer_id = str(data.get("drawer_id") or data.get("slot_id") or "").strip()
    notes = str(data.get("notes", "")).strip()
    slot = slot_by_id(drawer_id)
    if not part_id or not part_name or not slot:
        raise HTTPException(status_code=400, detail="Teil, Name und gueltiges Fach sind erforderlich.")
    now = int(time.time())
    with db() as con:
        con.execute(
            """
            insert into assignments
                (part_id, part_name, slot_id, notes, created_at, updated_at, drawer_id, partdb_part_id, led_start, led_end)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            on conflict(part_id) do update set
                part_name=excluded.part_name,
                slot_id=excluded.slot_id,
                notes=excluded.notes,
                updated_at=excluded.updated_at,
                drawer_id=excluded.drawer_id,
                partdb_part_id=excluded.partdb_part_id,
                led_start=excluded.led_start,
                led_end=excluded.led_end
            """,
            (part_id, part_name, slot["id"], notes, now, now, slot["id"], part_id, slot["led_start"], slot["led_stop"] - 1),
        )
    call_wled(wled_state_for_slot(slot, "assign"))
    return {"saved": True, "slot": slot}


@app.delete("/api/assignments/{part_id}")
def api_delete_assignment(part_id: str):
    with db() as con:
        con.execute("delete from assignments where part_id=? or partdb_part_id=?", (part_id, part_id))
    return {"deleted": True}


@app.get("/api/partdb/search")
def api_partdb_search(q: str = ""):
    return partdb_search(q.strip())


@app.get("/api/find")
def api_find(q: str = ""):
    query = q.strip()
    normalized = normalize(query)
    for item in assignments():
        hay = normalize(f"{item['part_name']} {item.get('notes', '')} {item.get('partdb_part_id', '')}")
        if normalized and normalized in hay:
            slot = item["slot"]
            call_wled(wled_state_for_slot(slot, "locate"))
            return {"found": True, "assignment": item}
    feedback("error", "Keine Zuordnung gefunden.")
    raise HTTPException(status_code=404, detail={"found": False, "query": query})


@app.post("/api/slots/{slot_id}/locate")
def api_locate_slot(slot_id: str, data: dict = Body(default={})):
    slot = slot_by_id(slot_id)
    if not slot:
        raise HTTPException(status_code=404, detail="Fach nicht gefunden.")
    result = call_wled(wled_state_for_slot(slot, data.get("mode", "locate")))
    return {"slot": slot, "wled": result}


@app.post("/api/wled/range")
def api_locate_range(data: dict = Body(...)):
    start = int(data.get("start", -1))
    stop = int(data.get("stop", -1))
    mode = data.get("mode", "test")
    if start < 0 or stop <= start:
        raise HTTPException(status_code=400, detail="Gueltiger LED-Start und LED-Stop sind erforderlich.")
    result = call_wled(wled_state_for_slot({"led_start": start, "led_stop": stop}, mode))
    return {"led_start": start, "led_stop": stop, "wled": result}


@app.post("/api/wled/test")
def api_wled_test(data: dict = Body(default={})):
    cfg = settings()
    url = str(data.get("wled_url") or cfg["wled_url"]).rstrip("/")
    response = requests.get(f"{url}/json/info", timeout=2)
    response.raise_for_status()
    return {"ok": True, "info": response.json()}


@app.get("/api/wled/zones")
def api_wled_zones(mode: str = "drawers"):
    if mode not in ("drawers", "cabinets"):
        raise HTTPException(status_code=400, detail="mode muss drawers oder cabinets sein.")
    zones = wled_zones(mode)
    return {"mode": mode, "zones": zones, "segments": wled_segments_for_zones(zones), "payload": wled_preview_payload_for_zones(zones)}


@app.post("/api/wled/apply-zones")
def api_wled_apply_zones(data: dict = Body(default={})):
    mode = data.get("mode", "drawers")
    brightness = int(data.get("brightness", 180))
    if mode not in ("drawers", "cabinets"):
        raise HTTPException(status_code=400, detail="mode muss drawers oder cabinets sein.")
    zones = wled_zones(mode)
    payload = wled_preview_payload_for_zones(zones, brightness)
    return {"ok": True, "mode": mode, "zones": zones, "wled": call_wled(payload)}


@app.post("/api/wled/off")
def api_wled_off():
    return call_wled({"on": False})


@app.post("/api/scan")
def api_scan(data: dict = Body(...)):
    cfg = settings()
    if not cfg["barcode_enabled"]:
        return {"ok": False, **feedback("error", "Barcode-Modul ist deaktiviert.")}
    code = normalize_scan_code(data.get("code", ""))
    upper = code.upper()
    session = current_session()
    if not code:
        return {"ok": False, "session": session, **feedback("error", "Leerer Barcode.")}
    if upper == "CANCEL":
        clear_session()
        return {"ok": True, "session": current_session(), **feedback("success", "Scan abgebrochen.")}
    if upper.startswith("PART:"):
        part_id = code.split(":", 1)[1].strip()
        assignment = find_assignment_by_part(part_id)
        session["partdb_part_id"] = part_id
        session["part_name"] = assignment["part_name"] if assignment else f"Teil {part_id}"
        if assignment:
            session["drawer_id"] = assignment["drawer_id"]
        return {"ok": True, "session": save_session(session), **feedback("success", f"Teil {session['part_name']} gewählt.")}
    if upper.startswith("DRAWER:"):
        drawer_id = code.split(":", 1)[1].strip()
        slot = slot_by_id(drawer_id)
        if not slot:
            record_stock_event("scan_error", session.get("partdb_part_id"), session.get("part_name"), drawer_id, 1, code, "Fach nicht gefunden.", status="failed")
            return {"ok": False, "session": session, **feedback("error", "Fach nicht gefunden.")}
        assignment = find_assignment_by_drawer(drawer_id)
        session["drawer_id"] = slot["id"]
        if assignment and not session.get("partdb_part_id"):
            session["partdb_part_id"] = assignment["partdb_part_id"]
            session["part_name"] = assignment["part_name"]
        return {"ok": True, "session": save_session(session), **feedback("locate", f"{slot['label']} gewaehlt: LED {slot['led_start']}-{slot['led_stop'] - 1}.", slot)}
    if upper in ("ADD", "REMOVE", "WISHLIST"):
        return handle_action(upper, code)
    record_stock_event("scan_error", session.get("partdb_part_id"), session.get("part_name"), session.get("drawer_id"), 1, code, "Unbekannter Barcode.", status="failed")
    return {"ok": False, "session": session, **feedback("error", f"Unbekannter Barcode: {code}")}


@app.get("/api/scan/session")
def api_scan_session():
    return {"session": current_session(), "settings": {"scan_timeout_seconds": settings()["scan_timeout_seconds"]}}


@app.post("/api/stock/add")
def api_stock_add(data: dict = Body(...)):
    session = {
        "partdb_part_id": str(data.get("partdb_part_id") or "").strip(),
        "part_name": str(data.get("part_name") or "").strip() or None,
        "drawer_id": str(data.get("drawer_id") or "").strip(),
    }
    save_session(session)
    return handle_action("ADD", "ADD")


@app.post("/api/stock/remove")
def api_stock_remove(data: dict = Body(...)):
    session = {
        "partdb_part_id": str(data.get("partdb_part_id") or "").strip(),
        "part_name": str(data.get("part_name") or "").strip() or None,
        "drawer_id": str(data.get("drawer_id") or "").strip(),
    }
    save_session(session)
    return handle_action("REMOVE", "REMOVE")


@app.get("/api/stock/events")
def api_stock_events(limit: int = 100):
    with db() as con:
        rows = con.execute("select * from stock_events order by created_at desc, id desc limit ?", (max(1, min(500, int(limit))),)).fetchall()
    return [dict(row) for row in rows]


@app.exception_handler(requests.RequestException)
def requests_exception_handler(_request: Request, exc: requests.RequestException):
    return JSONResponse(status_code=502, content={"detail": str(exc)})


ensure_data()

if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=8090)
