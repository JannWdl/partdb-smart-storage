import json
import os
import re
import socket
import sqlite3
import threading
import time
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from urllib.parse import quote

import requests
import uvicorn
from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from core import DEFAULT_LAYOUT, computed_slots as build_slots, validate_layout
from zvt import ACK as ZVT_ACK, ALLOWED_COMMANDS as ZVT_ALLOWED_COMMANDS, Connection as ZvtConnection
from zvt import display_frame, parse_key as zvt_parse_key, validate_outbound

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
    "zvt_enabled": os.environ.get("ZVT_ENABLED", "true").lower() in ("1", "true", "yes", "on"),
    "zvt_host": os.environ.get("ZVT_HOST", "192.168.178.44"),
    "zvt_port": int(os.environ.get("ZVT_PORT", "20007")),
    "zvt_registration_command": os.environ.get("ZVT_REGISTRATION_COMMAND", "06 00"),
    "zvt_display_input_command": os.environ.get("ZVT_DISPLAY_INPUT_COMMAND", "06 E1"),
    "assistant_ai_enabled": os.environ.get("ASSISTANT_AI_ENABLED", "false").lower() in ("1", "true", "yes", "on"),
    "assistant_ai_url": os.environ.get("ASSISTANT_AI_URL", "").rstrip("/"),
    "assistant_ai_model": os.environ.get("ASSISTANT_AI_MODEL", "llama3.2:3b"),
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

@asynccontextmanager
async def lifespan(_app):
    if settings()["zvt_enabled"]:
        zvt_controller.start()
    try:
        yield
    finally:
        zvt_controller.stop()


app = FastAPI(title="Part-DB Smart Storage", version="0.2.0", lifespan=lifespan)
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
    result["zvt_enabled"] = bool(result["zvt_enabled"])
    result["zvt_host"] = str(result["zvt_host"] or "192.168.178.44").strip()
    result["zvt_port"] = int(result["zvt_port"] or 20007)
    result["assistant_ai_enabled"] = bool(result.get("assistant_ai_enabled"))
    result["assistant_ai_url"] = str(result.get("assistant_ai_url") or "").rstrip("/")
    result["assistant_ai_model"] = str(result.get("assistant_ai_model") or "llama3.2:3b")
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
            if key == "zvt_port":
                value = max(1, min(65535, int(value or 20007)))
            if key in ("barcode_enabled", "barcode_camera_enabled", "partdb_stock_write_enabled", "zvt_enabled", "assistant_ai_enabled"):
                value = bool(value)
            if key in ("zvt_host", "zvt_registration_command", "zvt_display_input_command", "assistant_ai_url", "assistant_ai_model"):
                value = str(value).strip()
            if key == "assistant_ai_url":
                value = str(value).strip().rstrip("/")
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
        return "Part-DB verweigert den API-Zugriff. Token-Scope und Benutzerrecht Miscellaneous/API in Part-DB prüfen."
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


def first_part_lot(part_id, *, part=None, timeout=12):
    candidates = []
    if part is None:
        part = partdb_get(f"/parts/{entity_id(part_id)}", timeout=timeout)
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
            candidates.extend(collection_items(partdb_get(query, timeout=timeout)))
        except Exception:
            continue
    for candidate in candidates:
        lot_path = candidate.get("@id") if isinstance(candidate, dict) else candidate
        if lot_path:
            lot = candidate if isinstance(candidate, dict) and "amount" in candidate else partdb_get(lot_path, timeout=timeout)
            lot_part = lot.get("part") if isinstance(lot, dict) else ""
            if isinstance(lot_part, dict):
                lot_part = lot_part.get("@id") or lot_part.get("id")
            if str(entity_id(lot_part)) in ("", str(entity_id(part_id))):
                return lot
    raise RuntimeError("Kein Part-DB-Lagerlos für dieses Teil gefunden.")


def lot_amount(lot):
    for key in ("amount", "instock", "instock_amount", "stock"):
        if isinstance(lot, dict) and lot.get(key) is not None:
            return float(lot[key])
    raise RuntimeError("Part-DB-Lagerlos enthält keinen lesbaren Bestand.")


def write_partdb_stock(part_id, action, quantity=1):
    cfg = settings()
    if not cfg["partdb_api_token"]:
        raise RuntimeError("Part-DB API-Token fehlt.")
    strategy = "part_lot_patch_direct"
    lot = first_part_lot(part_id)
    old_amount = lot_amount(lot)
    delta = float(quantity or 1) * (1 if action == "ADD" else -1)
    new_amount = old_amount + delta
    if new_amount < 0:
        raise RuntimeError("Nicht genug Bestand in Part-DB.")
    lot_path = lot.get("@id") or f"/part_lots/{entity_id(lot.get('id'))}"
    result = partdb_patch(lot_path, {"amount": new_amount})
    return {
        "strategy": strategy,
        "lot": lot_path,
        "old_amount": old_amount,
        "new_amount": new_amount,
        "result": result,
    }


def partdb_stock_error_message(exc, part_id=None, part_name=None):
    raw = str(exc)
    label = part_name or (f"Teil {entity_id(part_id)}" if part_id else "dieses Teil")
    if "Kein Part-DB-Lagerlos" in raw:
        return (
            f"Part-DB hat für {label} noch keinen Bestandseintrag. "
            "Öffne das Teil in Part-DB und lege einmal einen Bestand bzw. ein Lagerlos an. "
            "Danach kann Smart Storage per Sprache, Barcode, Telegram und ZVT buchen."
        )
    if "enthält keinen lesbaren Bestand" in raw:
        return (
            f"Der Bestand von {label} konnte in Part-DB nicht gelesen werden. "
            "Prüfe das Lagerlos bzw. den Bestandseintrag in Part-DB."
        )
    return f"Part-DB Buchung fehlgeschlagen: {raw}"


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


