"""Build long-form topics as themed compilations of already-published episodes.

The shorts topic generator looks for one novel incident, and after enough
episodes in a narrow niche it saturates: every fresh candidate collides with the
duplicate guardrail. Long-form does not need a novel incident — it needs a theme
broad enough to sustain several minutes, and the strongest raw material is the
back catalogue, which is already researched and already proven with an audience.

So a long-form subject here is a *cluster* of published episodes that share a
keyword, rendered as an explicit chapter list. It is fed to the pipeline as a
preset subject, which bypasses the single-incident duplicate check by design.

Brand-agnostic: callers supply the niche/format filters.
"""
from __future__ import annotations

import re
from collections import defaultdict

# Words that group episodes uselessly (channel furniture, not subject matter).
STOPWORDS = {
    "history", "historyfacts", "weirdhistory", "didyouknow", "strange",
    "archive", "shorts", "short", "facts", "their", "there", "which", "would",
    "after", "before", "years", "sentenced", "defeated", "started", "returned",
    "became", "ended", "killed", "caused", "forced", "changed", "cost",
}
MIN_CLUSTER = 3
DEFAULT_CHAPTERS = 6


def keywords(title: str) -> set[str]:
    words = re.findall(r"[a-z]{5,}", title.lower().split("#")[0])
    return {word for word in words if word not in STOPWORDS}


def published_episodes(analytics: dict, niche_contains: str, video_format: str = "short") -> list[dict]:
    """Published episodes with a title, newest last. Views may be absent."""
    videos = analytics.get("videos")
    if not isinstance(videos, list):
        return []
    episodes: list[dict] = []
    seen: set[str] = set()
    for video in videos:
        if not isinstance(video, dict):
            continue
        if niche_contains.lower() not in str(video.get("niche") or "").lower():
            continue
        if video.get("format") != video_format:
            continue
        title = str(video.get("title") or "").split("#")[0].strip().rstrip("|").strip()
        url = str(video.get("url") or "").strip()
        if not title or not url or title.lower() in seen:
            continue
        seen.add(title.lower())
        views = video.get("views")
        if not isinstance(views, int) or isinstance(views, bool) or views < 0:
            views = 0
        episodes.append({"title": title, "views": views, "date": str(video.get("date") or "")})
    return episodes


def cluster_by_keyword(episodes: list[dict]) -> dict[str, list[dict]]:
    clusters: dict[str, list[dict]] = defaultdict(list)
    for episode in episodes:
        for word in keywords(episode["title"]):
            clusters[word].append(episode)
    return {word: members for word, members in clusters.items() if len(members) >= MIN_CLUSTER}


def rank_clusters(clusters: dict[str, list[dict]], used_themes: set[str] | None = None) -> list[tuple[str, list[dict]]]:
    """Best theme first: proven reach, then breadth. Skips already-used themes."""
    used = {theme.lower() for theme in (used_themes or set())}
    ranked = []
    for word, members in clusters.items():
        if word in used:
            continue
        ordered = sorted(members, key=lambda e: e["views"], reverse=True)
        # Median-ish reach of the members, so one viral outlier cannot carry a
        # weak cluster, plus a mild bonus for having more chapters available.
        reach = sum(e["views"] for e in ordered) / len(ordered)
        ranked.append((word, ordered, reach + len(ordered) * 25))
    ranked.sort(key=lambda item: item[2], reverse=True)
    return [(word, members) for word, members, _ in ranked]


def build_theme_subject(
    analytics: dict,
    niche_contains: str,
    used_themes: set[str] | None = None,
    chapters: int = DEFAULT_CHAPTERS,
) -> dict | None:
    """Return {theme, subject, chapters:[titles]} or None if the catalogue is too thin."""
    episodes = published_episodes(analytics, niche_contains)
    ranked = rank_clusters(cluster_by_keyword(episodes), used_themes)
    if not ranked:
        return None
    theme, members = ranked[0]
    picked = members[: max(MIN_CLUSTER, chapters)]
    lines = "\n".join(f"{index}. {episode['title']}" for index, episode in enumerate(picked, 1))
    subject = (
        f"A single documentary-style compilation episode on the theme of "
        f"'{theme}' in real history. Cover each of these documented cases as its "
        f"own chapter, in this order, with a linking sentence between them:\n{lines}\n"
        "Open by naming the thread that connects them; close by restating it. "
        "Every case must stay factually accurate to the real documented event."
    )
    return {"theme": theme, "subject": subject, "chapters": [e["title"] for e in picked]}
