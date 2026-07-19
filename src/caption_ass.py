"""ASS karaoke captions + FFmpeg burn-in.

Opt-in alternative to the default MoviePy ``TextClip`` word-caption overlays
in ``video_captions.py`` — select it with ``caption_backend: "ass_karaoke"``
(global config or a brand's ``production`` override; see
``config.get_caption_backend()``). ``YouTube.combine()`` calls this module's
``write_ass_from_srt``/``burn_captions`` as a post-render step when selected,
falling back to MoviePy captions if FFmpeg is unavailable. Implements the
Verticals / ai-video-captions pattern: Whisper/SRT word timings → ASS with
``\\k`` karaoke tags → ``ffmpeg -vf ass=...`` burn-in.

Standalone operator spike/preview tool (same functions, no YouTube class
involved):

    python scripts/spike_ass_captions.py --srt path.srt --video path.mp4 --out out.mp4
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class AssStyle:
    """Vertical Shorts-oriented ASS style defaults."""

    name: str = "Karaoke"
    font_name: str = "Montserrat"
    font_size: int = 72
    primary_colour: str = "&H00FFFFFF"  # ASS BGR
    highlight_colour: str = "&H0000D9FF"  # yellow-ish BGR
    outline_colour: str = "&H00000000"
    back_colour: str = "&H80000000"
    bold: int = 1
    outline: int = 4
    shadow: int = 0
    alignment: int = 2  # bottom-center
    margin_v: int = 280
    margin_l: int = 80
    margin_r: int = 80
    play_res_x: int = 1080
    play_res_y: int = 1920


@dataclass(frozen=True)
class CaptionWord:
    text: str
    start: float
    end: float


@dataclass(frozen=True)
class CaptionCue:
    """A short phrase shown together; words carry per-word karaoke timing."""

    words: tuple[CaptionWord, ...]

    @property
    def start(self) -> float:
        return self.words[0].start if self.words else 0.0

    @property
    def end(self) -> float:
        return self.words[-1].end if self.words else 0.0


_SRT_BLOCK = re.compile(
    r"(\d+)\s*\n"
    r"(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})\s*\n"
    r"([\s\S]*?)(?=\n\d+\s*\n|\Z)",
    re.MULTILINE,
)


def srt_timestamp_to_seconds(ts: str) -> float:
    h, m, rest = ts.strip().split(":")
    s, ms = rest.split(",")
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


def seconds_to_ass_timestamp(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours}:{minutes:02d}:{secs:05.2f}"


def parse_srt_entries(srt_path: str) -> list[dict]:
    """Parse SRT into ``{start, end, text}`` dicts (line breaks preserved)."""
    with open(srt_path, "r", encoding="utf-8") as handle:
        content = handle.read().strip()
    if not content:
        return []
    # Prefer regex blocks; fall back to blank-line split like video_captions.
    matches = list(_SRT_BLOCK.finditer(content + "\n"))
    if matches:
        entries = []
        for match in matches:
            text = match.group(4).strip()
            if not text:
                continue
            entries.append(
                {
                    "start": srt_timestamp_to_seconds(match.group(2)),
                    "end": srt_timestamp_to_seconds(match.group(3)),
                    "text": text,
                }
            )
        return entries

    entries = []
    for block in re.split(r"\n\s*\n", content):
        lines = block.strip().split("\n")
        if len(lines) < 3 or "-->" not in lines[1]:
            continue
        start_s, end_s = lines[1].split("-->")
        text = "\n".join(lines[2:]).strip()
        if not text:
            continue
        entries.append(
            {
                "start": srt_timestamp_to_seconds(start_s),
                "end": srt_timestamp_to_seconds(end_s),
                "text": text,
            }
        )
    return entries


def entries_to_cues(
    entries: Sequence[dict],
    *,
    max_words_per_cue: int = 4,
) -> list[CaptionCue]:
    """Split SRT entries into short karaoke cues with evenly spaced words.

    When STT only provides phrase-level timings (typical SRT), word durations
    are apportioned evenly inside the phrase — same approach as MoviePy word
    captions today. Forced-alignment can replace this later without changing
    ASS rendering.
    """
    if max_words_per_cue < 1:
        raise ValueError("max_words_per_cue must be >= 1")
    cues: list[CaptionCue] = []
    for entry in entries:
        words = [w for w in str(entry.get("text") or "").split() if w.strip()]
        if not words:
            continue
        start = float(entry["start"])
        end = float(entry["end"])
        total = max(0.05, end - start)
        word_dur = total / len(words)
        timed = [
            CaptionWord(
                text=re.sub(r"[^\w'\-]", "", word).strip() or word,
                start=start + i * word_dur,
                end=start + (i + 1) * word_dur,
            )
            for i, word in enumerate(words)
        ]
        for i in range(0, len(timed), max_words_per_cue):
            chunk = timed[i : i + max_words_per_cue]
            cues.append(CaptionCue(words=tuple(chunk)))
    return cues


def _ass_style_line(style: AssStyle) -> str:
    return (
        f"Style: {style.name},{style.font_name},{style.font_size},"
        f"{style.primary_colour},{style.highlight_colour},{style.outline_colour},"
        f"{style.back_colour},{style.bold},0,0,0,100,100,0,0,1,"
        f"{style.outline},{style.shadow},{style.alignment},"
        f"{style.margin_l},{style.margin_r},{style.margin_v},1"
    )


def _karaoke_dialogue_text(cue: CaptionCue) -> str:
    parts: list[str] = []
    for word in cue.words:
        centiseconds = max(1, int(round((word.end - word.start) * 100)))
        # Uppercase for Shorts readability; \\k advances highlight timing.
        parts.append(f"{{\\k{centiseconds}}}{word.text.upper()}")
    return " ".join(parts)


def build_ass_document(
    cues: Sequence[CaptionCue],
    style: AssStyle | None = None,
) -> str:
    """Return a complete ASS file body for the given cues."""
    style = style or AssStyle()
    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        f"PlayResX: {style.play_res_x}",
        f"PlayResY: {style.play_res_y}",
        "YCbCr Matrix: TV.709",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding",
        _ass_style_line(style),
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, "
        "Effect, Text",
    ]
    for cue in cues:
        if not cue.words:
            continue
        lines.append(
            "Dialogue: 0,"
            f"{seconds_to_ass_timestamp(cue.start)},"
            f"{seconds_to_ass_timestamp(cue.end)},"
            f"{style.name},,0,0,0,,"
            f"{_karaoke_dialogue_text(cue)}"
        )
    lines.append("")
    return "\n".join(lines)


def write_ass_from_srt(
    srt_path: str,
    ass_path: str,
    *,
    style: AssStyle | None = None,
    max_words_per_cue: int = 4,
) -> str:
    """Convert an SRT file to ASS karaoke and write ``ass_path``. Returns path."""
    entries = parse_srt_entries(srt_path)
    cues = entries_to_cues(entries, max_words_per_cue=max_words_per_cue)
    body = build_ass_document(cues, style=style)
    os.makedirs(os.path.dirname(os.path.abspath(ass_path)) or ".", exist_ok=True)
    with open(ass_path, "w", encoding="utf-8") as handle:
        handle.write(body)
    return ass_path


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def build_burn_in_command(
    video_path: str,
    ass_path: str,
    output_path: str,
    *,
    fonts_dir: str | None = None,
) -> list[str]:
    """Build an FFmpeg argv that burns ASS captions without re-encoding audio."""
    # Escape Windows drive-letter colons for the ass filter path.
    ass_filter_path = ass_path.replace("\\", "/").replace(":", "\\:")
    vf = f"ass={ass_filter_path}"
    if fonts_dir:
        fonts_filter = fonts_dir.replace("\\", "/").replace(":", "\\:")
        vf = f"ass={ass_filter_path}:fontsdir={fonts_filter}"
    return [
        "ffmpeg",
        "-y",
        "-i",
        video_path,
        "-vf",
        vf,
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "18",
        "-c:a",
        "copy",
        output_path,
    ]


def burn_captions(
    video_path: str,
    ass_path: str,
    output_path: str,
    *,
    fonts_dir: str | None = None,
) -> str:
    """Burn ASS captions into ``output_path`` via FFmpeg. Returns output path."""
    if not ffmpeg_available():
        raise RuntimeError(
            "ffmpeg not found on PATH. Install FFmpeg to burn ASS captions."
        )
    if not os.path.isfile(video_path):
        raise FileNotFoundError(f"Video not found: {video_path}")
    if not os.path.isfile(ass_path):
        raise FileNotFoundError(f"ASS not found: {ass_path}")
    cmd = build_burn_in_command(
        video_path, ass_path, output_path, fonts_dir=fonts_dir
    )
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    return output_path