def wled_led_bounds():
    slots = computed_slots(read_layout())
    if not slots:
        return 0, 1
    return min(slot["led_start"] for slot in slots), max(slot["led_stop"] for slot in slots)


WLED_SHOWS = {
    "matrix": {"label": "Matrix", "fx": 27, "sx": 190, "ix": 210, "pal": 0, "colors": [[0, 255, 72], [0, 45, 14], [0, 0, 0]]},
    "rainbow": {"label": "Rainbow", "fx": 9, "sx": 150, "ix": 180, "pal": 11, "colors": [[255, 0, 80], [0, 255, 170], [255, 220, 0]]},
    "scanner": {"label": "Scanner", "fx": 12, "sx": 210, "ix": 180, "pal": 0, "colors": [[255, 0, 40], [0, 0, 0], [0, 0, 0]]},
    "sparkle": {"label": "Sparkle", "fx": 20, "sx": 170, "ix": 210, "pal": 7, "colors": [[255, 245, 170], [80, 200, 255], [255, 0, 160]]},
}


def wled_show_payload(show="matrix", brightness=180):
    start, stop = wled_led_bounds()
    config = WLED_SHOWS.get(show)
    if not config:
        raise ValueError("Unbekannter WLED-Effekt.")
    return {
        "on": True,
        "bri": max(1, min(255, int(brightness))),
        "transition": 0,
        "mainseg": 0,
        "seg": wled_clear_segments() + [{
            "id": 0,
            "start": start,
            "stop": stop,
            "on": True,
            "bri": max(1, min(255, int(brightness))),
            "col": config["colors"],
            "fx": config["fx"],
            "sx": config["sx"],
            "ix": config["ix"],
            "pal": config["pal"],
        }],
    }


def run_wled_slot_cycle(brightness=220, step_ms=120, repeats=1):
    zones = wled_zones("drawers")
    if not zones:
        raise RuntimeError("Keine Fächer im Layout gefunden.")
    step_seconds = max(40, min(1200, int(step_ms))) / 1000
    repeat_count = max(1, min(5, int(repeats)))
    sent = 0
    for _ in range(repeat_count):
        for index, zone in enumerate(zones):
            payload = wled_state_for_slot(zone, "locate")
            payload["bri"] = max(1, min(255, int(brightness)))
            segment = payload["seg"][-1]
            segment["bri"] = max(1, min(255, int(brightness)))
            segment["col"] = [ZONE_PALETTE[index % len(ZONE_PALETTE)], [0, 0, 0], [0, 0, 0]]
            call_wled(payload)
            sent += 1
            time.sleep(step_seconds)
    return {"ok": True, "mode": "cycle", "steps": sent, "slots": len(zones), "repeats": repeat_count}


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


def find_assignment_by_text(query):
    text = str(query or "").strip()
    if not text:
        return None
    normalized = normalize(text)
    exact_id = entity_id(text)
    for item in assignments():
        values = [
            item.get("partdb_part_id"),
            item.get("part_id"),
            item.get("drawer_id"),
            item.get("slot_id"),
            item.get("part_name"),
            item.get("notes"),
        ]
        if exact_id and any(str(value or "").strip() == exact_id for value in values[:4]):
            return item
        haystack = normalize(" ".join(str(value or "") for value in values))
        if normalized and normalized in haystack:
            return item
    return None


def direct_stock_action(action, term, quantity=1):
    action = str(action or "").upper()
    quantity = max(1, int(float(quantity or 1)))
    assignment = find_assignment_by_text(term)
    part_id = assignment["partdb_part_id"] if assignment else entity_id(term)
    part_name = assignment["part_name"] if assignment else f"Teil {part_id}"
    drawer_id = assignment["drawer_id"] if assignment else None
    slot = assignment.get("slot") if assignment else None
    if not part_id:
        record_stock_event("scan_error", None, None, drawer_id, quantity, action, "Kein Teil angegeben.", status="failed")
        return {"ok": False, "status": "failed", **feedback("error", "Kein Teil angegeben.", slot)}
    event_type = {"ADD": "add", "REMOVE": "remove", "WISHLIST": "wishlist"}[action]
    if action == "WISHLIST":
        message = "Nachkauf lokal markiert."
        record_stock_event(event_type, part_id, part_name, drawer_id, quantity, action, message, status="local")
        return {"ok": True, "status": "local", "event_type": event_type, "assignment": assignment, **feedback("wishlist", message, slot)}
    if not settings()["partdb_stock_write_enabled"]:
        message = "Testmodus: Bestand nicht in Part-DB geändert."
        record_stock_event(event_type, part_id, part_name, drawer_id, quantity, action, message, status="local")
        return {"ok": True, "status": "local", "event_type": event_type, "assignment": assignment, **feedback("success", message, slot)}
    try:
        partdb_result = write_partdb_stock(part_id, action, quantity)
    except Exception as exc:
        message = partdb_stock_error_message(exc, part_id, part_name)
        record_stock_event(event_type, part_id, part_name, drawer_id, quantity, action, message, status="failed", sync_error=str(exc))
        return {"ok": False, "status": "failed", "event_type": event_type, "assignment": assignment, **feedback("error", message, slot)}
    message = {
        "ADD": f"{quantity} Zugang in Part-DB gebucht.",
        "REMOVE": f"{quantity} Abgang in Part-DB gebucht.",
    }[action]
    record_stock_event(event_type, part_id, part_name, drawer_id, quantity, action, message, status="synced", partdb_result=partdb_result)
    return {"ok": True, "status": "synced", "event_type": event_type, "assignment": assignment, "partdb": partdb_result, **feedback("success", message, slot)}


