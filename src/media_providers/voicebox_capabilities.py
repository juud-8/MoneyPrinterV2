"""Versioned, conservative capability map for Voicebox 0.5.0 engines."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from .errors import (
    VoiceboxInvalidEngineError,
    VoiceboxUnsupportedCapabilityError,
    VoiceboxUnsupportedTagError,
)


VOICEBOX_CAPABILITY_MAP_VERSION = "voicebox-0.5.0@da79e37"
VOICEBOX_MAX_TEXT_LENGTH = 50_000
PERFORMANCE_TAGS = (
    "laugh",
    "chuckle",
    "gasp",
    "cough",
    "sigh",
    "groan",
    "sniff",
    "shush",
    "clear throat",
)
_PERFORMANCE_TAG = re.compile(
    r"\[(?:" + "|".join(re.escape(tag) for tag in PERFORMANCE_TAGS) + r")\]",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class VoiceboxEngineCapabilities:
    engine_id: str
    model_names: tuple[str, ...]
    languages: tuple[str, ...]
    model_sizes: tuple[str, ...] = ()
    voice_cloning: bool = True
    preset_voices: bool = False
    delivery_instructions: bool = False
    paralinguistic_tags: bool = False
    long_form_chunking: bool = True
    effects: bool = True
    transcription: bool = True
    seed_or_takes: bool = True
    streaming: bool = True
    asynchronous: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


TEN_LANGUAGES = ("zh", "en", "ja", "ko", "de", "fr", "ru", "pt", "es", "it")
TWENTY_THREE_LANGUAGES = TEN_LANGUAGES + (
    "he",
    "ar",
    "da",
    "el",
    "fi",
    "hi",
    "ms",
    "nl",
    "no",
    "pl",
    "sv",
    "sw",
    "tr",
)


VOICEBOX_ENGINES: dict[str, VoiceboxEngineCapabilities] = {
    "qwen": VoiceboxEngineCapabilities(
        "qwen",
        ("qwen-tts-1.7B", "qwen-tts-0.6B"),
        TEN_LANGUAGES,
        model_sizes=("1.7B", "0.6B"),
    ),
    "qwen_custom_voice": VoiceboxEngineCapabilities(
        "qwen_custom_voice",
        ("qwen-custom-voice-1.7B", "qwen-custom-voice-0.6B"),
        TEN_LANGUAGES,
        model_sizes=("1.7B", "0.6B"),
        voice_cloning=False,
        preset_voices=True,
        delivery_instructions=True,
    ),
    "luxtts": VoiceboxEngineCapabilities(
        "luxtts", ("luxtts",), ("en",)
    ),
    "chatterbox": VoiceboxEngineCapabilities(
        "chatterbox", ("chatterbox-tts",), TWENTY_THREE_LANGUAGES
    ),
    "chatterbox_turbo": VoiceboxEngineCapabilities(
        "chatterbox_turbo",
        ("chatterbox-turbo",),
        ("en",),
        paralinguistic_tags=True,
    ),
    "tada": VoiceboxEngineCapabilities(
        "tada",
        ("tada-1b", "tada-3b-ml"),
        ("en", "ar", "zh", "de", "es", "fr", "it", "ja", "pl", "pt"),
        model_sizes=("1B", "3B"),
    ),
    "kokoro": VoiceboxEngineCapabilities(
        "kokoro",
        ("kokoro",),
        ("en", "es", "fr", "hi", "it", "pt", "ja", "zh"),
        voice_cloning=False,
        preset_voices=True,
    ),
}


def capabilities_for_engine(engine: str) -> VoiceboxEngineCapabilities:
    normalized = str(engine or "").strip().lower()
    try:
        return VOICEBOX_ENGINES[normalized]
    except KeyError as exc:
        raise VoiceboxInvalidEngineError(
            f"Unknown engine {engine!r}. Choose one of: {', '.join(VOICEBOX_ENGINES)}."
        ) from exc


def model_name_for_engine(engine: str, model_size: str | None) -> tuple[str, str | None]:
    capability = capabilities_for_engine(engine)
    if not capability.model_sizes:
        if model_size not in (None, ""):
            raise VoiceboxUnsupportedCapabilityError(
                f"Engine {engine!r} does not accept a model_size setting. Remove it."
            )
        return capability.model_names[0], None

    selected = model_size
    if selected is None:
        selected = "1B" if engine == "tada" else "1.7B"
    if selected not in capability.model_sizes:
        raise VoiceboxInvalidEngineError(
            f"Engine {engine!r} model_size must be one of {capability.model_sizes}; "
            f"received {selected!r}."
        )
    index = capability.model_sizes.index(selected)
    return capability.model_names[index], selected


def prepare_performance_tags(
    text: str,
    *,
    engine: str,
    unsupported_policy: str,
) -> tuple[str, tuple[str, ...]]:
    """Validate or explicitly strip Voicebox's documented performance tags."""

    matches = tuple(match.group(0) for match in _PERFORMANCE_TAG.finditer(text))
    if not matches or capabilities_for_engine(engine).paralinguistic_tags:
        return text, ()
    if unsupported_policy == "error":
        raise VoiceboxUnsupportedTagError(
            f"Engine {engine!r} would speak performance tags literally. "
            "Select 'chatterbox_turbo' or set unsupported_tag_policy to 'strip'."
        )
    if unsupported_policy != "strip":
        raise VoiceboxUnsupportedCapabilityError(
            "unsupported_tag_policy must be 'error' or 'strip'."
        )
    stripped = _PERFORMANCE_TAG.sub("", text)
    stripped = re.sub(r"[ \t]{2,}", " ", stripped)
    stripped = re.sub(r" *\n *", "\n", stripped).strip()
    if not stripped:
        raise VoiceboxUnsupportedTagError(
            "Removing unsupported performance tags would leave empty narration."
        )
    return stripped, (
        f"Explicitly stripped {len(matches)} unsupported performance tag(s) for {engine}.",
    )
