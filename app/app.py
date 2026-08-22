import json
import os
import re
import sqlite3
import time
from pathlib import Path

import requests
from flask import Flask, jsonify, request, send_from_directory

from core import DEFAULT_LAYOUT, computed_slots as build_slots, validate_layout

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
CONFIG_DIR = Path(os.environ.get("CONFIG_DIR", "/config"))
DB_PATH = DATA_DIR / "smart-storage.db"
LAYOUT_PATH = DATA_DIR / "layout.json"

PARTDB_INTERNAL_URL = os.environ.get("PARTDB_INTERNAL_URL", "http://partdb:80").rstrip("/")
PARTDB_PUBLIC_URL = os.environ.get("PARTDB_PUBLIC_URL", "http://partdb.local:8080").rstrip("/")
PARTDB_API_TOKEN = os.environ.get("PARTDB_API_TOKEN", "")
WLED_BASE_URL = os.environ.get("WLED_BASE_URL", "http://192.168.178.220").rstrip("/")

DEFAULT_COLORS = {
    "locate": [255, 185, 0],
    "assign": [0, 255, 120],
    "missing": [255, 0, 0],
    "test": [0, 140, 255],
}

app = Flask(__name__, static_folder="static")


def ensure_data():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not LAYOUT_PATH.exists():
        example = CONFIG_DIR / "example-layout.json"
        if example.exists():
            LAYOUT_PATH.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
        else:
            LAYOUT_PATH.write_text(json.dumps(DEFAULT_LAYOUT, indent=2), encoding="utf-8")
    with sqlite3.connect(DB_PATH) as con:
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


def auth_headers():
    headers = {"Accept": "application/json"}
    if PARTDB_API_TOKEN:
        headers["Authorization"] = f"Bearer {PARTDB_API_TOKEN}"
    return headers


def normalize(text):
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def partdb_search(query):
    if not query:
        return []
    candidates = []
    endpoints = [
        f"{PARTDB_INTERNAL_URL}/api/parts?name={requests.utils.quote(query)}",
        f"{PARTDB_INTERNAL_URL}/api/parts?filter={requests.utils.quote(query)}",
        f"{PARTDB_INTERNAL_URL}/de/parts/search?keyword={requests.utils.quote(query)}",
    ]
    for url in endpoints:
        try:
            response = requests.get(url, headers=auth_headers(), timeout=3)
            if response.status_code >= 400:
                continue
            payload = response.json() if "json" in response.headers.get("content-type", "") else {}
            raw_items = payload.get("hydra:member") or payload.get("items") or payload.get("data") or []
            for item in raw_items:
                part_id = item.get("id") or item.get("@id", "").rstrip("/").split("/")[-1]
                name = item.get("name") or item.get("full_name") or f"Teil {part_id}"
                candidates.append(
                    {
                        "id": str(part_id),
                        "name": name,
                        "description": item.get("description", ""),
                        "url": f"{PARTDB_PUBLIC_URL}/de/part/{part_id}",
                    }
                )
            if candidates:
                return candidates[:30]
        except Exception:
            continue
    return local_assignment_search(query)


def local_assignment_search(query):
    q = normalize(query)
    with sqlite3.connect(DB_PATH) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute("select part_id, part_name from assignments order by part_name").fetchall()
    return [
        {"id": row["part_id"], "name": row["part_name"], "description": "", "url": f"{PARTDB_PUBLIC_URL}/de/part/{row['part_id']}"}
        for row in rows
        if q in normalize(row["part_name"])
    ][:30]


def wled_state_for_slot(slot, color_name="locate"):
    color = DEFAULT_COLORS.get(color_name, DEFAULT_COLORS["locate"])
    return {
        "on": True,
        "bri": 220,
        "transition": 4,
        "seg": [
            {
                "id": 0,
                "start": slot["led_start"],
                "stop": slot["led_stop"],
                "on": True,
                "bri": 255,
                "col": [color, [0, 0, 0], [0, 0, 0]],
                "fx": 2 if color_name == "locate" else 0,
                "sx": 140,
                "ix": 180,
                "pal": 0,
            }
        ],
    }


