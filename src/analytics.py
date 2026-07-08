"""Video performance analytics logging for weekly iteration and dashboards."""

import json
import os
import re
from datetime import datetime, timedelta

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _analytics_path() -> str:
    return os.path.join(ROOT_DIR, ".mp", "analytics.json")


def get_asset_spend_alert_threshold_usd() -> float:
    """Read spend alert threshold without importing the full config module."""
    config_path = os.path.join(ROOT_DIR, "config.json")
    if not os.path.isfile(config_path):
        return 25.0
    with open(config_path, "r", encoding="utf-8") as file:
        return float(json.load(file).get("asset_spend_alert_threshold_usd", 25))


def _load() -> dict:
    path = _analytics_path()
    if not os.path.isfile(path):
        return {"videos": [], "weekly_notes": [], "asset_spend": []}
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
        data.setdefault("asset_spend", [])
        return data


def _save(data: dict) -> None:
    path = _analytics_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _normalize_title(title: str) -> str:
    """Collapse whitespace and strip channel suffix for dedupe keys."""
    text = re.sub(r"\s+", " ", (title or "").strip())
    if " | " in text:
        text = text.rsplit(" | ", 1)[0].strip()
    return text.lower()


def _parse_date(value: str) -> datetime | None:
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return None


def _brand_lookup() -> tuple[dict[str, str], dict[str, str]]:
    """Return (niche -> brand_id, channel_name -> brand_id) from manifests."""
    try:
        from brand_switcher import list_brands
    except ImportError:
        return {}, {}

    niche_map: dict[str, str] = {}
    channel_map: dict[str, str] = {}
    for brand in list_brands():
        brand_id = brand["brand_id"]
        niche = (brand.get("niche") or "").strip()
        if niche:
            niche_map[niche] = brand_id
        channel_name = (brand.get("channel_name") or "").strip()
        if channel_name:
            channel_map[channel_name] = brand_id
    return niche_map, channel_map


def _infer_brand_id(entry: dict, niche_map: dict[str, str], channel_map: dict[str, str]) -> str:
    brand_id = (entry.get("brand_id") or "").strip()
    if brand_id:
        return brand_id

    video_path = (entry.get("video_path") or "").replace("\\", "/")
    match = re.search(r"/output/([^/]+)/", video_path, re.IGNORECASE)
    if match:
        return match.group(1)

    niche = (entry.get("niche") or "").strip()
    if niche in niche_map:
        return niche_map[niche]

    title = entry.get("title") or ""
    if " | " in title:
        channel_suffix = title.rsplit(" | ", 1)[-1].strip()
        if channel_suffix in channel_map:
            return channel_map[channel_suffix]

    return "unknown"


def _video_dedupe_key(entry: dict, brand_id: str) -> str:
    title = _normalize_title(entry.get("title", ""))
    subject = _normalize_title(entry.get("subject", ""))
    label = title or subject or (entry.get("url") or "").strip()
    return f"video:{brand_id}:{label}"


def _entry_priority(entry: dict) -> tuple[int, str]:
    """Higher is better when picking the canonical row for a video."""
    score = 0
    if entry.get("url"):
        score += 4
    if entry.get("status") == "uploaded":
        score += 2
    elif not entry.get("status") or entry.get("status") == "generated":
        score += 1
    return score, entry.get("date") or ""


def _merge_video_entries(entries: list[dict]) -> dict:
    canonical = max(entries, key=_entry_priority)
    merged = dict(canonical)
    merged["generate_count"] = sum(1 for e in entries if e.get("status") != "uploaded")
    merged["event_count"] = len(entries)
    if any(e.get("status") == "uploaded" for e in entries) or merged.get("url"):
        merged["status"] = "uploaded"
    elif not merged.get("status"):
        merged["status"] = "generated"
    return merged


def dedupe_videos(videos: list[dict] | None = None) -> list[dict]:
    """Return one canonical record per video, merging generate/upload duplicates."""
    raw = videos if videos is not None else _load().get("videos", [])
    niche_map, channel_map = _brand_lookup()

    groups: dict[str, list[dict]] = {}
    for entry in raw:
        enriched = dict(entry)
        enriched["brand_id"] = _infer_brand_id(enriched, niche_map, channel_map)
        key = _video_dedupe_key(enriched, enriched["brand_id"])
        groups.setdefault(key, []).append(enriched)

    merged = [_merge_video_entries(group) for group in groups.values()]
    merged.sort(key=lambda item: item.get("date") or "", reverse=True)
    return merged


