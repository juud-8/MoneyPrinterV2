"""Pure-logic helpers for cleaning and shape-checking generated video titles.

Kept out of `classes/YouTube.py` so they stay importable (and testable)
without pulling in MoviePy/Selenium.
"""

import re

# How many extra tries the reserved non-"How" title slot gets before we give up
# and accept whatever the LLM returned.
ALT_TITLE_RETRIES = 2

# Labels the LLM likes to prepend despite "Return ONLY the title".
_TITLE_LABEL_PREFIX = re.compile(r"^\s*(?:\*\*)?title\s*[:\-—]\s*", re.IGNORECASE)

_OPENS_WITH_HOW = re.compile(r"^\W*how\b", re.IGNORECASE)


def clean_title_candidate(raw: str) -> str:
    """Reduce a raw LLM title response to the bare title line.

    Strips a leading "Title:"-style label, surrounding quotes/markdown, and
    hashtags — the latter get truncated into junk fragments ("#His") once
    suffixes and length limits apply. Descriptions keep their hashtags.
    """
    if not raw:
        return ""

    cleaned = raw.strip().split("\n")[0]
    cleaned = _TITLE_LABEL_PREFIX.sub("", cleaned)
    cleaned = cleaned.strip().strip("*").strip().strip('"').strip("'")
    return re.sub(r"\s*#\w+", "", cleaned).strip(" -|—")


def opens_with_how(title: str) -> bool:
    """True if a title leads with the word "How".

    Ignores leading punctuation/quotes so a stray wrapper can't smuggle a
    "How ..." title past the opener-variety check.
    """
    return bool(_OPENS_WITH_HOW.match(title or ""))
