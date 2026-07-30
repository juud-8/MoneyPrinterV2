"""Durable status heartbeat for unattended production runs."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_STATUS_PATH = ROOT_DIR / ".mp" / "last_run_status.json"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _status_path(path: str | os.PathLike[str] | None = None) -> Path:
    return Path(path) if path is not None else DEFAULT_STATUS_PATH


def write_run_status(
    ok: bool,
    reason: str = "",
    *,
    task: str | None = None,
    path: str | os.PathLike[str] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Atomically persist the most recent unattended-run outcome."""
    timestamp = now or _utc_now()
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    payload = {
        "ok": bool(ok),
        "reason": str(reason or ""),
        "timestamp": timestamp.astimezone(timezone.utc).isoformat(),
        "task": str(task or os.environ.get("MPV2_RUN_TASK") or "unknown"),
    }
    destination = _status_path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temporary.replace(destination)
    return payload


def format_run_failure(exc: BaseException) -> str:
    """Return an operator-facing reason, distinguishing expired OAuth."""
    if type(exc).__name__ == "RefreshError":
        return f"AUTH_EXPIRED: {exc}"
    if isinstance(exc, SystemExit):
        return f"SystemExit({exc.code})"
    return f"{type(exc).__name__}: {exc}"


def get_run_status_alert(
    *,
    path: str | os.PathLike[str] | None = None,
    stale_after: timedelta = timedelta(hours=24),
    now: datetime | None = None,
) -> dict[str, Any]:
    """Read the heartbeat and label failed, missing, malformed, or stale state."""
    destination = _status_path(path)
    if not destination.is_file():
        return {
            "alert": True,
            "ok": None,
            "stale": True,
            "reason": "No unattended-run status has been recorded.",
            "timestamp": "",
            "task": "unknown",
        }

    try:
        payload = json.loads(destination.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("status payload is not an object")
        parsed = datetime.fromisoformat(
            str(payload.get("timestamp") or "").replace("Z", "+00:00")
        )
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        return {
            "alert": True,
            "ok": None,
            "stale": True,
            "reason": f"Unattended-run status is unreadable: {exc}",
            "timestamp": "",
            "task": "unknown",
        }

    reference = now or _utc_now()
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    age = reference.astimezone(timezone.utc) - parsed.astimezone(timezone.utc)
    stale = age > stale_after
    ok = payload.get("ok") is True
    reason = str(payload.get("reason") or "")
    if stale:
        age_hours = max(0, round(age.total_seconds() / 3600))
        reason = f"Unattended-run status is stale ({age_hours}h old)."
    elif not ok and not reason:
        reason = "The latest unattended run failed without a reason."

    return {
        "alert": stale or not ok,
        "ok": ok,
        "stale": stale,
        "reason": reason,
        "timestamp": str(payload.get("timestamp") or ""),
        "task": str(payload.get("task") or "unknown"),
    }
