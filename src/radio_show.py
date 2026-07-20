"""Two-host "radio show" long-form audio generator.

Pipeline: research/source text -> quality-LLM dialogue script (host persona +
a curious caller) -> Gemini multi-speaker TTS (REST, same auth pattern as
llm_provider) -> mono WAV -> optional 1080p video bed (brand card + waveform)
so the episode can be uploaded to YouTube as long-form.

Brand-agnostic: persona, voices, and visuals come from arguments; the CLI
wrapper (scripts/radio_show.py) reads them from the brand manifest
(``production.radio_voices``, ``persona``, ``outro_clip``).

Costs (Gemini 3.x Flash TTS, mid-2026): audio out is billed ~25 tokens/second,
so a 20-minute two-host show is roughly 30k output tokens — well under a
dollar. The expensive path (generating 20 minutes of AI *video*) is
deliberately avoided: the bed is a static brand card with a live waveform.
"""

from __future__ import annotations

import base64
import re
import wave

import requests

from config import get_gemini_api_key

TTS_SAMPLE_RATE = 24_000  # Gemini TTS returns 16-bit mono PCM at 24 kHz

# Dialogue chunk size per TTS call. Generous margin under model limits while
# keeping any single failed call cheap to retry.
MAX_CHUNK_CHARS = 3_000

DEFAULT_VOICES = {"HOST": "Charon", "CALLER": "Kore"}


def build_show_prompt(
    topic: str,
    persona: dict,
    minutes: int,
    source_text: str = "",
    sign_off: str = "",
) -> str:
    """Prompt for the quality LLM to write the two-speaker radio script."""
    words = minutes * 150
    persona_name = persona.get("name", "The Host")
    persona_desc = persona.get("description", "a calm, knowledgeable narrator")
    return (
        f"Write a late-night radio show segment of about {words} words "
        f"(~{minutes} minutes read aloud) about: {topic}\n\n"
        f"Format: strictly alternating dialogue lines, each starting with "
        f"'HOST:' or 'CALLER:'. No stage directions, no markdown, no headers.\n"
        f"HOST is {persona_name}: {persona_desc}\n"
        "CALLER is a curious late-night listener who phoned in: asks sharp, "
        "short questions, reacts naturally, occasionally skeptical.\n\n"
        "Structure: cold-open hook (HOST alone, 2-3 lines), then the story in "
        "3 escalating segments driven by CALLER questions, then a quiet "
        "closing reflection."
        + (f" HOST's final line must end with: {sign_off}\n" if sign_off else "\n")
        + "Stick strictly to documented history; if a detail is disputed, HOST "
        "says so on air.\n"
        + (f"\nSource material to stay faithful to:\n{source_text}\n" if source_text else "")
    )


def parse_dialogue(script: str) -> list[tuple[str, str]]:
    """Extract (SPEAKER, line) pairs; tolerates markdown bold and extra space."""
    lines = []
    for raw in (script or "").splitlines():
        match = re.match(r"\s*\**\s*(HOST|CALLER)\s*\**\s*:\s*\**\s*(.+)", raw.strip())
        if match:
            lines.append((match.group(1).upper(), match.group(2).strip()))
    return lines


def chunk_dialogue(
    lines: list[tuple[str, str]], max_chars: int = MAX_CHUNK_CHARS
) -> list[str]:
    """Group dialogue into TTS-call-sized transcripts, never splitting a line."""
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for speaker, text in lines:
        rendered = f"{speaker}: {text}"
        if current and size + len(rendered) > max_chars:
            chunks.append("\n".join(current))
            current, size = [], 0
        current.append(rendered)
        size += len(rendered) + 1
    if current:
        chunks.append("\n".join(current))
    return chunks


def build_tts_payload(transcript: str, voices: dict) -> dict:
    """Gemini generateContent body for a multi-speaker TTS call."""
    speaker_configs = [
        {
            "speaker": speaker,
            "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}},
        }
        for speaker, voice in voices.items()
    ]
    return {
        "contents": [
            {
                "parts": [
                    {
                        "text": (
                            "TTS the following radio conversation. Calm, "
                            "intimate late-night delivery, unhurried pacing:\n"
                            + transcript
                        )
                    }
                ]
            }
        ],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {
                "multiSpeakerVoiceConfig": {"speakerVoiceConfigs": speaker_configs}
            },
        },
    }


