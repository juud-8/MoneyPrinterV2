import os
import sys
import unittest
from unittest.mock import patch

ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
SRC_DIR = os.path.join(ROOT_DIR, "src")

if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

# test_cron_post_bridge.py registers stubs in sys.modules; ensure we load
# the real modules (same pattern as test_llm_provider.py).
sys.modules.pop("classes.YouTube", None)
sys.modules.pop("llm_provider", None)

import classes.YouTube as yt_module
from classes.YouTube import YouTube


class _FakeClip:
    def __init__(self, duration: float) -> None:
        self.duration = duration


class DurationGateTests(unittest.TestCase):
    """_enforce_max_audio_duration: reject/retry/abort on real audio length."""

    def _make_youtube(self) -> YouTube:
        yt = YouTube.__new__(YouTube)  # skip __init__ (accounts/Selenium)
        yt.format_type = "short"
        yt.tts_path = "fake.wav"
        yt.subject = "test subject"
        yt.production_metadata = {}
        yt.calls = {"script": 0, "metadata": 0, "tts": 0}
        yt.generate_script = lambda **kw: yt.calls.__setitem__(
            "script", yt.calls["script"] + 1
        )
        yt.generate_metadata = lambda: yt.calls.__setitem__(
            "metadata", yt.calls["metadata"] + 1
        )
        yt.generate_script_to_speech = lambda tts: yt.calls.__setitem__(
            "tts", yt.calls["tts"] + 1
        )
        yt._short_target_words = lambda: 130
        return yt

    def _run_gate(self, durations: list[float], style: dict) -> tuple[YouTube, list]:
        yt = self._make_youtube()
        rejections = []
        queue = list(durations)

        def fake_log(**kwargs):
            rejections.append(kwargs)

        with (
            patch.object(yt_module, "AudioFileClip", lambda path: _FakeClip(queue.pop(0))),
            patch.object(yt_module, "log_duration_rejection", fake_log),
            patch.object(yt_module, "load_active_brand", lambda: {"brand_id": "test_brand"}),
            patch.object(yt_module, "warning", lambda *a, **k: None),
        ):
            yt._enforce_max_audio_duration(tts_instance=object(), style=style)
        return yt, rejections

    def test_under_cap_passes_untouched(self) -> None:
        yt, rejections = self._run_gate([60.0], {"max_audio_duration_seconds": 75.0})
        self.assertEqual(rejections, [])
        self.assertEqual(yt.calls["script"], 0)

    def test_over_cap_retries_shorter_then_passes(self) -> None:
        yt, rejections = self._run_gate(
            [80.0, 60.0], {"max_audio_duration_seconds": 75.0}
        )
        self.assertEqual(len(rejections), 1)
        self.assertEqual(rejections[0]["action"], "retry")
        self.assertEqual(rejections[0]["audio_seconds"], 80.0)
        self.assertEqual(rejections[0]["brand_id"], "test_brand")
        self.assertEqual(yt.calls, {"script": 1, "metadata": 1, "tts": 1})

    def test_still_over_cap_after_retries_aborts(self) -> None:
        with self.assertRaises(RuntimeError):
            self._run_gate([80.0, 79.0, 78.0], {"max_audio_duration_seconds": 75.0})

        # Re-run capturing rejections (assertRaises swallowed the return).
        yt = self._make_youtube()
        rejections = []
        queue = [80.0, 79.0, 78.0]
        with (
            patch.object(yt_module, "AudioFileClip", lambda path: _FakeClip(queue.pop(0))),
            patch.object(
                yt_module, "log_duration_rejection", lambda **kw: rejections.append(kw)
            ),
            patch.object(yt_module, "load_active_brand", lambda: {"brand_id": "test_brand"}),
            patch.object(yt_module, "warning", lambda *a, **k: None),
        ):
            with self.assertRaises(RuntimeError):
                yt._enforce_max_audio_duration(tts_instance=object(), style={
                    "max_audio_duration_seconds": 75.0
                })
        self.assertEqual(
            [r["action"] for r in rejections], ["retry", "retry", "abort"]
        )
        self.assertEqual(yt.calls["script"], 2)

    def test_no_cap_configured_is_a_noop(self) -> None:
        yt = self._make_youtube()

        def boom(path):
            raise AssertionError("audio should not be inspected without a cap")

        with patch.object(yt_module, "AudioFileClip", boom):
            yt._enforce_max_audio_duration(
                tts_instance=object(), style={"max_audio_duration_seconds": None}
            )
        self.assertEqual(yt.calls["script"], 0)

    def test_longform_skips_the_gate(self) -> None:
        yt = self._make_youtube()
        yt.format_type = "longform"

        def boom(path):
            raise AssertionError("longform must skip the gate")

        with patch.object(yt_module, "AudioFileClip", boom):
            yt._enforce_max_audio_duration(
                tts_instance=object(), style={"max_audio_duration_seconds": 75.0}
            )


if __name__ == "__main__":
    unittest.main()
