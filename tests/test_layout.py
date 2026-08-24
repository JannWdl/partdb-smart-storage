import unittest
from pathlib import Path
import sys


class LayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        sys.path.insert(0, str(root / "app"))
        import core
        cls.core = core

    def test_computed_slots_default_layout(self):
        slots = self.core.computed_slots(self.core.DEFAULT_LAYOUT)
        self.assertEqual(len(slots), 21)
        self.assertEqual(slots[0]["leds"], [0, 1, 2, 3])
        self.assertEqual(slots[19]["leds"], [76, 77, 78, 79])
        self.assertEqual(slots[20]["leds"], list(range(80, 96)))

    def test_serpentine_led_mapping(self):
        layout = {
            "name": "Test",
            "cabinets": [
                {
                    "id": "a",
                    "name": "A",
                    "rows": 2,
                    "columns": 3,
                    "start_led": 10,
                    "leds_per_slot": 2,
                    "serpentine": True,
                }
            ],
        }
        slots = self.core.computed_slots(layout)
        self.assertEqual(slots[0]["leds"], [10, 11])
        self.assertEqual(slots[1]["leds"], [12, 13])
        self.assertEqual(slots[2]["leds"], [14, 15])
        self.assertEqual(slots[3]["leds"], [20, 21])
        self.assertEqual(slots[4]["leds"], [18, 19])
        self.assertEqual(slots[5]["leds"], [16, 17])

    def test_column_strip_path_maps_as_continuous_walk(self):
        layout = {
            "name": "Column strip path",
            "cabinets": [
                {
                    "id": "a",
                    "name": "A",
                    "rows": 3,
                    "columns": 2,
                    "start_led": 0,
                    "leds_per_slot": 1,
                    "strip_path": "columns",
                }
            ],
        }
        slots = self.core.computed_slots(layout)
        self.assertEqual(slots[0]["leds"], [0])
        self.assertEqual(slots[2]["leds"], [1])
        self.assertEqual(slots[4]["leds"], [2])
        self.assertEqual(slots[1]["leds"], [3])

    def test_legacy_wiring_order_still_loads(self):
        layout = {
            "name": "Legacy",
            "cabinets": [
                {
                    "id": "a",
                    "name": "A",
                    "rows": 2,
                    "columns": 2,
                    "start_led": 0,
                    "leds_per_slot": 1,
                    "wiring_order": "columns",
                    "serpentine": True,
                }
            ],
        }
        slots = self.core.computed_slots(layout)
        self.assertEqual(slots[0]["leds"], [0])
        self.assertEqual(slots[2]["leds"], [1])
        self.assertEqual(slots[3]["leds"], [2])
        self.assertEqual(slots[1]["leds"], [3])


if __name__ == "__main__":
    unittest.main()
