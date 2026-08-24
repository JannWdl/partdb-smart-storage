DEFAULT_LAYOUT = {
    "name": "Kleinteilemagazin",
    "wled_segment_mode": "single",
    "cabinets": [
        {
            "id": "main",
            "name": "Hauptmagazin",
            "rows": 5,
            "columns": 4,
            "start_led": 0,
            "leds_per_slot": 4,
            "slot_width_mm": 55,
            "slot_height_mm": 38,
            "x": 24,
            "y": 24,
            "wiring_order": "rows",
            "serpentine": False,
            "slot_prefix": "Fach",
        },
        {
            "id": "bottom",
            "name": "Grosses Fach unten",
            "rows": 1,
            "columns": 1,
            "start_led": 80,
            "leds_per_slot": 16,
            "slot_width_mm": 220,
            "slot_height_mm": 55,
            "x": 24,
            "y": 270,
            "wiring_order": "rows",
            "serpentine": False,
            "slot_prefix": "Fach",
        },
    ],
}


def validate_layout(layout):
    if not isinstance(layout, dict) or not layout.get("cabinets"):
        raise ValueError("Layout braucht mindestens ein Magazin.")
    for cabinet in layout["cabinets"]:
        for key in ("id", "name", "rows", "columns", "start_led", "leds_per_slot"):
            if key not in cabinet:
                raise ValueError(f"Magazin ohne Feld: {key}")
        if int(cabinet["rows"]) < 1 or int(cabinet["columns"]) < 1:
            raise ValueError("Reihen und Spalten muessen groesser als 0 sein.")
        if int(cabinet["leds_per_slot"]) < 1:
            raise ValueError("LEDs pro Fach muss groesser als 0 sein.")
        if cabinet.get("wiring_order", "rows") not in ("rows", "columns"):
            raise ValueError("wiring_order muss rows oder columns sein.")


def computed_slots(layout):
    slots = []
    global_index = 1
    for cabinet in layout["cabinets"]:
        rows = int(cabinet["rows"])
        columns = int(cabinet["columns"])
        start_led = int(cabinet["start_led"])
        leds_per_slot = int(cabinet["leds_per_slot"])
        serpentine = bool(cabinet.get("serpentine"))
        wiring_order = cabinet.get("wiring_order", "rows")
        for row in range(rows):
            for col in range(columns):
                if wiring_order == "columns":
                    physical_row = rows - 1 - row if serpentine and col % 2 else row
                    offset = (col * rows + physical_row) * leds_per_slot
                else:
                    physical_col = columns - 1 - col if serpentine and row % 2 else col
                    offset = (row * columns + physical_col) * leds_per_slot
                led_start = start_led + offset
                slot_id = f"{cabinet['id']}-{row + 1}-{col + 1}"
                label = f"{cabinet.get('slot_prefix', 'Fach')} {global_index}"
                slots.append(
                    {
                        "id": slot_id,
                        "label": label,
                        "global_index": global_index,
                        "cabinet_id": cabinet["id"],
                        "cabinet_name": cabinet["name"],
                        "row": row + 1,
                        "column": col + 1,
                        "led_start": led_start,
                        "led_stop": led_start + leds_per_slot,
                        "leds": list(range(led_start, led_start + leds_per_slot)),
                        "slot_width_mm": int(cabinet.get("slot_width_mm", 0) or 0),
                        "slot_height_mm": int(cabinet.get("slot_height_mm", 0) or 0),
                    }
                )
                global_index += 1
    return slots