def format_assignment_line(item):
    slot = item.get("slot") or {}
    location = slot.get("label") or item.get("drawer_id") or "kein Fach"
    return f"{item['part_name']} (Teil {item['partdb_part_id']}, {location})"


def telegram_help_text():
    return "\n".join([
        "Smart Storage Bot",
        "",
        "Befehle:",
        "/status - Dienste prüfen",
        "/suche <text> - Teile in Part-DB suchen",
        "/find <text> - Teil suchen und Fach leuchten lassen",
        "/fach <id> - Fach leuchten lassen",
        "/stock <teil-id> - Bestand auslesen",
        "/inventory - zugeordnete Teile anzeigen",
        "/add <teil-id oder name> [menge] - Bestand erhöhen",
        "/remove <teil-id oder name> [menge] - Bestand senken",
        "/assign <teil-id> <fach-id> <name> - Teil einem Fach zuordnen",
        "/wishlist <teil-id oder name> - Nachkauf markieren",
        "/off - WLED ausschalten",
        "/events - letzte Buchungen anzeigen",
        "/help - Hilfe anzeigen",
    ])


def split_telegram_command(text):
    cleaned = str(text or "").strip()
    if not cleaned:
        return "", ""
    parts = cleaned.split(maxsplit=1)
    command = parts[0].split("@", 1)[0].lower()
    args = parts[1].strip() if len(parts) > 1 else ""
    return command, args


def parse_term_and_quantity(args):
    text = str(args or "").strip()
    if not text:
        return "", 1
    parts = text.rsplit(maxsplit=1)
    if len(parts) == 2:
        try:
            quantity = max(1, int(float(parts[1].replace(",", "."))))
            return parts[0].strip(), quantity
        except ValueError:
            pass
    return text, 1


def telegram_stock_reply(part_id):
    normalized_id = entity_id(part_id)
    if not normalized_id:
        return {"ok": False, "reply": "Bitte Part-ID angeben, zum Beispiel /stock 42."}
    try:
        part = partdb_get(f"/parts/{normalized_id}", timeout=4)
        candidate = part_candidate(part) or {"id": normalized_id, "name": f"Teil {normalized_id}"}
        amount = lot_amount(first_part_lot(normalized_id, part=part, timeout=4))
    except Exception as exc:
        return {"ok": False, "reply": f"Bestand konnte nicht gelesen werden: {exc}"}
    assignment = find_assignment_by_part(normalized_id)
    drawer = format_assignment_line(assignment) if assignment else "kein Fach zugeordnet"
    return {"ok": True, "reply": f"{candidate['name']}\nTeil {normalized_id}\nBestand: {amount:g}\n{drawer}"}


def telegram_inventory_reply(limit=20):
    rows = assignments()[: max(1, min(50, int(limit or 20)))]
    if not rows:
        return {"ok": True, "reply": "Noch keine Teile zugeordnet."}
    lines = []
    for row in rows:
        amount = "?"
        try:
            part = partdb_get(f"/parts/{entity_id(row['partdb_part_id'])}", timeout=3)
            amount = f"{lot_amount(first_part_lot(row['partdb_part_id'], part=part, timeout=3)):g}"
        except Exception:
            pass
        slot = row.get("slot") or {}
        lines.append(f"{row['part_name']} · Bestand {amount} · {slot.get('label') or row['drawer_id']} · Teil {row['partdb_part_id']}")
    return {"ok": True, "reply": "Lagerliste:\n" + "\n".join(lines)}


def telegram_assign(args):
    parts = str(args or "").strip().split(maxsplit=2)
    if len(parts) < 3:
        return {"ok": False, "reply": "Bitte so angeben: /assign <teil-id> <fach-id> <name>"}
    try:
        result = api_assign({"part_id": parts[0], "drawer_id": parts[1], "part_name": parts[2], "notes": "Telegram / n8n"})
    except HTTPException as exc:
        return {"ok": False, "reply": f"Zuordnung fehlgeschlagen: {exc.detail}"}
    return {"ok": True, "reply": f"Zuordnung gespeichert: {result['slot']['label']} für {parts[2]}"}


