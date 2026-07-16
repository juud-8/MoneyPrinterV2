"""Offline tests for the manual Archive Song boundary and contracts."""

import json
import importlib
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

from archive_song import (
    AUDIO_MODE_ARCHIVE_SONG,
    ArchiveSongState,
    AwaitingSongAudio,
    SongAudioValidation,
    SongPackage,
    build_ffmpeg_normalize_command,
    build_lyric_alignment,
    compute_file_identity,
    discover_song_audio,
    identities_match,
    invalidate_audio_dependent_outputs,
    load_state,
    lyrics_content_hash,
    prepare_timed_beat_maps,
    save_state,
    snap_durations_to_frames,
    validate_and_normalize_audio,
    write_song_package_files,
)
from archive_song_settings import (
    ArchiveSongSettings,
    default_archive_song_settings,
    resolve_archive_song_settings,
)
from archive_song_visuals import (
    build_archive_shot_plan,
    durations_match_audio,
    normalize_timed_beats,
)
from asset_gen import AssetResult
from classes.YouTube import YouTube

yt_module = importlib.import_module("classes.YouTube")
DEFAULT_SETTINGS = default_archive_song_settings()


FIXTURE_PATH = os.path.join(
    ROOT_DIR, "tests", "fixtures", "dancing_plague_1518.json"
)


def load_fixture() -> tuple[dict, SongPackage]:
    with open(FIXTURE_PATH, "r", encoding="utf-8") as file:
        value = json.load(file)
    brief = value["research_brief"]
    return brief, SongPackage.from_dict(value["song_package"], brief)


class ArchiveSongContractTests(unittest.TestCase):
    def test_dancing_plague_package_is_valid_and_traceable(self) -> None:
        brief, package = load_fixture()
        self.assertEqual(package.target_duration_seconds, 60)
        self.assertGreaterEqual(len(package.visual_beat_map), 6)
        self.assertTrue(
            all(beat.source_ids for beat in package.visual_beat_map)
        )
        self.assertTrue(
            all(entry["research_claim_match"] for entry in package.fact_traceability)
        )
        self.assertEqual(
            package.disputed_claim_warnings, brief["disputed_points"]
        )

    def test_schema_rejects_unknown_beat_sources(self) -> None:
        brief, package = load_fixture()
        value = package.to_dict()
        value["visual_beat_map"][0]["source_ids"] = ["S999"]
        with self.assertRaisesRegex(ValueError, "cite at least one"):
            SongPackage.from_dict(value, brief)

    def test_package_files_and_state_round_trip(self) -> None:
        brief, package = load_fixture()
        with tempfile.TemporaryDirectory() as temp_dir:
            write_song_package_files(temp_dir, package, brief, "resume command")
            expected = {
                "song_package.json",
                "lyrics.txt",
                "suno_prompt.txt",
                "pronunciations.json",
                "visual_beat_map.json",
                "fact_check.json",
                "README_SUNO.md",
            }
            self.assertTrue(expected.issubset(set(os.listdir(temp_dir))))

            state = ArchiveSongState(
                episode_id="pilot",
                brand_id="alpha",
                status="awaiting_song_audio",
                research_brief=brief,
                song_package=package.to_dict(),
            )
            save_state(temp_dir, state)
            restored = load_state(temp_dir)
            self.assertEqual(restored.status, "awaiting_song_audio")
            self.assertEqual(restored.episode_id, "pilot")

    def test_caption_alignment_fallback_preserves_source_lines(self) -> None:
        lyrics = "First factual line.\nSecond haunting line?"
        with tempfile.TemporaryDirectory() as temp_dir:
            alignment_path, srt_path = build_lyric_alignment(
                temp_dir, lyrics, 60.0, detected_entries=[]
            )
            with open(alignment_path, "r", encoding="utf-8") as file:
                alignment = json.load(file)
            self.assertEqual(
                [entry["text"] for entry in alignment["entries"]],
                lyrics.splitlines(),
            )
            self.assertTrue(
                all(
                    entry["timing_source"] == "proportional_phrase_fallback"
                    for entry in alignment["entries"]
                )
            )
            self.assertTrue(os.path.isfile(srt_path))


