#!/usr/bin/env python3
"""Upload an existing Short MP4 for a brand (no regeneration)."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
os.chdir(ROOT)

from brand_switcher import switch_brand, resolve_youtube_account, load_active_brand
from classes.YouTube import YouTube
from content_funnel import build_description
from review_gate import should_proceed_with_upload


def _arg(flag: str) -> str | None:
    if flag in sys.argv:
        i = sys.argv.index(flag)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    prefix = f"{flag}="
    for arg in sys.argv:
        if arg.startswith(prefix):
            return arg.split("=", 1)[1]
    return None


def main():
    brand_id = next(
        (a for a in sys.argv[1:] if not a.startswith("-")),
        "the_strange_archive",
    )
    video = _arg("--file")
    if not video:
        print("Usage: upload_brand_short.py <brand_id> --file <path.mp4> [--title ...] [--episode 01]")
        sys.exit(1)

    video = os.path.abspath(video)
    if not os.path.isfile(video):
        print(f"ERROR: Video not found: {video}")
        sys.exit(1)

    switch_brand(brand_id)
    brand = load_active_brand()
    account = resolve_youtube_account(brand, create=False)
    if not account:
        print("ERROR: No YouTube account linked for brand")
        sys.exit(1)

    title = _arg("--title")
    episode = _arg("--episode")
    if not title:
        base = os.path.splitext(os.path.basename(video))[0].replace("_", " ")
        title = base
    if episode and not title.lower().startswith("episode"):
        ep_label = str(episode).zfill(2) if str(episode).isdigit() else str(episode)
        title = f"Episode {ep_label}: {title}"

    suffix = brand.get("production", {}).get("title_suffix", "")
    if suffix and suffix not in title:
        candidate = f"{title} {suffix}".strip()
        if len(candidate) <= 100:
            title = candidate

    description = _arg("--description") or build_description(
        brand.get("tagline", "Strange history, filed for you."),
        subject=title,
        format_type="short",
        include_affiliate=True,
    )

    youtube = YouTube(
        account["id"],
        account["nickname"],
        account["firefox_profile"],
        account["niche"],
        account["language"],
    )
    youtube.video_path = video
    youtube.metadata = {"title": title[:100], "description": description}

    print(f"Uploading: {video}")
    print(f"Title: {youtube.metadata['title']}")

    if not should_proceed_with_upload(
        video,
        youtube.metadata["title"],
        youtube.metadata["description"],
        interactive=False,
    ):
        print("UPLOAD: skipped")
        sys.exit(0)

    ok = youtube.upload_video()
    print(f"UPLOAD: {'success' if ok else 'failed'}")
    if ok and getattr(youtube, "uploaded_video_url", None):
        print(f"URL: {youtube.uploaded_video_url}")
    youtube.close_browser()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
