import os
import sys
import unittest
from datetime import date, datetime, timezone

ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
SRC_DIR = os.path.join(ROOT_DIR, "src")

if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

import notebooklm_publish as pub


class SanitizeTests(unittest.TestCase):
    def test_strips_notebooklm_citation_markers(self) -> None:
        self.assertEqual(
            pub.strip_citations("The war lasted 38 minutes [1-3] and ended [2, 5] at sea. [4]"),
            "The war lasted 38 minutes and ended at sea.",
        )

    def test_title_removes_quotes_hashtags_and_caps_length(self) -> None:
        raw = '"The 38-Minute War [1]" #history #shorts'
        self.assertEqual(pub.sanitize_title(raw), "The 38-Minute War history shorts")
        long = "How " + "Very " * 40 + "Long"
        self.assertLessEqual(len(pub.sanitize_title(long)), pub.DEFAULT_TITLE_MAX)
        # Cap lands on a word boundary, not mid-word.
        self.assertFalse(pub.sanitize_title(long).endswith("Ver"))

    def test_parse_llm_metadata_handles_fenced_json_and_garbage(self) -> None:
        fenced = 'Sure!\n```json\n{"title": "A", "description": "B"}\n```'
        self.assertEqual(
            pub.parse_llm_metadata(fenced), {"title": "A", "description": "B"}
        )
        self.assertEqual(pub.parse_llm_metadata("no json here"), {})
        self.assertEqual(pub.parse_llm_metadata(""), {})


class PublishSlotTests(unittest.TestCase):
    # Fixed reference: 2026-07-20 15:00 UTC = 11:00 EDT.
    NOW = datetime(2026, 7, 20, 15, 0, tzinfo=timezone.utc)

    def test_first_slot_respects_min_lead(self) -> None:
        # Today's 18:30 EDT is only 7.5h away -> pushed to tomorrow.
        slots = pub.compute_publish_slots(
            3, "18:30", "America/New_York", min_lead_hours=20, now=self.NOW
        )
        self.assertEqual(slots[0], "2026-07-21T22:30:00Z")  # 18:30 EDT = 22:30 UTC

    def test_slots_are_consecutive_days_same_local_time(self) -> None:
        slots = pub.compute_publish_slots(
            3, "18:30", "America/New_York", min_lead_hours=20, now=self.NOW
        )
        self.assertEqual(
            slots,
            ["2026-07-21T22:30:00Z", "2026-07-22T22:30:00Z", "2026-07-23T22:30:00Z"],
        )

    def test_short_lead_allows_same_day(self) -> None:
        slots = pub.compute_publish_slots(
            1, "18:30", "America/New_York", min_lead_hours=2, now=self.NOW
        )
        self.assertEqual(slots[0], "2026-07-20T22:30:00Z")

    def test_explicit_start_day_still_enforces_lead(self) -> None:
        slots = pub.compute_publish_slots(
            1, "18:30", "America/New_York",
            start_day=date(2026, 7, 20), min_lead_hours=20, now=self.NOW,
        )
        self.assertEqual(slots[0], "2026-07-21T22:30:00Z")

    def test_zero_count_returns_empty(self) -> None:
        self.assertEqual(pub.compute_publish_slots(0, "18:30", "UTC"), [])


if __name__ == "__main__":
    unittest.main()