class ArchiveSongAudioTests(unittest.TestCase):
    def _write_tone(self, path: str, duration: float, sample_rate: int = 22050) -> None:
        import numpy as np
        import soundfile as sf

        samples = np.arange(int(duration * sample_rate), dtype=np.float32)
        wave = 0.25 * np.sin(2 * np.pi * 220 * samples / sample_rate)
        sf.write(path, wave, sample_rate)

    def test_audio_normalization_creates_renderer_wav(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = os.path.join(temp_dir, "song.wav")
            self._write_tone(source, 1.0)
            result = validate_and_normalize_audio(
                source,
                temp_dir,
                target_duration_seconds=1,
                min_duration_seconds=0.5,
                max_duration_seconds=2,
            )
            self.assertTrue(result.valid, result.errors)
            self.assertEqual(result.sample_rate_hz, 44100)
            self.assertEqual(result.channels, 2)
            self.assertTrue(os.path.isfile(result.normalized_path))

    def test_missing_and_invalid_audio_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            missing = validate_and_normalize_audio(
                os.path.join(temp_dir, "song.wav"), temp_dir
            )
            self.assertFalse(missing.valid)
            invalid_path = os.path.join(temp_dir, "song.wav")
            Path(invalid_path).write_text("not audio", encoding="utf-8")
            invalid = validate_and_normalize_audio(invalid_path, temp_dir)
            self.assertFalse(invalid.valid)
            self.assertTrue(any("decoded" in error for error in invalid.errors))

    def test_overlong_audio_returns_actionable_error_without_trimming(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = os.path.join(temp_dir, "song.wav")
            self._write_tone(source, 2.0)
            result = validate_and_normalize_audio(
                source,
                temp_dir,
                target_duration_seconds=1,
                min_duration_seconds=0.5,
                max_duration_seconds=1.0,
            )
            self.assertFalse(result.valid)
            self.assertTrue(any("will not truncate" in error for error in result.errors))
            self.assertGreater(result.duration_seconds, 1.5)


class ArchiveSongPipelineTests(unittest.TestCase):
    def _stub(self) -> YouTube:
        youtube = YouTube.__new__(YouTube)
        youtube._niche = "historical mysteries"
        youtube._language = "English"
        youtube.format_type = "short"
        youtube.audio_mode = AUDIO_MODE_ARCHIVE_SONG
        youtube.archive_song_resume = False
        youtube.archive_song_episode_id = "pilot"
        youtube.archive_song_audio_path = ""
        youtube.regenerate_song_package = False
        youtube.skip_song_validation = False
        youtube.episode_number = "pilot"
        youtube.subject = "The Dancing Plague of 1518"
        youtube.images = []
        youtube.asset_modalities = []
        youtube.asset_results = []
        youtube.production_metadata = {}
        youtube.run_id = "test-run"
        youtube.archive_subtitles_path = ""
        return youtube

    def test_narration_mode_still_enters_original_pipeline(self) -> None:
        youtube = self._stub()
        youtube.audio_mode = "narration"
        marker = RuntimeError("original narration pipeline entered")
        with (
            patch.object(youtube, "_generate_archive_song_pipeline") as archive,
            patch.object(youtube, "_generate_topic_and_research", side_effect=marker),
        ):
            with self.assertRaisesRegex(RuntimeError, "original narration"):
                youtube._generate_pipeline(Mock(), interactive=False)
        archive.assert_not_called()

    def test_initial_run_pauses_before_assets(self) -> None:
        brief, package = load_fixture()
        youtube = self._stub()

        def research(**_kwargs) -> None:
            youtube.subject = brief["topic"]
            youtube.research_brief = brief
            youtube.research_notes = "source-backed"
            youtube.research_brief_path = ""

        def script() -> str:
            youtube.script = "Approved researched narration script."
            return youtube.script

        with (
            tempfile.TemporaryDirectory() as temp_dir,
            patch.object(yt_module, "load_active_brand", return_value={"brand_id": "alpha"}),
            patch.object(yt_module, "ensure_episode_directory", return_value=temp_dir),
            patch.object(
                yt_module,
                "load_resolved_archive_song_settings",
                return_value=DEFAULT_SETTINGS,
            ),
            patch.object(youtube, "_generate_topic_and_research", side_effect=research),
            patch.object(youtube, "generate_script", side_effect=script),
            patch.object(youtube, "_generate_archive_song_package", return_value=package),
            patch.object(youtube, "_generate_archive_assets") as assets,
        ):
            with self.assertRaises(AwaitingSongAudio):
                youtube._generate_archive_song_pipeline()
            state = load_state(temp_dir)
            self.assertEqual(state.status, "awaiting_song_audio")
            self.assertTrue(os.path.isfile(os.path.join(temp_dir, "README_SUNO.md")))
            assets.assert_not_called()

    def test_resume_renders_then_rerun_is_idempotent(self) -> None:
        brief, package = load_fixture()
        with tempfile.TemporaryDirectory() as temp_dir:
            imported = os.path.join(temp_dir, "song.wav")
            normalized = os.path.join(temp_dir, "production_audio.wav")
            Path(imported).write_bytes(b"operator audio")
            Path(normalized).write_bytes(b"normalized")
            state = ArchiveSongState(
                episode_id="pilot",
                brand_id="alpha",
                status="awaiting_song_audio",
                subject=brief["topic"],
                script="Approved researched narration script.",
                metadata={"title": "Pilot", "description": "Description"},
                research_brief=brief,
                song_package=package.to_dict(),
            )
            save_state(temp_dir, state)
            render_temp = os.path.join(temp_dir, "renderer-temp.mp4")
            Path(render_temp).write_bytes(b"video")
            timed = os.path.join(temp_dir, "visual_beat_map_timed.json")
            alignment = os.path.join(temp_dir, "lyrics_alignment.json")
            subtitles = os.path.join(temp_dir, "lyrics.srt")
            for path in (timed, alignment, subtitles):
                Path(path).write_text("{}", encoding="utf-8")

            validation = SongAudioValidation(
                input_path=imported,
                normalized_path=normalized,
                supported_format=True,
                decodable=True,
                duration_seconds=60,
                sample_rate_hz=44100,
                channels=2,
            )
            youtube = self._stub()
            youtube.archive_song_resume = True

            def assets(current_state, package_arg=None, settings_arg=None) -> None:
                youtube.asset_results = [AssetResult("shot.png", "image", "standard")]
                youtube.images = ["shot.png"]
                youtube.asset_modalities = ["image"]
                youtube.shot_durations = [60.0]

            with (
                patch.object(yt_module, "load_active_brand", return_value={"brand_id": "alpha"}),
                patch.object(yt_module, "ensure_episode_directory", return_value=temp_dir),
                patch.object(
                    yt_module,
                    "load_resolved_archive_song_settings",
                    return_value=DEFAULT_SETTINGS,
                ),
                patch.object(yt_module, "validate_and_normalize_audio", return_value=validation) as validate,
                patch.object(
                    yt_module,
                    "prepare_timed_beat_maps",
                    return_value=(timed, timed),
                ),
                patch.object(yt_module, "build_lyric_alignment", return_value=(alignment, subtitles)),
                patch.object(youtube, "generate_subtitles_local_whisper", side_effect=RuntimeError("offline")),
                patch.object(youtube, "_generate_archive_assets", side_effect=assets),
                patch.object(youtube, "combine", return_value=render_temp),
                patch.object(yt_module, "log_video"),
            ):
                first = youtube._generate_archive_song_pipeline()
                second = youtube._generate_archive_song_pipeline()

            self.assertEqual(first, os.path.join(temp_dir, "final_video.mp4"))
            self.assertEqual(second, first)
            self.assertEqual(validate.call_count, 1)
            self.assertEqual(load_state(temp_dir).status, "rendered")


class ArchiveSongSettingsTests(unittest.TestCase):
    def test_brand_defaults_override_config(self) -> None:
        settings = resolve_archive_song_settings(
            config_block={"target_duration_seconds": 60, "bpm_min": 70},
            brand={
                "production": {
                    "archive_song": {
                        "target_duration_seconds": 58,
                        "default_musical_direction": "brand folk cabaret",
                        "caption_style": "phrase_only",
                    }
                }
            },
        )
        self.assertEqual(settings.target_duration_seconds, 58)
        self.assertEqual(settings.default_musical_direction, "brand folk cabaret")
        self.assertEqual(settings.caption_style, "phrase_only")
        self.assertEqual(settings.bpm_min, 70)

    def test_episode_overrides_brand_defaults(self) -> None:
        settings = resolve_archive_song_settings(
            brand={
                "production": {
                    "archive_song": {
                        "target_duration_seconds": 60,
                        "default_vocal_direction": "brand vocal",
                        "default_musical_direction": "brand folk cabaret",
                    }
                }
            },
            episode_package={
                "target_duration_seconds": 57,
                "vocal_direction": "episode vocal",
                "suno_style_prompt": "episode musical direction with enough detail",
                "estimated_bpm": 96,
            },
        )
        self.assertEqual(settings.target_duration_seconds, 57)
        self.assertEqual(settings.default_vocal_direction, "episode vocal")
        # Generated Suno style text must not overwrite brand musical direction.
        self.assertEqual(settings.default_musical_direction, "brand folk cabaret")

    def test_false_and_zero_overrides_are_honored(self) -> None:
        settings = resolve_archive_song_settings(
            config_block={"show_source_on_screen": True, "min_shot_seconds": 2.0},
            brand={
                "production": {
                    "archive_song": {
                        "show_source_on_screen": False,
                        "min_shot_seconds": 0,
                        "embed_source_in_visual_prompts": False,
                    }
                }
            },
        )
        self.assertFalse(settings.show_source_on_screen)
        self.assertEqual(settings.min_shot_seconds, 0.0)
        self.assertFalse(settings.embed_source_in_visual_prompts)

    def test_cli_overrides_enforce_duration(self) -> None:
        settings = resolve_archive_song_settings(
            brand={"production": {"archive_song": {"enforce_duration": True}}},
            cli_overrides={"skip_song_validation": True},
        )
        self.assertFalse(settings.enforce_duration)


class ArchiveSongVisualPlanTests(unittest.TestCase):
    def _timed_fixture(self, temp_dir: str, audio_duration: float = 60.0) -> str:
        _, package = load_fixture()
        beats = []
        for beat in package.visual_beat_map:
            beats.append(
                {
                    "start_seconds": beat.progress_start * audio_duration,
                    "end_seconds": beat.progress_end * audio_duration,
                    "lyric_phrase": beat.lyric_phrase,
                    "historical_fact": beat.historical_fact,
                    "suggested_visual": beat.suggested_visual,
                    "camera_motion": beat.camera_motion,
                    "on_screen_text": beat.on_screen_text,
                    "source_ids": beat.source_ids,
                    "confidence": beat.confidence,
                }
            )
        path = os.path.join(temp_dir, "visual_beat_map_timed.json")
        with open(path, "w", encoding="utf-8") as file:
            json.dump(beats, file)
        return path

    def test_beat_map_prompts_and_durations_match_audio(self) -> None:
        _, package = load_fixture()
        with tempfile.TemporaryDirectory() as temp_dir:
            timed = self._timed_fixture(temp_dir, 60.0)
            plan = build_archive_shot_plan(
                audio_duration=60.0,
                timed_beat_map_path=timed,
                package_beats=package.visual_beat_map,
                subject=package.historical_topic,
                historical_topic=package.historical_topic,
                style_suffix="engraving style",
                settings=DEFAULT_SETTINGS,
                fallback_prompts=["generic lyric prompt"],
            )
        self.assertFalse(plan.used_fallback)
        self.assertEqual(plan.source, "beat_map")
        self.assertGreaterEqual(len(plan.shots), 6)
        self.assertTrue(
            any("woodcut" in shot.prompt.lower() for shot in plan.shots)
        )
        self.assertFalse(
            any("generic lyric prompt" == shot.prompt for shot in plan.shots)
        )
        durations = [shot.duration_seconds for shot in plan.shots]
        self.assertTrue(
            durations_match_audio(
                durations, 60.0, DEFAULT_SETTINGS.duration_tolerance_seconds
            )
        )
        self.assertAlmostEqual(sum(durations), 60.0, places=2)

    def test_missing_and_malformed_beat_map_fallback(self) -> None:
        missing = build_archive_shot_plan(
            audio_duration=60.0,
            timed_beat_map_path=None,
            package_beats=[],
            fallback_prompts=["fallback one", "fallback two"],
            settings=DEFAULT_SETTINGS,
        )
        self.assertTrue(missing.used_fallback)
        self.assertEqual(len(missing.shots), 2)
        self.assertIn("missing", missing.fallback_reason)

        with tempfile.TemporaryDirectory() as temp_dir:
            bad_path = os.path.join(temp_dir, "broken.json")
            Path(bad_path).write_text("{not-json", encoding="utf-8")
            malformed = build_archive_shot_plan(
                audio_duration=60.0,
                timed_beat_map_path=bad_path,
                fallback_prompts=["a", "b", "c"],
                settings=DEFAULT_SETTINGS,
            )
        self.assertTrue(malformed.used_fallback)
        self.assertEqual(len(malformed.shots), 3)

    def test_zero_length_and_overlapping_beats(self) -> None:
        beats = [
            {
                "start_seconds": 0,
                "end_seconds": 0,
                "suggested_visual": "drop me",
                "historical_fact": "fact",
                "camera_motion": "push",
                "source_ids": ["S1"],
            },
            {
                "start_seconds": 0,
                "end_seconds": 20,
                "suggested_visual": "first",
                "historical_fact": "fact one",
                "camera_motion": "push",
                "source_ids": ["S1"],
            },
            {
                "start_seconds": 10,
                "end_seconds": 40,
                "suggested_visual": "overlap",
                "historical_fact": "fact two",
                "camera_motion": "pan",
                "source_ids": ["S1"],
            },
            {
                "start_seconds": 40,
                "end_seconds": 60,
                "suggested_visual": "last",
                "historical_fact": "fact three",
                "camera_motion": "pull",
                "source_ids": ["S1"],
            },
        ]
        normalized = normalize_timed_beats(beats, 60.0, DEFAULT_SETTINGS)
        self.assertTrue(all(row["end_seconds"] > row["start_seconds"] for row in normalized))
        for index in range(1, len(normalized)):
            self.assertGreaterEqual(
                normalized[index]["start_seconds"],
                normalized[index - 1]["end_seconds"] - 1e-9,
            )
        self.assertAlmostEqual(normalized[0]["start_seconds"], 0.0)
        self.assertAlmostEqual(normalized[-1]["end_seconds"], 60.0)

    def test_short_beats_merge_and_long_beats_split(self) -> None:
        settings = ArchiveSongSettings(min_shot_seconds=3.0, max_shot_seconds=10.0)
        short_merge = normalize_timed_beats(
            [
                {
                    "start_seconds": 0,
                    "end_seconds": 1,
                    "suggested_visual": "tiny a",
                    "historical_fact": "fact a",
                    "camera_motion": "cut",
                    "source_ids": ["S1"],
                },
                {
                    "start_seconds": 1,
                    "end_seconds": 2,
                    "suggested_visual": "tiny b",
                    "historical_fact": "fact b",
                    "camera_motion": "cut",
                    "source_ids": ["S1"],
                },
                {
                    "start_seconds": 2,
                    "end_seconds": 20,
                    "suggested_visual": "hold",
                    "historical_fact": "fact c",
                    "camera_motion": "drift",
                    "source_ids": ["S1"],
                },
            ],
            20.0,
            settings,
        )
        self.assertTrue(
            all(
                (row["end_seconds"] - row["start_seconds"]) >= settings.min_shot_seconds - 1e-6
                for row in short_merge
            )
        )
        self.assertTrue(
            any("tiny a" in str(row.get("suggested_visual")) for row in short_merge)
        )

        long_split = normalize_timed_beats(
            [
                {
                    "start_seconds": 0,
                    "end_seconds": 30,
                    "suggested_visual": "long scene",
                    "historical_fact": "one fact only",
                    "camera_motion": "slow push",
                    "source_ids": ["S1"],
                }
            ],
            30.0,
            settings,
        )
        self.assertGreaterEqual(len(long_split), 3)
        self.assertTrue(all(row["historical_fact"] == "one fact only" for row in long_split))
        self.assertTrue(
            all(
                (row["end_seconds"] - row["start_seconds"]) <= settings.max_shot_seconds + 1e-6
                for row in long_split
            )
        )

    def test_embed_source_in_prompts_is_optional(self) -> None:
        _, package = load_fixture()
        with tempfile.TemporaryDirectory() as temp_dir:
            timed = self._timed_fixture(temp_dir)
            off = build_archive_shot_plan(
                audio_duration=60.0,
                timed_beat_map_path=timed,
                settings=ArchiveSongSettings(embed_source_in_visual_prompts=False),
            )
            on = build_archive_shot_plan(
                audio_duration=60.0,
                timed_beat_map_path=timed,
                settings=ArchiveSongSettings(embed_source_in_visual_prompts=True),
            )
        self.assertFalse(any("Internal provenance" in shot.prompt for shot in off.shots))
        self.assertTrue(any("Internal provenance" in shot.prompt for shot in on.shots))

    def test_ffmpeg_command_is_list_argv_for_windows_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            spaced = os.path.join(temp_dir, "episode dir")
            os.makedirs(spaced, exist_ok=True)
            source = os.path.join(spaced, "song file.wav")
            dest = os.path.join(spaced, "production_audio.wav")
            Path(source).write_bytes(b"x")
            command = build_ffmpeg_normalize_command(source, dest)
        # List argv (shell=False) keeps spaced Windows paths as single elements.
        self.assertIsInstance(command, list)
        input_arg = command[command.index("-i") + 1]
        self.assertEqual(input_arg, os.path.abspath(source))
        self.assertEqual(command[-1], os.path.abspath(dest))
        self.assertIn("song file.wav", input_arg)
        self.assertIn("episode dir", input_arg)
        self.assertFalse(any("&" in part or "|" in part for part in command))


class ArchiveSongInvalidationTests(unittest.TestCase):
    def test_explicit_song_audio_beats_directory_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            older = os.path.join(temp_dir, "song.wav")
            newer = os.path.join(temp_dir, "archive_song.mp3")
            Path(older).write_bytes(b"old")
            Path(newer).write_bytes(b"new")
            os.utime(older, (1, 1))
            os.utime(newer, (2, 2))
            explicit = os.path.join(temp_dir, "explicit.wav")
            Path(explicit).write_bytes(b"explicit")
            chosen = discover_song_audio(temp_dir, explicit_path=explicit)
            self.assertEqual(chosen, os.path.abspath(explicit))
            newest = discover_song_audio(temp_dir)
            self.assertEqual(newest, os.path.abspath(newer))

    def test_import_replacement_invalidates_derived_outputs(self) -> None:
        brief, package = load_fixture()
        with tempfile.TemporaryDirectory() as temp_dir:
            first = os.path.join(temp_dir, "song.wav")
            second = os.path.join(temp_dir, "archive_song.wav")
            Path(first).write_bytes(b"first-audio-bytes")
            Path(second).write_bytes(b"replacement-audio-bytes-different")
            state = ArchiveSongState(
                episode_id="pilot",
                brand_id="alpha",
                status="rendered",
                subject=brief["topic"],
                script="script",
                research_brief=brief,
                song_package=package.to_dict(),
                imported_audio_path=first,
                imported_audio_identity=compute_file_identity(first),
                package_lyrics_hash=lyrics_content_hash(package.lyrics.text),
                timed_beat_map_path=os.path.join(temp_dir, "visual_beat_map_normalized.json"),
                caption_alignment_path=os.path.join(temp_dir, "lyrics_alignment.json"),
                subtitles_path=os.path.join(temp_dir, "lyrics.srt"),
                image_prompts=["one"],
                shot_durations=[60.0],
                assets=[{"path": "shot.png"}],
                rendered_video_path=os.path.join(temp_dir, "final_video.mp4"),
                normalized_audio_path=os.path.join(temp_dir, "production_audio.wav"),
            )
            for path in (
                state.timed_beat_map_path,
                state.caption_alignment_path,
                state.subtitles_path,
                state.rendered_video_path,
                state.normalized_audio_path,
            ):
                Path(path).write_text("{}", encoding="utf-8")
            save_state(temp_dir, state)

            identity = compute_file_identity(second)
            self.assertFalse(identities_match(identity, state.imported_audio_identity))
            invalidate_audio_dependent_outputs(state)
            self.assertEqual(state.timed_beat_map_path, "")
            self.assertEqual(state.caption_alignment_path, "")
            self.assertEqual(state.rendered_video_path, "")
            self.assertEqual(state.assets, [])
            # Original import files remain on disk.
            self.assertTrue(os.path.isfile(first))
            self.assertTrue(os.path.isfile(second))

    def test_original_import_is_not_overwritten_on_resume(self) -> None:
        brief, package = load_fixture()
        with tempfile.TemporaryDirectory() as temp_dir:
            archive_song = os.path.join(temp_dir, "archive_song.wav")
            song_wav = os.path.join(temp_dir, "song.wav")
            Path(archive_song).write_bytes(b"keep-me-archive")
            Path(song_wav).write_bytes(b"keep-me-song")
            before_archive = Path(archive_song).read_bytes()
            before_song = Path(song_wav).read_bytes()
            normalized = os.path.join(temp_dir, "production_audio.wav")
            Path(normalized).write_bytes(b"normalized")
            state = ArchiveSongState(
                episode_id="pilot",
                brand_id="alpha",
                status="awaiting_song_audio",
                subject=brief["topic"],
                script="script",
                metadata={"title": "t", "description": "d"},
                research_brief=brief,
                song_package=package.to_dict(),
            )
            save_state(temp_dir, state)
            validation = SongAudioValidation(
                input_path=archive_song,
                normalized_path=normalized,
                supported_format=True,
                decodable=True,
                duration_seconds=60,
                sample_rate_hz=44100,
                channels=2,
            )
            youtube = YouTube.__new__(YouTube)
            youtube._niche = "historical mysteries"
            youtube._language = "English"
            youtube.format_type = "short"
            youtube.audio_mode = AUDIO_MODE_ARCHIVE_SONG
            youtube.archive_song_resume = True
            youtube.archive_song_episode_id = "pilot"
            youtube.archive_song_audio_path = ""
            youtube.regenerate_song_package = False
            youtube.skip_song_validation = False
            youtube.episode_number = "pilot"
            youtube.subject = brief["topic"]
            youtube.images = []
            youtube.asset_modalities = []
            youtube.asset_results = []
            youtube.production_metadata = {}
            youtube.archive_subtitles_path = ""
            youtube.run_id = "test-run"
            youtube.experiment_metadata = {}
            render_temp = os.path.join(temp_dir, "renderer-temp.mp4")
            Path(render_temp).write_bytes(b"video")

            def assets(current_state, package_arg=None, settings_arg=None) -> None:
                youtube.asset_results = [AssetResult("shot.png", "image", "standard")]
                youtube.images = ["shot.png"]
                youtube.asset_modalities = ["image"]
                youtube.shot_durations = [60.0]

            with (
                patch.object(yt_module, "load_active_brand", return_value={"brand_id": "alpha"}),
                patch.object(yt_module, "ensure_episode_directory", return_value=temp_dir),
                patch.object(
                    yt_module,
                    "load_resolved_archive_song_settings",
                    return_value=DEFAULT_SETTINGS,
                ),
                patch.object(yt_module, "validate_and_normalize_audio", return_value=validation),
                patch.object(
                    yt_module,
                    "prepare_timed_beat_maps",
                    return_value=(
                        os.path.join(temp_dir, "visual_beat_map_timed.json"),
                        os.path.join(temp_dir, "visual_beat_map_normalized.json"),
                    ),
                ),
                patch.object(
                    yt_module,
                    "build_lyric_alignment",
                    return_value=(
                        os.path.join(temp_dir, "lyrics_alignment.json"),
                        os.path.join(temp_dir, "lyrics.srt"),
                    ),
                ),
                patch.object(youtube, "generate_subtitles_local_whisper", side_effect=RuntimeError("offline")),
                patch.object(youtube, "_generate_archive_assets", side_effect=assets),
                patch.object(youtube, "combine", return_value=render_temp),
                patch.object(yt_module, "log_video"),
                patch.object(youtube, "_build_experiment_metadata", return_value={}),
                patch.object(youtube, "_research_metadata", return_value={}),
            ):
                youtube._generate_archive_song_pipeline()

            self.assertEqual(Path(archive_song).read_bytes(), before_archive)
            self.assertEqual(Path(song_wav).read_bytes(), before_song)
            restored = load_state(temp_dir)
            # Newest accepted candidate is used without rewriting song.wav.
            self.assertTrue(
                restored.imported_audio_path.endswith("archive_song.wav")
                or restored.imported_audio_path.endswith("song.wav")
            )

    def test_manual_alignment_survives_resume_when_audio_unchanged(self) -> None:
        brief, package = load_fixture()
        with tempfile.TemporaryDirectory() as temp_dir:
            song = os.path.join(temp_dir, "song.wav")
            Path(song).write_bytes(b"stable-audio")
            normalized = os.path.join(temp_dir, "production_audio.wav")
            Path(normalized).write_bytes(b"normalized")
            alignment = os.path.join(temp_dir, "lyrics_alignment.json")
            subtitles = os.path.join(temp_dir, "lyrics.srt")
            Path(alignment).write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "entries": [
                            {
                                "index": 1,
                                "start_seconds": 0.0,
                                "end_seconds": 60.0,
                                "text": "MANUAL EDIT",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            Path(subtitles).write_text("1\n00:00:00,000 --> 00:01:00,000\nMANUAL EDIT\n", encoding="utf-8")
            timed = os.path.join(temp_dir, "visual_beat_map_normalized.json")
            Path(timed).write_text("[]", encoding="utf-8")
            state = ArchiveSongState(
                episode_id="pilot",
                brand_id="alpha",
                status="audio_ready",
                subject=brief["topic"],
                script="script",
                metadata={"title": "t", "description": "d"},
                research_brief=brief,
                song_package=package.to_dict(),
                imported_audio_path=song,
                imported_audio_identity=compute_file_identity(song),
                package_lyrics_hash=lyrics_content_hash(package.lyrics.text),
                normalized_audio_path=normalized,
                timed_beat_map_path=timed,
                caption_alignment_path=alignment,
                subtitles_path=subtitles,
            )
            save_state(temp_dir, state)
            youtube = YouTube.__new__(YouTube)
            youtube._niche = "historical mysteries"
            youtube._language = "English"
            youtube.format_type = "short"
            youtube.audio_mode = AUDIO_MODE_ARCHIVE_SONG
            youtube.archive_song_resume = True
            youtube.archive_song_episode_id = "pilot"
            youtube.archive_song_audio_path = ""
            youtube.regenerate_song_package = False
            youtube.skip_song_validation = False
            youtube.episode_number = "pilot"
            youtube.subject = brief["topic"]
            youtube.images = []
            youtube.asset_modalities = []
            youtube.asset_results = []
            youtube.production_metadata = {}
            youtube.archive_subtitles_path = ""
            youtube.run_id = "test-run"
            youtube.experiment_metadata = {}
            render_temp = os.path.join(temp_dir, "renderer-temp.mp4")
            Path(render_temp).write_bytes(b"video")
            validation = SongAudioValidation(
                input_path=song,
                normalized_path=normalized,
                supported_format=True,
                decodable=True,
                duration_seconds=60,
                sample_rate_hz=44100,
                channels=2,
            )

            def assets(current_state, package_arg=None, settings_arg=None) -> None:
                youtube.asset_results = [AssetResult("shot.png", "image", "standard")]
                youtube.images = ["shot.png"]
                youtube.asset_modalities = ["image"]
                youtube.shot_durations = [60.0]

            with (
                patch.object(yt_module, "load_active_brand", return_value={"brand_id": "alpha"}),
                patch.object(yt_module, "ensure_episode_directory", return_value=temp_dir),
                patch.object(
                    yt_module,
                    "load_resolved_archive_song_settings",
                    return_value=DEFAULT_SETTINGS,
                ),
                patch.object(yt_module, "validate_and_normalize_audio", return_value=validation),
                patch.object(yt_module, "build_lyric_alignment") as rebuild,
                patch.object(youtube, "_generate_archive_assets", side_effect=assets),
                patch.object(youtube, "combine", return_value=render_temp),
                patch.object(yt_module, "log_video"),
                patch.object(youtube, "_build_experiment_metadata", return_value={}),
                patch.object(youtube, "_research_metadata", return_value={}),
            ):
                youtube._generate_archive_song_pipeline()

            rebuild.assert_not_called()
            with open(alignment, "r", encoding="utf-8") as file:
                payload = json.load(file)
            self.assertEqual(payload["entries"][0]["text"], "MANUAL EDIT")

    def test_frame_snapping_preserves_total(self) -> None:
        snapped = snap_durations_to_frames([1.004, 2.004, 3.0], total_seconds=6.0, fps=30.0)
        self.assertAlmostEqual(sum(snapped), 6.0, places=5)
        frame = 1.0 / 30.0
        for value in snapped:
            self.assertAlmostEqual(value / frame, round(value / frame), places=5)

    def test_normalized_beat_map_is_written_for_captions_and_shots(self) -> None:
        _, package = load_fixture()
        with tempfile.TemporaryDirectory() as temp_dir:
            raw_path, normalized_path = prepare_timed_beat_maps(
                temp_dir,
                package.visual_beat_map,
                60.0,
                DEFAULT_SETTINGS,
            )
            self.assertTrue(os.path.isfile(raw_path))
            self.assertTrue(os.path.isfile(normalized_path))
            self.assertIn("normalized", os.path.basename(normalized_path))
            with open(normalized_path, "r", encoding="utf-8") as file:
                beats = json.load(file)
            self.assertGreaterEqual(len(beats), 2)
            self.assertAlmostEqual(beats[0]["start_seconds"], 0.0)
            self.assertAlmostEqual(beats[-1]["end_seconds"], 60.0)

    def test_ffmpeg_failure_leaves_no_valid_derived_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = os.path.join(temp_dir, "song.wav")
            Path(source).write_text("not-audio", encoding="utf-8")
            production = os.path.join(temp_dir, "production_audio.wav")
            Path(production).write_bytes(b"stale-derived")
            result = validate_and_normalize_audio(
                source,
                temp_dir,
                target_duration_seconds=1,
                min_duration_seconds=0.1,
                max_duration_seconds=2,
            )
            self.assertFalse(result.valid)
            # Failed normalize must not accept a partial temp as production audio.
            self.assertFalse(bool(result.normalized_path))
            self.assertFalse(
                os.path.isfile(os.path.join(temp_dir, "production_audio.tmp.wav"))
            )


class ArchiveSongCliTests(unittest.TestCase):
    def test_cli_argument_parsing(self) -> None:
        from scripts.run_brand_short import build_parser

        args = build_parser().parse_args(
            [
                "alpha",
                "--audio-mode",
                "archive-song",
                "--episode",
                "42",
                "--resume",
                "--song-audio",
                "candidate.mp3",
                "--regenerate-song-package",
                "--skip-song-validation",
            ]
        )
        self.assertEqual(args.brand_id, "alpha")
        self.assertEqual(args.audio_mode, "archive-song")
        self.assertTrue(args.resume)
        self.assertEqual(args.episode, "42")
        self.assertTrue(args.skip_song_validation)


if __name__ == "__main__":
    unittest.main()
