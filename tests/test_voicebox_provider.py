"""Offline Voicebox client/provider tests; no local service or model is used."""

from __future__ import annotations

import io
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path, PureWindowsPath
from types import SimpleNamespace
from unittest.mock import Mock, patch

import requests


sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from media_providers import (
    GenerationRequest,
    HealthState,
    ProviderConfigurationError,
    VoiceboxAudioProvider,
    VoiceboxAuthenticationError,
    VoiceboxGenerationError,
    VoiceboxHealthCheckError,
    VoiceboxInvalidAudioError,
    VoiceboxInvalidEngineError,
    VoiceboxInvalidProfileError,
    VoiceboxMalformedResponseError,
    VoiceboxMissingResultError,
    VoiceboxNormalizationError,
    VoiceboxRequestTimeoutError,
    VoiceboxServiceUnavailableError,
    VoiceboxSettings,
    VoiceboxUnsupportedCapabilityError,
    VoiceboxUnsupportedTagError,
    VoiceboxVersionIncompatibilityError,
    capabilities_for_engine,
    prepare_performance_tags,
    resolve_audio_provider_settings,
    sha256_file,
)
from media_providers.audio_assets import (
    inspect_audio,
    normalize_production_audio,
)
from media_providers.voicebox_client import VoiceboxClient
from media_providers.voicebox_schemas import (
    VoiceboxAudioDownload,
    VoiceboxGeneration,
    VoiceboxHealth,
    VoiceboxModelStatus,
    VoiceboxProfile,
    VoiceboxServerInfo,
)
import config


def wav_bytes(*, sample_rate: int = 44_100, channels: int = 2, frames: int = 441) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(b"\x00\x00" * channels * frames)
    return output.getvalue()


class FakeResponse:
    def __init__(
        self,
        status_code: int = 200,
        payload=None,
        *,
        content: bytes = b"",
        headers: dict | None = None,
        text: str = "",
    ):
        self.status_code = status_code
        self._payload = payload
        self.content = content
        self.headers = headers or {}
        self.text = text

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class QueueSession:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class Clock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value

    def sleep(self, seconds):
        self.value += seconds


def profile_json(**overrides):
    value = {
        "id": "profile-123",
        "name": "Archive Narrator",
        "language": "en",
        "voice_type": "cloned",
        "preset_engine": None,
        "default_engine": "qwen",
        "updated_at": "2026-07-15T12:00:00Z",
        "sample_count": 1,
    }
    value.update(overrides)
    return value


def generation_json(**overrides):
    value = {
        "id": "generation-1",
        "profile_id": "profile-123",
        "status": "generating",
        "engine": "qwen",
        "model_size": "1.7B",
        "audio_path": None,
        "duration": 0,
        "seed": None,
        "error": None,
    }
    value.update(overrides)
    return value


