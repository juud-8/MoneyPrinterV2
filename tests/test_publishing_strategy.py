import os
import sys
import unittest
from datetime import datetime

ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
SRC_DIR = os.path.join(ROOT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from publishing_strategy import enabled_slots_for_day, is_publish_slot_active, validate_publishing_strategy


class PublishingStrategyTests(unittest.TestCase):
    def setUp(self):
        self.manifest = {
            "publishing": {
                "shorts_per_week": 10,
                "minimum_hours_between_posts": 6,
                "publish_slots": {
                    "midday": {
                        "enabled": True,
                        "days": ["tuesday", "thursday", "saturday"],
                        "window_start": "12:15",
                        "window_end": "12:30",
                    },
                    "prime": {
                        "enabled": True,
                        "window_start": "18:30",
                        "window_end": "19:00",
                    },
                    "early": {
                        "enabled": False,
                        "window_start": "17:45",
                        "window_end": "18:00",
                    },
                },
            }
        }

    def test_slot_days_and_disabled_slots(self):
        tuesday = datetime(2026, 7, 7, 10, 0)
        monday = datetime(2026, 7, 6, 10, 0)
        self.assertTrue(is_publish_slot_active(self.manifest, "midday", tuesday))
        self.assertFalse(is_publish_slot_active(self.manifest, "midday", monday))
        self.assertFalse(is_publish_slot_active(self.manifest, "early", tuesday))
        self.assertEqual(enabled_slots_for_day(self.manifest, tuesday), ["midday", "prime"])

    def test_valid_strategy_has_no_warnings(self):
        self.assertEqual(validate_publishing_strategy(self.manifest), [])

    def test_spacing_and_weekly_count_warnings(self):
        self.manifest["publishing"]["publish_slots"]["early"]["enabled"] = True
        warnings = validate_publishing_strategy(self.manifest)
        self.assertTrue(any("only" in warning and "minimum" in warning for warning in warnings))
        self.assertTrue(any("enabled slot-days total" in warning for warning in warnings))


if __name__ == "__main__":
    unittest.main()