def call_wled(payload):
    response = requests.post(f"{WLED_BASE_URL}/json/state", json=payload, timeout=2)
    response.raise_for_status()
    try:
        return response.json()
    except Exception:
        return {"ok": True}


def assignments():
    slots = {slot["id"]: slot for slot in computed_slots()}
    with sqlite3.connect(DB_PATH) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute("select * from assignments order by part_name").fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["slot"] = slots.get(row["slot_id"])
        item["partdb_url"] = f"{PARTDB_PUBLIC_URL}/de/part/{row['part_id']}"
        result.append(item)
    return result


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/api/health")
def health():
    partdb_ok = False
    wled_ok = False
    try:
        partdb_ok = requests.get(PARTDB_INTERNAL_URL, timeout=2).status_code < 500
    except Exception:
        pass
    try:
        wled_ok = requests.get(f"{WLED_BASE_URL}/json/info", timeout=2).status_code == 200
    except Exception:
        pass
    return jsonify({"ok": True, "partdb": partdb_ok, "wled": wled_ok})


@app.get("/api/layout")
def api_layout():
    layout = read_layout()
    return jsonify({"layout": layout, "slots": computed_slots(layout)})


@app.put("/api/layout")
def api_save_layout():
    payload = request.get_json(force=True)
    layout = payload.get("layout", payload)
    write_layout(layout)
    return jsonify({"saved": True, "slots": computed_slots(layout)})


@app.get("/api/assignments")
def api_assignments():
    return jsonify(assignments())


@app.post("/api/assignments")
def api_assign():
    data = request.get_json(force=True)
    part_id = str(data.get("part_id", "")).strip()
    part_name = str(data.get("part_name", "")).strip()
    slot_id = str(data.get("slot_id", "")).strip()
    notes = str(data.get("notes", "")).strip()
    slot = slot_by_id(slot_id)
    if not part_id or not part_name or not slot:
        return jsonify({"error": "Teil, Name und gueltiges Fach sind erforderlich."}), 400
    now = int(time.time())
    with sqlite3.connect(DB_PATH) as con:
        con.execute(
            """
            insert into assignments (part_id, part_name, slot_id, notes, created_at, updated_at)
            values (?, ?, ?, ?, ?, ?)
            on conflict(part_id) do update set
                part_name=excluded.part_name,
                slot_id=excluded.slot_id,
                notes=excluded.notes,
                updated_at=excluded.updated_at
            """,
            (part_id, part_name, slot["id"], notes, now, now),
        )
    call_wled(wled_state_for_slot(slot, "assign"))
    return jsonify({"saved": True, "slot": slot})


@app.delete("/api/assignments/<part_id>")
def api_delete_assignment(part_id):
    with sqlite3.connect(DB_PATH) as con:
        con.execute("delete from assignments where part_id=?", (part_id,))
    return jsonify({"deleted": True})


@app.get("/api/partdb/search")
def api_partdb_search():
    return jsonify(partdb_search(request.args.get("q", "").strip()))


@app.get("/api/find")
def api_find():
    query = request.args.get("q", "").strip()
    q = normalize(query)
    for item in assignments():
        hay = normalize(f"{item['part_name']} {item.get('notes', '')} {item.get('part_id', '')}")
        if q and q in hay:
            slot = item["slot"]
            call_wled(wled_state_for_slot(slot, "locate"))
            return jsonify({"found": True, "assignment": item})
    call_wled({"on": True, "bri": 180, "seg": [{"start": 0, "stop": 1, "col": [DEFAULT_COLORS["missing"]], "fx": 2}]})
    return jsonify({"found": False, "query": query}), 404


@app.post("/api/slots/<slot_id>/locate")
def api_locate_slot(slot_id):
    slot = slot_by_id(slot_id)
    if not slot:
        return jsonify({"error": "Fach nicht gefunden."}), 404
    data = request.get_json(silent=True) or {}
    result = call_wled(wled_state_for_slot(slot, data.get("mode", "locate")))
    return jsonify({"slot": slot, "wled": result})


@app.post("/api/wled/off")
def api_wled_off():
    return jsonify(call_wled({"on": False}))


ensure_data()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8090)