def log_video(
    title: str,
    format_type: str,
    niche: str,
    video_path: str = "",
    url: str = "",
    subject: str = "",
    brand_id: str = "",
    status: str = "generated",
) -> None:
    """Log a published or generated video for later weekly review."""
    data = _load()
    data["videos"].append(
        {
            "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "title": title,
            "format": format_type,
            "niche": niche,
            "subject": subject,
            "video_path": video_path,
            "url": url,
            "brand_id": brand_id,
            "status": status,
            "views": None,
            "ctr": None,
            "avg_view_duration": None,
            "rpm": None,
            "affiliate_clicks": None,
            "notes": "",
        }
    )
    _save(data)


def set_video_retention(needle: str, avg_view_pct: float) -> int:
    """Record Studio's "average percentage viewed" (0-100) on matching videos.

    `needle` matches a YouTube video id / URL fragment, or a case-insensitive
    title substring. Updates every matching raw entry so the deduped rows and
    the retention-aware topic ranking (performance_insights.py) pick it up.
    Returns the number of entries updated.

    CLI: python src/analytics.py retention "<video id or title fragment>" <pct>
    """
    pct = float(avg_view_pct)
    if not 0.0 <= pct <= 100.0:
        raise ValueError(f"avg_view_pct must be 0-100, got {pct}")
    needle = (needle or "").strip()
    needle_norm = _normalize_title(needle)
    if not needle_norm:
        return 0

    data = _load()
    updated = 0
    for entry in data.get("videos", []):
        in_url = needle in (entry.get("url") or "")
        in_title = needle_norm in _normalize_title(entry.get("title", ""))
        if in_url or in_title:
            entry["avg_view_pct"] = pct
            updated += 1
    if updated:
        _save(data)
    return updated


def log_asset_spend(
    video_title: str,
    role: str,
    tier: str,
    modality: str,
    provider: str,
    cost_usd: float,
    brand_id: str = "",
) -> None:
    """Log a single premium asset generation for cost visibility."""
    data = _load()
    data["asset_spend"].append(
        {
            "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "video_title": video_title,
            "brand_id": brand_id,
            "role": role,
            "tier": tier,
            "modality": modality,
            "provider": provider,
            "cost_usd": round(float(cost_usd or 0.0), 2),
        }
    )
    _save(data)


def _spend_in_window(entries: list[dict], days: int | None = None) -> list[dict]:
    if days is None:
        return entries
    cutoff = datetime.now() - timedelta(days=days)
    recent = []
    for entry in entries:
        entry_date = _parse_date(entry.get("date", ""))
        if entry_date and entry_date >= cutoff:
            recent.append(entry)
    return recent


def _assign_spend_brand(entry: dict, videos: list[dict], niche_map: dict[str, str], channel_map: dict[str, str]) -> str:
    brand_id = (entry.get("brand_id") or "").strip()
    if brand_id:
        return brand_id

    needle = _normalize_title(entry.get("video_title", ""))
    if needle:
        for video in videos:
            for field in ("subject", "title"):
                candidate = _normalize_title(video.get(field, ""))
                if candidate and (candidate == needle or needle in candidate or candidate in needle):
                    return video.get("brand_id") or "unknown"
    return "unknown"


def get_asset_spend_summary(days: int = 7) -> dict:
    """Total and recent (last N days) premium asset spend."""
    data = _load()
    entries = data.get("asset_spend", [])
    total = round(sum(e.get("cost_usd", 0.0) for e in entries), 2)

    recent_entries = _spend_in_window(entries, days)
    recent_total = round(sum(e.get("cost_usd", 0.0) for e in recent_entries), 2)

    return {
        "total_usd": total,
        "recent_usd": recent_total,
        "recent_days": days,
        "recent_count": len(recent_entries),
        "total_count": len(entries),
    }


def get_brand_summary(days: int = 7) -> list[dict]:
    """Per-brand counts and spend totals from deduped video rows."""
    videos = dedupe_videos()
    niche_map, channel_map = _brand_lookup()
    spend_entries = _load().get("asset_spend", [])

    try:
        from brand_switcher import list_brands
        brand_names = {b["brand_id"]: b["channel_name"] for b in list_brands()}
    except ImportError:
        brand_names = {}

    brand_ids = set(brand_names)
    brand_ids.update(v.get("brand_id", "unknown") for v in videos)
    brand_ids.update(
        _assign_spend_brand(entry, videos, niche_map, channel_map) for entry in spend_entries
    )

    summaries = []
    for brand_id in sorted(brand_ids):
        brand_videos = [v for v in videos if v.get("brand_id") == brand_id]
        uploaded = [v for v in brand_videos if v.get("status") == "uploaded"]
        views_values = [v["views"] for v in brand_videos if v.get("views") is not None]

        brand_spend = [
            e
            for e in spend_entries
            if _assign_spend_brand(e, videos, niche_map, channel_map) == brand_id
        ]
        spend_all = round(sum(e.get("cost_usd", 0.0) for e in brand_spend), 2)
        spend_recent = round(
            sum(e.get("cost_usd", 0.0) for e in _spend_in_window(brand_spend, days)), 2
        )

        summaries.append(
            {
                "brand_id": brand_id,
                "channel_name": brand_names.get(brand_id, brand_id.replace("_", " ").title()),
                "post_count": len(brand_videos),
                "uploaded_count": len(uploaded),
                "tracked_views": sum(views_values) if views_values else None,
                "metrics_filled": len(views_values),
                "spend_all_time_usd": spend_all,
                f"spend_{days}d_usd": spend_recent,
                "recent_posts": brand_videos[:5],
            }
        )

    summaries.sort(key=lambda item: (item["post_count"], item["channel_name"]), reverse=True)
    return summaries


