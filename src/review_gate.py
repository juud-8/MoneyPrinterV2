"""Human review gate before upload."""

import os

from config import get_ai_disclosure_default, get_review_before_upload
from brand_switcher import get_production_setting
from channel_branding import get_publishing_config
from status import info, question, warning


def should_proceed_with_upload(
    video_path: str,
    title: str,
    description: str,
    interactive: bool = True,
) -> bool:
    """
    Show generated asset summary and ask for approval before upload.

    Returns True if upload should proceed.
    """
    review = get_review_before_upload()
    pub = get_publishing_config()
    if pub.get("review_before_upload") is False:
        review = False

    if not review:
        return True

    pilot_mode = bool(get_production_setting("pilot_mode", False))

    if not interactive:
        if not pilot_mode:
            # Non-pilot brands keep prior behavior: review_before_upload has
            # no automated-run effect (there's no one to ask), so scheduled
            # uploads proceed as before.
            return True

        confirmed = os.environ.get("MPV2_PILOT_UPLOAD_CONFIRMED", "").strip() == "1"
        warning(
            "Pilot mode active: verify title, facts, captions, music, and AI "
            "disclosure before public upload."
        )
        if confirmed:
            info(
                "Pilot mode: automated upload confirmed via "
                "MPV2_PILOT_UPLOAD_CONFIRMED=1.",
                False,
            )
            return True

        warning(
            "Automated/non-interactive upload blocked while pilot_mode is active. "
            "Review the generated video manually, then either re-run with "
            "MPV2_PILOT_UPLOAD_CONFIRMED=1 set, or omit --upload/-Upload to only "
            "generate. See brands/the_strange_archive/PILOT_RUNBOOK.md."
        )
        return False

    disclose_ai = bool(
        get_production_setting("ai_disclosure", get_ai_disclosure_default())
    )

    info("\n============ REVIEW BEFORE UPLOAD ============", False)
    print(f" Video:  {video_path}")
    print(f" Exists: {os.path.isfile(video_path)}")
    print(f" Title:  {title[:100]}")
    print(f" Desc:   {description[:200]}...")
    print(f" AI disclosure target: {'Yes' if disclose_ai else 'No'}")
    print(
        " ⚠ The AI-disclosure toggle is set best-effort via Selenium and can "
        "silently fail if YouTube Studio's UI changed — double-check it in "
        "Studio's 'Show more' section after upload if in doubt."
    )
    info("==============================================\n", False)

    if pilot_mode:
        warning(
            "Pilot mode active: verify title, facts, captions, music, and AI "
            "disclosure before public upload."
        )

    answer = question("Approve upload? (Yes/No): ").strip().lower()
    if answer != "yes":
        warning("Upload skipped by human review gate.")
        return False
    return True
