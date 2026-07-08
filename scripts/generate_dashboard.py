#!/usr/bin/env python3
"""Generate the static HTML brand dashboard."""

import os
import sys
import webbrowser

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(ROOT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from dashboard import write_html_dashboard  # noqa: E402


def main() -> None:
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass

    days = 7
    open_browser = "--open" in sys.argv
    for arg in sys.argv[1:]:
        if arg.startswith("--"):
            continue
        try:
            days = int(arg)
        except ValueError:
            print("Usage: python scripts/generate_dashboard.py [days=7] [--open]")
            sys.exit(1)

    path = write_html_dashboard(days=days)
    print(f"Wrote dashboard: {path}")

    if open_browser:
        if sys.platform == "win32":
            try:
                os.startfile(path)  # type: ignore[attr-defined]
            except OSError:
                webbrowser.open(f"file:///{path.replace(os.sep, '/')}")
        else:
            webbrowser.open(f"file://{os.path.abspath(path)}")


if __name__ == "__main__":
    main()
