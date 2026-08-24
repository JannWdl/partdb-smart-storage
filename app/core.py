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
            "strip_path": "rows",
            "serpentine": False,
            "slot_prefix": "Fach",
        },
        {
            "id": "bottom",
            "name": "Großes Fach unten",
            "rows": 1,
            "columns": 1,
            "start_led": 80,
            "leds_per_slot": 16,
            "slot_width_mm": 220,
            "slot_height_mm": 55,
            "x": 24,
            "y": 270,
            "strip_path": "rows",
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
            raise ValueError("Reihen und Spalten müssen größer als 0 sein.")
        if int(cabinet["leds_per_slot"]) < 1:
            raise ValueError("LEDs pro Fach muss größer als 0 sein.")
        strip_path = cabinet.get("strip_path", cabinet.get("wiring_order", "rows"))
        if strip_path not in ("rows", "columns"):
            raise ValueError("strip_path muss rows oder columns sein.")


def computed_slots(layout):
    slots = []
    global_index = 1
    for cabinet in layout["cabinets"]:
        rows = int(cabinet["rows"])
        columns = int(cabinet["columns"])
        start_led = int(cabinet["start_led"])
        leds_per_slot = int(cabinet["leds_per_slot"])
        serpentine = bool(cabinet.get("serpentine"))
        strip_path = cabinet.get("strip_path", cabinet.get("wiring_order", "rows"))
        for row in range(rows):
            for col in range(columns):
                if strip_path == "columns":
                    path_row = rows - 1 - row if serpentine and col % 2 else row
                    path_index = col * rows + path_row
                else:
                    path_col = columns - 1 - col if serpentine and row % 2 else col
                    path_index = row * columns + path_col
                led_start = start_led + path_index * leds_per_slot
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
