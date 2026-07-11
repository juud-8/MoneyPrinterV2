"""Low-cost near-duplicate detection for generated video topics."""

from __future__ import annotations

import re
from difflib import SequenceMatcher

STOP_WORDS = {
    "a", "an", "and", "as", "at", "for", "from", "how", "in", "into",
    "of", "on", "the", "then", "to", "was", "were", "when", "why", "with",
}


def _stem(token: str) -> str:
    """Fold trivial plurals so "emus"/"emu" and "guns"/"gun" match."""
    if token.isdigit() or len(token) <= 3 or token.endswith("ss"):
        return token
    return token[:-1] if token.endswith("s") else token


def _tokens(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    return [_stem(word) for word in words if word not in STOP_WORDS and len(word) > 1]


def topic_similarity(left: str, right: str) -> float:
    """Blend token overlap and text sequence similarity into a 0-1 score."""
    left_tokens = _tokens(left)
    right_tokens = _tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0

    left_set = set(left_tokens)
    right_set = set(right_tokens)
    jaccard = len(left_set & right_set) / len(left_set | right_set)
    containment = len(left_set & right_set) / min(len(left_set), len(right_set))
    sequence = SequenceMatcher(None, " ".join(left_tokens), " ".join(right_tokens)).ratio()

    # Shared rare-looking identifiers (years, long names, unusual nouns) are
    # strong evidence that two differently worded titles cover the same event.
    distinctive_left = {token for token in left_set if token.isdigit() or len(token) >= 7}
    distinctive_right = {token for token in right_set if token.isdigit() or len(token) >= 7}
    distinctive = 1.0 if distinctive_left & distinctive_right else 0.0
    score = min(1.0, 0.35 * jaccard + 0.30 * containment + 0.25 * sequence + 0.10 * distinctive)

    shared_numbers = {token for token in left_set & right_set if token.isdigit()}
    shared_long_terms = {token for token in left_set & right_set if len(token) >= 7}
    if len(shared_numbers) >= 2 and shared_long_terms:
        # A proper-name-like anchor plus the same two quantities is a strong
        # event fingerprint even when verbs are paraphrased by the LLM.
        score = max(score, 0.78)

    shared_words = {token for token in left_set & right_set if not token.isdigit()}
    if shared_numbers and len(shared_words) >= 3:
        # Same year plus three shared content words is almost always the same
        # event reworded (the Emu War double-up scored only ~0.33 on the
        # blended metrics above). A false positive just skips one candidate.
        score = max(score, 0.66)
    return score


def find_near_duplicate(
    candidate: str, existing_topics: list[str], threshold: float = 0.62
) -> tuple[str, float] | None:
    best_text = ""
    best_score = 0.0
    for existing in existing_topics:
        score = topic_similarity(candidate, existing)
        if score > best_score:
            best_text, best_score = existing, score
    if best_text and best_score >= threshold:
        return best_text, best_score
    return None
