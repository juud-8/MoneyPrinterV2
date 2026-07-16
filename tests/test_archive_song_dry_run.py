"""Offline dry-run: package pause → synthetic audio → resume shot plan (no paid APIs)."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
SRC_DIR = os.path.join(ROOT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

import importlib

from archive_song import (
    AUDIO_MODE_ARCHIVE_SONG,
    ArchiveSongState,
    AwaitingSongAudio,
    SongPackage,
    load_state,
    save_state,
    validate_and_normalize_audio,
)
from archive_song_settings import default_archive_song_settings
from archive_song_visuals import build_archive_shot_plan
from asset_gen import AssetResult
from classes.YouTube import YouTube

yt_module = importlib.import_module("classes.YouTube")
FIXTURE_PATH = os.path.join(ROOT_DIR, "tests", "fixtures", "dancing_plague_1518.json")
SETTINGS = default_archive_song_settings()


def _load_fixture() -> tuple[dict, SongPackage]:
    with open(FIXTURE_PATH, "r", encoding="utf-8") as file:
        value = json.load(file)
    brief = value["research_brief"]
    return brief, SongPackage.from_dict(value["song_package"], brief)


class ArchiveSongOfflineDryRunTests(unittest.TestCase):
    def _write_tone(self, path: str, duration: float = 60.0) -> None:
        import numpy as np
        import soundfile as sf

        sample_rate = 44100
        samples = np.arange(int(duration * sample_rate), dtype=np.float32)
        wave = 0.2 * np.sin(2 * np.pi * 196 * samples / sample_rate)
        sf.write(path, wave, sample_rate)

    def test_separate_resume_builds_plan_and_stops_before_paid_assets(self) -> None:
        brief, package = _load_fixture()
        with tempfile.TemporaryDirectory() as temp_dir:
            # Phase 1: initial process pauses at awaiting_song_audio.
            youtube = YouTube.__new__(YouTube)
            youtube._niche = "historical mysteries"
            youtube._language = "English"
            youtube.format_type = "short"
            youtube.audio_mode = AUDIO_MODE_ARCHIVE_SONG
            youtube.archive_song_resume = False
            youtube.archive_song_episode_id = "dancing-plague-1518"
            youtube.archive_song_audio_path = ""
            youtube.regenerate_song_package = False
            youtube.skip_song_validation = False
            youtube.episode_number = "dancing-plague-1518"
            youtube.subject = brief["topic"]
            youtube.images = []
            youtube.asset_modalities = []
            youtube.asset_results = []
            youtube.production_metadata = {}
            youtube.run_id = "dry-run"
            youtube.archive_subtitles_path = ""

            def research(**_kwargs) -> None:
                youtube.subject = brief["topic"]
                youtube.research_brief = brief
                youtube.research_notes = "source-backed"
                youtube.research_brief_path = ""

            def script() -> str:
                youtube.script = "Approved researched narration script."
                return youtube.script

            with (
                patch.object(yt_module, "load_active_brand", return_value={"brand_id": "alpha"}),
                patch.object(yt_module, "ensure_episode_directory", return_value=temp_dir),
                patch.object(
                    yt_module,
                    "load_resolved_archive_song_settings",
                    return_value=SETTINGS,
                ),
                patch.object(youtube, "_generate_topic_and_research", side_effect=research),
                patch.object(youtube, "generate_script", side_effect=script),
                patch.object(youtube, "_generate_archive_song_package", return_value=package),
            ):
                with self.assertRaises(AwaitingSongAudio):
                    youtube._generate_archive_song_pipeline()

            state = load_state(temp_dir)
            self.assertEqual(state.status, "awaiting_song_audio")
            self.assertTrue(os.path.isfile(os.path.join(temp_dir, "song_package.json")))
            self.assertTrue(os.path.isfile(os.path.join(temp_dir, "lyrics.txt")))

            # Operator places synthetic Suno export.
            song_path = os.path.join(temp_dir, "song.wav")
            self._write_tone(song_path, 60.0)

            # Phase 2: new process-style resume using only persisted state.
            resume = YouTube.__new__(YouTube)
            resume._niche = "historical mysteries"
            resume._language = "English"
            resume.format_type = "short"
            resume.audio_mode = AUDIO_MODE_ARCHIVE_SONG
            resume.archive_song_resume = True
            resume.archive_song_episode_id = "dancing-plague-1518"
            resume.archive_song_audio_path = ""
            resume.regenerate_song_package = False
            resume.skip_song_validation = False
            resume.episode_number = "dancing-plague-1518"
            resume.subject = brief["topic"]
            resume.images = []
            resume.asset_modalities = []
            resume.asset_results = []
            resume.production_metadata = {}
            resume.run_id = "dry-run-resume"
            resume.archive_subtitles_path = ""
            resume.experiment_metadata = {}

            paid_calls = []

            def refuse_paid_assets(current_state, package_arg=None, settings_arg=None):
                # Build the real shot plan offline, then stop before providers.
                audio = validate_and_normalize_audio(
                    song_path,
                    temp_dir,
                    target_duration_seconds=60,
                    min_duration_seconds=55,
                    max_duration_seconds=65,
                )
                self.assertTrue(audio.valid, audio.errors)
                plan = build_archive_shot_plan(
                    audio_duration=audio.duration_seconds,
                    timed_beat_map_path=current_state.timed_beat_map_path,
                    package_beats=package.visual_beat_map,
                    subject=brief["topic"],
                    historical_topic=package.historical_topic,
                    style_suffix="engraving",
                    settings=SETTINGS,
                )
                self.assertFalse(plan.used_fallback)
                self.assertGreaterEqual(len(plan.shots), 6)
                paid_calls.append(len(plan.shots))
                raise RuntimeError("DRY_RUN_STOP_BEFORE_PAID_ASSET_GENERATION")

            with (
                patch.object(yt_module, "load_active_brand", return_value={"brand_id": "alpha"}),
                patch.object(yt_module, "ensure_episode_directory", return_value=temp_dir),
                patch.object(
                    yt_module,
                    "load_resolved_archive_song_settings",
                    return_value=SETTINGS,
                ),
                patch.object(
                    resume,
                    "generate_subtitles_local_whisper",
                    side_effect=RuntimeError("offline whisper"),
                ),
                patch.object(resume, "_generate_archive_assets", side_effect=refuse_paid_assets),
            ):
                with self.assertRaisesRegex(RuntimeError, "DRY_RUN_STOP_BEFORE_PAID"):
                    resume._generate_archive_song_pipeline()

            self.assertEqual(paid_calls[0], 6)
            resumed = load_state(temp_dir)
            self.assertEqual(resumed.status, "audio_ready")
            self.assertTrue(os.path.isfile(resumed.normalized_audio_path))
            self.assertTrue(os.path.isfile(resumed.timed_beat_map_path))
            self.assertTrue(os.path.isfile(resumed.caption_alignment_path))
            self.assertIn("normalized", os.path.basename(resumed.timed_beat_map_path))


if __name__ == "__main__":
    unittest.main()
