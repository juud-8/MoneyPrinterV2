"""Word-by-word animated caption overlays for Shorts."""

import os
import re

from moviepy import CompositeVideoClip, TextClip

from config import get_font, get_fonts_dir


def _parse_srt(srt_path: str) -> list[dict]:
    """Parse SRT file into list of {start, end, text} dicts."""
    with open(srt_path, "r", encoding="utf-8") as f:
        content = f.read()

    blocks = re.split(r"\n\s*\n", content.strip())
    entries = []

    for block in blocks:
        lines = block.strip().split("\n")
        if len(lines) < 3:
            continue
        timing = lines[1]
        if "-->" not in timing:
            continue
        start_s, end_s = timing.split("-->")
        # Preserve authored lyric/paragraph line breaks. Word-caption callers
        # can still split on whitespace, while block/lyric layouts retain form.
        text = "\n".join(lines[2:]).strip()
        if not text:
            continue
        entries.append(
            {
                "start": _srt_time_to_seconds(start_s.strip()),
                "end": _srt_time_to_seconds(end_s.strip()),
                "text": text,
            }
        )
    return entries


def _srt_time_to_seconds(ts: str) -> float:
    h, m, rest = ts.split(":")
    s, ms = rest.split(",")
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


def _font_size_for_word(word: str) -> int:
    length = len(word)
    if length <= 8:
        return 78
    if length <= 12:
        return 64
    if length <= 16:
        return 52
    return 44


def build_word_caption_clips(
    srt_path: str,
    video_size: tuple[int, int] = (1080, 1920),
    highlight_color: str = "#FFD93D",
    base_color: str = "#FFFFFF",
) -> list:
    """
    Build per-word TextClips — one active word at a time (Shorts-safe layout).

    Returns a flat list of clips to composite on top of the video.
    """
    font_path = os.path.join(get_fonts_dir(), get_font())
    entries = _parse_srt(srt_path)
    clips = []
    w, h = video_size
    margin_x = 80
    caption_width = w - (margin_x * 2)
    # Sit above YouTube Shorts bottom UI safe zone
    y_pos = int(h * 0.62)

    for entry in entries:
        words = entry["text"].split()
        if not words:
            continue

        total_dur = max(0.05, entry["end"] - entry["start"])
        word_dur = total_dur / len(words)

        for i, word in enumerate(words):
            word_start = entry["start"] + i * word_dur
            word_end = word_start + word_dur
            clean_word = re.sub(r"[^\w'\-]", "", word).strip() or word
            display_text = clean_word.upper()
            font_size = _font_size_for_word(clean_word)

            try:
                txt_clip = TextClip(
                    text=display_text,
                    font=font_path,
                    font_size=font_size,
                    color=highlight_color,
                    stroke_color="black",
                    stroke_width=5,
                    size=(caption_width, 180),
                    method="caption",
                    text_align="center",
                )
                txt_clip = (
                    txt_clip.with_start(word_start)
                    .with_duration(word_end - word_start)
                    .with_position(("center", y_pos))
                )
                clips.append(txt_clip)
            except Exception:
                continue

    return clips


def composite_captions_on_video(base_clip, srt_path: str):
    """Composite word-highlight captions onto a base video clip."""
    caption_clips = build_word_caption_clips(
        srt_path, video_size=(base_clip.w, base_clip.h)
    )
    if not caption_clips:
        return base_clip
    return CompositeVideoClip([base_clip, *caption_clips])


