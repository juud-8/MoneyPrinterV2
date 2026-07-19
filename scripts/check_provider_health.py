#!/usr/bin/env python3
"""Check external provider quotas/credits before daily automation."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
os.chdir(ROOT)

from provider_health import collect_provider_health  # noqa: E402


def main() -> int:
    snapshot = collect_provider_health(ROOT)
    remaining = snapshot["elevenlabs_remaining"]
    limit = snapshot["elevenlabs_limit"]
    if remaining is not None and limit is not None:
        print(f"[INFO] ElevenLabs quota: {remaining} of {limit} character(s) remaining")
    print(f"[INFO] Songs/: {snapshot['songs_count']} track(s)")

    for issue in snapshot["warnings"]:
        print(f"[WARN] {issue.message}")
        if issue.next_action:
            print(f"       Next action: {issue.next_action}")

    failures = snapshot["blocking_failures"]
    if failures:
        for issue in failures:
            print(f"[FAIL] {issue.message}")
            if issue.next_action:
                print(f"       Next action: {issue.next_action}")
        print(f"\nProvider health check failed with {len(failures)} blocking issue(s).")
        return 1

    print("\nProvider health check passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
