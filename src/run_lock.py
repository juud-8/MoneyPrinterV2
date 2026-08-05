"""Single-run lock for pipeline jobs that share the `.mp/` scratch directory.

`utils.rem_temp_files()` deletes every non-JSON file at the top level of
`.mp/`, so two generation runs that overlap will delete each other's in-flight
WAV/PNG/MP4 scratch — the failure looks like a corrupt render rather than a
collision. Once long-form runs on its own schedule alongside the daily shorts
task, overlap stops being hypothetical: a long-form render takes 30-60+
minutes.

A run takes a lock before generating; a second run sees it and exits instead
of wrecking both. Locks live in `.mp/locks/` because `rem_temp_files()` skips
subdirectories — a lock at the top level would be deleted by the very run it
is meant to exclude.

Locks are stamped with a PID and a start time and expire after `ttl_seconds`,
so a crashed run cannot wedge the schedule forever.
"""

from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager

# A long-form render is the longest job in the system (30-60+ minutes, longer
# on a slow premium-asset provider). Expire well past that so a healthy run is
# never stolen from, but not so far that a crash blocks a whole week.
DEFAULT_TTL_SECONDS = 4 * 60 * 60


class RunLockBusy(RuntimeError):
    """Raised when another live run already holds the lock."""

    def __init__(self, name: str, holder: dict):
        self.name = name
        self.holder = holder
        pid = holder.get("pid", "?")
        started = holder.get("started_at", 0)
        age_min = max(0, int((time.time() - started) / 60)) if started else "?"
        super().__init__(
            f"Another '{name}' run is already in progress "
            f"(pid {pid}, started {age_min} min ago). "
            "Runs share the .mp/ scratch directory and would corrupt each "
            "other, so this run is stopping. Wait for it to finish, or remove "
            "the lock file if you know the run is dead."
        )


def lock_path(name: str, directory: str) -> str:
    return os.path.join(directory, f"{name}.lock")


def read_lock(name: str, directory: str) -> dict:
    """Lock metadata, or {} when absent/unreadable."""
    try:
        with open(lock_path(name, directory), encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def is_stale(holder: dict, ttl_seconds: int, now: float | None = None) -> bool:
    """True when a lock is old enough to assume its owner died.

    A lock with no usable start time is treated as stale — an unreadable or
    truncated lock file should not block the schedule indefinitely.
    """
    started = holder.get("started_at")
    if not isinstance(started, (int, float)) or started <= 0:
        return True
    return (now if now is not None else time.time()) - started >= ttl_seconds


def acquire(name: str, directory: str, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> dict:
    """Take the named lock, or raise RunLockBusy if a live run holds it.

    Returns the metadata written for this run.
    """
    os.makedirs(directory, exist_ok=True)
    path = lock_path(name, directory)
    payload = {"pid": os.getpid(), "started_at": time.time(), "name": name}
    encoded = json.dumps(payload)

    for _ in range(2):
        try:
            handle = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            holder = read_lock(name, directory)
            if not is_stale(holder, ttl_seconds):
                raise RunLockBusy(name, holder) from None
            # Expired: clear it and retry once. A second FileExistsError means
            # another process won the same race, and its lock is fresh.
            try:
                os.remove(path)
            except OSError:
                pass
            continue

        with os.fdopen(handle, "w", encoding="utf-8") as file:
            file.write(encoded)
        return payload

    raise RunLockBusy(name, read_lock(name, directory))


def release(name: str, directory: str, payload: dict | None = None) -> None:
    """Drop the lock. Never raises — a failed release must not fail the run.

    Only removes a lock this process owns, so a run that overran its TTL and
    got superseded cannot delete the newer run's lock on its way out.
    """
    holder = read_lock(name, directory)
    if payload and holder and holder.get("started_at") != payload.get("started_at"):
        return
    try:
        os.remove(lock_path(name, directory))
    except OSError:
        pass


@contextmanager
def run_lock(name: str, directory: str, ttl_seconds: int = DEFAULT_TTL_SECONDS):
    """Context manager wrapper around acquire()/release()."""
    payload = acquire(name, directory, ttl_seconds)
    try:
        yield payload
    finally:
        release(name, directory, payload)
