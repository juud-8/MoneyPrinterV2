import os
import re
from pathlib import Path

import requests
import soundfile as sf
from kittentts import KittenTTS as KittenModel

from config import (
    ROOT_DIR,
    get_audio_provider_settings,
    get_edge_tts_voice,
    get_elevenlabs_api_key,
    get_elevenlabs_model,
    get_elevenlabs_voice_id,
    get_fishaudio_api_key,
    get_fishaudio_model,
    get_fishaudio_voice_id,
    get_tts_voice,
)
from brand_switcher import get_production_setting
from status import warning

KITTEN_MODEL = "KittenML/kitten-tts-mini-0.8"
KITTEN_SAMPLE_RATE = 24000
ELEVENLABS_SAMPLE_RATE = 44100
VOICEBOX_PERFORMANCE_TAG = re.compile(
    r"\[(?:laugh|chuckle|gasp|cough|sigh|groan|sniff|shush|clear throat)\]",
    re.IGNORECASE,
)


class TTS:
    def __init__(self, *, episode_audio: dict | None = None, cli_audio: dict | None = None) -> None:
        self._audio_settings = get_audio_provider_settings(episode_audio, cli_audio)
        self._provider = self._audio_settings.provider
        self._voice = get_tts_voice()
        self.last_provider_used = ""
        self.last_model_used = ""
        self.last_generation_metadata = {}
        self._kitten = None
        if self._provider == "kittentts":
            self._kitten = KittenModel(KITTEN_MODEL)

    def _synthesize_elevenlabs(self, text: str, output_file: str) -> str:
        api_key = get_elevenlabs_api_key()
        voice_id = get_elevenlabs_voice_id()
        if not api_key or not voice_id:
            raise RuntimeError(
                "ElevenLabs selected but elevenlabs_api_key or elevenlabs_voice_id missing."
            )

        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
        headers = {
            "xi-api-key": api_key,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        }
        payload = {
            "text": text,
            "model_id": get_elevenlabs_model(),
            "voice_settings": {
                "stability": 0.45,
                "similarity_boost": 0.75,
                "style": 0.35,
                "use_speaker_boost": True,
            },
        }
        response = requests.post(url, headers=headers, json=payload, timeout=120)
        response.raise_for_status()

        # ElevenLabs returns MP3; MoviePy reads MP3 directly
        mp3_path = output_file if output_file.endswith(".mp3") else output_file.replace(".wav", ".mp3")
        with open(mp3_path, "wb") as f:
            f.write(response.content)
        self.last_provider_used = "elevenlabs"
        self.last_model_used = get_elevenlabs_model()
        return mp3_path

    def _synthesize_fishaudio(self, text: str, output_file: str) -> str:
        api_key = get_fishaudio_api_key()
        voice_id = get_fishaudio_voice_id()
        if not api_key or not voice_id:
            raise RuntimeError(
                "Fish Audio selected but fishaudio_api_key or fishaudio_voice_id missing."
            )

        response = requests.post(
            "https://api.fish.audio/v1/tts",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "model": get_fishaudio_model(),
            },
            json={
                "text": text,
                "reference_id": voice_id,
                "format": "mp3",
            },
            timeout=120,
        )
        response.raise_for_status()

        # Fish Audio returns MP3; MoviePy reads MP3 directly
        mp3_path = output_file if output_file.endswith(".mp3") else output_file.replace(".wav", ".mp3")
        with open(mp3_path, "wb") as f:
            f.write(response.content)
        self.last_provider_used = "fishaudio"
        self.last_model_used = get_fishaudio_model()
        return mp3_path

    def _synthesize_kitten(self, text: str, output_file: str) -> str:
        if self._kitten is None:
            self._kitten = KittenModel(KITTEN_MODEL)
        audio = self._kitten.generate(text, voice=self._voice)
        sf.write(output_file, audio, KITTEN_SAMPLE_RATE)
        self.last_provider_used = "kittentts"
        self.last_model_used = KITTEN_MODEL
        return output_file

    def _synthesize_edge_tts(self, text: str, output_file: str) -> str:
        """Free Microsoft Edge neural TTS (unofficial; best-effort cost floor)."""
        import asyncio

        try:
            import edge_tts
        except ImportError as exc:
            raise RuntimeError(
                "edge_tts provider selected but the edge-tts package is not installed. "
                "Run: pip install edge-tts"
            ) from exc

        voice = get_edge_tts_voice()
        mp3_path = (
            output_file if output_file.endswith(".mp3") else output_file.replace(".wav", ".mp3")
        )
        if mp3_path == output_file and not output_file.endswith(".mp3"):
            mp3_path = output_file + ".mp3"

        async def _run() -> None:
            communicate = edge_tts.Communicate(text, voice)
            await communicate.save(mp3_path)

        asyncio.run(_run())
        self.last_provider_used = "edge_tts"
        self.last_model_used = voice
        return mp3_path

    def sanitize_text(self, text: str) -> str:
        """Keep legacy cleanup exact while preserving verified Voicebox tags."""

        if self._provider != "voicebox":
            return re.sub(r"[^\w\s.?!]", "", text)
        protected: list[str] = []

        def reserve(match: re.Match) -> str:
            protected.append(match.group(0))
            return f"MPVVOICEBOXTAG{len(protected) - 1}TOKEN"

        reserved = VOICEBOX_PERFORMANCE_TAG.sub(reserve, text)
        cleaned = re.sub(r"[^\w\s.?!]", "", reserved)
        for index, tag in enumerate(protected):
            cleaned = cleaned.replace(f"MPVVOICEBOXTAG{index}TOKEN", tag)
        return cleaned

    def _provider_manifest_path(self, output_file: str, artifact_directory: str = "") -> Path:
        if artifact_directory:
            return Path(artifact_directory, "provider_manifest.json")
        target = Path(output_file).resolve()
        return target.parent / "narration" / "manifests" / f"{target.stem}.json"

    def _persist_provider_manifest(
        self,
        output_file: str,
        manifest: dict,
        *,
        artifact_directory: str = "",
    ) -> str:
        from media_providers.audio_assets import atomic_write_json

        path = self._provider_manifest_path(output_file, artifact_directory)
        atomic_write_json(path, manifest)
        return str(path)

    def _synthesize_voicebox(self, text: str, output_file: str) -> str:
        from media_providers.contracts import GenerationRequest
        from media_providers.voicebox_provider import build_voicebox_provider

        provider = build_voicebox_provider(self._audio_settings.voicebox)
        result = provider.generate(
            GenerationRequest(
                content=text,
                output_path=output_file,
                fallback_behavior=(
                    f"explicit:{self._audio_settings.fallback_provider}"
                    if self._audio_settings.allow_fallback
                    else "disabled"
                ),
            )
        )
        self.last_provider_used = "voicebox"
        self.last_model_used = str(result.metadata.get("model_name") or "")
        manifest = {
            "schema_version": 1,
            "status": "completed",
            "requested_provider": "voicebox",
            "failed_provider": None,
            "error_class": None,
            "selected_provider": "voicebox",
            "selected_fallback": None,
            "attempt_count": int(result.metadata.get("attempt_count") or 1),
            "output_path": str(result.output_path),
            "output_sha256": result.provenance.derived_artifact_hash,
            "source_sha256": result.provenance.source_artifact_hash,
            "request_hash": result.provenance.request_hash,
            "provenance_path": str(
                Path(str(result.metadata.get("artifact_directory") or ""), "provenance.json")
            ),
        }
        manifest_path = self._persist_provider_manifest(
            output_file,
            manifest,
            artifact_directory=str(result.metadata.get("artifact_directory") or ""),
        )
        manifest["manifest_path"] = manifest_path
        manifest["artifact_directory"] = str(
            result.metadata.get("artifact_directory") or ""
        )
        self.last_generation_metadata = manifest
        return str(result.output_path)

    def _synthesize_explicit_fallback(
        self,
        provider: str,
        text: str,
        output_file: str,
    ) -> str:
        if provider == "elevenlabs":
            return self._synthesize_elevenlabs(text, output_file)
        if provider == "fishaudio":
            return self._synthesize_fishaudio(text, output_file)
        if provider == "edge_tts":
            return self._synthesize_edge_tts(text, output_file)
        if provider == "kittentts":
            return self._synthesize_kitten(text, output_file)
        raise RuntimeError(f"Unsupported explicit Voicebox fallback provider {provider!r}.")

    def _voicebox_fallback(
        self,
        error: Exception,
        text: str,
        output_file: str,
    ) -> str:
        fallback = self._audio_settings.fallback_provider
        attempt_count = int(getattr(error, "attempt_count", 0) or 1)
        manifest = {
            "schema_version": 1,
            "status": "fallback_pending",
            "requested_provider": "voicebox",
            "failed_provider": "voicebox",
            "error_class": type(error).__name__,
            "selected_provider": fallback,
            "selected_fallback": fallback,
            "attempt_count": attempt_count,
        }
        try:
            warning(
                f"Voicebox failed ({type(error).__name__}); using explicit fallback "
                f"{fallback}."
            )
            result = self._synthesize_explicit_fallback(fallback, text, output_file)
            from media_providers.provenance import sha256_file

            manifest.update(
                {
                    "status": "fallback_completed",
                    "output_path": str(result),
                    "output_sha256": sha256_file(result),
                }
            )
            manifest_path = self._persist_provider_manifest(output_file, manifest)
            manifest["manifest_path"] = manifest_path
            self.last_generation_metadata = manifest
            return result
        except Exception as fallback_error:
            manifest.update(
                {
                    "status": "fallback_failed",
                    "fallback_error_class": type(fallback_error).__name__,
                }
            )
            self._persist_provider_manifest(output_file, manifest)
            self.last_generation_metadata = manifest
            raise

    def _allow_kitten_fallback(self) -> bool:
        if os.environ.get("MPV2_ALLOW_KITTEN_TTS_FALLBACK", "").strip() == "1":
            return True
        if bool(get_production_setting("pilot_mode", False)):
            return False
        return True

    def _fallback_to_kitten(self, provider: str, error: Exception, output_file: str, text: str) -> str:
        if not self._allow_kitten_fallback():
            raise RuntimeError(
                f"{provider} synthesis failed during pilot mode and KittenTTS fallback is "
                f"disabled to protect the brand voice: {error}"
            ) from error
        warning(f"{provider} failed ({error}); falling back to KittenTTS.")
        return self._synthesize_kitten(text, output_file)

    def synthesize(self, text, output_file=os.path.join(ROOT_DIR, ".mp", "audio.wav")):
        if self._provider == "voicebox":
            from media_providers.errors import ProviderError

            try:
                return self._synthesize_voicebox(text, output_file)
            except ProviderError as error:
                if not self._audio_settings.allow_fallback:
                    self.last_generation_metadata = {
                        "schema_version": 1,
                        "status": "failed",
                        "requested_provider": "voicebox",
                        "failed_provider": "voicebox",
                        "error_class": type(error).__name__,
                        "selected_provider": None,
                        "selected_fallback": None,
                        "attempt_count": int(getattr(error, "attempt_count", 0) or 1),
                    }
                    self._persist_provider_manifest(output_file, self.last_generation_metadata)
                    raise
                return self._voicebox_fallback(error, text, output_file)
        if self._provider == "fishaudio":
            try:
                return self._synthesize_fishaudio(text, output_file)
            except Exception as e:
                if get_elevenlabs_api_key():
                    warning(f"Fish Audio failed ({e}); falling back to ElevenLabs.")
                    try:
                        return self._synthesize_elevenlabs(text, output_file)
                    except Exception as e2:
                        return self._fallback_to_kitten("ElevenLabs", e2, output_file, text)
                return self._fallback_to_kitten("Fish Audio", e, output_file, text)
        if self._provider == "elevenlabs":
            try:
                return self._synthesize_elevenlabs(text, output_file)
            except Exception as e:
                return self._fallback_to_kitten("ElevenLabs", e, output_file, text)
        if self._provider == "edge_tts":
            try:
                return self._synthesize_edge_tts(text, output_file)
            except Exception as e:
                return self._fallback_to_kitten("edge_tts", e, output_file, text)
        return self._synthesize_kitten(text, output_file)
