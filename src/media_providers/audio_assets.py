"""Windows-safe atomic audio artifact helpers shared by local providers."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Mapping
from uuid import uuid4

from .errors import VoiceboxInvalidAudioError, VoiceboxNormalizationError
from .provenance import sha256_file


@dataclass(frozen=True)
class AudioInspection:
    path: str
    sha256: str
    size_bytes: int
    duration_seconds: float
    sample_rate_hz: int
    channels: int
    frames: int
    format: str
    subtype: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def atomic_write_json(path: str | os.PathLike[str], value: Mapping[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
    try:
        with open(temporary, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(dict(value), handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary, target)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def atomic_write_immutable_bytes(
    path: str | os.PathLike[str],
    content: bytes,
) -> None:
    """Create an immutable original without replacing a previous successful take."""

    target = Path(path)
    if target.exists():
        raise VoiceboxInvalidAudioError(
            f"Refusing to replace immutable Voicebox original at {target}. "
            "Start a new narration request instead."
        )
    if not isinstance(content, bytes) or not content:
        raise VoiceboxInvalidAudioError("Voicebox returned an empty audio response.")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.stem}.{uuid4().hex}.partial{target.suffix}")
    try:
        with open(temporary, "xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def inspect_audio(path: str | os.PathLike[str]) -> AudioInspection:
    target = Path(path)
    if not target.is_file() or target.stat().st_size <= 0:
        raise VoiceboxInvalidAudioError(f"Audio file is missing or empty: {target}")
    try:
        import soundfile as sf

        with sf.SoundFile(str(target), mode="r") as audio:
            frames = int(audio.frames)
            sample_rate = int(audio.samplerate)
            channels = int(audio.channels)
            format_name = str(audio.format or "")
            subtype = str(audio.subtype or "")
    except Exception as exc:
        raise VoiceboxInvalidAudioError(
            f"Voicebox audio could not be decoded: {exc}. "
            "Inspect the Voicebox generation and retry after correcting the local service."
        ) from exc
    if frames <= 0 or sample_rate <= 0 or channels <= 0:
        raise VoiceboxInvalidAudioError(
            "Voicebox audio decoded with zero frames, sample rate, or channels."
        )
    return AudioInspection(
        path=str(target.resolve()),
        sha256=sha256_file(target),
        size_bytes=target.stat().st_size,
        duration_seconds=float(frames / sample_rate),
        sample_rate_hz=sample_rate,
        channels=channels,
        frames=frames,
        format=format_name,
        subtype=subtype,
    )


def build_ffmpeg_normalize_command(
    input_path: str | os.PathLike[str],
    output_path: str | os.PathLike[str],
) -> list[str]:
    """Return a shell-free argv list that preserves Windows paths with spaces."""

    from moviepy.config import FFMPEG_BINARY

    return [
        str(FFMPEG_BINARY),
        "-y",
        "-v",
        "error",
        "-i",
        str(Path(input_path).resolve()),
        "-vn",
        "-ar",
        "44100",
        "-ac",
        "2",
        "-c:a",
        "pcm_s16le",
        str(Path(output_path).resolve()),
    ]


def normalize_production_audio(
    original_path: str | os.PathLike[str],
    production_path: str | os.PathLike[str],
    *,
    run_command: Callable[..., Any] = subprocess.run,
) -> AudioInspection:
    """Atomically derive 44.1 kHz stereo PCM without editing the original."""

    source = Path(original_path)
    target = Path(production_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.stem}.{uuid4().hex}.partial.wav")
    try:
        try:
            completed = run_command(
                build_ffmpeg_normalize_command(source, temporary),
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
                shell=False,
            )
        except FileNotFoundError as exc:
            raise VoiceboxNormalizationError(
                "FFmpeg was not found. Confirm MoviePy's FFMPEG_BINARY before using Voicebox."
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise VoiceboxNormalizationError(
                "FFmpeg normalization exceeded 180 seconds; inspect the original audio."
            ) from exc
        if int(getattr(completed, "returncode", 1)) != 0:
            stderr = str(getattr(completed, "stderr", "") or "FFmpeg rejected the audio")
            detail = stderr.strip().splitlines()[-1]
            raise VoiceboxNormalizationError(
                f"FFmpeg could not normalize Voicebox audio: {detail}"
            )
        inspection = inspect_audio(temporary)
        if inspection.sample_rate_hz != 44_100 or inspection.channels != 2:
            raise VoiceboxNormalizationError(
                "Normalized Voicebox audio is not 44.1 kHz stereo PCM."
            )
        os.replace(temporary, target)
        return inspect_audio(target)
    except VoiceboxNormalizationError:
        raise
    except VoiceboxInvalidAudioError as exc:
        raise VoiceboxNormalizationError(
            f"Normalized Voicebox audio is invalid: {exc}"
        ) from exc
    except Exception as exc:
        raise VoiceboxNormalizationError(
            f"Voicebox audio normalization failed: {exc}"
        ) from exc
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
