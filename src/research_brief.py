"""Ground nonfiction scripts in retrievable source material.

The source collectors intentionally use public, no-key APIs so research does
not add a per-video service cost.  The resulting brief is an audit artifact,
not a claim that every source is authoritative: a human still owns final fact
checking, and the brief records enough context to make that review practical.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime
from typing import Callable

import requests

from config import ROOT_DIR

USER_AGENT = "MoneyPrinterV2/2.0 (source-backed video research)"
WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
LOC_SEARCH_API = "https://www.loc.gov/search/"


def _get_json(url: str, params: dict, timeout: float = 12.0) -> dict:
    response = requests.get(
        url,
        params=params,
        headers={"User-Agent": USER_AGENT},
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, dict) else {}


def search_wikipedia(
    topic: str,
    limit: int = 3,
    fetch_json: Callable[[str, dict, float], dict] = _get_json,
) -> list[dict]:
    """Return concise Wikipedia source excerpts for a topic."""
    payload = fetch_json(
        WIKIPEDIA_API,
        {
            "action": "query",
            "generator": "search",
            "gsrsearch": topic,
            "gsrlimit": max(1, int(limit)),
            "prop": "extracts|info",
            "exintro": 1,
            "explaintext": 1,
            "exchars": 1400,
            "inprop": "url",
            "format": "json",
            "formatversion": 2,
        },
        12.0,
    )
    pages = (payload.get("query") or {}).get("pages") or []
    pages = sorted(pages, key=lambda page: page.get("index", 9999))
    sources = []
    for page in pages[:limit]:
        title = str(page.get("title") or "").strip()
        url = str(page.get("fullurl") or "").strip()
        excerpt = re.sub(r"\s+", " ", str(page.get("extract") or "")).strip()
        if title and url and excerpt:
            sources.append(
                {
                    "provider": "wikipedia",
                    "title": title,
                    "url": url,
                    "excerpt": excerpt[:1400],
                    "rights": "See the linked page and its cited sources.",
                }
            )
    return sources


def search_library_of_congress(
    topic: str,
    limit: int = 3,
    fetch_json: Callable[[str, dict, float], dict] = _get_json,
) -> list[dict]:
    """Return digitized-item leads from the Library of Congress."""
    payload = fetch_json(
        LOC_SEARCH_API,
        {"q": topic, "fo": "json", "c": max(1, int(limit)), "at": "results"},
        12.0,
    )
    sources = []
    for item in (payload.get("results") or [])[:limit]:
        title = str(item.get("title") or "").strip()
        url = str(item.get("id") or "").strip()
        date = str(item.get("date") or "").strip()
        description = item.get("description") or []
        if isinstance(description, str):
            description = [description]
        excerpt = " ".join(str(value) for value in description if value)
        excerpt = re.sub(r"\s+", " ", f"{date} {excerpt}").strip()
        if title and url:
            sources.append(
                {
                    "provider": "library_of_congress",
                    "title": title,
                    "url": url,
                    "excerpt": excerpt[:1400] or "Digitized collection item and catalog record.",
                    "rights": str(item.get("rights") or "Check the item Rights & Access statement."),
                }
            )
    return sources


_NARRATIVE_STOPWORDS = {
    "how",
    "why",
    "when",
    "what",
    "the",
    "a",
    "an",
    "of",
    "in",
    "on",
    "to",
    "for",
    "and",
    "or",
    "with",
    "from",
    "that",
    "this",
    "into",
    "over",
    "after",
    "before",
    "during",
    "between",
    "forced",
    "sparked",
    "ended",
    "began",
    "made",
    "took",
    "sent",
    "single",
    "major",
    "full",
    "scale",
    "fullscale",
    "humiliating",
    "organized",
    "domestic",
    "runaway",
    "military",
    "invasion",
    "border",
    "forcing",
    "emperor",
    "retreat",
    "july",
    "june",
    "august",
    "september",
    "october",
    "november",
    "december",
    "january",
    "february",
    "march",
    "april",
    "crate",
}


def _topic_is_title_case(topic: str) -> bool:
    words = [w for w in re.findall(r"[A-Za-z]+", topic) if len(w) > 2]
    if len(words) < 4:
        return False
    capped = sum(1 for w in words if w[0].isupper())
    return capped / len(words) >= 0.7


def search_queries_for_topic(topic: str) -> list[str]:
    """Build progressively shorter search queries for public archives.

    LLM topic sentences ("How a single runaway dog sparked...") and Title Case
    hooks ("How 1 Crate of Exploding Vinyl...") are poor Wikipedia/LOC queries.
    Prefer the full topic first, then compact year + content-keyword queries.
    """
    topic = (topic or "").strip()
    if not topic:
        return []

    years = re.findall(r"\b(?:1[0-9]{3}|20[0-9]{2})\b", topic)
    tokens = re.findall(r"[A-Za-z]{3,}", topic)
    content_words = [
        token
        for token in tokens
        if token.lower() not in _NARRATIVE_STOPWORDS and not token.isdigit()
    ]

    queries = [topic]

    # Strip "How/Why ..." framing and leading numerals: keeps more searchable nouns.
    stripped = re.sub(
        r"^(?:how|why|when|what)\s+(?:\d+\s+)?",
        "",
        topic,
        flags=re.IGNORECASE,
    ).strip(" .")
    stripped = re.sub(r"\bon\s+[A-Za-z]+\s+\d{1,2},\s*\d{4}\.?$", "", stripped, flags=re.IGNORECASE).strip()
    if stripped and stripped.lower() != topic.lower():
        queries.append(stripped)

    # Multi-word institution/place phrases only when the topic is NOT title case
    # (title case makes every word look like a proper noun).
    if not _topic_is_title_case(topic):
        proper = re.findall(r"\b(?:[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b", topic)
        entity_names = [
            name
            for name in proper
            if name.lower() not in _NARRATIVE_STOPWORDS
        ]
        if years and len(entity_names) >= 2:
            short = f"{entity_names[0]} {entity_names[1]} {years[0]}"
            if short not in queries:
                queries.append(short)
        elif years and entity_names:
            short = f"{entity_names[0]} {years[0]}"
            if short not in queries:
                queries.append(short)

    # Year + distinctive content nouns (vinyl, baseball, forfeit, etc.).
    # Prefer longer tokens; keep order of first appearance for readability.
    ranked = sorted(
        dict.fromkeys(content_words),
        key=lambda w: (-len(w), content_words.index(w)),
    )
    keyword_core = ranked[:4]
    if years and keyword_core:
        keyword_query = " ".join(keyword_core[:3] + years[:1])
        if keyword_query not in queries:
            queries.append(keyword_query)
    if years and len(keyword_core) >= 2:
        short_keywords = f"{keyword_core[0]} {keyword_core[1]} {years[0]}"
        if short_keywords not in queries:
            queries.append(short_keywords)

    # Deduplicate while preserving order.
    seen = set()
    unique = []
    for query in queries:
        key = query.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(query)
    return unique


def _filter_relevant_sources(
    topic: str,
    collected: list[dict],
    *,
    query: str | None = None,
) -> list[dict]:
    topic_terms = {
        term
        for term in re.findall(r"[a-z0-9]+", topic.lower())
        if len(term) > 2
        and term not in {"the", "and", "with", "from", "that", "this", "into", "great"}
    }
    if query:
        topic_terms |= {
            term
            for term in re.findall(r"[a-z0-9]+", query.lower())
            if len(term) > 2
            and term not in {"the", "and", "with", "from", "that", "this", "into", "great"}
        }
    distinctive_terms = {
        term for term in topic_terms if not term.isdigit() and len(term) >= 7
    }

    deduped = []
    seen_urls = set()
    for source in collected:
        url = source.get("url", "")
        if not url or url in seen_urls:
            continue
        source_text = f"{source.get('title', '')} {source.get('excerpt', '')}".lower()
        source_terms = set(re.findall(r"[a-z0-9]+", source_text))
        shared = topic_terms & source_terms
        # Require two meaningful shared terms, or one distinctive proper-name-
        # like anchor. This prevents broad "war" catalog results
        # from being counted as evidence for a specific historical anecdote.
        shared_words = {term for term in shared if not term.isdigit()}
        if len(shared_words) < 2 and not (shared_words & distinctive_terms):
            continue
        seen_urls.add(url)
        enriched = dict(source)
        enriched["id"] = f"S{len(deduped) + 1}"
        deduped.append(enriched)
    return deduped


def collect_sources(topic: str, per_provider: int = 3) -> list[dict]:
    """Collect and label source candidates, tolerating one provider outage."""
    best: list[dict] = []
    for query in search_queries_for_topic(topic):
        collected = []
        for collector in (search_wikipedia, search_library_of_congress):
            try:
                collected.extend(collector(query, limit=per_provider))
            except (requests.RequestException, ValueError, TypeError):
                continue
        filtered = _filter_relevant_sources(topic, collected, query=query)
        if len(filtered) > len(best):
            best = filtered
        if len(best) >= 2:
            return best
    return best


def build_grounded_research_prompt(topic: str, niche: str, sources: list[dict]) -> str:
    source_text = "\n\n".join(
        f"[{source['id']}] {source['title']}\nURL: {source['url']}\nEXCERPT: {source['excerpt']}"
        for source in sources
    )
    return f"""Create a factual research brief for a YouTube explainer.

