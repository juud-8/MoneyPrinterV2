"""Offline tests for shared media-provider contracts and legacy adapters."""

import json
import importlib.util
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path, PureWindowsPath
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from archive_song import compute_file_identity, lyrics_content_hash
from media_providers import (
    AssetProvenance,
    ElevenLabsNarrationAdapter,
    GenerationRequest,
    HealthState,
    HumanApprovalState,
    ProviderCapabilities,
    ProviderConfigurationError,
    ProviderHealth,
    ProviderKind,
    ProviderRegistry,
    ProviderRegistryEntry,
    ProviderUnavailableError,
    SongCandidate,
    UnknownProviderError,
    VideoResult,
    VoiceDescriptor,
    create_asset_provenance,
    elevenlabs_registry_entry,
    sha256_file,
    sha256_text,
)
from media_providers.errors import ProviderGenerationError


class ProviderContractTests(unittest.TestCase):
    def test_generation_request_rejects_untrusted_empty_content(self) -> None:
        with self.assertRaisesRegex(ValueError, "content"):
            GenerationRequest(content=" ", output_path="voice.mp3")

    def test_provider_capabilities_validate_provider_id_and_kind(self) -> None:
        capabilities = ProviderCapabilities(
            provider_id="local_worker-1",
            kinds=(ProviderKind.AUDIO, ProviderKind.VIDEO),
            output_formats=("WAV", ".MP4"),
            is_local=True,
            requires_network=False,
        )
        self.assertEqual(capabilities.output_formats, ("wav", "mp4"))
        self.assertEqual(
            capabilities.to_dict()["kinds"],
            ["audio", "video"],
        )
        with self.assertRaisesRegex(ValueError, "provider_id"):
            ProviderCapabilities(provider_id="Bad Provider", kinds=(ProviderKind.AUDIO,))

    def test_health_states_have_stable_usable_semantics(self) -> None:
        self.assertTrue(ProviderHealth(HealthState.READY, "ready").usable)
        self.assertTrue(ProviderHealth(HealthState.DEGRADED, "fallback active").usable)
        self.assertFalse(
            ProviderHealth(HealthState.MISCONFIGURED, "missing config").usable
        )
        self.assertFalse(ProviderHealth(HealthState.UNAVAILABLE, "offline").usable)

    def test_windows_path_survives_json_round_trip(self) -> None:
        windows_path = PureWindowsPath(
            r"C:\Media Work\episodes\dancing-plague\narration.mp3"
        )
        request = GenerationRequest(
            content="A factual narration.",
            output_path=windows_path,
            voice=VoiceDescriptor(provider="elevenlabs", voice_id="voice-test"),
        )
        payload = json.loads(json.dumps(request.to_dict()))
        restored = GenerationRequest.from_dict(payload)
        self.assertEqual(str(restored.output_path), str(windows_path))
        self.assertEqual(restored.voice.voice_id, "voice-test")

    def test_song_candidate_and_video_result_validate_media_metadata(self) -> None:
        provenance = AssetProvenance(provider="local-worker", engine="test-engine")
        song = SongCandidate(
            candidate_id="candidate-1",
            provider_id="local-worker",
            output_path=PureWindowsPath(r"C:\Media\candidate.wav"),
            provenance=provenance,
            duration_seconds=60.0,
        )
        video = VideoResult(
            provider_id="local-worker",
            output_path=PureWindowsPath(r"C:\Media\shot.mp4"),
            provenance=provenance,
            duration_seconds=5.0,
            width=1080,
            height=1920,
            fps=30.0,
        )
        self.assertEqual(song.duration_seconds, 60.0)
        self.assertEqual((video.width, video.height, video.fps), (1080, 1920, 30.0))
        with self.assertRaisesRegex(ValueError, "duration"):
            SongCandidate(
                candidate_id="bad",
                provider_id="local-worker",
                output_path="candidate.wav",
                provenance=provenance,
                duration_seconds=0,
            )


