import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
SRC_DIR = os.path.join(ROOT_DIR, "src")

if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

import provider_health


class ProviderHealthTests(unittest.TestCase):
    def test_score_song_filename_prefers_documentary_keywords(self) -> None:
        good = provider_health.score_song_filename("Distant_Tension_Ambient.mp3")
        bad = provider_health.score_song_filename("retrowave_outrun_vhs_110bpm.mp3")
        self.assertGreater(good, bad)

    def test_check_songs_library_fails_below_minimum(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            songs_dir = os.path.join(temp_dir, "Songs")
            os.mkdir(songs_dir)
            open(os.path.join(songs_dir, "ambient_test_01.mp3"), "wb").close()
            issues = provider_health.check_songs_library(temp_dir, min_tracks=15)
            self.assertTrue(any(issue.level == "fail" for issue in issues))

    def test_assert_pilot_providers_ready_raises_on_low_elevenlabs(self) -> None:
        brand = {
            "brand_id": "the_strange_archive",
            "firefox_profile": "",
            "production": {"pilot_mode": True},
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            songs_dir = os.path.join(temp_dir, "Songs")
            os.mkdir(songs_dir)
            for i in range(16):
                open(os.path.join(songs_dir, f"documentary_ambient_{i:02d}.mp3"), "wb").close()

            with patch.object(provider_health, "load_brand", return_value=brand):
                with patch.object(provider_health, "get_tts_provider", return_value="elevenlabs"):
                    with patch.object(
                        provider_health,
                        "check_elevenlabs_quota",
                        return_value=(100, 10000, [
                            provider_health.HealthIssue("fail", "quota too low", "upgrade")
                        ]),
                    ):
                        with patch.object(provider_health, "check_fal_credits", return_value=[]):
                            with patch.object(provider_health, "check_gemini_reachable", return_value=[]):
                                with self.assertRaises(RuntimeError):
                                    provider_health.assert_pilot_providers_ready(
                                        "the_strange_archive",
                                        temp_dir,
                                    )


if __name__ == "__main__":
    unittest.main()
