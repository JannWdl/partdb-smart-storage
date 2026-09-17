import uvicorn
from fastapi import Body, HTTPException

from app import (
    app,
    assignments,
    entity_id,
    find_assignment_by_part,
    first_part_lot,
    handle_stock_quantity,
    lot_amount,
    part_candidate,
    part_url,
    partdb_get,
    save_session,
)


def part_summary(part_id: str):
    normalized_id = entity_id(part_id)
    if not normalized_id:
        raise HTTPException(status_code=400, detail="Part-ID fehlt.")

    try:
        part = partdb_get(f"/parts/{normalized_id}", timeout=4)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Part-DB Teil konnte nicht geladen werden: {exc}") from exc

    candidate = part_candidate(part) or {
        "id": normalized_id,
        "name": f"Teil {normalized_id}",
        "description": "",
        "url": part_url(normalized_id),
    }
    assignment = find_assignment_by_part(normalized_id)

    amount = None
    stock_error = None
    try:
        amount = lot_amount(first_part_lot(normalized_id, part=part, timeout=4))
    except Exception as exc:
        stock_error = str(exc)

    return {
        "id": normalized_id,
        "name": candidate["name"],
        "description": candidate.get("description", ""),
        "url": candidate.get("url") or part_url(normalized_id),
        "amount": amount,
        "stock_error": stock_error,
        "assignment": assignment,
    }


@app.get("/api/parts/{part_id}/summary")
def api_part_summary(part_id: str):
    """Return the current Part-DB stock together with the Smart Storage drawer mapping."""
    return part_summary(part_id)


@app.get("/api/inventory")
def api_inventory(limit: int = 50):
    """Return mapped Smart Storage parts enriched with their current Part-DB stock."""
    rows = assignments()[: max(1, min(200, int(limit)))]
    result = []

    for row in rows:
        part_id = str(row.get("partdb_part_id") or row.get("part_id") or "").strip()
        item = {
            "id": part_id,
            "name": row.get("part_name") or f"Teil {part_id}",
            "url": row.get("partdb_url") or part_url(part_id),
            "amount": None,
            "stock_error": None,
            "assignment": row,
        }
        try:
            part = partdb_get(f"/parts/{entity_id(part_id)}", timeout=3)
            candidate = part_candidate(part)
            if candidate:
                item["name"] = candidate["name"]
                item["url"] = candidate["url"]
            item["amount"] = lot_amount(first_part_lot(part_id, part=part, timeout=3))
        except Exception as exc:
            item["stock_error"] = str(exc)
        result.append(item)

    return result


@app.post("/api/stock/change")
def api_stock_change(data: dict = Body(...)):
    """Book an arbitrary quantity using the same tested stock logic as the ZVT terminal."""
    part_id = str(data.get("partdb_part_id") or data.get("part_id") or "").strip()
    action = str(data.get("action") or "").strip().upper()
    quantity = max(1, min(9999, int(data.get("quantity") or 1)))

    if not part_id:
        raise HTTPException(status_code=400, detail="Part-ID fehlt.")
    if action not in ("ADD", "REMOVE"):
        raise HTTPException(status_code=400, detail="action muss ADD oder REMOVE sein.")

    assignment = find_assignment_by_part(part_id)
    drawer_id = str(data.get("drawer_id") or "").strip()
    part_name = str(data.get("part_name") or "").strip()

    if assignment:
        drawer_id = drawer_id or str(assignment.get("drawer_id") or assignment.get("slot_id") or "")
        part_name = part_name or str(assignment.get("part_name") or "")

    if not part_name:
        try:
            part = partdb_get(f"/parts/{entity_id(part_id)}", timeout=4)
            candidate = part_candidate(part)
            if candidate:
                part_name = candidate["name"]
        except Exception:
            pass

    session = {
        "partdb_part_id": entity_id(part_id),
        "part_name": part_name or f"Teil {entity_id(part_id)}",
        "drawer_id": drawer_id,
    }
    save_session(session)
    return handle_stock_quantity(action, quantity, "N8N")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8090)
