#!/usr/bin/env python3
"""Batch-produce NotebookLM episodes and schedule the finished ones on YouTube.

For each topic in a JSON file (``[{"topic": "..."}, ...]``):

1. Generate + auto-finish via scripts/notebooklm_short.py (deep research ->
   short video -> download -> de-brand + brand outro).
2. Verify the finished file (exists, Shorts spec, sane duration). Episodes
   that fail verification are NEVER uploaded — they stay staged for review.
3. With ``--schedule-upload``: upload via the YouTube Data API as *private*
   with a future ``publishAt`` (one slot per day at the brand's prime time),
   so every episode sits as a scheduled draft that can be QC'd or pulled in
   Studio before it goes live.

Resume-safe: progress persists to batch_state.json next to the episodes;
re-running skips completed work. Uploads are capped per run
(``--max-uploads``) to respect the ~6/day YouTube API quota budget.
"""
import argparse
import json
import os
import shutil
import sys
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)

# line_buffering so progress reaches redirected logs immediately — overnight
# runs are watched via `tail -f`.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

import notebooklm_short
import video_postprocess
from analytics import log_video
from archived_brands import is_brand_archived
from brand_switcher import load_brand, switch_brand
from config import (
    get_is_for_kids,
    get_youtube_api_category_id,
    get_youtube_api_client_secrets_path,
    get_youtube_api_token_path,
)
from content_funnel import build_description
from notebooklm_publish import (
    build_metadata_prompt,
    compute_publish_slots,
    parse_llm_metadata,
    sanitize_description,
    sanitize_title,
)

MIN_DURATION_S = 20.0
MAX_DURATION_S = 200.0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Batch NotebookLM episodes; optionally schedule as private drafts."
    )
    parser.add_argument("brand_id", nargs="?", default="the_strange_archive")
    parser.add_argument("--topics", required=True, help="JSON file: [{'topic': ...}, ...]")
    parser.add_argument(
        "--schedule-upload",
        action="store_true",
        help="after verification, upload as private + publishAt (scheduled draft)",
    )
    parser.add_argument(
        "--max-uploads",
        type=int,
        default=5,
        help="upload cap per run (videos.insert costs ~1600 of the 10k daily quota)",
    )
    parser.add_argument("--publish-time", help="HH:MM local slot (default: manifest prime slot)")
    parser.add_argument(
        "--min-lead-hours",
        type=float,
        default=20.0,
        help="first publishAt must be at least this far out (QC window)",
    )
    parser.add_argument("--limit", type=int, default=0, help="process at most N topics this run")
    parser.add_argument("--research-mode", choices=["deep", "fast", "none"], default="deep")
    parser.add_argument("--dry-run", action="store_true", help="print the plan and exit")
    return parser


def load_state(path: str) -> dict:
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {"episodes": {}, "slots": [], "next_slot": 0}


