"""YouTube tag generation, normalization, and description hashtag helpers."""

from __future__ import annotations

import json
import re

STUDIO_TAGS_MAX_CHARS = 500
STUDIO_TAG_MAX_LEN = 30
DEFAULT_MAX_TAGS = 15
DEFAULT_TOPIC_HASHTAGS = 3


def generate_tags_prompt(
    *,
    subject: str,
    title: str,
    script: str,
    niche: str = "",
    default_tags: list[str] | None = None,
    max_topic_tags: int = 7,
) -> str:
    """Build an LLM prompt for topic-specific YouTube tags."""
    staples = ", ".join(default_tags or []) or "(none)"
    return f"""Generate YouTube search tags for this video.

Topic: {subject}
Title: {title}
Niche: {niche or "general"}

Script excerpt:
{(script or "")[:1200]}

Channel staple tags (already included — do NOT repeat these):
{staples}

Rules:
- Return ONLY valid JSON: {{"tags": ["tag one", "tag two"]}}
- Provide {max_topic_tags} to {max_topic_tags + 2} NEW topic-specific tags only
- Lowercase phrases, no hashtags, no quotes inside tags
- Prefer concrete names, dates, events, places, and search phrases viewers would type
- Each tag must be <= {STUDIO_TAG_MAX_LEN} characters
- No generic filler like "video", "youtube", or "shorts"
"""


def parse_llm_tags(raw: str) -> list[str]:
    """Parse tags from LLM JSON or comma/newline-separated fallback."""
    text = (raw or "").strip()
    if not text:
        return []

    # Strip markdown code fences if present.
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()

    try:
        payload = json.loads(text)
        if isinstance(payload, dict) and isinstance(payload.get("tags"), list):
            return [str(item) for item in payload["tags"]]
    except json.JSONDecodeError:
        pass

    parts = re.split(r"[\n,;]+", text)
    return [part.strip().strip('"').strip("'") for part in parts if part.strip()]


def normalize_tag(value: str) -> str:
    """Normalize a single Studio tag."""
    cleaned = re.sub(r"\s+", " ", (value or "").strip().lower())
    cleaned = cleaned.strip(" #.-")
    if len(cleaned) > STUDIO_TAG_MAX_LEN:
        cleaned = cleaned[:STUDIO_TAG_MAX_LEN].rstrip()
    return cleaned


def merge_video_tags(
    default_tags: list[str] | None,
    generated_tags: list[str] | None,
    *,
    max_tags: int = DEFAULT_MAX_TAGS,
    max_chars: int = STUDIO_TAGS_MAX_CHARS,
) -> list[str]:
    """Merge staple + generated tags, dedupe, and enforce YouTube limits."""
    merged: list[str] = []
    seen: set[str] = set()

    for raw in list(default_tags or []) + list(generated_tags or []):
        tag = normalize_tag(raw)
        if not tag or tag in seen:
            continue
        candidate = merged + [tag]
        if len(candidate) > max_tags:
            break
        if studio_tags_char_count(candidate) > max_chars:
            continue
        merged.append(tag)
        seen.add(tag)

    return merged


def studio_tags_char_count(tags: list[str]) -> int:
    """Character count YouTube uses for the Tags field (tags + commas)."""
    if not tags:
        return 0
    return sum(len(tag) for tag in tags) + max(0, len(tags) - 1)


def format_studio_tags(tags: list[str]) -> str:
    """Comma-separated string for the Studio Tags input."""
    return ", ".join(tags)


def topic_hashtags_for_description(
    tags: list[str],
    default_tags: list[str] | None = None,
    *,
    max_count: int = DEFAULT_TOPIC_HASHTAGS,
) -> str:
    """Build extra description hashtags from topic-specific tags."""
    staples = {normalize_tag(tag) for tag in (default_tags or [])}
    extras: list[str] = []
    for tag in tags:
        if normalize_tag(tag) in staples:
            continue
        hashtag = tag_to_hashtag(tag)
        if hashtag and hashtag not in extras:
            extras.append(hashtag)
        if len(extras) >= max_count:
            break
    return " ".join(extras)


def tag_to_hashtag(tag: str) -> str:
    """Convert a tag phrase to a PascalCase hashtag."""
    cleaned = re.sub(r"[^a-zA-Z0-9 ]+", "", (tag or "").strip())
    words = [word for word in cleaned.split() if word]
    if not words:
        return ""
    if len(words) == 1:
        word = words[0]
        return f"#{word[0].upper()}{word[1:]}"
    return "#" + "".join(word.capitalize() for word in words)


def build_tags_from_llm_response(raw: str) -> list[str]:
    """Normalize parsed LLM tags."""
    return [normalize_tag(tag) for tag in parse_llm_tags(raw) if normalize_tag(tag)]
