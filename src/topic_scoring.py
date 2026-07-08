"""Heuristic topic/title scoring helper.

Used by content styles that opt in via `topic_candidate_count` /
`title_candidate_count` > 1 (see `content_styles.py`) to generate a few
candidate topics or titles and keep the best one, instead of always taking
the LLM's first draft. Purely a heuristic (no LLM call) so it's fast and
deterministic — tune the keyword lists/weights below as you see what
actually performs well.

Not wired into any style by default; existing brands are unaffected.
"""

import re

# Words that signal a "wait, what?" absurd-contrast historical hook —
# tuned for the weird-but-true-history content shape (wars, trials,
# disasters, royal/political oddities, hoaxes, scientific mishaps).
_ABSURD_CONTRAST_KEYWORDS = [
    "war", "army", "military", "battle", "trial", "hanged", "hung",
    "executed", "arrested", "sued", "surrendered", "declared",
    "banned", "outlawed", "emperor", "king", "queen", "pope",
    "president", "royal", "plague", "flood", "famine", "riot",
    "beer", "wine", "rabbit", "pig", "goat", "bucket", "duel",
    "hoax", "curse", "cursed", "eclipse", "comet", "mutiny",
    "invasion", "revolt", "uprising", "assassination", "trial",
    "lawsuit", "explosion", "disaster", "scandal", "conspiracy",
    "vs", "vs.",
]

# Generic/AI-slop phrasing that tends to signal a weak, interchangeable
# title rather than a specific real event.
_SLOP_PHRASES = [
    "you won't believe", "you wont believe", "mind blowing", "mind-blowing",
    "top 10", "top ten", "amazing facts", "shocking truth", "must know",
    "here are", "did you know that", "unbelievable",
]

_HAS_DIGIT = re.compile(r"\d")
_CAPITALIZED_WORD = re.compile(r"(?<!^)\b[A-Z][a-z]+")


def score_title(text: str) -> float:
    """Heuristic 0-100ish score favoring specific, concrete, clickable titles.

    Rewards: a number/year, a short clickable length, absurd-contrast
    keywords, and a specific capitalized proper-noun-like word beyond the
    first word. Penalizes generic/AI-slop phrasing and excessive length.
    """
    if not text:
        return 0.0

    clean = text.strip()
    lower = clean.lower()
    score = 50.0

    if _HAS_DIGIT.search(clean):
        score += 15.0

    length = len(clean)
    if length <= 55:
        score += 10.0
    elif length > 90:
        score -= 15.0

    keyword_hits = sum(1 for kw in _ABSURD_CONTRAST_KEYWORDS if kw in lower)
    score += min(keyword_hits, 3) * 8.0

    if _CAPITALIZED_WORD.search(clean):
        score += 10.0

    for phrase in _SLOP_PHRASES:
        if phrase in lower:
            score -= 20.0

    if clean.count("?") > 1 or "..." in clean:
        score -= 10.0

    return score


def pick_best(candidates: list[str], scorer=score_title) -> str:
    """Return the highest-scoring non-empty candidate (first on ties)."""
    valid = [c for c in candidates if c and c.strip()]
    if not valid:
        return candidates[0] if candidates else ""
    return max(valid, key=scorer)
