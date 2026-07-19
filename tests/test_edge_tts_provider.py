"""Tests for edge_tts provider selection (no live network)."""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
SRC_DIR = os.path.join(ROOT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from media_providers.voicebox_settings import resolve_audio_provider_settings


class EdgeTtsProviderTests(unittest.TestCase):
    def test_resolve_edge_tts_provider(self):
        settings = resolve_audio_provider_settings(
            legacy_provider="kittentts",
            global_audio={"provider": "edge_tts", "allow_fallback": False},
        )
        self.assertEqual(settings.provider, "edge_tts")

    def test_edge_tts_as_voicebox_fallback(self):
        settings = resolve_audio_provider_settings(
            legacy_provider="voicebox",
            global_audio={
                "provider": "voicebox",
                "allow_fallback": True,
                "fallback_provider": "edge_tts",
                "voicebox": {"profile": "narrator"},
            },
        )
        self.assertEqual(settings.fallback_provider, "edge_tts")

    def test_synthesize_edge_tts_mocked(self):
        from classes.Tts import TTS

        with patch("classes.Tts.get_audio_provider_settings") as mock_settings:
            mock_settings.return_value = resolve_audio_provider_settings(
                legacy_provider="edge_tts",
                cli_audio={"provider": "edge_tts", "allow_fallback": False},
            )
            tts = TTS(cli_audio={"provider": "edge_tts", "allow_fallback": False})
            tts._provider = "edge_tts"

            fake_communicate = MagicMock()
            fake_communicate.save = MagicMock(return_value=None)

            class _Comm:
                def __init__(self, text, voice):
                    self.text = text
                    self.voice = voice

                async def save(self, path):
                    with open(path, "wb") as handle:
                        handle.write(b"ID3")

            with patch.dict("sys.modules", {"edge_tts": MagicMock(Communicate=_Comm)}):
                with patch("classes.Tts.get_edge_tts_voice", return_value="en-US-GuyNeural"):
                    import tempfile

                    out = os.path.join(tempfile.gettempdir(), "mpv2_edge_test.mp3")
                    if os.path.exists(out):
                        os.remove(out)
                    path = tts._synthesize_edge_tts("Hello.", out)
                    self.assertTrue(os.path.isfile(path))
                    self.assertEqual(tts.last_provider_used, "edge_tts")
                    self.assertEqual(tts.last_model_used, "en-US-GuyNeural")


if __name__ == "__main__":
    unittest.main()