def resolve_tts_model(preferred: str = "", api_key: str = "") -> str:
    """Pick a TTS-capable Gemini model: configured name first, else the newest
    ``*-tts*`` model the API reports."""
    if preferred:
        return preferred
    key = api_key or get_gemini_api_key()
    response = requests.get(
        "https://generativelanguage.googleapis.com/v1beta/models",
        headers={"x-goog-api-key": key},
        params={"pageSize": 200},
        timeout=60,
    )
    response.raise_for_status()
    names = [
        model.get("name", "").split("/")[-1]
        for model in response.json().get("models", [])
    ]
    tts = sorted(name for name in names if "tts" in name)
    if not tts:
        raise RuntimeError("No TTS-capable Gemini model available on this API key")
    return tts[-1]


def tts_chunk(transcript: str, voices: dict, model: str, api_key: str = "") -> bytes:
    """One multi-speaker TTS call -> raw 16-bit mono PCM."""
    key = api_key or get_gemini_api_key()
    response = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        headers={"x-goog-api-key": key, "Content-Type": "application/json"},
        json=build_tts_payload(transcript, voices),
        timeout=600,
    )
    response.raise_for_status()
    body = response.json()
    try:
        data = body["candidates"][0]["content"]["parts"][0]["inlineData"]["data"]
    except (KeyError, IndexError) as exc:
        raise RuntimeError(f"Unexpected TTS response shape: {str(body)[:400]}") from exc
    return base64.b64decode(data)


def write_wav(pcm: bytes, path: str, sample_rate: int = TTS_SAMPLE_RATE) -> None:
    with wave.open(path, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm)


def synthesize_show(
    script: str,
    voices: dict | None = None,
    model: str = "",
    wav_path: str = "show.wav",
    progress=print,
) -> tuple[str, float]:
    """Script text -> single WAV. Returns (path, duration_seconds)."""
    lines = parse_dialogue(script)
    if not lines:
        raise RuntimeError("Script contains no HOST:/CALLER: dialogue lines")
    chunks = chunk_dialogue(lines)
    resolved = resolve_tts_model(model)
    progress(f"  TTS model: {resolved}; {len(lines)} lines in {len(chunks)} chunk(s)")
    pcm = b""
    for index, chunk in enumerate(chunks, 1):
        progress(f"  TTS chunk {index}/{len(chunks)} ({len(chunk)} chars)...")
        pcm += tts_chunk(chunk, voices or DEFAULT_VOICES, resolved)
    write_wav(pcm, wav_path)
    return wav_path, len(pcm) / 2 / TTS_SAMPLE_RATE


def build_bed_command(
    bed_source: str,
    audio_path: str,
    output_path: str,
    waveform_color: str = "C9A66B",
    width: int = 1920,
    height: int = 1080,
    ffmpeg: str = "ffmpeg",
) -> list[str]:
    """ffmpeg argv: still brand card (blur-filled to 16:9 from any source
    image/video frame) + live waveform strip, muxed with the show audio."""
    color = waveform_color.lstrip("#")
    filter_complex = (
        # Background: blurred cover-fit of the bed art...
        f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},boxblur=24:2[bg];"
        # ...with the same art sharp and contained in the center.
        f"[0:v]scale={width}:{height}:force_original_aspect_ratio=decrease[fg];"
        f"[bg][fg]overlay=(W-w)/2:(H-h)/2[card];"
        f"[1:a]showwaves=s={width}x160:mode=cline:colors=0x{color}[wave];"
        f"[card][wave]overlay=0:H-h-40:format=auto,format=yuv420p[v]"
    )
    return [
        ffmpeg, "-loop", "1", "-i", bed_source, "-i", audio_path,
        "-filter_complex", filter_complex,
        "-map", "[v]", "-map", "1:a",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-r", "24",
        "-c:a", "aac", "-b:a", "192k", "-shortest",
        "-movflags", "+faststart", "-y", output_path,
    ]
