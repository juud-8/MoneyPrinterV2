#!/usr/bin/env python3
"""Generate a NotebookLM (Gemini Notebook) Video Overview short and stage it for
manual review — this script NEVER uploads or posts anywhere.

Flow: create notebook -> add sources / run research -> generate video overview
-> download MP4 into output/<brand_id>/notebooklm/<date>_<slug>/ alongside a
NOTES.md with suggested titles and a finishing checklist (Canva pass to remove
NotebookLM branding, add brand outro, manual upload).

Requires the notebooklm CLI (unofficial notebooklm-py package):
    uv tool install "notebooklm-py[browser]"
    notebooklm login --browser-cookies chrome
"""
import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
os.chdir(ROOT)

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from archived_brands import is_brand_archived
from brand_switcher import load_brand

DEFAULT_PROMPT = (
    "Fast-paced vertical short. Open with the single strangest fact as a hook, "
    "keep a tight narrative arc, end on an unresolved question. Stick strictly "
    "to what the sources support."
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate a NotebookLM video short for review only (no upload)."
    )
    parser.add_argument("brand_id", nargs="?", default="the_strange_archive")
    parser.add_argument("--topic", required=True, help="episode topic / research query")
    parser.add_argument(
        "--notebook",
        help="reuse an existing notebook id (skips create + sources + research)",
    )
    parser.add_argument(
        "--source",
        action="append",
        default=[],
        help="URL or file to add as a source (repeatable)",
    )
    parser.add_argument(
        "--research-mode",
        choices=["deep", "fast", "none"],
        default="deep",
        help="web research depth; 'none' uses only --source material (default: deep)",
    )
    parser.add_argument(
        "--format",
        dest="video_format",
        choices=["short", "explainer", "brief", "cinematic"],
        default="short",
    )
    parser.add_argument(
        "--style",
        help="visual style (explainer/brief formats only, e.g. heritage, retro-print)",
    )
    parser.add_argument("--prompt", help="generation instructions override")
    parser.add_argument(
        "--download-only",
        action="store_true",
        help="skip generation; stage the notebook's latest existing video (requires --notebook)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=None,
        help="seconds per phase (default: 1800; 3600 for cinematic)",
    )
    parser.add_argument("--cli", default="notebooklm", help="notebooklm executable")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the CLI commands without executing anything",
    )
    return parser


def run_cli(cmd: list[str], timeout: int, dry_run: bool) -> subprocess.CompletedProcess | None:
    print(f"  $ {' '.join(cmd)}")
    if dry_run:
        return None
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Command failed ({result.returncode}): {' '.join(cmd)}\n"
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    return result