def telegram_command(text):
    command, args = split_telegram_command(text)
    if command in ("", "/start", "/help", "help"):
        return {"ok": True, "reply": telegram_help_text()}
    if command == "/status":
        state = health()
        return {"ok": True, "reply": f"Smart Storage läuft.\nPart-DB: {'ok' if state['partdb'] else 'nicht erreichbar'}\nWLED: {'ok' if state['wled'] else 'nicht erreichbar'}"}
    if command in ("/suche", "/search", "/part"):
        if not args:
            return {"ok": False, "reply": "Bitte Suchtext angeben, zum Beispiel /suche 10k."}
        try:
            results = partdb_search(args)[:5]
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, str) else exc.detail.get("detail", exc.detail)
            return {"ok": False, "reply": f"Part-DB Suche fehlgeschlagen: {detail}"}
        if not results:
            return {"ok": True, "reply": f"Keine Teile für „{args}“ gefunden."}
        lines = [f"{part['id']}: {part['name']}" for part in results]
        return {"ok": True, "reply": "Gefundene Teile:\n" + "\n".join(lines)}
    if command in ("/find", "/leuchten", "/locate"):
        assignment = find_assignment_by_text(args)
        if not assignment or not assignment.get("slot"):
            feedback("error", "Keine Zuordnung gefunden.")
            return {"ok": False, "reply": f"Keine Zuordnung für „{args}“ gefunden."}
        call_wled(wled_state_for_slot(assignment["slot"], "locate"))
        return {"ok": True, "reply": f"Leuchtet: {format_assignment_line(assignment)}"}
    if command in ("/fach", "/drawer"):
        slot = slot_by_id(args)
        if not slot:
            return {"ok": False, "reply": f"Fach „{args}“ nicht gefunden."}
        call_wled(wled_state_for_slot(slot, "locate"))
        return {"ok": True, "reply": f"{slot['label']} leuchtet: LED {slot['led_start']}-{slot['led_stop'] - 1}."}
    if command in ("/stock", "/bestand"):
        return telegram_stock_reply(args)
    if command in ("/inventory", "/lager"):
        return telegram_inventory_reply()
    if command in ("/add", "/plus", "+"):
        term, quantity = parse_term_and_quantity(args)
        result = direct_stock_action("ADD", term, quantity)
        return {"ok": result["ok"], "reply": result["message"]}
    if command in ("/remove", "/minus", "-"):
        term, quantity = parse_term_and_quantity(args)
        result = direct_stock_action("REMOVE", term, quantity)
        return {"ok": result["ok"], "reply": result["message"]}
    if command in ("/wishlist", "/nachkauf"):
        term, quantity = parse_term_and_quantity(args)
        result = direct_stock_action("WISHLIST", term, quantity)
        return {"ok": result["ok"], "reply": result["message"]}
    if command in ("/assign", "/zuordnen"):
        return telegram_assign(args)
    if command == "/off":
        try:
            call_wled({"on": False})
        except Exception as exc:
            return {"ok": False, "reply": f"WLED konnte nicht ausgeschaltet werden: {exc}"}
        return {"ok": True, "reply": "Licht aus."}
    if command == "/events":
        events = api_stock_events(8)
        if not events:
            return {"ok": True, "reply": "Noch keine Buchungen vorhanden."}
        lines = []
        for event in events:
            sign = {"add": "+", "remove": "-", "wishlist": "Nachkauf", "scan_error": "Fehler"}.get(event["event_type"], event["event_type"])
            lines.append(f"{sign} {event['quantity']}x {event.get('part_name') or event.get('partdb_part_id') or 'unbekannt'} ({event['status']})")
        return {"ok": True, "reply": "Letzte Buchungen:\n" + "\n".join(lines)}
    return {"ok": False, "reply": f"Unbekannter Befehl: {command}\n\n{telegram_help_text()}"}


GERMAN_NUMBER_WORDS = {
    "ein": 1,
    "eine": 1,
    "einen": 1,
    "eins": 1,
    "zwei": 2,
    "drei": 3,
    "vier": 4,
    "fünf": 5,
    "fuenf": 5,
    "sechs": 6,
    "sieben": 7,
    "acht": 8,
    "neun": 9,
    "zehn": 10,
    "elf": 11,
    "zwölf": 12,
    "zwoelf": 12,
    "zwanzig": 20,
}


def voice_quantity(text):
    words = re.findall(r"[a-zäöüß0-9]+", str(text or "").lower())
    for word in words:
        if word.isdigit():
            return max(1, int(word))
        if word in GERMAN_NUMBER_WORDS:
            return GERMAN_NUMBER_WORDS[word]
    return 1


def voice_quantity_uses_digit(text):
    words = re.findall(r"[a-zäöüß0-9]+", str(text or "").lower())
    for word in words:
        if word.isdigit():
            return True
        if word in GERMAN_NUMBER_WORDS:
            return False
    return False


def voice_term(text, remove_digit_quantity=False):
    cleaned = str(text or "").strip()
    cleaned = re.sub(r"\b(bit­te|bitte|stück|stueck|teile|teil|bestand|lager|von|vom|den|der|die|das)\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(buche|buchen|einbuchen|einlagern|rein|raus|ausbuchen|entnehmen|senken|erhöhen|erhoehen|leuchten|zeige|zeig|finde|such|suche|nachkauf|wunschliste|markieren|markiere)\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(" + "|".join(map(re.escape, GERMAN_NUMBER_WORDS.keys())) + r")\b", " ", cleaned, flags=re.IGNORECASE)
    if remove_digit_quantity:
        cleaned = re.sub(r"\b\d+\b", " ", cleaned, count=1)
    return re.sub(r"\s+", " ", cleaned).strip()


