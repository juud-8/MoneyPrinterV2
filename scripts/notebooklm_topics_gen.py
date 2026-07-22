#!/usr/bin/env python3
"""Keep a brand's NotebookLM topic backlog stocked with fresh, deduped topics.

Reads the brand's ``content_strategy.topic_mix`` categories, everything already
in the topics file, and every published title/subject in analytics, then asks
the quality LLM for new documented weird-history topics that share no rare
keyword with any of them. Appends survivors to the topics file.

Run daily (cheap, one LLM call, skips itself when the backlog is healthy):
    python scripts/notebooklm_topics_gen.py <brand_id> --min-backlog 6
"""
import argparse
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
os.chdir(ROOT)

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

from brand_switcher import load_brand
from notebooklm_publish import parse_llm_metadata  # noqa: F401  (shared JSON habits)

STOPWORDS = {
    "history", "there", "their", "which", "would", "after", "before", "years",
    "about", "world", "great", "first", "single", "every", "people", "story",
}


def rare_keywords(text: str) -> set:
    return {
        word
        for word in re.findall(r"[a-z]{5,}", (text or "").lower())
        if word not in STOPWORDS
    }


def is_duplicate(candidate: str, existing_keyword_sets: list[set]) -> bool:
    """A candidate collides when it shares two or more rare keywords with the
    same existing item — one generic word ("prison", "island") in common is
    fine; two together ("basel" + "rooster") means the same event."""
    keywords = rare_keywords(candidate)
    return any(len(keywords & existing) >= 2 for existing in existing_keyword_sets)


def parse_topic_array(reply: str) -> list[dict]:
    match = re.search(r"\[.*\]", reply or "", flags=re.DOTALL)
    if not match:
        return []
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    return [
        {"topic": str(e.get("topic", "")).strip(), "category": str(e.get("category", ""))}
        for e in data
        if isinstance(e, dict) and e.get("topic")
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Replenish the NotebookLM topic backlog.")
    parser.add_argument("brand_id", nargs="?", default="the_strange_archive")
    parser.add_argument("--topics", help="topics file (default: brands/<id>/notebooklm_topics.json)")
    parser.add_argument("--count", type=int, default=6, help="new topics to request")
    parser.add_argument(
        "--min-backlog",
        type=int,
        default=0,
        help="skip generation while this many topics are still unscheduled",
    )
    parser.add_argument("--dry-run", action="store_true", help="print candidates, don't append")
    args = parser.parse_args(argv)

    brand = load_brand(args.brand_id)
    if not brand:
        print(f"ERROR: unknown brand: {args.brand_id}")
        return 2
    topics_path = args.topics or os.path.join(
        ROOT, "brands", args.brand_id, "notebooklm_topics.json"
    )
    topics = []
    if os.path.isfile(topics_path):
        with open(topics_path, encoding="utf-8") as f:
            topics = json.load(f)

    if args.min_backlog:
        state_path = os.path.join(
            ROOT, "output", args.brand_id, "notebooklm", "batch_state.json"
        )
        scheduled = set()
        if os.path.isfile(state_path):
            with open(state_path, encoding="utf-8") as f:
                episodes = json.load(f).get("episodes", {})
            scheduled = {t for t, r in episodes.items() if r.get("status") == "scheduled"}
        backlog = sum(1 for e in topics if e["topic"] not in scheduled)
        if backlog >= args.min_backlog:
            print(f"Backlog healthy ({backlog} unscheduled topics); nothing to do.")
            return 0

    existing_sets = [rare_keywords(e["topic"]) for e in topics]
    analytics_path = os.path.join(ROOT, ".mp", "analytics.json")
    if os.path.isfile(analytics_path):
        with open(analytics_path, encoding="utf-8") as f:
            for video in json.load(f).get("videos", []):
                if args.brand_id in (video.get("brand_id", ""), "") or "history" in (
                    video.get("niche") or ""
                ):
                    existing_sets.append(
                        rare_keywords(f"{video.get('title', '')} {video.get('subject', '')}")
                    )

    mix = brand.get("production", {}).get("content_strategy", {}).get("topic_mix", [])
    categories = "\n".join(
        f"- {m['name']} (weight {m.get('weight', 0)}): {m.get('guidance', '')}" for m in mix
    ) or "- weird but true documented history"
    used = "\n".join(f"- {e['topic']}" for e in topics[-40:])

    from llm_provider import generate_text

    reply = generate_text(
        f"Propose {args.count * 2} NEW documented weird-but-true history topics "
        "for 60-second YouTube Shorts. Requirements: each is one specific real, "
        "well-documented event or person (include the year); no urban legends "
        "or disputed tales; nothing overlapping these already-used topics:\n"
        f"{used}\n\nBalance across these categories:\n{categories}\n\n"
        'Reply with ONLY a JSON array: [{"topic": "...", "category": "..."}]. '
        "Each topic is a single research-query-ready sentence.",
        quality=True,
    )
    candidates = parse_topic_array(reply)
    fresh = []
    for entry in candidates:
        if is_duplicate(entry["topic"], existing_sets):
            continue
        existing_sets.append(rare_keywords(entry["topic"]))
        fresh.append(entry)
        if len(fresh) >= args.count:
            break

    if not fresh:
        print("No non-duplicate candidates survived; try again later.")
        return 1
    for entry in fresh:
        print(f"  + {entry['topic']}")
    if args.dry_run:
        print(f"(dry run - {len(fresh)} topics not appended)")
        return 0
    with open(topics_path, "w", encoding="utf-8") as f:
        json.dump(topics + fresh, f, indent=2, ensure_ascii=False)
    print(f"Appended {len(fresh)} topics -> {topics_path} ({len(topics) + len(fresh)} total)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