class VoiceboxClientTests(unittest.TestCase):
    def make_client(self, session, **overrides):
        return VoiceboxClient(
            "http://127.0.0.1:17493",
            session=session,
            health_timeout_seconds=overrides.get("health_timeout_seconds", 2),
            request_timeout_seconds=overrides.get("request_timeout_seconds", 10),
            poll_interval_seconds=overrides.get("poll_interval_seconds", 0.1),
            clock=overrides.get("clock", lambda: 0.0),
            sleeper=overrides.get("sleeper", lambda _seconds: None),
        )

    def test_health_and_profile_discovery_parse_verified_shapes(self):
        session = QueueSession(
            FakeResponse(
                payload={
                    "status": "healthy",
                    "model_loaded": False,
                    "model_downloaded": True,
                    "gpu_available": True,
                    "backend_type": "pytorch",
                }
            ),
            FakeResponse(payload=[profile_json()]),
        )
        client = self.make_client(session)

        health = client.health()
        profiles = client.list_profiles()

        self.assertEqual(health.status, "healthy")
        self.assertFalse(health.model_loaded)
        self.assertEqual(profiles[0].name, "Archive Narrator")
        self.assertEqual(session.calls[0][2]["timeout"], 2.0)

    def test_runtime_openapi_supplies_version_when_root_may_serve_spa(self):
        session = QueueSession(
            FakeResponse(payload={"info": {"title": "voicebox API", "version": "0.5.0"}})
        )
        info = self.make_client(session).server_info()
        self.assertEqual(info.version, "0.5.0")
        self.assertTrue(session.calls[0][1].endswith("/openapi.json"))

    def test_health_unavailable_and_timeout_are_actionable(self):
        unavailable = self.make_client(QueueSession(requests.ConnectionError("refused")))
        with self.assertRaisesRegex(VoiceboxServiceUnavailableError, "not reachable"):
            unavailable.server_info()

        timeout = self.make_client(QueueSession(requests.Timeout("slow")))
        with self.assertRaises(VoiceboxHealthCheckError):
            timeout.health()

    def test_authentication_and_nonretryable_http_errors_are_typed(self):
        client = self.make_client(QueueSession(FakeResponse(401, {"detail": "denied"})))
        with self.assertRaises(VoiceboxAuthenticationError):
            client.list_profiles()

        client = self.make_client(QueueSession(FakeResponse(422, {"detail": "bad payload"})))
        with self.assertRaises(VoiceboxGenerationError) as raised:
            client.submit_generation({"text": "test"})
        self.assertFalse(raised.exception.retryable)

    def test_async_generation_polls_history_then_downloads_audio(self):
        session = QueueSession(
            FakeResponse(payload=generation_json(status="generating")),
            FakeResponse(
                payload=generation_json(
                    status="completed", audio_path="generations/generation-1.wav", duration=1.2
                )
            ),
            FakeResponse(
                content=wav_bytes(), headers={"Content-Type": "audio/wav"}
            ),
        )
        clock = Clock()
        client = self.make_client(session, clock=clock, sleeper=clock.sleep)

        submitted = client.submit_generation(
            {"profile_id": "profile-123", "text": "UTF-8: déjà vu — 東京"}
        )
        completed = client.wait_for_generation(submitted)
        audio = client.download_audio(completed.id)

        self.assertEqual(completed.status, "completed")
        self.assertEqual(audio.content_type, "audio/wav")
        self.assertIn("déjà vu", session.calls[0][2]["json"]["text"])
        self.assertTrue(session.calls[1][1].endswith("/history/generation-1"))
        self.assertTrue(session.calls[2][1].endswith("/audio/generation-1"))

    def test_poll_timeout_requests_cancellation_and_cleans_up_control_flow(self):
        session = QueueSession(
            FakeResponse(payload=generation_json(status="generating")),
            FakeResponse(payload=generation_json(status="generating")),
            FakeResponse(payload={"message": "Generation cancellation requested"}),
        )
        clock = Clock()
        client = self.make_client(
            session,
            clock=clock,
            sleeper=clock.sleep,
            request_timeout_seconds=0.2,
            poll_interval_seconds=0.2,
        )
        submitted = client.submit_generation({"profile_id": "profile-123", "text": "test"})
        with self.assertRaises(VoiceboxRequestTimeoutError):
            client.wait_for_generation(submitted)
        self.assertTrue(session.calls[-1][1].endswith("/generate/generation-1/cancel"))

    def test_malformed_and_missing_results_fail_explicitly(self):
        malformed = self.make_client(
            QueueSession(FakeResponse(payload=ValueError("not json")))
        )
        with self.assertRaises(VoiceboxMalformedResponseError):
            malformed.list_profiles()

        empty = self.make_client(QueueSession(FakeResponse(content=b"")))
        with self.assertRaises(VoiceboxMissingResultError):
            empty.download_audio("generation-1")


