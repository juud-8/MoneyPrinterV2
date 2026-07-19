"""Manual, on-demand trend discovery for topic suggestions.

Sources current search trends and asks the configured LLM to translate a
brand's niche into search-friendly seed queries, then filters/ranks the
results for niche fit. Manually triggered from the dashboard only — nothing
here runs automatically. Any failure (missing dependency, network error, LLM
error) degrades to an empty list rather than raising, so a broken or
unavailable trend source never breaks the dashboard.
"""

from __future__ import annotations

from llm_provider import generate_text
from status import warning

MAX_SEED_QUERIES = 4
MAX_CANDIDATES = 5


def _fetch_google_trends_raw(seed_queries: list[str]) -> dict[str, list[str]]:
    """Return {seed: [related query, ...]} from Google Trends.

    Uses the unofficial `pytrends` package, which scrapes an undocumented
    Google endpoint rather than a real public API — it has broken before and
    may again. Verify against pytrends' current README if this starts
    raising unexpectedly; callers must always tolerate this failing.
    """
    from pytrends.request import TrendReq  # lazy: optional, pulls in pandas

    client = TrendReq(hl="en-US", tz=360)
    results: dict[str, list[str]] = {}
    for seed in seed_queries:
        client.build_payload([seed], timeframe="now 7-d")
        related = client.related_queries() or {}
        entry = related.get(seed) or {}
        queries: list[str] = []
        for key in ("rising", "top"):
            frame = entry.get(key)
            if frame is not None and not frame.empty:
                queries.extend(str(q) for q in frame["query"].tolist())
        results[seed] = queries
    return results


def _seed_queries_from_niche(niche: str) -> list[str]:
    """Turn a brand's prose niche description into short search phrases."""
    prompt = (
        "Turn this content niche description into 2-4 short (2-4 word) search "
        "phrases someone would actually type into a search engine. Return ONLY "
        "the phrases, one per line, no numbering or extra commentary.\n\n"
        f"Niche: {niche}"
    )
    response = generate_text(prompt) or ""
    phrases = [line.strip("-*• \t") for line in response.splitlines()]
    return [p for p in phrases if p][:MAX_SEED_QUERIES]


def _rank_candidates_for_niche(niche: str, candidates: list[str]) -> list[str]:
    """Filter/reorder raw trend candidates for fit with a brand's niche."""
    if not candidates:
        return []
    listing = "\n".join(f"- {c}" for c in candidates)
    prompt = (
        f"A content channel covers this niche: {niche}\n\n"
        f"Here are currently-trending search queries:\n{listing}\n\n"
        "Return ONLY the ones (verbatim, as listed) that could plausibly "
        "inspire a good video for this specific niche, best fit first, one "
        "per line, no extra commentary. If none fit, return nothing."
    )
    response = generate_text(prompt) or ""
    ranked = [line.strip("-*• \t") for line in response.splitlines()]
    ranked = [r for r in ranked if r]
    # Only keep candidates the LLM actually echoed back verbatim (case-
    # insensitively) — never let it invent a "trending" topic that wasn't
    # actually in the fetched data.
    by_lower = {c.lower(): c for c in candidates}
    kept = [by_lower[r.lower()] for r in ranked if r.lower() in by_lower]
    return kept[:MAX_CANDIDATES]


def fetch_trending_topics(niche: str) -> list[str]:
    """Return up to MAX_CANDIDATES trending topic candidates fit to a niche.

    Never raises to the caller — any failure logs a warning and returns [].
    """
    niche = (niche or "").strip()
    if not niche:
        return []
    try:
        seeds = _seed_queries_from_niche(niche)
        if not seeds:
            return []
        raw = _fetch_google_trends_raw(seeds)
        candidates: list[str] = []
        seen: set[str] = set()
        for queries in raw.values():
            for query in queries:
                key = query.lower()
                if key not in seen:
                    seen.add(key)
                    candidates.append(query)
        return _rank_candidates_for_niche(niche, candidates)
    except Exception as exc:  # pytrends/network/LLM failures all land here
        warning(f"Trend discovery failed: {exc}")
        return []
