"""Tests for YouTube Studio upload visibility helpers."""

import unittest

from youtube_upload_flow import (
    extract_outcome_signals,
    parse_moviepy_progress,
    radio_matches_visibility,
    resolve_upload_visibility,
    visibility_radios_present,
)


class ResolveVisibilityTests(unittest.TestCase):
    def test_default_unlisted(self):
        self.assertEqual(resolve_upload_visibility(None), "unlisted")
        self.assertEqual(resolve_upload_visibility({}), "unlisted")

    def test_brand_override(self):
        self.assertEqual(
            resolve_upload_visibility({"default_visibility": "public"}),
            "public",
        )
        self.assertEqual(
            resolve_upload_visibility({"default_visibility": "PRIVATE"}),
            "private",
        )

    def test_invalid_falls_back(self):
        self.assertEqual(
            resolve_upload_visibility({"default_visibility": "friends"}, "unlisted"),
            "unlisted",
        )


class RadioMatchTests(unittest.TestCase):
    def test_matches_label_words(self):
        self.assertTrue(radio_matches_visibility("Unlisted", "unlisted"))
        self.assertTrue(radio_matches_visibility("PUBLIC", "public"))
        self.assertTrue(radio_matches_visibility("Save or publish Private", "private"))

    def test_rejects_partial_noise(self):
        self.assertFalse(radio_matches_visibility("Publication date", "public"))
        self.assertFalse(radio_matches_visibility("", "unlisted"))


class VisibilityStepTests(unittest.TestCase):
    def test_detects_visibility_step(self):
        self.assertTrue(
            visibility_radios_present(["Private", "Unlisted", "Public"])
        )
        self.assertFalse(
            visibility_radios_present(["Yes", "No", "Made for kids"])
        )


class OutcomeSignalTests(unittest.TestCase):
    def test_draft_and_published(self):
        draft = extract_outcome_signals("Video saved as draft in Content")
        self.assertTrue(draft["mentions_draft"])
        live = extract_outcome_signals("Video published successfully")
        self.assertTrue(live["mentions_published"])


class MoviePyProgressTests(unittest.TestCase):
    def test_percent_bar(self):
        self.assertEqual(parse_moviepy_progress("45%|####"), 45.0)

    def test_fraction(self):
        self.assertAlmostEqual(parse_moviepy_progress("90/180"), 50.0)


if __name__ == "__main__":
    unittest.main()
