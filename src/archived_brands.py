"""Brands paused from automated or interactive production.

Engine code stays brand-agnostic; archival is a single registry here so
scheduled tasks, CLI runners, and the web UI can refuse to run a brand
without deleting its data, cache entries, or historical analytics.
"""

from __future__ import annotations

ARCHIVED_BRANDS: dict[str, dict[str, str]] = {
    "sixty_second_thrillers": {
        "channel_name": "60 Second Thrillers",
        "archived_at": "2026-07-11",
        "reason": "Paused in favor of the_strange_archive pilot.",
        "resurrect": (
            "1) Remove 'sixty_second_thrillers' from ARCHIVED_BRANDS in "
            "src/archived_brands.py. 2) Restore brands/sixty_second_thrillers/"
            "manifest.json from brands/_archived/sixty_second_thrillers/ if "
            "needed. 3) Re-register Task Scheduler from "
            "scripts/_archived/sixty_second_thrillers/run_thrillers_daily.bat."
        ),
    },
}


class BrandArchivedError(RuntimeError):
    """Raised when production is requested for an archived brand."""


def is_brand_archived(brand_id: str) -> bool:
    return (brand_id or "").strip() in ARCHIVED_BRANDS


def archived_brand_message(brand_id: str) -> str:
    meta = ARCHIVED_BRANDS.get(brand_id, {})
    reason = meta.get("reason", "This brand is archived.")
    return f"Brand '{brand_id}' is archived and cannot run: {reason}"


def assert_brand_runnable(brand_id: str) -> None:
    """Raise BrandArchivedError if ``brand_id`` is archived."""
    if is_brand_archived(brand_id):
        raise BrandArchivedError(archived_brand_message(brand_id))
