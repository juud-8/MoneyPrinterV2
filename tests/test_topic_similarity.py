import os
import sys
import unittest

ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
SRC_DIR = os.path.join(ROOT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from topic_similarity import find_near_duplicate, topic_similarity


class TopicSimilarityTests(unittest.TestCase):
    def test_reworded_same_event_is_duplicate(self):
        old = "How Liechtenstein Sent 80 Soldiers to War and Returned with 81"
        new = "Liechtenstein Deployed 80 Men in 1866 and Brought 81 Home"
        self.assertGreaterEqual(topic_similarity(old, new), 0.62)
        self.assertIsNotNone(find_near_duplicate(new, [old]))

    def test_real_emu_war_double_up_is_caught(self):
        # The exact wordings that slipped through on 2026-07-01/02.
        old = (
            "In 1932, the Australian military deployed machine guns against a "
            "population of over 20,000 emus, resulting in one of history's most "
            "bizarre military defeats."
        )
        new = (
            "In 1932, Australia famously declared war on its native emu population "
            "and, despite deploying soldiers with machine guns, ultimately lost."
        )
        self.assertGreaterEqual(topic_similarity(old, new), 0.62)
        self.assertIsNotNone(find_near_duplicate(new, [old]))

    def test_same_year_alone_is_not_a_duplicate(self):
        old = "The 1932 Emu War in Western Australia"
        new = "How the 1932 Bonus Army March Reached Washington"
        self.assertLess(topic_similarity(old, new), 0.62)

    def test_distinct_events_are_not_duplicates(self):
        old = "The 1457 Pig Trial in Savigny"
        new = "How Boston's Molasses Flood Reached 35 Miles Per Hour"
        self.assertLess(topic_similarity(old, new), 0.62)
        self.assertIsNone(find_near_duplicate(new, [old]))


if __name__ == "__main__":
    unittest.main()
