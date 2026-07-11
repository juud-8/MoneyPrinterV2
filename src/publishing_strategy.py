"""Manifest-driven publishing cadence helpers.

The scheduling engine stays brand-agnostic: brands declare enabled slots,
days, and spacing rules in ``publishing`` and runners ask this module whether
a slot should run before doing expensive generation work.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def _publishing(manifest: dict) -> dict:
    value = manifest.get("publishing") or {}
    return value if isinstance(value, dict) else {}


def _local_datetime(manifest: dict, when: datetime | None = None) -> datetime:
    current = when or datetime.now()
    timezone_name = _publishing(manifest).get("timezone")
    if not timezone_name or current.tzinfo is None:
        return current
    try:
        return current.astimezone(ZoneInfo(timezone_name))
    except ZoneInfoNotFoundError:
        return current


def is_publish_slot_active(manifest: dict, slot_name: str, when: datetime | None = None) -> bool:
    """Return whether ``slot_name`` is enabled for the applicable weekday."""
    slots = _publishing(manifest).get("publish_slots") or {}
    slot = slots.get(slot_name)
    if not isinstance(slot, dict) or slot.get("enabled", True) is False:
        return False

    configured_days = slot.get("days")
    if not configured_days:
        return True
    allowed = {str(day).strip().lower() for day in configured_days}
    weekday = WEEKDAYS[_local_datetime(manifest, when).weekday()]
    return weekday in allowed


def enabled_slots_for_day(manifest: dict, when: datetime | None = None) -> list[str]:
    slots = _publishing(manifest).get("publish_slots") or {}
    return [name for name in slots if is_publish_slot_active(manifest, name, when)]


def validate_publishing_strategy(manifest: dict) -> list[str]:
    """Return actionable manifest warnings without mutating configuration."""
    publishing = _publishing(manifest)
    slots = publishing.get("publish_slots") or {}
    warnings: list[str] = []

    def minute_of_day(value: str) -> int | None:
        try:
            hour, minute = (int(part) for part in value.split(":"))
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise ValueError
            return hour * 60 + minute
        except (AttributeError, TypeError, ValueError):
            return None

    active_by_day: dict[str, list[tuple[str, int]]] = {day: [] for day in WEEKDAYS}
    for name, slot in slots.items():
        if not isinstance(slot, dict) or slot.get("enabled", True) is False:
            continue
        start = minute_of_day(slot.get("window_start"))
        end = minute_of_day(slot.get("window_end"))
        if start is None or end is None:
            warnings.append(f"Slot '{name}' needs valid HH:MM window_start/window_end values")
            continue
        if end <= start:
            warnings.append(f"Slot '{name}' must end after it starts on the same day")
        days = slot.get("days") or WEEKDAYS
        normalized_days = {str(day).strip().lower() for day in days}
        invalid_days = sorted(normalized_days.difference(WEEKDAYS))
        if invalid_days:
            warnings.append(f"Slot '{name}' has invalid days: {', '.join(invalid_days)}")
        for day in normalized_days.intersection(WEEKDAYS):
            active_by_day[day].append((name, start))

    minimum_gap = float(publishing.get("minimum_hours_between_posts") or 0)
    for day, day_slots in active_by_day.items():
        ordered = sorted(day_slots, key=lambda item: item[1])
        for (left_name, left), (right_name, right) in zip(ordered, ordered[1:]):
            gap_hours = (right - left) / 60
            if gap_hours < minimum_gap:
                warnings.append(
                    f"{day.title()} slots '{left_name}' and '{right_name}' are only "
                    f"{gap_hours:g}h apart; minimum is {minimum_gap:g}h"
                )

    weekly_slots = sum(len(items) for items in active_by_day.values())
    configured_weekly = publishing.get("shorts_per_week")
    if configured_weekly is not None:
        try:
            configured_weekly_count = int(configured_weekly)
        except (TypeError, ValueError):
            warnings.append("publishing.shorts_per_week must be an integer")
        else:
            if configured_weekly_count != weekly_slots:
                warnings.append(
                    f"publishing.shorts_per_week is {configured_weekly}, but enabled slot-days total {weekly_slots}"
                )
    return warnings
