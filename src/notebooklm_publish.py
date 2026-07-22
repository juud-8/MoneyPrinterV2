"""Pure helpers for scheduling reviewed NotebookLM episodes onto YouTube.

Everything here is deterministic and unit-testable: slot computation for
``publishAt`` scheduling, and sanitizers for LLM/notebook-suggested metadata
(NotebookLM's ``ask`` answers embed citation markers like ``[1-3]`` that must
never reach YouTube metadata).

Brand-agnostic: timezone, slot time, and lead-time arrive as arguments — the
batch runner reads them from the brand manifest.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

# YouTube titles hard-cap at 100 chars; stay under it so nothing truncates
# mid-word in the feed.
DEFAULT_TITLE_MAX = 95

_CITATION = re.compile(r"\s*\[[0-9]+(?:\s*[-,]\s*[0-9]+)*\]")


def strip_citations(text: str) -> str:
    """Remove NotebookLM citation markers like ``[1]`` / ``[1-3]`` / ``[2, 5]``."""
    return _CITATION.sub("", text or "")


def sanitize_title(raw: str, max_len: int = DEFAULT_TITLE_MAX) -> str:
    """Clean a suggested title for YouTube: no citations, quotes, hashtags,
    markdown bullets, or angle brackets; collapsed whitespace; length-capped
    on a word boundary."""
    text = strip_citations(raw or "")
    text = re.sub(r"[#*_`<>\"“”]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_len:
        text = text[:max_len].rsplit(" ", 1)[0].rstrip(",;:-")
    return text


def sanitize_description(raw: str) -> str:
    """Citation-free description body with normalized blank lines."""
    text = strip_citations(raw or "").strip()
    return re.sub(r"\n{3,}", "\n\n", text)


def parse_llm_metadata(reply: str) -> dict:
    """Extract ``{"title": ..., "description": ...}`` from an LLM reply that
    may wrap the JSON in prose or code fences. Returns {} when unparsable."""
    if not reply:
        return {}
    match = re.search(r"\{.*\}", reply, flags=re.DOTALL)
    if not match:
        return {}
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        "title": str(data.get("title") or "").strip(),
        "description": str(data.get("description") or "").strip(),
    }


def compute_publish_slots(
    count: int,
    slot_time: str,
    tz_name: str,
    start_day: date | None = None,
    min_lead_hours: float = 20.0,
    now: datetime | None = None,
) -> list[str]:
    """RFC3339 UTC ``publishAt`` times: one slot per day at ``slot_time`` local.

    The first slot is pushed forward day-by-day until it is at least
    ``min_lead_hours`` away, preserving a review window (scheduled videos sit
    private until publishAt, so there is time to QC or flip the AI-disclosure
    toggle in Studio before anything goes live).
    """
    if count <= 0:
        return []
    hour, minute = (int(part) for part in slot_time.split(":"))
    tz = ZoneInfo(tz_name)
    reference = now if now is not None else datetime.now(timezone.utc)
    day = start_day or reference.astimezone(tz).date()

    first = datetime.combine(day, time(hour, minute), tzinfo=tz)
    while first - reference < timedelta(hours=min_lead_hours):
        day += timedelta(days=1)
        first = datetime.combine(day, time(hour, minute), tzinfo=tz)

    slots = []
    for offset in range(count):
        slot_local = datetime.combine(
            day + timedelta(days=offset), time(hour, minute), tzinfo=tz
        )
        slots.append(slot_local.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    return slots


def extend_publish_slots(
    slots: list[str],
    count: int,
    slot_time: str,
    tz_name: str,
    min_lead_hours: float = 20.0,
    now: datetime | None = None,
) -> list[str]:
    """Append ``count`` more daily slots after the last existing one, so a
    rolling batch never runs out of publish dates."""
    if not slots:
        return compute_publish_slots(
            count, slot_time, tz_name, min_lead_hours=min_lead_hours, now=now
        )
    last = datetime.strptime(slots[-1], "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=timezone.utc
    )
    next_day = last.astimezone(ZoneInfo(tz_name)).date() + timedelta(days=1)
    return slots + compute_publish_slots(
        count, slot_time, tz_name, start_day=next_day, min_lead_hours=0, now=now
    )


def build_metadata_prompt(topic: str, suggestions: str, channel_tagline: str) -> str:
    """Prompt for the quality LLM to pick final upload metadata."""
    return (
        "You are titling a YouTube Short for a weird-but-true history channel "
        f"({channel_tagline}).\n"
        f"Episode topic: {topic}\n"
        f"Suggested options from research notes:\n{suggestions or '(none)'}\n\n"
        "Reply with ONLY a JSON object: {\"title\": ..., \"description\": ...}.\n"
        "Title: under 90 characters, curiosity-driven, specific (a real date, "
        "number, or name beats vague teasing), no hashtags, no quotes, no "
        "clickbait words like SHOCKING.\n"
        "Description: 2 sentences, factual, no hashtags, no citations."
    )