def assistant_ai_interpret(text):
    cfg = settings()
    if not cfg["assistant_ai_enabled"] or not cfg["assistant_ai_url"]:
        return None
    system = (
        "Du bist der deutsche Sprachassistent für ein Kleinteilelager. "
        "Antworte ausschließlich als JSON mit den Feldern command und reply. "
        "command ist leer für Smalltalk oder eine dieser Aktionen: "
        "/status, /events, /off, /suche <text>, /find <text>, /stock <teil-id>, "
        "/inventory, /add <teil-id oder name> <menge>, /remove <teil-id oder name> <menge>, "
        "/wishlist <teil-id oder name>, /fach <fach-id>. "
        "Wenn der Benutzer Bestand ändern will, nutze /add oder /remove. "
        "Wenn er ein Fach sehen will, nutze /find oder /fach. "
        "Wenn Angaben fehlen, lasse command leer und stelle eine kurze Rückfrage in reply."
    )
    try:
        response = requests.post(
            f"{cfg['assistant_ai_url']}/api/chat",
            json={
                "model": cfg["assistant_ai_model"],
                "stream": False,
                "format": "json",
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": str(text or "")},
                ],
            },
            timeout=20,
        )
        response.raise_for_status()
        content = response.json().get("message", {}).get("content", "{}")
        parsed = json.loads(content)
        command = str(parsed.get("command") or "").strip()
        reply = str(parsed.get("reply") or "").strip()
        if command and not command.startswith("/"):
            command = ""
        return {"command": command, "reply": reply, "ai": True}
    except Exception as exc:
        return {"command": "", "reply": f"Lokale KI ist nicht erreichbar, nutze Regelmodus. ({exc})", "ai": False}


def voice_to_telegram_command(text):
    raw = str(text or "").strip()
    if not raw:
        return "/help"
    lower = raw.lower()
    if raw.startswith("/"):
        return raw
    if any(word in lower for word in ("licht aus", "led aus", "alles aus", "ausschalten")):
        return "/off"
    if any(word in lower for word in ("status", "gesundheit")):
        return "/status"
    if any(word in lower for word in ("letzte buch", "verlauf", "ereignis")):
        return "/events"
    quantity = voice_quantity(lower)
    if any(word in lower for word in ("buche", "buchen", "einlagern", "einbuchen", "rein", "erhöhe", "erhoehe", "plus", "zugang")):
        term = voice_term(raw, remove_digit_quantity=voice_quantity_uses_digit(lower))
        return f"/add {term} {quantity}".strip()
    if any(word in lower for word in ("entnehmen", "ausbuchen", "raus", "senke", "minus", "abgang")):
        term = voice_term(raw, remove_digit_quantity=voice_quantity_uses_digit(lower))
        return f"/remove {term} {quantity}".strip()
    if any(word in lower for word in ("bestand", "wie viel", "wieviel", "lagerstand")):
        term = voice_term(raw)
        return f"/stock {term}".strip()
    if any(word in lower for word in ("leuchte", "leuchten", "zeige", "zeig", "finde")):
        term = voice_term(raw)
        return f"/find {term}".strip()
    if any(word in lower for word in ("nachkauf", "wunschliste", "nachbestellen")):
        term = voice_term(raw)
        return f"/wishlist {term}".strip()
    if any(word in lower for word in ("suche", "such")):
        term = voice_term(raw)
        return f"/suche {term}".strip()
    return f"/suche {raw}"


@app.post("/api/voice/command")
def api_voice_command(data: dict = Body(...)):
    text = str(data.get("text") or "").strip()
    ai_result = assistant_ai_interpret(text)
    if ai_result and ai_result.get("ai") and not ai_result.get("command"):
        return {"ok": True, "reply": ai_result.get("reply") or "Ich bin bereit.", "command": "", "text": text, "ai": True}
    if ai_result and ai_result.get("command"):
        result = telegram_command(ai_result["command"])
        reply = result.get("reply") or ai_result.get("reply") or "Fertig."
        if ai_result.get("reply") and result.get("ok") is False:
            reply = f"{ai_result['reply']}\n{reply}"
        return {**result, "reply": reply, "command": ai_result["command"], "text": text, "ai": True}
    command = voice_to_telegram_command(text)
    result = telegram_command(command)
    if ai_result and ai_result.get("reply") and result.get("ok"):
        result["reply"] = f"{result['reply']}\n{ai_result['reply']}"
    return {**result, "command": command, "text": text, "ai": False}


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
        message = "Testmodus: Bestand nicht in Part-DB geändert."
        record_stock_event(event_type, part_id, session.get("part_name"), drawer_id, 1, code, message, status="local")
        return {"ok": True, "event_type": event_type, "session": save_session(session), "status": "local", **feedback("success", message, slot)}
    try:
        partdb_result = write_partdb_stock(part_id, action, 1)
    except Exception as exc:
        message = partdb_stock_error_message(exc, part_id, session.get("part_name"))
        record_stock_event(event_type, part_id, session.get("part_name"), drawer_id, 1, code, message, status="failed", sync_error=str(exc))
        return {"ok": False, "event_type": event_type, "session": session, "status": "failed", **feedback("error", message, slot)}
    message = {"ADD": "Zugang in Part-DB gebucht.", "REMOVE": "Abgang in Part-DB gebucht."}[action]
    record_stock_event(event_type, part_id, session.get("part_name"), drawer_id, 1, code, message, status="synced", partdb_result=partdb_result)
    return {"ok": True, "event_type": event_type, "session": save_session(session), "status": "synced", "partdb": partdb_result, **feedback("success", message, slot)}


def hex_bytes(value, fallback):
    text = str(value or "").strip()
    if not text:
        text = fallback
    try:
        data = bytes(int(part, 16) for part in re.split(r"[\s,;:]+", text) if part)
    except ValueError as exc:
        raise ValueError("Ungueltige ZVT-Kommando-Konfiguration.") from exc
    return data