def get_dashboard_data(days: int = 7) -> dict:
    """Structured payload for CLI and HTML dashboards."""
    videos = dedupe_videos()
    spend_entries = _load().get("asset_spend", [])
    recent_spend = _spend_in_window(spend_entries, days)

    spend_by_provider: dict[str, float] = {}
    spend_by_tier: dict[str, float] = {}
    for entry in recent_spend:
        provider = entry.get("provider") or "unknown"
        tier = entry.get("tier") or "unknown"
        cost = float(entry.get("cost_usd") or 0.0)
        spend_by_provider[provider] = round(spend_by_provider.get(provider, 0.0) + cost, 2)
        spend_by_tier[tier] = round(spend_by_tier.get(tier, 0.0) + cost, 2)

    brands = get_brand_summary(days=days)
    uploaded_total = sum(b["uploaded_count"] for b in brands)
    spend_summary = get_asset_spend_summary(days=days)

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "window_days": days,
        "brands": brands,
        "videos": videos,
        "recent_spend": recent_spend,
        "spend_by_provider": spend_by_provider,
        "spend_by_tier": spend_by_tier,
        "totals": {
            "videos": len(videos),
            "uploaded": uploaded_total,
            "spend_all_time_usd": spend_summary["total_usd"],
            f"spend_{days}d_usd": spend_summary["recent_usd"],
            "premium_assets_all_time": spend_summary["total_count"],
            f"premium_assets_{days}d": spend_summary["recent_count"],
        },
    }


def get_weekly_summary() -> str:
    """Return a text summary of recent videos for manual review."""
    data = get_dashboard_data(days=7)
    videos = data["videos"]
    if not videos:
        return "No videos logged yet. Generate and upload content to start tracking."

    recent = videos[:20]
    lines = ["=== Weekly Analytics Review (last 20 videos) ===", ""]
    for v in recent:
        brand = v.get("brand_id") or "unknown"
        status = v.get("status") or "generated"
        lines.append(
            f"- [{v['date']}] [{brand}] {v['format'].upper()} ({status}): {v['title'][:60]}"
        )
        if v.get("url"):
            lines.append(f"  URL: {v['url']}")
        metrics = []
        for key in ("views", "ctr", "rpm", "affiliate_clicks"):
            if v.get(key) is not None:
                metrics.append(f"{key}={v[key]}")
        if metrics:
            lines.append(f"  Metrics: {', '.join(metrics)}")
        lines.append("")

    lines.append("Action: Update metrics from YouTube Studio + affiliate dashboard weekly.")
    lines.append("Double down on topics with highest retention and affiliate CTR.")

    spend = get_asset_spend_summary(days=7)
    if spend["total_count"] > 0:
        lines.append("")
        lines.append("=== Premium Asset Spend ===")
        lines.append(
            f"Last {spend['recent_days']} days: ${spend['recent_usd']:.2f} "
            f"({spend['recent_count']} premium asset(s))"
        )
        lines.append(
            f"All-time logged: ${spend['total_usd']:.2f} ({spend['total_count']} premium asset(s))"
        )
        threshold = get_asset_spend_alert_threshold_usd()
        if spend["recent_usd"] > threshold:
            lines.append(
                f"⚠ Recent premium spend (${spend['recent_usd']:.2f}) exceeds your "
                f"alert threshold (${threshold:.2f}). Review asset_strategy if unintended."
            )

    return "\n".join(lines)


def print_weekly_review() -> None:
    print(get_weekly_summary())


if __name__ == "__main__":
    import sys as _sys

    _args = _sys.argv[1:]
    if _args and _args[0] == "retention":
        if len(_args) != 3:
            print('Usage: python src/analytics.py retention "<video id or title fragment>" <pct>')
            _sys.exit(2)
        _count = set_video_retention(_args[1], float(_args[2]))
        print(f"Set avg_view_pct={float(_args[2]):g} on {_count} matching entr{'y' if _count == 1 else 'ies'}.")
        if not _count:
            _sys.exit(1)
    else:
        print_weekly_review()
