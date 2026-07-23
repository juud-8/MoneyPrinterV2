"""De-brand and finish a downloaded provider video (e.g. a NotebookLM /
Gemini Notebook Video Overview) so it is channel-ready.

Two steps, both optional:

1. De-brand — remove the provider's watermark strip along the bottom edge,
   either by cropping it away and re-covering the target frame with a slight
   center zoom ("crop" mode, default) or by painting a solid bar over it
   ("cover" mode — preserves framing, useful if the crop zoom cuts too much).
2. Outro — append the brand outro clip, normalized to the same resolution,
   frame rate, and audio format so concat never fails on stream mismatch.

Brand-agnostic by design: watermark geometry, outro path, and cover color
arrive as plain arguments (the CLI wrapper reads them from the brand
manifest — `production.notebooklm_crop_bottom_frac`, `production.outro_clip`,
`color_palette.secondary`). Nothing here knows any brand's name.

The command builders are pure (no subprocess) so they stay unit-testable;
`probe_media()` and `run_finish()` are the thin impure wrappers around
ffprobe/ffmpeg.
"""

import json
import os
import subprocess

# Watermark strips observed on provider downloads sit in the bottom ~5-10%
# of the frame. 8% is the calibration starting point, not a promise — use
# the CLI's --inspect flag on a real download to dial it in per provider.
DEFAULT_CROP_BOTTOM_FRAC = 0.08

# Refuse obviously wrong crop values instead of silently destroying the video.
MAX_CROP_BOTTOM_FRAC = 0.30

AUDIO_NORMALIZE = "aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo"


def _even(value: int) -> int:
    """Round down to an even number (yuv420p requires even dimensions)."""
    return max(2, int(value) - (int(value) % 2))


def watermark_strip_px(src_h: int, crop_bottom_frac: float) -> int:
    """Height in pixels of the bottom strip to remove, always even."""
    if not 0 <= crop_bottom_frac <= MAX_CROP_BOTTOM_FRAC:
        raise ValueError(
            f"crop_bottom_frac must be within [0, {MAX_CROP_BOTTOM_FRAC}], "
            f"got {crop_bottom_frac}"
        )
    return _even(round(src_h * crop_bottom_frac))


def build_debrand_filter(
    src_h: int,
    crop_bottom_frac: float,
    target_w: int,
    target_h: int,
    mode: str = "crop",
    cover_color: str = "#000000",
    fps: int = 30,
) -> str:
    """Filter chain that removes the bottom watermark strip and normalizes
    the frame to target_w x target_h (cover-fit: scale up, center crop)."""
    if mode not in ("crop", "cover"):
        raise ValueError(f"mode must be 'crop' or 'cover', got {mode!r}")

    strip = watermark_strip_px(src_h, crop_bottom_frac)
    steps = []
    if strip > 2 and mode == "crop":
        steps.append(f"crop=iw:{src_h - strip}:0:0")
    elif strip > 2 and mode == "cover":
        color = cover_color.lstrip("#")
        steps.append(f"drawbox=x=0:y=ih-{strip}:w=iw:h={strip}:color=0x{color}:t=fill")

    steps += [
        # lanczos matters here: NotebookLM shorts download at 406x720 and get
        # upscaled ~2.7x to hit the 1080x1920 Shorts spec.
        f"scale={target_w}:{target_h}:force_original_aspect_ratio=increase:flags=lanczos",
        f"crop={target_w}:{target_h}",
        f"fps={fps}",
        "setsar=1",
        "format=yuv420p",
    ]
    return ",".join(steps)