def save_state(path: str, state: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def verify_final(final_path: str) -> str | None:
    """Return a rejection reason, or None when the file is upload-worthy."""
    if not os.path.isfile(final_path):
        return "final.mp4 missing (de-brand/finish step failed)"
    info = video_postprocess.probe_media(final_path)
    if (info["width"], info["height"]) != (1080, 1920):
        return f"not Shorts spec: {info['width']}x{info['height']}"
    if not MIN_DURATION_S <= info["duration"] <= MAX_DURATION_S:
        return f"suspicious duration: {info['duration']:.1f}s"
    if not info["has_audio"]:
        return "no audio stream"
    return None


def decide_metadata(topic: str, suggestions: str, tagline: str) -> tuple[str, str]:
    """Final (title, description) — quality LLM pick, sanitized, with fallbacks."""
    title, description = "", ""
    try:
        from llm_provider import generate_text

        reply = generate_text(
            build_metadata_prompt(topic, suggestions, tagline), quality=True
        )
        parsed = parse_llm_metadata(reply)
        title = sanitize_title(parsed.get("title", ""))
        description = sanitize_description(parsed.get("description", ""))
    except Exception as exc:  # LLM outage must not block the batch
        print(f"    (metadata LLM failed, using fallbacks: {exc})")
    if not title:
        title = sanitize_title(topic)
    if not description:
        description = f"{topic}. Filed by The Strange Archive."
    return title, description


def upload_scheduled(final_path: str, title: str, description: str, brand: dict,
                     publish_at: str) -> str:
    """Upload as a scheduled private draft; returns the watch URL."""
    from youtube_api_upload import (
        build_api_upload_request,
        load_or_refresh_credentials,
        upload_video_resumable,
    )

    request = build_api_upload_request(
        video_path=final_path,
        title=title,
        description=description,
        tags=brand.get("default_tags", []),
        category_id=get_youtube_api_category_id(),
        made_for_kids=get_is_for_kids(),
        publish_at=publish_at,
    )
    credentials = load_or_refresh_credentials(
        get_youtube_api_client_secrets_path(), get_youtube_api_token_path()
    )
    result = upload_video_resumable(request, credentials=credentials, execute=True)
    return result.watch_url()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if is_brand_archived(args.brand_id):
        print(f"ERROR: {args.brand_id} is archived.")
        return 2
    brand = load_brand(args.brand_id)
    if not brand:
        print(f"ERROR: unknown brand: {args.brand_id}")
        return 2

    with open(args.topics, encoding="utf-8") as f:
        topics = [entry["topic"] for entry in json.load(f) if entry.get("topic")]
    if not topics:
        print("ERROR: topics file is empty")
        return 2

    publishing = brand.get("publishing", {})
    slot_time = args.publish_time or (
        publishing.get("publish_slots", {}).get("prime", {}).get("window_start", "18:30")
    )
    tz_name = publishing.get("timezone", "America/New_York")

    state_path = os.path.join(ROOT, "output", args.brand_id, "notebooklm", "batch_state.json")
    state = load_state(state_path)
    for topic in topics:
        state["episodes"].setdefault(topic, {"status": "pending"})
    if args.schedule_upload and not state["slots"]:
        state["slots"] = compute_publish_slots(
            len(topics), slot_time, tz_name, min_lead_hours=args.min_lead_hours
        )

    pending = [t for t in topics if state["episodes"][t]["status"] != "scheduled"]
    print(
        f"NotebookLM batch [{args.brand_id}]: {len(topics)} topics, "
        f"{len(topics) - len(pending)} already scheduled, {len(pending)} to do."
    )
    if args.schedule_upload:
        print(f"Publish slots: daily {slot_time} {tz_name}, first = {state['slots'][0]} (UTC)")

    if args.dry_run:
        for i, topic in enumerate(pending):
            slot = state["slots"][i] if i < len(state.get("slots", [])) else "(no slot)"
            print(f"  [{i + 1}/{len(pending)}] {topic}  ->  {slot}")
        return 0

    if not shutil.which("notebooklm"):
        print("ERROR: notebooklm CLI not found on PATH.")
        return 2
    switch_brand(args.brand_id)
    tagline = brand.get("tagline", "")

    uploads_this_run = 0
    quota_exhausted = False
    processed = 0
    for topic in topics:
        rec = state["episodes"][topic]
        if rec["status"] == "scheduled":
            continue
        if args.limit and processed >= args.limit:
            break
        processed += 1
        index = topics.index(topic) + 1
        print(f"\n[{index}/{len(topics)}] {topic}")

        try:
            if not rec.get("episode_dir") or not os.path.isdir(rec["episode_dir"]):
                rc = notebooklm_short.main(
                    [args.brand_id, "--topic", topic, "--research-mode", args.research_mode]
                )
                if rc != 0:
                    raise RuntimeError(f"generation exited {rc}")
                rec["episode_dir"] = notebooklm_short.episode_dir_for(args.brand_id, topic)
            else:
                print(f"  reusing staged episode: {rec['episode_dir']}")

            final_path = os.path.join(rec["episode_dir"], "final.mp4")
            reason = verify_final(final_path)
            if reason:
                rec["status"], rec["error"] = "needs_review", reason
                print(f"  NOT uploading - {reason}. Staged for manual review.")
                continue
            rec["status"] = "generated"
            rec.pop("error", None)

            if not args.schedule_upload or quota_exhausted or uploads_this_run >= args.max_uploads:
                print("  verified; upload deferred to a later run.")
                continue

            suggestions = ""
            meta_path = os.path.join(rec["episode_dir"], "meta.json")
            if os.path.isfile(meta_path):
                with open(meta_path, encoding="utf-8") as f:
                    suggestions = json.load(f).get("suggestions", "")
            title, body = decide_metadata(topic, suggestions, tagline)
            description = build_description(
                body + "\n\nAI-generated narration and visuals, based on documented history.",
                subject=topic,
                format_type="short",
            )

            if not rec.get("publish_at"):
                rec["publish_at"] = state["slots"][state["next_slot"]]
                state["next_slot"] += 1
            url = upload_scheduled(final_path, title, description, brand, rec["publish_at"])
            rec.update({"status": "scheduled", "title": title, "url": url})
            uploads_this_run += 1
            log_video(
                title=title,
                format_type="short",
                niche=brand.get("niche", ""),
                video_path=final_path,
                url=url,
                subject=topic,
                brand_id=args.brand_id,
                status="scheduled",
            )
            print(f"  SCHEDULED {rec['publish_at']} (UTC): {url}")
        except Exception as exc:
            message = str(exc)
            rec["status"], rec["error"] = "failed", message[:500]
            print(f"  FAILED: {message[:300]}")
            if "quota" in message.lower():
                quota_exhausted = True
                print("  (API quota exhausted - remaining uploads deferred to next run)")
            if os.environ.get("MPV2_BATCH_DEBUG"):
                traceback.print_exc()
        finally:
            save_state(state_path, state)

    counts: dict[str, int] = {}
    for rec in state["episodes"].values():
        counts[rec["status"]] = counts.get(rec["status"], 0) + 1
    print(f"\nBatch pass done: {counts}. State: {state_path}")
    print("Scheduled videos stay PRIVATE until their publishAt — QC/pull them in Studio.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RuntimeError as exc:
        print(f"ERROR: {exc}")
        sys.exit(1)