class ProvenanceTests(unittest.TestCase):
    def test_provenance_serializes_all_identity_and_approval_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir, "voice.mp3")
            output.write_bytes(b"derived audio")
            source_hash = sha256_text("source artifact")
            request = GenerationRequest(
                content="Narration text",
                output_path=output,
                settings={"pace": 1.0},
                seed=42,
                parent_artifact="parent:research-brief",
                retry_count=2,
                fallback_behavior="reuse last approved narration",
            )
            provenance = create_asset_provenance(
                request,
                provider="elevenlabs",
                engine="legacy-tts",
                model="eleven_multilingual_v2",
                model_version="2026-01",
                output_path=output,
                source_artifact_hash=source_hash,
                human_approval_state=HumanApprovalState.APPROVED,
            )

            payload = json.loads(json.dumps(provenance.to_dict()))
            restored = AssetProvenance.from_dict(payload)

            self.assertEqual(restored, provenance)
            self.assertEqual(restored.input_content_hash, sha256_text("Narration text"))
            self.assertEqual(restored.source_artifact_hash, source_hash)
            self.assertEqual(restored.derived_artifact_hash, sha256_file(output))
            self.assertEqual(restored.human_approval_state, HumanApprovalState.APPROVED)
            self.assertEqual(restored.retry_count, 2)
            self.assertEqual(restored.fallback_behavior, "reuse last approved narration")
            self.assertNotIn("Narration text", json.dumps(payload))

    def test_invalid_provenance_hash_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            AssetProvenance(
                provider="test",
                engine="engine",
                request_hash="not-a-hash",
            )

    def test_archive_song_identity_reuses_shared_sha256(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir, "archive_song.wav")
            path.write_bytes(b"operator-owned archive song")
            identity = compute_file_identity(str(path))
            self.assertEqual(
                set(identity),
                {"path", "size", "mtime_ns", "sha256"},
            )
            self.assertEqual(identity["sha256"], sha256_file(path))
            self.assertEqual(lyrics_content_hash("lyrics"), sha256_text("lyrics"))


class _FakeAudioProvider:
    provider_id = "fake-audio"

    def health(self):
        return ProviderHealth(HealthState.READY, "ready")

    def capabilities(self):
        return ProviderCapabilities(self.provider_id, (ProviderKind.AUDIO,))

    def generate(self, request):
        raise AssertionError("not used")


class ProviderRegistryTests(unittest.TestCase):
    def test_registry_registers_lists_and_creates_provider(self) -> None:
        registry = ProviderRegistry()
        entry = ProviderRegistryEntry(
            provider_id="fake-audio",
            kind=ProviderKind.AUDIO,
            factory=_FakeAudioProvider,
        )
        registry.register(entry)
        self.assertEqual(registry.entries(ProviderKind.AUDIO), (entry,))
        self.assertIsInstance(registry.create("audio", "FAKE-AUDIO"), _FakeAudioProvider)

    def test_registry_rejects_duplicate_and_unknown_provider(self) -> None:
        registry = ProviderRegistry()
        entry = ProviderRegistryEntry(
            provider_id="fake-audio",
            kind=ProviderKind.AUDIO,
            factory=_FakeAudioProvider,
        )
        registry.register(entry)
        with self.assertRaises(ProviderConfigurationError):
            registry.register(entry)
        with self.assertRaises(UnknownProviderError) as raised:
            registry.create(ProviderKind.VIDEO, "missing")
        self.assertEqual(raised.exception.kind, "video")

    def test_disabled_provider_is_not_created(self) -> None:
        factory = Mock(side_effect=AssertionError("must not instantiate"))
        registry = ProviderRegistry()
        registry.register(
            ProviderRegistryEntry(
                provider_id="fake-audio",
                kind=ProviderKind.AUDIO,
                factory=factory,
                enabled=False,
            )
        )
        with self.assertRaises(ProviderUnavailableError):
            registry.create(ProviderKind.AUDIO, "fake-audio")
        factory.assert_not_called()


class _LegacyTTS:
    def __init__(self, *, fail: bool = False):
        self.fail = fail
        self.calls = []

    def _synthesize_elevenlabs(self, text: str, output_file: str) -> str:
        self.calls.append((text, output_file))
        if self.fail:
            raise RuntimeError("offline failure")
        output = output_file if output_file.endswith(".mp3") else output_file.replace(".wav", ".mp3")
        Path(output).write_bytes(b"existing elevenlabs bytes")
        return output