def build_finish_command(
    input_path: str,
    output_path: str,
    src_h: int,
    target_w: int,
    target_h: int,
    crop_bottom_frac: float = DEFAULT_CROP_BOTTOM_FRAC,
    mode: str = "crop",
    cover_color: str = "#000000",
    fps: int = 30,
    outro_path: str = None,
    outro_has_audio: bool = True,
    outro_duration: float = 0.0,
    ffmpeg: str = "ffmpeg",
) -> list:
    """Full ffmpeg argv. Pure — builds the command, runs nothing."""
    debrand = build_debrand_filter(
        src_h, crop_bottom_frac, target_w, target_h, mode, cover_color, fps
    )
    encode = [
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-movflags", "+faststart", "-y", output_path,
    ]

    if not outro_path:
        return [ffmpeg, "-i", input_path, "-vf", debrand,
                "-af", AUDIO_NORMALIZE] + encode

    normalize_outro = (
        f"scale={target_w}:{target_h}:force_original_aspect_ratio=increase:flags=lanczos,"
        f"crop={target_w}:{target_h},fps={fps},setsar=1,format=yuv420p"
    )
    if outro_has_audio:
        outro_audio = f"[1:a]{AUDIO_NORMALIZE}[a1]"
    else:
        # Outro has no audio track — synthesize silence so concat still works.
        outro_audio = (
            f"anullsrc=channel_layout=stereo:sample_rate=48000,"
            f"atrim=0:{max(outro_duration, 0.1):.3f}[a1]"
        )

    filter_complex = (
        f"[0:v]{debrand}[v0];"
        f"[0:a]{AUDIO_NORMALIZE}[a0];"
        f"[1:v]{normalize_outro}[v1];"
        f"{outro_audio};"
        f"[v0][a0][v1][a1]concat=n=2:v=1:a=1[v][a]"
    )
    return [
        ffmpeg, "-i", input_path, "-i", outro_path,
        "-filter_complex", filter_complex,
        "-map", "[v]", "-map", "[a]",
    ] + encode


def default_target(src_w: int, src_h: int) -> tuple:
    """Portrait sources finish as 1080x1920 Shorts; landscape as 1920x1080."""
    return (1080, 1920) if src_h >= src_w else (1920, 1080)


def probe_media(path: str, ffprobe: str = "ffprobe") -> dict:
    """Width/height/duration/has_audio via ffprobe (impure)."""
    result = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries",
         "stream=codec_type,width,height", "-show_entries", "format=duration",
         "-of", "json", path],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed for {path}: {result.stderr.strip()}")
    data = json.loads(result.stdout)
    video = next(
        (s for s in data.get("streams", []) if s.get("codec_type") == "video"), {}
    )
    return {
        "width": int(video.get("width", 0)),
        "height": int(video.get("height", 0)),
        "duration": float(data.get("format", {}).get("duration", 0.0)),
        "has_audio": any(
            s.get("codec_type") == "audio" for s in data.get("streams", [])
        ),
    }


def run_finish(
    input_path: str,
    output_path: str,
    crop_bottom_frac: float = DEFAULT_CROP_BOTTOM_FRAC,
    mode: str = "crop",
    cover_color: str = "#000000",
    outro_path: str = None,
    target: tuple = None,
    ffmpeg: str = "ffmpeg",
    ffprobe: str = "ffprobe",
) -> dict:
    """Probe, de-brand, append outro, verify. Returns the output probe."""
    src = probe_media(input_path, ffprobe)
    if not src["width"] or not src["height"]:
        raise RuntimeError(f"No video stream found in {input_path}")
    target_w, target_h = target or default_target(src["width"], src["height"])

    outro = None
    if outro_path:
        if not os.path.isfile(outro_path):
            raise RuntimeError(f"Outro clip not found: {outro_path}")
        outro = probe_media(outro_path, ffprobe)

    cmd = build_finish_command(
        input_path, output_path,
        src_h=src["height"], target_w=target_w, target_h=target_h,
        crop_bottom_frac=crop_bottom_frac, mode=mode, cover_color=cover_color,
        outro_path=outro_path,
        outro_has_audio=outro["has_audio"] if outro else True,
        outro_duration=outro["duration"] if outro else 0.0,
        ffmpeg=ffmpeg,
    )
    result = subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {result.stderr[-2000:]}")

    finished = probe_media(output_path, ffprobe)
    if finished["width"] != target_w or finished["height"] != target_h:
        raise RuntimeError(
            f"Output is {finished['width']}x{finished['height']}, "
            f"expected {target_w}x{target_h}"
        )
    return finished