def zvt_registration_frame(cfg=None):
    cfg = cfg or settings()
    frame = hex_bytes(cfg.get("zvt_registration_command"), "06 00")
    if frame != b"\x06\x00":
        raise ValueError("Nur ZVT Registration 06 00 ist für die Lagersteuerung erlaubt.")
    # Exact registration accepted by this CCV: password 000000, config 00, EUR.
    return bytes.fromhex("06 00 06 00 00 00 00 09 78")


def zvt_display_input_frame(lines, cfg=None):
    cfg = cfg or settings()
    command = hex_bytes(cfg.get("zvt_display_input_command"), "06 E1")
    if command != b"\x06\xe1":
        raise ValueError("Nur ZVT Display/Input 06 E1 ist für die Lagersteuerung erlaubt.")
    return display_frame(lines)


def zvt_text(value, width=22):
    text = " ".join(str(value).split())
    return text if len(text) <= width else text[:width - 3] + "..."


def zvt_amount(value):
    return "?" if value is None else f"{float(value):g}"


def zvt_selection(session):
    return (session.get("partdb_part_id"), session.get("drawer_id"))


def zvt_menu_lines(context=None):
    context = context or current_session()
    if not context.get("partdb_part_id"):
        return ["Smart Storage", "Teil scannen", "F1 Raus  F2 Rein", "F3 Info  F4 Licht"]
    stock = zvt_amount(context.get("amount"))
    drawer = context.get("drawer_label") or context.get("drawer_id") or "Fach fehlt"
    return [
        zvt_text(context.get("part_name") or f"Teil {context['partdb_part_id']}"),
        zvt_text(f"Best. {stock} / {drawer}"),
        "F1 Raus  F2 Rein",
        "F3 Info  F4 Licht",
    ]


def zvt_quantity_lines(action, quantity, context=None):
    context = context or current_session()
    label = "Raus" if action == "REMOVE" else "Rein"
    return [
        zvt_text(context.get("part_name") or context.get("partdb_part_id") or "Teil fehlt"),
        zvt_text(f"{label}: {quantity} / Best. {zvt_amount(context.get('amount'))}"),
        "F1 -1  F2 +1",
        "OK buchen  STOP zurueck",
    ]


def handle_stock_quantity(action, quantity, code="ZVT", expected_session=None):
    cfg = settings()
    session = current_session()
    if expected_session is not None and zvt_selection(session) != zvt_selection(expected_session):
        return {"ok": False, "status": "failed", "reason": "selection_changed", "session": session,
                "message": "Auswahl geaendert oder abgelaufen. Bitte neu scannen."}
    part_id = session.get("partdb_part_id")
    drawer_id = session.get("drawer_id")
    assignment = find_assignment_by_part(part_id) if part_id else None
    if assignment and not drawer_id:
        drawer_id = assignment["drawer_id"]
    slot = slot_by_id(drawer_id) if drawer_id else None
    quantity = max(1, int(quantity or 1))
    if not part_id or not drawer_id:
        record_stock_event("scan_error", part_id, session.get("part_name"), drawer_id, quantity, code, "Teil oder Fach fehlt.", status="failed")
        return {"ok": False, "session": session, **feedback("error", "Erst Teil und Fach scannen.")}
    event_type = "add" if action == "ADD" else "remove"
    if not cfg["partdb_stock_write_enabled"]:
        message = "Testmodus: Bestand nicht in Part-DB geändert."
        record_stock_event(event_type, part_id, session.get("part_name"), drawer_id, quantity, code, message, status="local")
        return {"ok": True, "event_type": event_type, "session": save_session(session), "status": "local", **feedback("success", message, slot)}
    try:
        partdb_result = write_partdb_stock(part_id, action, quantity)
    except Exception as exc:
        message = partdb_stock_error_message(exc, part_id, session.get("part_name"))
        record_stock_event(event_type, part_id, session.get("part_name"), drawer_id, quantity, code, message, status="failed", sync_error=str(exc))
        return {"ok": False, "event_type": event_type, "session": session, "status": "failed", **feedback("error", message, slot)}
    message = {
        "ADD": f"{quantity} Zugang in Part-DB gebucht.",
        "REMOVE": f"{quantity} Abgang in Part-DB gebucht.",
    }[action]
    record_stock_event(event_type, part_id, session.get("part_name"), drawer_id, quantity, code, message, status="synced", partdb_result=partdb_result)
    return {"ok": True, "event_type": event_type, "session": save_session(session), "status": "synced", "partdb": partdb_result, **feedback("success", message, slot)}


