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


def collect_sources(topic: str, per_provider: int = 3) -> list[dict]:
    """Collect and label source candidates, tolerating one provider outage."""
    collected = []
    for collector in (search_wikipedia, search_library_of_congress):
        try:
            collected.extend(collector(topic, limit=per_provider))
        except (requests.RequestException, ValueError, TypeError):
            continue

    topic_terms = {
        term
        for term in re.findall(r"[a-z0-9]+", topic.lower())
        if len(term) > 2
        and term not in {"the", "and", "with", "from", "that", "this", "into", "great"}
    }
    distinctive_terms = {term for term in topic_terms if not term.isdigit() and len(term) >= 7}

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