def parse_json_output(result: subprocess.CompletedProcess | None) -> dict:
    if result is None:
        return {}
    try:
        return json.loads(result.stdout)
    except (json.JSONDecodeError, TypeError):
        return {}


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return slug[:60] or "episode"


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.style and args.video_format in ("short", "cinematic"):
        build_parser().error("--style is not supported with --format short/cinematic")
    if args.download_only and not args.notebook:
        build_parser().error("--download-only requires --notebook")
    if not args.notebook and args.research_mode == "none" and not args.source:
        build_parser().error("--research-mode none requires at least one --source")

    if is_brand_archived(args.brand_id):
        print(f"ERROR: {args.brand_id} is archived.")
        return 2
    brand = load_brand(args.brand_id)
    if not brand:
        print(f"ERROR: unknown brand: {args.brand_id}")
        return 2

    if not args.dry_run and not shutil.which(args.cli):
        print("ERROR: notebooklm CLI not found. Install and log in first:")
        print('  uv tool install "notebooklm-py[browser]"')
        print("  notebooklm login --browser-cookies chrome")
        return 2

    timeout = args.timeout or (3600 if args.video_format == "cinematic" else 1800)
    prompt = (
        args.prompt
        or brand.get("production", {}).get("notebooklm_video_prompt")
        or DEFAULT_PROMPT
    )

    episode_dir = os.path.join(
        ROOT,
        "output",
        args.brand_id,
        "notebooklm",
        f"{datetime.date.today().isoformat()}_{slugify(args.topic)}",
    )
    video_path = os.path.join(episode_dir, "notebooklm_short.mp4")

    print(f"NotebookLM short for '{args.topic}' [{args.brand_id}] - review-only, no upload.")
    if not args.dry_run:
        run_cli([args.cli, "auth", "check", "--test", "--json"], 120, False)

    notebook_id = args.notebook
    if notebook_id:
        print(f" => Reusing notebook {notebook_id}")
    else:
        print(" => Creating notebook...")
        result = run_cli(
            [args.cli, "create", args.topic, "--use", "--json"], 120, args.dry_run
        )
        notebook_id = parse_json_output(result).get("active_notebook_id", "")
        if not notebook_id and not args.dry_run:
            raise RuntimeError("Could not parse notebook id from create output.")

        for src in args.source:
            print(f" => Adding source: {src}")
            run_cli(
                [args.cli, "source", "add", src, "-n", notebook_id or "<nb>"],
                600,
                args.dry_run,
            )

        if args.research_mode != "none":
            print(f" => Running {args.research_mode} web research (this can take a while)...")
            run_cli(
                [
                    args.cli, "source", "add-research", args.topic,
                    "--mode", args.research_mode, "--import-all",
                    "--timeout", str(timeout), "-n", notebook_id or "<nb>",
                ],
                timeout * 2 + 300,
                args.dry_run,
            )

    if args.download_only:
        print(" => Download-only: skipping generation, using latest existing video.")
    else:
        print(f" => Generating {args.video_format} video overview...")
        generate_cmd = [
            args.cli, "generate", "video", prompt,
            "--format", args.video_format,
            "--wait", "--timeout", str(timeout), "--retry", "2",
            "--json", "-n", notebook_id or "<nb>",
        ]
        if args.style:
            generate_cmd += ["--style", args.style]
        run_cli(generate_cmd, timeout + 300, args.dry_run)

    print(" => Downloading video...")
    if not args.dry_run:
        os.makedirs(episode_dir, exist_ok=True)
    run_cli(
        [args.cli, "download", "video", video_path, "--latest", "-n", notebook_id or "<nb>"],
        600,
        args.dry_run,
    )

    print(" => Asking notebook for title/description suggestions...")
    suggestions = ""
    try:
        result = run_cli(
            [
                args.cli, "ask",
                (
                    "Suggest 3 YouTube Shorts title options (under 80 characters, "
                    "curiosity-driven, no hashtags) and a 2-sentence video "
                    f"description for a short-form video about: {args.topic}"
                ),
                "--json", "-n", notebook_id or "<nb>",
            ],
            300,
            args.dry_run,
        )
        suggestions = parse_json_output(result).get("answer", "")
    except (RuntimeError, subprocess.TimeoutExpired) as exc:
        print(f"    (suggestions failed, continuing: {exc})")

    if not args.dry_run:
        notes_path = os.path.join(episode_dir, "NOTES.md")
        with open(notes_path, "w", encoding="utf-8") as f:
            f.write(
                f"# {args.topic}\n\n"
                f"- Brand: {args.brand_id}\n"
                f"- Notebook id: {notebook_id}\n"
                f"- Format: {'latest existing (download-only)' if args.download_only else args.video_format}\n"
                f"- Generated: {datetime.datetime.now().isoformat(timespec='seconds')}\n"
                f"- Generation prompt: {prompt}\n\n"
                "## Title / description suggestions\n\n"
                f"{suggestions or '(none — ask step failed)'}\n\n"
                "## Finishing checklist (manual)\n\n"
                "- [ ] Canva: remove NotebookLM watermark/branding\n"
                "- [ ] Canva: add brand intro/outro + captions styling\n"
                "- [ ] Upload manually; set the AI-disclosure toggle in Studio\n"
                "- [ ] Add episode to analytics tracker\n"
            )
        print(f"\nDone. Staged for review at:\n  {episode_dir}")
        print("Nothing was uploaded or posted.")
    else:
        print(f"\nDry run complete. Would stage into:\n  {episode_dir}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RuntimeError as exc:
        print(f"ERROR: {exc}")
        sys.exit(1)
