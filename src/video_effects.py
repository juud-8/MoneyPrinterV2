"""Video motion effects: Ken Burns zoom/pan and crossfade transitions."""

import random

from moviepy import ImageClip, vfx


def apply_ken_burns(clip: ImageClip, duration: float, index: int = 0) -> ImageClip:
    """
    Apply a subtle Ken Burns zoom/pan to a static image clip.

    Alternates zoom-in vs zoom-out per index for visual variety.
    """
    clip = clip.with_duration(duration)

    # Start slightly larger than frame so we can pan/zoom
    target_w, target_h = 1080, 1920
    scale = 1.12
    clip = clip.resized(new_size=(int(target_w * scale), int(target_h * scale)))

    zoom_in = index % 2 == 0
    pan_x = random.choice([-1, 1]) * 20

    if zoom_in:

        def resize_fn(t):
            progress = min(1.0, t / max(duration, 0.01))
            return 1.0 + 0.08 * progress

        clip = clip.resized(resize_fn)
    else:

        def resize_fn(t):
            progress = min(1.0, t / max(duration, 0.01))
            return 1.08 - 0.06 * progress

        clip = clip.resized(resize_fn)

    def position_fn(t):
        progress = min(1.0, t / max(duration, 0.01))
        x = int(pan_x * progress)
        return ("center", x)

    clip = clip.with_position(position_fn)
    clip = clip.cropped(
        width=target_w,
        height=target_h,
        x_center=clip.w / 2,
        y_center=clip.h / 2,
    )
    return clip.with_duration(duration)


def apply_crossfade(clips: list, fade_duration: float = 0.4) -> list:
    """Add crossfade in/out effects to a list of clips."""
    if len(clips) <= 1:
        return clips

    faded = []
    for i, clip in enumerate(clips):
        effects = []
        if i > 0:
            effects.append(vfx.CrossFadeIn(fade_duration))
        if i < len(clips) - 1:
            effects.append(vfx.CrossFadeOut(fade_duration))
        if effects:
            clip = clip.with_effects(effects)
        faded.append(clip)
    return faded