class ZvtStorageController:
    def __init__(self):
        self.thread = None
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.lifecycle_lock = threading.Lock()
        self.sock = None
        self.status = "stopped"
        self.last_error = None
        self.last_result = None
        self.mode = "menu"
        self.pending_action = None
        self.quantity = 1
        self.display_lines = None
        self.last_response = None
        self.last_key = None
        self.registered = False
        self.display_confirmed = False
        self.context = {}
        self.pending_context = None
        self.context_loaded_at = 0
        self.action_lock = threading.RLock()

    def snapshot(self):
        return {
            "enabled": settings()["zvt_enabled"],
            "status": self.status,
            "last_error": self.last_error,
            "last_result": self.last_result,
            "mode": self.mode,
            "pending_action": self.pending_action,
            "quantity": self.quantity,
            "host": settings()["zvt_host"],
            "port": settings()["zvt_port"],
            "registered": self.registered,
            "display_confirmed": self.display_confirmed,
            "last_response": self.last_response,
            "last_key": self.last_key,
            "input_mode": "function_keys",
            "display_lines": self.display_lines,
        }

    def start(self):
        with self.lifecycle_lock:
            if self.thread and self.thread.is_alive():
                return self.snapshot()
            self.stop_event.clear()
            self.status = "starting"
            self.last_error = None
            self.thread = threading.Thread(target=self.run, name="zvt-storage", daemon=True)
            self.thread.start()
        return self.snapshot()

    def stop(self):
        with self.lifecycle_lock:
            self.stop_event.set()
            with self.lock:
                self.status = "stopping"
                if self.sock:
                    try:
                        # Wake recv; only the owning worker closes the socket.
                        self.sock.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
            if self.thread:
                self.thread.join(timeout=10)
            if not self.thread or not self.thread.is_alive():
                self.status = "stopped"
                self.last_error = None
        return self.snapshot()

    def send_frame(self, frame):
        validate_outbound(frame)
        with self.lock:
            if not self.sock or self.stop_event.is_set():
                raise ConnectionError("ZVT ist nicht verbunden.")
            self.sock.sendall(frame)

    def show(self, lines):
        with self.lock:
            self.display_lines = [zvt_text(line) for line in lines[:4]]

    def load_context(self, force=False):
        session = current_session()
        if not force and zvt_selection(session) == zvt_selection(self.context) and time.monotonic() - self.context_loaded_at < 15:
            return self.context
        context = dict(session)
        slot = slot_by_id(session["drawer_id"]) if session.get("drawer_id") else None
        context["drawer_label"] = slot["label"] if slot else "Fach fehlt"
        context["amount"] = None
        if session.get("partdb_part_id"):
            try:
                part = partdb_get(f"/parts/{entity_id(session['partdb_part_id'])}", timeout=3)
                context["part_name"] = part.get("name") or session.get("part_name")
                context["amount"] = lot_amount(first_part_lot(session["partdb_part_id"], part=part, timeout=3))
            except Exception:
                context["stock_error"] = True
        self.context = context
        self.context_loaded_at = time.monotonic()
        return context

    def show_menu(self):
        with self.action_lock:
            self.mode = "menu"
            self.pending_action = None
            self.pending_context = None
            self.quantity = 1
            self.show(zvt_menu_lines(self.load_context()))

    def show_result(self, result, action, quantity, context):
        self.mode = "result"
        self.pending_action = None
        self.pending_context = None
        self.quantity = 1
        self.context_loaded_at = 0
        if not result.get("ok"):
            reason = result.get("message", "")
            if result.get("reason") == "selection_changed":
                lines = ["NICHT GEBUCHT", "Auswahl abgelaufen", "oder geaendert"]
            elif "Nicht genug Bestand" in reason:
                lines = ["NICHT GEBUCHT", "Bestand reicht nicht", zvt_text(context.get("part_name") or "Teil")]
            elif not context.get("partdb_part_id") or not context.get("drawer_id"):
                lines = ["NICHT GEBUCHT", "Teil oder Fach fehlt", "Bitte neu scannen"]
            else:
                lines = ["BUCHUNG FEHLGESCHLAGEN", "Part-DB pruefen", "Details im Web"]
        elif result.get("status") == "local":
            lines = ["TEST: NICHT GEBUCHT", zvt_text(context.get("part_name") or "Teil"), "Bestand unveraendert"]
        else:
            stock = result.get("partdb", {})
            change = f"Bestand: {zvt_amount(stock.get('old_amount'))} -> {zvt_amount(stock.get('new_amount'))}"
            label = "entnommen" if action == "REMOVE" else "eingelagert"
            lines = [zvt_text(context.get("part_name") or "Teil"), f"{quantity} {label}", change]
        self.show([*lines, "OK/STOP zurueck"])

    def observe_frame(self, direction, frame):
        if direction == "rx":
            self.last_response = frame.hex(" ").upper()[:256]

    def run_connection(self, sock, cfg):
        connection = ZvtConnection(sock, self.stop_event, self.observe_frame)
        self.status = "registering"
        connection.register(zvt_registration_frame(cfg))
        self.registered = True
        self.status = "waiting_for_input"
        self.show_menu()
        while not self.stop_event.is_set():
            with self.lock:
                lines = self.display_lines
            connection.send(zvt_display_input_frame(lines, cfg))
            deadline = time.monotonic() + 15
            while not self.stop_event.is_set():
                response = connection.receive(max(0, deadline - time.monotonic()))
                key = zvt_parse_key(response)
                if key is None:
                    if response == ZVT_ACK:
                        continue
                    raise RuntimeError(f"Unerwartete ZVT-Antwort: {response.hex(' ').upper()}")
                self.display_confirmed = True
                self.status = "ready"
                self.last_key = key
                if key == "TIMEOUT":
                    if self.mode == "menu":
                        self.show_menu()
                else:
                    self.apply_key(key)
                break

    def run(self):
        while not self.stop_event.is_set():
            cfg = settings()
            if not cfg["zvt_enabled"]:
                self.status = "disabled"
                self.stop_event.wait(2)
                continue
            try:
                with socket.create_connection((cfg["zvt_host"], int(cfg["zvt_port"])), timeout=5) as sock:
                    with self.lock:
                        self.sock = sock
                        self.last_error = None
                    self.run_connection(sock, cfg)
            except Exception as exc:
                if not self.stop_event.is_set():
                    self.status = "error"
                    self.last_error = str(exc)
            finally:
                with self.lock:
                    self.sock = None
                    self.registered = False
                    self.display_confirmed = False
            self.stop_event.wait(3)
        with self.lock:
            self.sock = None
            if self.status != "disabled":
                self.status = "stopped"

    def apply_key(self, key):
        with self.action_lock:
            return self._apply_key(key)

    def _apply_key(self, key):
        key = str(key).upper()
        if key in ("F1", "F2", "F3", "F4"):
            key = key[1:]
        if key == "CANCEL":
            self.show_menu()
            return {"ok": True, "mode": self.mode}
        if self.mode in ("result", "info"):
            if key == "OK":
                self.show_menu()
            return {"ok": True, "mode": self.mode}
        if self.mode == "quantity":
            if key in ("1", "-"):
                self.quantity = max(1, self.quantity - 1)
                self.show(zvt_quantity_lines(self.pending_action, self.quantity, self.pending_context))
            elif key in ("2", "+"):
                self.quantity = min(9999, self.quantity + 1)
                self.show(zvt_quantity_lines(self.pending_action, self.quantity, self.pending_context))
            elif key == "OK":
                action, quantity, context = self.pending_action, self.quantity, self.pending_context
                result = handle_stock_quantity(action, quantity, "ZVT", expected_session=context)
                self.last_result = result
                self.show_result(result, action, quantity, context)
                return result
            return {"ok": True, "mode": self.mode, "quantity": self.quantity}
        if key in ("1", "2"):
            context = self.context or self.load_context()
            if not context.get("partdb_part_id") or not context.get("drawer_id"):
                self.mode = "info"
                self.show(["Teil oder Fach fehlt", "Bitte zuerst scannen", "", "OK/STOP zurueck"])
                return {"ok": False, "mode": self.mode}
            self.mode = "quantity"
            self.pending_action = "REMOVE" if key == "1" else "ADD"
            self.pending_context = dict(context)
            self.quantity = 1
            self.show(zvt_quantity_lines(self.pending_action, self.quantity, self.pending_context))
        elif key == "3":
            context = self.load_context(force=True)
            self.mode = "info"
            self.show([
                context.get("part_name") or "Kein Teil gewaehlt",
                "Bestand nicht abrufbar" if context.get("stock_error") else f"Buchungsbestand: {zvt_amount(context.get('amount'))}",
                f"{context.get('drawer_label')} / #{context.get('partdb_part_id') or '-'}",
                "OK/STOP zurueck",
            ])
        elif key == "4":
            session = current_session()
            drawer_id = session.get("drawer_id")
            slot = slot_by_id(drawer_id) if drawer_id else None
            result = feedback("locate", "Fach leuchtet.", slot) if slot else feedback("error", "Kein Fach gewaehlt.")
            self.last_result = result
            self.mode = "info"
            self.show(["Fach leuchtet" if slot and not result.get("wled_error") else "Licht nicht verfuegbar", slot["label"] if slot else "Kein Fach gewaehlt", "", "OK/STOP zurueck"])
            return result
        elif key == "OK":
            self.show_menu()
        return {"ok": True, "mode": self.mode, "pending_action": self.pending_action, "quantity": self.quantity}


