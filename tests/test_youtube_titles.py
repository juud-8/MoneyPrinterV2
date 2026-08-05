"""Tests for generated-title cleaning and opener-shape checks."""

import os
import sys
import unittest

ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
SRC_DIR = os.path.join(ROOT_DIR, "src")

if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from youtube_titles import clean_title_candidate, opens_with_how


class CleanTitleCandidateTests(unittest.TestCase):
    def test_returns_empty_for_blank_input(self):
        self.assertEqual(clean_title_candidate(""), "")
        self.assertEqual(clean_title_candidate(None), "")

    def test_keeps_a_plain_title_intact(self):
        title = "The 5-Year-Old Girl Mailed Across Idaho for 53 Cents in 1914"
        self.assertEqual(clean_title_candidate(title), title)

    def test_strips_label_prefix(self):
        self.assertEqual(
            clean_title_candidate("Title: The Kentucky Meat Shower of 1876"),
            "The Kentucky Meat Shower of 1876",
        )

    def test_strips_markdown_and_quotes(self):
        self.assertEqual(
            clean_title_candidate('**Title:** "The Great Molasses Flood of 1919"'),
            "The Great Molasses Flood of 1919",
        )

    def test_keeps_only_the_first_line(self):
        self.assertEqual(
            clean_title_candidate("The 1859 Pig War\n\nLet me know if you want more!"),
            "The 1859 Pig War",
        )

    def test_strips_hashtags(self):
        self.assertEqual(
            clean_title_candidate("The 1859 Pig War #history #shorts"),
            "The 1859 Pig War",
        )


class OpensWithHowTests(unittest.TestCase):
    def test_detects_plain_how_opener(self):
        self.assertTrue(opens_with_how("How Cherries Made a President in 1850"))

    def test_is_case_insensitive(self):
        self.assertTrue(opens_with_how("HOW 25 BISON SAVED THE HERD"))

    def test_ignores_leading_punctuation(self):
        self.assertTrue(opens_with_how('"How a 1,400-Pound Cheese Got to Washington'))

    def test_rejects_non_how_openers(self):
        self.assertFalse(opens_with_how("The Kentucky Meat Shower of 1876"))
        self.assertFalse(opens_with_how("Why Liechtenstein Came Home with 81 Men"))

    def test_does_not_match_how_as_a_substring(self):
        self.assertFalse(opens_with_how("Howard Hughes Bought a Casino to Fix His TV"))

    def test_handles_empty_input(self):
        self.assertFalse(opens_with_how(""))
        self.assertFalse(opens_with_how(None))


if __name__ == "__main__":
    unittest.main()
