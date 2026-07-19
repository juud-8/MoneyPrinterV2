"""Helpers for the YouTube Studio Selenium upload wizard.

Keeps visibility resolution and draft/success heuristics out of the giant
YouTube class so they can be unit-tested without a browser.
"""

from __future__ import annotations

VALID_VISIBILITIES = ("private", "unlisted", "public")


def resolve_upload_visibility(
    publishing: dict | None = None,
    fallback: str = "unlisted",
) -> str:
    """Pick Studio visibility from brand publishing config.

    Defaults to unlisted (safe for pilot / review) when unset or invalid.
    """
    raw = ""
    if isinstance(publishing, dict):
        raw = str(publishing.get("default_visibility") or "").strip().lower()
    if raw in VALID_VISIBILITIES:
        return raw
    fb = str(fallback or "").strip().lower()
    if fb in VALID_VISIBILITIES:
        return fb
    return "unlisted"


def radio_matches_visibility(label_text: str, visibility: str) -> bool:
    """True if a Studio radio label refers to the requested visibility."""
    text = " ".join((label_text or "").lower().split())
    target = (visibility or "").lower().strip()
    if not text or target not in VALID_VISIBILITIES:
        return False
    # Exact word match preferred — "public" must not match "not public".
    tokens = set(text.replace("/", " ").replace("-", " ").split())
    if target in tokens:
        return True
    return text == target or text.startswith(f"{target} ")


def visibility_radios_present(label_texts: list[str]) -> bool:
    """Detect the Visibility step from collected radioLabel texts."""
    joined = " ".join((t or "").lower() for t in label_texts)
    return (
        "private" in joined
        and "unlisted" in joined
        and "public" in joined
    )


def extract_outcome_signals(log_or_page_text: str) -> dict:
    """Best-effort signals from Studio page text or upload log snippets."""
    text = (log_or_page_text or "").lower()
    return {
        "mentions_draft": (
            ("draft" in text and "drafts" in text)
            or "saved as draft" in text
            or "video is still a draft" in text
        ),
        "mentions_published": any(
            phrase in text
            for phrase in (
                "video published",
                "video is being uploaded",
                "processing",
                "share publicly",
                "uploaded video",
            )
        ),
        "mentions_checks_incomplete": any(
            phrase in text
            for phrase in (
                "checks incomplete",
                "copyright check in progress",
                "checking your video",
            )
        ),
    }


def parse_moviepy_progress(chunk: str) -> float | None:
    """Return 0–100 progress from a MoviePy/tqdm fragment, if present."""
    import re

    if not chunk:
        return None
    # Prefer tqdm-style "45%|" or "45%" near frame counters.
    m = re.search(r"(\d{1,3})%\s*\|", chunk)
    if m:
        return min(100.0, float(m.group(1)))
    m = re.search(r"\b(\d+)\s*/\s*(\d+)\b", chunk)
    if m:
        cur, total = int(m.group(1)), int(m.group(2))
        if total > 0:
            return min(100.0, 100.0 * cur / total)
    return None
