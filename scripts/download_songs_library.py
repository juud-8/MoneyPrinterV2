#!/usr/bin/env python3
"""Download licensed YouTube Audio Library tracks into Songs/.

Uses the community catalog at thibaultjanbeyer.github.io/YouTube-Free-Audio-Library-API
(Google Drive file ids sourced from YouTube's Audio Library). Tracks are renamed with
documentary-friendly keywords so choose_random_song() prefers them for weird_history.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from provider_health import (  # noqa: E402
    YOUTUBE_AUDIO_LIBRARY_API,
    score_song_filename,
)

DEFAULT_TARGET_COUNT = 18
ARCHIVE_DIRNAME = "_archived"


def _score_track(name: str) -> int:
    return score_song_filename(name)


def _safe_filename(name: str, index: int) -> str:
    stem = os.path.splitext(name)[0]
    stem = re.sub(r"[^a-zA-Z0-9]+", "_", stem).strip("_").lower()
    if not stem:
        stem = f"track_{index:02d}"
    keyword = "documentary_ambient_cinematic"
    for kw in (
        "mysterious",
        "documentary",
        "ambient",
        "cinematic",
        "orchestral",
        "classical",
        "piano",
        "strings",
        "tension",
        "ancient",
        "curious",
    ):
        if kw in stem:
            keyword = kw
            break
    return f"{keyword}_{stem}_{index:02d}.mp3"


def _download_file(file_id: str, dest_path: str) -> None:
    url = f"https://docs.google.com/uc?export=download&id={file_id}"
    with urllib.request.urlopen(url, timeout=120) as response:
        data = response.read()
    if len(data) < 1024:
        raise RuntimeError(f"Download too small for {file_id} — got {len(data)} bytes")
    with open(dest_path, "wb") as handle:
        handle.write(data)


def _archive_offbrand_tracks(songs_dir: str) -> list[str]:
    archived: list[str] = []
    archive_dir = os.path.join(songs_dir, ARCHIVE_DIRNAME)
    os.makedirs(archive_dir, exist_ok=True)
    for name in os.listdir(songs_dir):
        path = os.path.join(songs_dir, name)
        if not os.path.isfile(path):
            continue
        if not name.lower().endswith((".mp3", ".wav", ".m4a", ".aac", ".ogg")):
            continue
        lower = name.lower()
        if any(kw in lower for kw in AVOID_SONG_KEYWORDS):
            dest = os.path.join(archive_dir, name)
            if os.path.exists(dest):
                os.remove(dest)
            os.replace(path, dest)
            archived.append(name)
    return archived


def select_tracks(catalog: list[dict], target_count: int) -> list[dict]:
    ranked = sorted(
        catalog,
        key=lambda item: (_score_track(item.get("name", "")), item.get("name", "")),
        reverse=True,
    )
    selected: list[dict] = []
    seen_stems: set[str] = set()
    for item in ranked:
        if _score_track(item.get("name", "")) < 1:
            continue
        stem = os.path.splitext(item.get("name", ""))[0].lower()
        if stem in seen_stems:
            continue
        seen_stems.add(stem)
        selected.append(item)
        if len(selected) >= target_count:
            break
    return selected


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Seed Songs/ from YouTube Audio Library catalog.")
    parser.add_argument("--count", type=int, default=DEFAULT_TARGET_COUNT)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    songs_dir = os.path.join(ROOT, "Songs")
    os.makedirs(songs_dir, exist_ok=True)

    archived = _archive_offbrand_tracks(songs_dir)
    if archived:
        print(f"Archived {len(archived)} off-brand track(s) to Songs/{ARCHIVE_DIRNAME}/")

    with urllib.request.urlopen(YOUTUBE_AUDIO_LIBRARY_API, timeout=60) as response:
        payload = json.load(response)
    catalog = payload.get("all") or []

    existing = {
        name
        for name in os.listdir(songs_dir)
        if os.path.isfile(os.path.join(songs_dir, name))
        and name.lower().endswith((".mp3", ".wav", ".m4a", ".aac", ".ogg"))
    }
    need = max(0, args.count - len(existing))
    if need == 0:
        print(f"Songs/ already has {len(existing)} track(s) (target {args.count}). Nothing to do.")
        return 0

    selected = select_tracks(catalog, need)
    if len(selected) < need:
        print(
            f"WARNING: only found {len(selected)} suitable catalog track(s); "
            f"wanted {need} more."
        )

    print(f"Downloading {len(selected)} track(s) into Songs/ ...")
    for index, item in enumerate(selected, start=1):
        file_id = item["id"]
        original_name = item.get("name", f"track_{index}.mp3")
        dest_name = _safe_filename(original_name, len(existing) + index)
        dest_path = os.path.join(songs_dir, dest_name)
        if args.dry_run:
            print(f"  [dry-run] {original_name} -> {dest_name}")
            continue
        print(f"  {original_name} -> {dest_name}")
        _download_file(file_id, dest_path)

    final_count = len(
        [
            name
            for name in os.listdir(songs_dir)
            if os.path.isfile(os.path.join(songs_dir, name))
            and name.lower().endswith((".mp3", ".wav", ".m4a", ".aac", ".ogg"))
        ]
    )
    print(f"Done. Songs/ now has {final_count} track(s).")
    return 0 if final_count >= min(args.count, 15) else 1


if __name__ == "__main__":
    sys.exit(main())
