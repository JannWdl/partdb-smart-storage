from fastapi import Body

from app import (
    app,
    assignments,
    call_wled,
    db,
    entity_id,
    find_assignment_by_part,
    first_part_lot,
    lot_amount,
    normalize,
    part_candidate,
    partdb_get,
    partdb_search,
    record_stock_event,
    settings,
    slot_by_id,
    wled_state_for_slot,
    write_partdb_stock,
)


HELP_TEXT = """🤖 Smart Storage Bot

Befehle:
/bestand <Name oder ID> – aktuellen Bestand anzeigen
/plus <Name oder ID> [Menge] – einlagern
/minus <Name oder ID> [Menge] – entnehmen
/licht <Name oder ID> – Fach leuchten lassen
/suche <Text> – Teile suchen
/faecher – belegte Fächer anzeigen
/events – letzte Buchungen anzeigen
/aus – WLED ausschalten
/hilfe – diese Hilfe

Ohne /Befehl wird Text wie /bestand behandelt.
Beispiele:
/bestand M3 Schraube
/plus M3 Schraube 10
/minus 42 2
/licht Widerstand 10k"""


def _resolve_part(query: str):
    query = str(query or "").strip()
    if not query:
        raise ValueError("Teilname oder Part-DB-ID fehlt.")

    if query.isdigit():
        part = partdb_get(f"/parts/{entity_id(query)}")
        candidate = part_candidate(part)
        if candidate:
            return candidate
        return {"id": entity_id(query), "name": f"Teil {entity_id(query)}", "description": "", "url": ""}

    results = partdb_search(query)
    if not results:
        raise ValueError(f"Kein Teil für '{query}' gefunden.")

    nq = normalize(query)
    exact = [item for item in results if normalize(item.get("name", "")) == nq]
    return (exact or results)[0]


def _stock_snapshot(query: str):
    part = _resolve_part(query)
    part_id = str(part["id"])
    assignment = find_assignment_by_part(part_id)
    slot = assignment.get("slot") if assignment else None

    amount = None
    stock_error = None
    try:
        full_part = partdb_get(f"/parts/{entity_id(part_id)}")
        lot = first_part_lot(part_id, part=full_part)
        amount = lot_amount(lot)
    except Exception as exc:
        stock_error = str(exc)

    return {
        "part": part,
        "amount": amount,
        "stock_error": stock_error,
        "assignment": assignment,
        "slot": slot,
    }


def _format_amount(value):
    if value is None:
        return "?"
    number = float(value)
    return str(int(number)) if number.is_integer() else f"{number:g}"


def _stock_text(snapshot):
    part = snapshot["part"]
    slot = snapshot.get("slot")
    lines = [f"📦 {part['name']}", f"Bestand: {_format_amount(snapshot.get('amount'))}"]
    if slot:
        lines.append(f"Fach: {slot['label']} ({slot['id']})")
    else:
        lines.append("Fach: nicht zugeordnet")
    if snapshot.get("stock_error"):
        lines.append(f"⚠️ Bestand nicht lesbar: {snapshot['stock_error']}")
    return "\n".join(lines)


def _change_stock(query: str, action: str, quantity: int):
    action = str(action or "").upper()
    if action not in ("ADD", "REMOVE"):
        raise ValueError("Ungültige Buchungsart.")

    quantity = max(1, min(9999, int(quantity or 1)))
    part = _resolve_part(query)
    part_id = str(part["id"])
    assignment = find_assignment_by_part(part_id)
    drawer_id = assignment.get("drawer_id") if assignment else None
    slot = slot_by_id(drawer_id) if drawer_id else None
    event_type = "add" if action == "ADD" else "remove"

    cfg = settings()
    if not cfg["partdb_stock_write_enabled"]:
        message = "Testmodus: Bestand wurde nicht in Part-DB geändert."
        record_stock_event(event_type, part_id, part["name"], drawer_id, quantity, "TELEGRAM", message, status="local")
        if slot:
            try:
                call_wled(wled_state_for_slot(slot, "success"))
            except Exception:
                pass
        return {
            "ok": True,
            "status": "local",
            "part": part,
            "quantity": quantity,
            "text": f"🧪 {part['name']}\n{message}\nMenge: {quantity}",
        }

    try:
        result = write_partdb_stock(part_id, action, quantity)
    except Exception as exc:
        message = f"Part-DB Buchung fehlgeschlagen: {exc}"
        record_stock_event(
            event_type,
            part_id,
            part["name"],
            drawer_id,
            quantity,
            "TELEGRAM",
            message,
            status="failed",
            sync_error=str(exc),
        )
        raise RuntimeError(message) from exc

    message = f"{quantity} {'eingelagert' if action == 'ADD' else 'entnommen'}."
    record_stock_event(
        event_type,
        part_id,
        part["name"],
        drawer_id,
        quantity,
        "TELEGRAM",
        message,
        status="synced",
        partdb_result=result,
    )

    if slot:
        try:
            call_wled(wled_state_for_slot(slot, "success"))
        except Exception:
            pass

    arrow = "➕" if action == "ADD" else "➖"
    drawer_text = f"\nFach: {slot['label']}" if slot else ""
    text = (
        f"{arrow} {part['name']}\n"
        f"Menge: {quantity}\n"
        f"Bestand: {_format_amount(result.get('old_amount'))} → {_format_amount(result.get('new_amount'))}"
        f"{drawer_text}"
    )
    return {"ok": True, "status": "synced", "part": part, "quantity": quantity, "partdb": result, "text": text}