class VoiceboxSettingsTests(unittest.TestCase):
    def test_precedence_preserves_false_zero_null_and_empty_semantics(self):
        settings = resolve_audio_provider_settings(
            legacy_provider="elevenlabs",
            global_audio={
                "provider": "voicebox",
                "allow_fallback": True,
                "fallback_provider": "elevenlabs",
                "voicebox": {
                    "profile": "global",
                    "engine": "qwen",
                    "max_retries": 2,
                    "crossfade_ms": 50,
                    "normalize": True,
                },
            },
            brand_audio={
                "allow_fallback": False,
                "voicebox": {
                    "profile": "brand",
                    "engine": None,
                    "max_retries": 0,
                    "crossfade_ms": 0,
                    "normalize": False,
                },
            },
        )
        self.assertEqual(settings.provider, "voicebox")
        self.assertFalse(settings.allow_fallback)
        self.assertEqual(settings.voicebox.profile, "brand")
        self.assertIsNone(settings.voicebox.engine)
        self.assertEqual(settings.voicebox.max_retries, 0)
        self.assertEqual(settings.voicebox.crossfade_ms, 0)
        self.assertFalse(settings.voicebox.normalize)

        with self.assertRaisesRegex(ProviderConfigurationError, "profile is empty"):
            resolve_audio_provider_settings(
                legacy_provider="elevenlabs",
                global_audio={"provider": "voicebox", "voicebox": {"profile": ""}},
            )

    def test_legacy_default_and_unknown_keys(self):
        selection = resolve_audio_provider_settings(legacy_provider="ElevenLabs")
        self.assertEqual(selection.provider, "elevenlabs")
        self.assertFalse(selection.allow_fallback)
        with self.assertRaisesRegex(ProviderConfigurationError, "Unknown audio.voicebox"):
            VoiceboxSettings.from_mapping({"profile": "test", "engin": "qwen"})
        with self.assertRaisesRegex(ProviderConfigurationError, "does not accept effects preset"):
            VoiceboxSettings.from_mapping(
                {"profile": "test", "effects_preset": "Radio"}
            )

    def test_remote_or_ambiguous_base_urls_are_rejected(self):
        for value in (
            "https://127.0.0.1:17493",
            "http://voicebox.example:17493",
            "http://127.0.0.1",
            "http://user:pass@127.0.0.1:17493",
        ):
            with self.subTest(value=value), self.assertRaises(ProviderConfigurationError):
                VoiceboxSettings.from_mapping({"profile": "test", "base_url": value})

    def test_repository_config_resolves_global_brand_episode_cli_precedence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            Path(temp_dir, "config.json").write_text(
                json.dumps(
                    {
                        "tts_provider": "elevenlabs",
                        "audio": {
                            "provider": "voicebox",
                            "voicebox": {"profile": "global", "engine": "qwen"},
                        },
                    }
                ),
                encoding="utf-8",
            )
            with patch.object(config, "ROOT_DIR", temp_dir), patch(
                "brand_switcher.load_active_brand",
                return_value={
                    "production": {"audio": {"voicebox": {"profile": "brand"}}}
                },
            ):
                resolved = config.get_audio_provider_settings(
                    {"voicebox": {"profile": "episode"}},
                    {"voicebox": {"profile": "cli", "engine": None}},
                )
                selected = config.get_tts_provider()
        self.assertEqual(selected, "voicebox")
        self.assertEqual(resolved.voicebox.profile, "cli")
        self.assertIsNone(resolved.voicebox.engine)

    def test_repository_config_keeps_legacy_provider_when_audio_is_absent(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            Path(temp_dir, "config.json").write_text(
                json.dumps({"tts_provider": "FishAudio"}), encoding="utf-8"
            )
            with patch.object(config, "ROOT_DIR", temp_dir), patch(
                "brand_switcher.load_active_brand", return_value={"production": {}}
            ):
                self.assertEqual(config.get_tts_provider(), "fishaudio")


class VoiceboxCapabilityTests(unittest.TestCase):
    def test_capability_map_is_conservative_and_engine_specific(self):
        qwen = capabilities_for_engine("qwen")
        custom = capabilities_for_engine("qwen_custom_voice")
        turbo = capabilities_for_engine("chatterbox_turbo")
        self.assertTrue(qwen.voice_cloning)
        self.assertFalse(qwen.delivery_instructions)
        self.assertTrue(custom.preset_voices)
        self.assertTrue(custom.delivery_instructions)
        self.assertTrue(turbo.paralinguistic_tags)
        with self.assertRaises(VoiceboxInvalidEngineError):
            capabilities_for_engine("qwen3-tts")

    def test_supported_and_unsupported_performance_tags(self):
        original = "The witness paused. [sigh] Then the bell rang."
        supported, warnings = prepare_performance_tags(
            original, engine="chatterbox_turbo", unsupported_policy="error"
        )
        self.assertEqual(supported, original)
        self.assertEqual(warnings, ())

        with self.assertRaises(VoiceboxUnsupportedTagError):
            prepare_performance_tags(original, engine="qwen", unsupported_policy="error")
        stripped, warnings = prepare_performance_tags(
            original, engine="qwen", unsupported_policy="strip"
        )
        self.assertNotIn("[sigh]", stripped)
        self.assertIn("bell rang", stripped)
        self.assertTrue(warnings)


class FakeProviderClient:
    def __init__(self):
        self.info = VoiceboxServerInfo(version="0.5.0", message="voicebox API")
        self.health_result = VoiceboxHealth(
            status="healthy", model_loaded=False, gpu_available=True
        )
        self.profiles = (VoiceboxProfile.from_json(profile_json()),)
        self.models = (
            VoiceboxModelStatus(
                model_name="qwen-tts-1.7B",
                display_name="Qwen TTS 1.7B",
                downloaded=True,
                downloading=False,
                loaded=False,
            ),
        )
        self.audio = VoiceboxAudioDownload(wav_bytes(), "audio/wav")
        self.submit_errors = []
        self.payloads = []
        self.submit_count = 0

    def server_info(self):
        if isinstance(self.info, Exception):
            raise self.info
        return self.info

    def health(self):
        if isinstance(self.health_result, Exception):
            raise self.health_result
        return self.health_result

    def list_profiles(self):
        return self.profiles

    def list_models(self):
        return self.models

    def submit_generation(self, payload):
        self.submit_count += 1
        self.payloads.append(dict(payload))
        if self.submit_errors:
            error = self.submit_errors.pop(0)
            if error:
                raise error
        return VoiceboxGeneration.from_json(generation_json())

    def wait_for_generation(self, generation):
        return VoiceboxGeneration.from_json(
            generation_json(
                status="completed",
                audio_path=f"generations/{generation.id}.wav",
                duration=0.01,
            )
        )

    def download_audio(self, _generation_id):
        return self.audio


def copy_normalizer(source, target):
    shutil.copy2(source, target)
    return inspect_audio(target)


class VoiceboxProviderTests(unittest.TestCase):
    def make_provider(self, client=None, **settings):
        value = {
            "profile": "Archive Narrator",
            "engine": "qwen",
            "max_retries": 1,
        }
        value.update(settings)
        return VoiceboxAudioProvider(
            VoiceboxSettings.from_mapping(value),
            client=client or FakeProviderClient(),
            normalizer=copy_normalizer,
        )

    def test_health_success_unavailable_and_version_incompatibility(self):
        provider = self.make_provider()
        self.assertEqual(provider.health().state, HealthState.READY)
        self.assertFalse(provider.health().details["model_loaded"])

        unavailable_client = FakeProviderClient()
        unavailable_client.info = VoiceboxServiceUnavailableError("offline")
        self.assertEqual(
            self.make_provider(unavailable_client).health().state,
            HealthState.UNAVAILABLE,
        )

        incompatible = FakeProviderClient()
        incompatible.info = VoiceboxServerInfo(version="0.6.0")
        health = self.make_provider(incompatible).health()
        self.assertEqual(health.state, HealthState.MISCONFIGURED)
        with self.assertRaises(VoiceboxVersionIncompatibilityError):
            self.make_provider(incompatible).generate(
                GenerationRequest(content="text", output_path="narration.wav")
            )

    def test_profile_and_engine_discovery(self):
        provider = self.make_provider()
        self.assertEqual(provider.discover_profiles()[0].id, "profile-123")
        engines = provider.discover_engines()
        qwen = next(item for item in engines if item["engine"] == "qwen")
        self.assertEqual(qwen["models"][0]["model_name"], "qwen-tts-1.7B")
        self.assertTrue(qwen["models"][0]["downloaded"])

    def test_invalid_profile_engine_language_and_missing_model(self):
        client = FakeProviderClient()
        with self.assertRaises(VoiceboxInvalidProfileError):
            self.make_provider(client, profile="missing").generate(
                GenerationRequest(content="text", output_path="narration.wav")
            )
        with self.assertRaises(VoiceboxInvalidEngineError):
            self.make_provider(client, engine="qwen3-tts").generate(
                GenerationRequest(content="text", output_path="narration.wav")
            )
        with self.assertRaises(VoiceboxUnsupportedCapabilityError):
            self.make_provider(client, language="ar").generate(
                GenerationRequest(content="text", output_path="narration.wav")
            )
        client.models = (
            VoiceboxModelStatus(
                "qwen-tts-1.7B", "Qwen", False, False, False
            ),
        )
        with self.assertRaisesRegex(VoiceboxServiceUnavailableError, "will not download"):
            self.make_provider(client).generate(
                GenerationRequest(content="text", output_path="narration.wav")
            )

    def test_tada_1b_rejects_languages_only_available_in_3b(self):
        client = FakeProviderClient()
        client.profiles = (
            VoiceboxProfile.from_json(profile_json(language="ar", default_engine="tada")),
        )
        client.models = (
            VoiceboxModelStatus("tada-1b", "TADA 1B", True, False, False),
        )
        with self.assertRaisesRegex(VoiceboxUnsupportedCapabilityError, "language 'ar'"):
            self.make_provider(
                client, engine="tada", model_size="1B", language="ar"
            ).generate(
                GenerationRequest(content="text", output_path="narration.wav")
            )

    def test_success_preserves_original_normalized_artifacts_and_provenance(self):
        client = FakeProviderClient()
        with tempfile.TemporaryDirectory(prefix="voicebox paths with spaces ") as temp_dir:
            requested = Path(temp_dir, "requested narration.wav")
            result = self.make_provider(client).generate(
                GenerationRequest(
                    content="A UTF-8 narration about café records in 東京.",
                    output_path=requested,
                    request_id="windows request 1",
                    seed=42,
                )
            )
            artifact_dir = Path(result.metadata["artifact_directory"])
            original = artifact_dir / "voicebox_original.wav"
            production = artifact_dir / "production_audio.wav"

            self.assertEqual(Path(result.output_path), production)
            self.assertEqual(original.read_bytes(), client.audio.content)
            self.assertEqual(sha256_file(original), result.provenance.source_artifact_hash)
            self.assertEqual(sha256_file(production), result.provenance.derived_artifact_hash)
            self.assertEqual(result.provenance.seed, 42)
            for name in (
                "voicebox_request.json",
                "audio_validation.json",
                "provenance.json",
            ):
                self.assertTrue(Path(artifact_dir, name).is_file(), name)
            manifest_text = Path(artifact_dir, "voicebox_request.json").read_text(
                encoding="utf-8"
            )
            self.assertNotIn("profile-123", manifest_text)
            self.assertNotIn("Archive Narrator", manifest_text)
            self.assertNotIn("café records", manifest_text)
            self.assertIn("東京", client.payloads[0]["text"])

    def test_retryable_and_nonretryable_failures_follow_explicit_policy(self):
        retry = FakeProviderClient()
        retry.submit_errors = [
            VoiceboxGenerationError("temporary queue error", retryable=True),
            None,
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            result = self.make_provider(retry, max_retries=1).generate(
                GenerationRequest(content="text", output_path=Path(temp_dir, "out.wav"))
            )
        self.assertEqual(retry.submit_count, 2)
        self.assertEqual(result.metadata["attempt_count"], 2)
        self.assertEqual(result.provenance.retry_count, 1)

        no_retry = FakeProviderClient()
        no_retry.submit_errors = [VoiceboxGenerationError("invalid", retryable=False)]
        with tempfile.TemporaryDirectory() as temp_dir, self.assertRaises(
            VoiceboxGenerationError
        ) as raised:
            self.make_provider(no_retry, max_retries=5).generate(
                GenerationRequest(content="text", output_path=Path(temp_dir, "out.wav"))
            )
        self.assertEqual(no_retry.submit_count, 1)
        self.assertEqual(raised.exception.attempt_count, 1)

    def test_invalid_audio_and_failed_normalization_do_not_return_stale_output(self):
        invalid = FakeProviderClient()
        invalid.audio = VoiceboxAudioDownload(b"not a wav", "audio/wav")
        with tempfile.TemporaryDirectory() as temp_dir, self.assertRaises(
            VoiceboxInvalidAudioError
        ):
            self.make_provider(invalid).generate(
                GenerationRequest(content="text", output_path=Path(temp_dir, "out.wav"))
            )

        def failing_normalizer(_source, target):
            Path(target).write_bytes(b"partial")
            raise VoiceboxNormalizationError("offline normalization failure")

        with tempfile.TemporaryDirectory() as temp_dir:
            provider = VoiceboxAudioProvider(
                VoiceboxSettings.from_mapping(
                    {"profile": "Archive Narrator", "engine": "qwen"}
                ),
                client=FakeProviderClient(),
                normalizer=failing_normalizer,
            )
            with self.assertRaises(VoiceboxNormalizationError):
                provider.generate(
                    GenerationRequest(content="text", output_path=Path(temp_dir, "out.wav"))
                )
            self.assertFalse(any(Path(temp_dir).rglob("provenance.json")))
            self.assertFalse(any(Path(temp_dir).rglob("production_audio.wav")))
            failed_manifest = next(Path(temp_dir).rglob("voicebox_request.json"))
            self.assertEqual(
                json.loads(failed_manifest.read_text(encoding="utf-8"))["status"],
                "failed",
            )

    def test_different_text_changes_identity_and_artifact_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            provider = self.make_provider()
            first = provider.generate(
                GenerationRequest(
                    content="First factual script.",
                    output_path=Path(temp_dir, "out.wav"),
                    request_id="one",
                )
            )
            second = provider.generate(
                GenerationRequest(
                    content="Second factual script.",
                    output_path=Path(temp_dir, "out.wav"),
                    request_id="two",
                )
            )
        self.assertNotEqual(first.provenance.request_hash, second.provenance.request_hash)
        self.assertNotEqual(first.output_path, second.output_path)

    def test_changed_profile_source_identity_invalidates_request_hash(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            first_client = FakeProviderClient()
            first = self.make_provider(first_client).generate(
                GenerationRequest(
                    content="Same factual script.",
                    output_path=Path(temp_dir, "out.wav"),
                    request_id="first",
                )
            )
            second_client = FakeProviderClient()
            second_client.profiles = (
                VoiceboxProfile.from_json(
                    profile_json(
                        updated_at="2026-07-16T12:00:00Z",
                        sample_count=2,
                    )
                ),
            )
            second = self.make_provider(second_client).generate(
                GenerationRequest(
                    content="Same factual script.",
                    output_path=Path(temp_dir, "out.wav"),
                    request_id="second",
                )
            )
        self.assertNotEqual(first.provenance.request_hash, second.provenance.request_hash)

    def test_same_artifact_directory_never_replaces_immutable_original(self):
        client = FakeProviderClient()
        with tempfile.TemporaryDirectory() as temp_dir:
            request = GenerationRequest(
                content="Same script.",
                output_path=Path(temp_dir, "out.wav"),
                request_id="same",
            )
            provider = self.make_provider(client)
            result = provider.generate(request)
            original = Path(result.metadata["artifact_directory"], "voicebox_original.wav")
            before = original.read_bytes()
            with self.assertRaises(VoiceboxInvalidAudioError):
                provider.generate(request)
            self.assertEqual(original.read_bytes(), before)

    def test_windows_path_object_survives_artifact_resolution(self):
        request = GenerationRequest(
            content="text",
            output_path=PureWindowsPath(r"C:\Media Work\episode\narration.wav"),
            request_id="windows",
        )
        self.assertIn("Media Work", str(request.output_path))


class AudioAssetTests(unittest.TestCase):
    def test_atomic_normalization_and_failed_partial_cleanup(self):
        with tempfile.TemporaryDirectory(prefix="audio normalize spaces ") as temp_dir:
            source = Path(temp_dir, "voicebox original.wav")
            target = Path(temp_dir, "production audio.wav")
            source.write_bytes(wav_bytes())

            def success(command, **_kwargs):
                shutil.copy2(command[command.index("-i") + 1], command[-1])
                return SimpleNamespace(returncode=0, stderr="")

            inspection = normalize_production_audio(
                source, target, run_command=success
            )
            self.assertEqual(inspection.sample_rate_hz, 44_100)
            self.assertEqual(inspection.channels, 2)
            self.assertEqual(source.read_bytes(), wav_bytes())

            failed_target = Path(temp_dir, "failed.wav")

            def failure(command, **_kwargs):
                Path(command[-1]).write_bytes(b"partial")
                return SimpleNamespace(returncode=1, stderr="decoder failed")

            with self.assertRaises(VoiceboxNormalizationError):
                normalize_production_audio(source, failed_target, run_command=failure)
            self.assertFalse(failed_target.exists())
            self.assertFalse(any(Path(temp_dir).glob(".*.partial.wav")))


class VoiceboxTtsWiringTests(unittest.TestCase):
    @staticmethod
    def load_tts_class():
        fake_kittentts = SimpleNamespace(KittenTTS=object)
        fake_soundfile = SimpleNamespace(write=Mock())
        module_path = Path(__file__).parents[1] / "src" / "classes" / "Tts.py"
        spec = importlib.util.spec_from_file_location("_offline_voicebox_tts", module_path)
        module = importlib.util.module_from_spec(spec)
        with patch.dict(
            sys.modules,
            {"kittentts": fake_kittentts, "soundfile": fake_soundfile},
        ):
            spec.loader.exec_module(module)
        return module.TTS

    def make_tts(self, *, allow_fallback: bool, fallback: str | None = None):
        TTS = self.load_tts_class()
        tts = TTS.__new__(TTS)
        tts._provider = "voicebox"
        tts._audio_settings = resolve_audio_provider_settings(
            legacy_provider="elevenlabs",
            global_audio={
                "provider": "voicebox",
                "allow_fallback": allow_fallback,
                "fallback_provider": fallback,
                "voicebox": {"profile": "Archive Narrator"},
            },
        )
        tts.last_provider_used = ""
        tts.last_model_used = ""
        tts.last_generation_metadata = {}
        return TTS, tts

    def test_fallback_disabled_propagates_typed_error_and_records_failure(self):
        TTS, tts = self.make_tts(allow_fallback=False)
        error = VoiceboxGenerationError(
            "offline generation failure", retryable=False, attempt_count=2
        )
        tts._synthesize_voicebox = Mock(side_effect=error)
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir, "narration.wav")
            with self.assertRaises(VoiceboxGenerationError):
                TTS.synthesize(tts, "script", str(output))
            manifest = json.loads(
                Path(
                    temp_dir,
                    "narration",
                    "manifests",
                    "narration.json",
                ).read_text(encoding="utf-8")
            )
        self.assertEqual(manifest["requested_provider"], "voicebox")
        self.assertIsNone(manifest["selected_fallback"])
        self.assertEqual(manifest["attempt_count"], 2)

    def test_explicit_fallback_records_required_provenance_fields(self):
        TTS, tts = self.make_tts(allow_fallback=True, fallback="elevenlabs")
        error = VoiceboxGenerationError(
            "offline generation failure", retryable=False, attempt_count=2
        )
        tts._synthesize_voicebox = Mock(side_effect=error)

        def fallback(provider, _text, output_file):
            self.assertEqual(provider, "elevenlabs")
            fallback_path = str(Path(output_file).with_suffix(".mp3"))
            Path(fallback_path).write_bytes(b"offline fallback bytes")
            tts.last_provider_used = provider
            return fallback_path

        tts._synthesize_explicit_fallback = fallback
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir, "narration.wav")
            result = TTS.synthesize(tts, "script", str(output))
            manifest_path = Path(tts.last_generation_metadata["manifest_path"])
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertTrue(result.endswith(".mp3"))
        self.assertEqual(manifest["requested_provider"], "voicebox")
        self.assertEqual(manifest["failed_provider"], "voicebox")
        self.assertEqual(manifest["error_class"], "VoiceboxGenerationError")
        self.assertEqual(manifest["selected_fallback"], "elevenlabs")
        self.assertEqual(manifest["attempt_count"], 2)
        self.assertTrue(manifest["output_sha256"])

    def test_voicebox_sanitization_preserves_only_verified_performance_tags(self):
        TTS, tts = self.make_tts(allow_fallback=False)
        text = "Fact: [sigh] café — source [12] / aside."
        cleaned = TTS.sanitize_text(tts, text)
        self.assertIn("[sigh]", cleaned)
        self.assertNotIn("[12]", cleaned)
        self.assertNotIn("—", cleaned)
        self.assertIn("café", cleaned)

        tts._provider = "elevenlabs"
        self.assertEqual(
            TTS.sanitize_text(tts, text),
            "Fact sigh café  source 12  aside.",
        )


if __name__ == "__main__":
    unittest.main()