Topic: {topic}
Niche: {niche}

Use ONLY facts directly supported by the supplied excerpts. Do not fill gaps from
memory. If sources conflict or a detail is uncertain, put it in disputed_points
instead of stating it as fact. Every claim must cite one or more supplied source IDs.

Return ONLY valid JSON with this exact shape:
{{
  "summary": "one-sentence editorial angle",
  "claims": [{{"text": "specific factual claim", "source_ids": ["S1"]}}],
  "disputed_points": ["uncertainty or conflict"],
  "visual_leads": [{{"source_id": "S2", "reason": "useful document, map, or image"}}]
}}

SUPPLIED SOURCES:
{source_text}
"""


def _extract_json(raw: str) -> dict:
    clean = (raw or "").strip()
    clean = re.sub(r"^```(?:json)?\s*", "", clean, flags=re.IGNORECASE)
    clean = re.sub(r"\s*```$", "", clean)
    start = clean.find("{")
    end = clean.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("Research response did not contain a JSON object.")
    payload = json.loads(clean[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("Research response must be a JSON object.")
    return payload


def parse_research_brief(raw: str, topic: str, sources: list[dict]) -> dict:
    """Validate source IDs and discard unsupported generated claims."""
    payload = _extract_json(raw)
    valid_ids = {source["id"] for source in sources}
    claims = []
    for claim in payload.get("claims") or []:
        if not isinstance(claim, dict):
            continue
        text = re.sub(r"\s+", " ", str(claim.get("text") or "")).strip()
        source_ids = [
            source_id
            for source_id in claim.get("source_ids") or []
            if source_id in valid_ids
        ]
        source_ids = list(dict.fromkeys(source_ids))
        if text and source_ids:
            claims.append({"text": text, "source_ids": source_ids})

    if not claims:
        raise ValueError("Research response contained no source-mapped claims.")

    visual_leads = []
    for lead in payload.get("visual_leads") or []:
        if not isinstance(lead, dict) or lead.get("source_id") not in valid_ids:
            continue
        visual_leads.append(
            {
                "source_id": lead["source_id"],
                "reason": str(lead.get("reason") or "").strip(),
            }
        )

    cited_ids = sorted({sid for claim in claims for sid in claim["source_ids"]})
    return {
        "topic": topic,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "summary": str(payload.get("summary") or "").strip(),
        "claims": claims,
        "disputed_points": [
            str(value).strip()
            for value in payload.get("disputed_points") or []
            if str(value).strip()
        ],
        "visual_leads": visual_leads,
        "sources": sources,
        "cited_source_ids": cited_ids,
    }


def research_quality_issues(
    brief: dict, min_claims: int = 4, min_cited_sources: int = 2
) -> list[str]:
    issues = []
    if len(brief.get("claims") or []) < min_claims:
        issues.append(f"fewer than {min_claims} source-mapped claims")
    if len(brief.get("cited_source_ids") or []) < min_cited_sources:
        issues.append(f"fewer than {min_cited_sources} cited sources")
    return issues


def render_research_notes(brief: dict) -> str:
    lines = []
    for claim in brief.get("claims") or []:
        citations = ",".join(claim.get("source_ids") or [])
        lines.append(f"- {claim['text']} [{citations}]")
    if brief.get("disputed_points"):
        lines.append("- DO NOT STATE AS SETTLED: " + "; ".join(brief["disputed_points"]))
    return "\n".join(lines)


def save_research_brief(brief: dict, brand_id: str = "unknown") -> str:
    digest = hashlib.sha1(brief.get("topic", "").encode("utf-8")).hexdigest()[:10]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    folder = os.path.join(ROOT_DIR, ".mp", "research", brand_id or "unknown")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"{timestamp}_{digest}.json")
    with open(path, "w", encoding="utf-8") as file:
        json.dump(brief, file, ensure_ascii=False, indent=2)
    return path