class ElevenLabsAdapterTests(unittest.TestCase):
    def _configured(self):
        return patch.multiple(
            "media_providers.elevenlabs_adapter",
            get_elevenlabs_api_key=Mock(return_value="api-secret"),
            get_elevenlabs_voice_id=Mock(return_value="voice-account-id"),
            get_elevenlabs_model=Mock(return_value="eleven_multilingual_v2"),
        )

    def test_adapter_preserves_existing_call_and_output_behavior(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, self._configured():
            legacy = _LegacyTTS()
            adapter = ElevenLabsNarrationAdapter(legacy)
            requested = str(Path(temp_dir, "narration.wav"))
            result = adapter.generate(
                GenerationRequest(
                    content="Exact existing narration text.",
                    output_path=requested,
                )
            )

            self.assertEqual(legacy.calls, [("Exact existing narration text.", requested)])
            self.assertEqual(result.output_path, requested.replace(".wav", ".mp3"))
            self.assertEqual(result.provenance.provider, "elevenlabs")
            self.assertEqual(result.provenance.derived_artifact_hash, sha256_file(result.output_path))
            serialized = json.dumps(result.to_dict())
            self.assertNotIn("api-secret", serialized)
            self.assertNotIn("voice-account-id", serialized)

    def test_invalid_provider_configuration_is_offline_and_actionable(self) -> None:
        with patch.multiple(
            "media_providers.elevenlabs_adapter",
            get_elevenlabs_api_key=Mock(return_value=""),
            get_elevenlabs_voice_id=Mock(return_value=""),
            get_elevenlabs_model=Mock(return_value="eleven_multilingual_v2"),
        ):
            adapter = ElevenLabsNarrationAdapter(_LegacyTTS())
            self.assertEqual(adapter.health().state, HealthState.MISCONFIGURED)
            with self.assertRaisesRegex(ProviderConfigurationError, "api key"):
                adapter.generate(
                    GenerationRequest(content="text", output_path="narration.wav")
                )

    def test_generation_failure_is_wrapped_without_fallback_side_effects(self) -> None:
        with self._configured():
            adapter = ElevenLabsNarrationAdapter(_LegacyTTS(fail=True))
            with self.assertRaises(ProviderGenerationError) as raised:
                adapter.generate(
                    GenerationRequest(content="text", output_path="narration.wav")
                )
            self.assertTrue(raised.exception.retryable)

    def test_registry_entry_defers_legacy_tts_creation(self) -> None:
        factory = Mock(return_value=_LegacyTTS())
        registry = ProviderRegistry()
        registry.register(elevenlabs_registry_entry(factory))
        factory.assert_not_called()
        provider = registry.create(ProviderKind.AUDIO, "elevenlabs")
        self.assertIsInstance(provider, ElevenLabsNarrationAdapter)
        factory.assert_called_once_with()


class ExistingNarrationRegressionTests(unittest.TestCase):
    @staticmethod
    def _load_tts_class():
        """Load the legacy dispatcher without importing the heavyweight model runtime."""

        fake_kittentts = types.ModuleType("kittentts")
        fake_kittentts.KittenTTS = object
        fake_soundfile = types.ModuleType("soundfile")
        fake_soundfile.write = Mock()
        module_path = Path(__file__).parents[1] / "src" / "classes" / "Tts.py"
        spec = importlib.util.spec_from_file_location("_offline_legacy_tts", module_path)
        module = importlib.util.module_from_spec(spec)
        with patch.dict(
            sys.modules,
            {"kittentts": fake_kittentts, "soundfile": fake_soundfile},
        ):
            spec.loader.exec_module(module)
        return module.TTS

    def test_existing_tts_dispatch_still_calls_elevenlabs_directly(self) -> None:
        TTS = self._load_tts_class()
        tts = TTS.__new__(TTS)
        tts._provider = "elevenlabs"
        tts._synthesize_elevenlabs = Mock(return_value="narration.mp3")
        tts._fallback_to_kitten = Mock()

        result = TTS.synthesize(tts, "Existing script", "narration.wav")

        self.assertEqual(result, "narration.mp3")
        tts._synthesize_elevenlabs.assert_called_once_with(
            "Existing script", "narration.wav"
        )
        tts._fallback_to_kitten.assert_not_called()

    def test_existing_tts_dispatch_retains_kitten_fallback(self) -> None:
        TTS = self._load_tts_class()
        tts = TTS.__new__(TTS)
        tts._provider = "elevenlabs"
        failure = RuntimeError("quota")
        tts._synthesize_elevenlabs = Mock(side_effect=failure)
        tts._fallback_to_kitten = Mock(return_value="narration.wav")

        result = TTS.synthesize(tts, "Existing script", "narration.wav")

        self.assertEqual(result, "narration.wav")
        tts._fallback_to_kitten.assert_called_once_with(
            "ElevenLabs", failure, "narration.wav", "Existing script"
        )


if __name__ == "__main__":
    unittest.main()