zvt_controller = ZvtStorageController()


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
        raise HTTPException(status_code=400, detail="Teil, Name und gültiges Fach sind erforderlich.")
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
        raise HTTPException(status_code=400, detail="Gültiger LED-Start und LED-Stop sind erforderlich.")
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


@app.get("/api/wled/effects")
def api_wled_effects():
    return {"effects": [{"id": key, "label": value["label"]} for key, value in WLED_SHOWS.items()]}


@app.post("/api/wled/effects/{effect_id}")
def api_wled_effect(effect_id: str, data: dict = Body(default={})):
    brightness = int(data.get("brightness", 180))
    try:
        payload = wled_show_payload(effect_id, brightness)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True, "effect": effect_id, "wled": call_wled(payload)}


@app.post("/api/wled/cycle")
def api_wled_cycle(data: dict = Body(default={})):
    return run_wled_slot_cycle(
        brightness=int(data.get("brightness", 220)),
        step_ms=int(data.get("step_ms", 120)),
        repeats=int(data.get("repeats", 1)),
    )


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
        return {"ok": True, "session": save_session(session), **feedback("locate", f"{slot['label']} gewählt: LED {slot['led_start']}-{slot['led_stop'] - 1}.", slot)}
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


@app.get("/api/zvt/status")
def api_zvt_status():
    return zvt_controller.snapshot()


@app.post("/api/zvt/start")
def api_zvt_start():
    return zvt_controller.start()


@app.post("/api/zvt/stop")
def api_zvt_stop():
    return zvt_controller.stop()


@app.post("/api/zvt/input")
def api_zvt_input(data: dict = Body(...)):
    key = str(data.get("key") or "").strip()
    if not key:
        raise HTTPException(status_code=400, detail="Taste fehlt.")
    return zvt_controller.apply_key(key)


@app.post("/api/telegram/command")
def api_telegram_command(data: dict = Body(...)):
    text = str(data.get("text") or "").strip()
    return telegram_command(text)


@app.exception_handler(requests.RequestException)
def requests_exception_handler(_request: Request, exc: requests.RequestException):
    return JSONResponse(status_code=502, content={"detail": str(exc)})


ensure_data()

if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=8090)