def build_lyric_caption_clips(
    srt_path: str,
    video_size: tuple[int, int] = (1080, 1920),
    highlight_color: str = "#FFD93D",
    base_color: str = "#FFFFFF",
    caption_style: str = "lyric_highlight",
) -> list:
    """Render authoritative lyric phrases plus the currently sung word.

    Timing comes from the post-import alignment file. The full phrase remains
    readable while the active word receives a separate high-contrast highlight.
    """
    font_path = os.path.join(get_fonts_dir(), get_font())
    entries = _parse_srt(srt_path)
    clips = []
    width, height = video_size
    caption_width = width - 140
    highlight_words = caption_style != "phrase_only"

    for entry in entries:
        words = entry["text"].split()
        duration = max(0.05, entry["end"] - entry["start"])
        if not words:
            continue
        try:
            phrase = TextClip(
                text=entry["text"],
                font=font_path,
                font_size=54,
                color=base_color,
                stroke_color="black",
                stroke_width=4,
                size=(caption_width, 260),
                method="caption",
                text_align="center",
            )
            clips.append(
                phrase.with_start(entry["start"])
                .with_duration(duration)
                .with_position(("center", int(height * 0.50)))
            )
        except Exception:
            pass

        if not highlight_words:
            continue
        word_duration = duration / len(words)
        for index, word in enumerate(words):
            clean = re.sub(r"[^\w'\-]", "", word).strip() or word
            try:
                active = TextClip(
                    text=clean.upper(),
                    font=font_path,
                    font_size=_font_size_for_word(clean),
                    color=highlight_color,
                    stroke_color="black",
                    stroke_width=5,
                    size=(caption_width, 150),
                    method="caption",
                    text_align="center",
                )
                clips.append(
                    active.with_start(entry["start"] + index * word_duration)
                    .with_duration(word_duration)
                    .with_position(("center", int(height * 0.66)))
                )
            except Exception:
                continue
    return clips


def composite_lyric_captions_on_video(
    base_clip,
    srt_path: str,
    timed_beat_map_path: str = "",
    caption_options: dict | None = None,
):
    """Composite lyric captions and optional full-screen beat-map moments."""
    import json

    options = caption_options or {}
    caption_style = str(options.get("caption_style") or "lyric_highlight")
    fullscreen_emphasis = str(options.get("fullscreen_emphasis") or "on_screen_text")
    fullscreen_max_seconds = float(options.get("fullscreen_max_seconds") or 1.5)
    show_source_on_screen = bool(options.get("show_source_on_screen"))

    clips = build_lyric_caption_clips(
        srt_path,
        video_size=(base_clip.w, base_clip.h),
        caption_style=caption_style,
    )
    if (
        fullscreen_emphasis != "off"
        and timed_beat_map_path
        and os.path.isfile(timed_beat_map_path)
    ):
        try:
            with open(timed_beat_map_path, "r", encoding="utf-8") as file:
                beats = json.load(file)
            font_path = os.path.join(get_fonts_dir(), get_font())
            for beat in beats:
                text = str(beat.get("on_screen_text") or "").strip()
                if fullscreen_emphasis == "hook_phrases" and not text:
                    text = str(beat.get("lyric_phrase") or "").strip()
                if show_source_on_screen:
                    source_bits = ", ".join(beat.get("source_ids") or [])
                    confidence = str(beat.get("confidence") or "").strip()
                    provenance = " · ".join(
                        part for part in (source_bits, confidence) if part
                    )
                    if provenance:
                        text = f"{text}\n{provenance}" if text else provenance
                start = float(beat.get("start_seconds") or 0)
                end = float(beat.get("end_seconds") or start)
                if not text or end <= start:
                    continue
                moment = TextClip(
                    text=text,
                    font=font_path,
                    font_size=88,
                    color="#FFD93D",
                    stroke_color="black",
                    stroke_width=6,
                    size=(base_clip.w - 120, 500),
                    method="caption",
                    text_align="center",
                )
                clips.append(
                    moment.with_start(start)
                    .with_duration(min(fullscreen_max_seconds, end - start))
                    .with_position(("center", "center"))
                )
        except Exception:
            # Captions remain usable even if optional full-screen guidance is
            # malformed or unsupported by the local ImageMagick setup.
            pass
    if not clips:
        return base_clip
    return CompositeVideoClip([base_clip, *clips])
