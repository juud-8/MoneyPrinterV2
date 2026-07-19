"""Tests for ASS karaoke caption spike (not production-wired)."""

import os
import sys
import tempfile
import unittest

ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
SRC_DIR = os.path.join(ROOT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from caption_ass import (
    AssStyle,
    build_ass_document,
    build_burn_in_command,
    entries_to_cues,
    parse_srt_entries,
    seconds_to_ass_timestamp,
    srt_timestamp_to_seconds,
    write_ass_from_srt,
)


SAMPLE_SRT = """1
00:00:00,000 --> 00:00:02,000
Hello world test

2
00:00:02,000 --> 00:00:03,500
Again
"""


class CaptionAssTests(unittest.TestCase):
    def test_timestamp_roundtrip_helpers(self):
        self.assertAlmostEqual(srt_timestamp_to_seconds("00:01:02,500"), 62.5)
        self.assertEqual(seconds_to_ass_timestamp(62.5), "0:01:02.50")

    def test_parse_and_cues(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "sample.srt")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(SAMPLE_SRT)
            entries = parse_srt_entries(path)
            self.assertEqual(len(entries), 2)
            cues = entries_to_cues(entries, max_words_per_cue=2)
            self.assertGreaterEqual(len(cues), 2)
            self.assertEqual(cues[0].words[0].text.lower(), "hello")

    def test_build_ass_contains_karaoke_tags(self):
        cues = entries_to_cues(
            [{"start": 0.0, "end": 1.0, "text": "one two"}],
            max_words_per_cue=4,
        )
        body = build_ass_document(cues, style=AssStyle(font_name="TestFont"))
        self.assertIn("PlayResX: 1080", body)
        self.assertIn("{\\k", body)
        self.assertIn("ONE", body)
        self.assertIn("TWO", body)
        self.assertIn("TestFont", body)

    def test_write_ass_from_srt(self):
        with tempfile.TemporaryDirectory() as tmp:
            srt = os.path.join(tmp, "a.srt")
            ass = os.path.join(tmp, "a.ass")
            with open(srt, "w", encoding="utf-8") as handle:
                handle.write(SAMPLE_SRT)
            write_ass_from_srt(srt, ass)
            with open(ass, encoding="utf-8") as handle:
                body = handle.read()
            self.assertIn("[Events]", body)
            self.assertIn("Dialogue:", body)

    def test_burn_in_command_escapes_and_copies_audio(self):
        cmd = build_burn_in_command(
            "in.mp4",
            r"C:\fonts\caps.ass",
            "out.mp4",
            fonts_dir=r"C:\fonts",
        )
        self.assertEqual(cmd[0], "ffmpeg")
        self.assertIn("-c:a", cmd)
        self.assertIn("copy", cmd)
        vf = cmd[cmd.index("-vf") + 1]
        self.assertIn("ass=", vf)
        self.assertIn("fontsdir=", vf)


if __name__ == "__main__":
    unittest.main()
