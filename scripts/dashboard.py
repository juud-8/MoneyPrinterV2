#!/usr/bin/env python3
"""Print the cross-brand CLI dashboard."""

import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(ROOT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from dashboard import print_cli_dashboard, write_html_dashboard  # noqa: E402


def main() -> None:
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass

    days = 7
    if len(sys.argv) > 1:
        try:
            days = int(sys.argv[1])
        except ValueError:
            print("Usage: python scripts/dashboard.py [days=7]")
            sys.exit(1)

    print_cli_dashboard(days=days)

    if "--html" in sys.argv:
        path = write_html_dashboard(days=days)
        print(f"\nHTML dashboard: {path}")


if __name__ == "__main__":
    main()