def _locate(query: str):
    query = str(query or "").strip()
    if not query:
        raise ValueError("Teilname oder Part-DB-ID fehlt.")

    nq = normalize(query)
    assignment = None
    for item in assignments():
        haystack = normalize(f"{item.get('part_name', '')} {item.get('notes', '')} {item.get('partdb_part_id', '')}")
        if nq and nq in haystack:
            assignment = item
            break

    if assignment is None:
        part = _resolve_part(query)
        assignment = find_assignment_by_part(str(part["id"]))

    if not assignment:
        raise ValueError("Für dieses Teil ist noch kein Fach zugeordnet.")

    slot = assignment.get("slot") or slot_by_id(assignment.get("drawer_id"))
    if not slot:
        raise ValueError("Das zugeordnete Fach existiert im aktuellen Layout nicht mehr.")

    call_wled(wled_state_for_slot(slot, "locate"))
    return {
        "ok": True,
        "assignment": assignment,
        "slot": slot,
        "text": f"💡 {assignment['part_name']}\nFach: {slot['label']}\nLED: {slot['led_start']}–{slot['led_stop'] - 1}",
    }


def _search_text(query: str):
    query = str(query or "").strip()
    if not query:
        raise ValueError("Suchtext fehlt.")
    results = partdb_search(query)[:10]
    if not results:
        return {"ok": True, "results": [], "text": f"🔎 Keine Treffer für '{query}'."}

    lines = [f"🔎 Treffer für '{query}':"]
    enriched = []
    for item in results:
        assignment = find_assignment_by_part(str(item["id"]))
        slot = assignment.get("slot") if assignment else None
        suffix = f" — {slot['label']}" if slot else ""
        lines.append(f"• {item['name']} [ID {item['id']}]{suffix}")
        enriched.append({**item, "slot": slot})
    return {"ok": True, "results": enriched, "text": "\n".join(lines)}


def _events_text(limit=10):
    limit = max(1, min(25, int(limit or 10)))
    with db() as con:
        rows = con.execute(
            "select * from stock_events order by created_at desc, id desc limit ?",
            (limit,),
        ).fetchall()
    events = [dict(row) for row in rows]
    if not events:
        return {"ok": True, "events": [], "text": "📜 Noch keine Buchungen vorhanden."}

    icons = {"add": "➕", "remove": "➖", "wishlist": "⭐", "scan_error": "⚠️"}
    lines = ["📜 Letzte Buchungen:"]
    for event in events:
        icon = icons.get(event.get("event_type"), "•")
        part_name = event.get("part_name") or event.get("partdb_part_id") or "Unbekannt"
        lines.append(f"{icon} {part_name}: {event.get('quantity', 1)} [{event.get('status', 'local')}]")
    return {"ok": True, "events": events, "text": "\n".join(lines)}


def _assignments_text(limit=30):
    items = assignments()[: max(1, min(50, int(limit or 30)))]
    if not items:
        return {"ok": True, "assignments": [], "text": "🗄️ Noch keine Fächer belegt."}

    lines = [f"🗄️ Belegte Fächer ({len(items)} angezeigt):"]
    for item in items:
        slot = item.get("slot")
        label = slot.get("label") if slot else item.get("drawer_id") or "?"
        lines.append(f"• {label}: {item['part_name']} [ID {item['partdb_part_id']}]")
    return {"ok": True, "assignments": items, "text": "\n".join(lines)}


@app.post("/api/telegram/action")
def api_telegram_action(data: dict = Body(default={})):
    action = str(data.get("action") or "help").strip().lower()
    query = str(data.get("query") or "").strip()
    quantity = int(data.get("quantity") or 1)

    try:
        if action in ("help", "start"):
            return {"ok": True, "text": HELP_TEXT}
        if action in ("stock", "bestand"):
            snapshot = _stock_snapshot(query)
            return {"ok": True, **snapshot, "text": _stock_text(snapshot)}
        if action in ("add", "plus", "einlagern"):
            return _change_stock(query, "ADD", quantity)
        if action in ("remove", "minus", "entnehmen"):
            return _change_stock(query, "REMOVE", quantity)
        if action in ("locate", "light", "licht", "leuchten"):
            return _locate(query)
        if action in ("search", "suche"):
            return _search_text(query)
        if action in ("events", "history", "verlauf"):
            return _events_text(data.get("limit", 10))
        if action in ("assignments", "drawers", "faecher", "fächer"):
            return _assignments_text(data.get("limit", 30))
        if action in ("off", "aus"):
            result = call_wled({"on": False})
            return {"ok": True, "wled": result, "text": "🌑 Lagerbeleuchtung ausgeschaltet."}
        return {"ok": False, "text": f"❓ Unbekannter Befehl: {action}\n\n{HELP_TEXT}"}
    except Exception as exc:
        return {"ok": False, "text": f"❌ {exc}"}
