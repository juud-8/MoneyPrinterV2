from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
SRC_DIR = os.path.join(ROOT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from run_status import format_run_failure, get_run_status_alert, write_run_status


class RunStatusTests(unittest.TestCase):
    def test_write_and_read_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "last_run_status.json")
            now = datetime(2026, 7, 29, 12, 0, tzinfo=timezone.utc)
            payload = write_run_status(
                True,
                task="prime",
                path=path,
                now=now,
            )
            alert = get_run_status_alert(path=path, now=now)

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["task"], "prime")
        self.assertFalse(alert["alert"])
        self.assertFalse(alert["stale"])

    def test_failed_status_alerts_with_reason(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "last_run_status.json")
            now = datetime(2026, 7, 29, 12, 0, tzinfo=timezone.utc)
            write_run_status(
                False,
                "AUTH_EXPIRED: invalid_grant",
                task="early",
                path=path,
                now=now,
            )
            alert = get_run_status_alert(path=path, now=now)

        self.assertTrue(alert["alert"])
        self.assertFalse(alert["ok"])
        self.assertEqual(alert["reason"], "AUTH_EXPIRED: invalid_grant")

    def test_status_older_than_24_hours_alerts_as_stale(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "last_run_status.json")
            written = datetime(2026, 7, 28, 10, 0, tzinfo=timezone.utc)
            write_run_status(True, task="prime", path=path, now=written)
            alert = get_run_status_alert(
                path=path,
                now=written + timedelta(hours=25),
            )

        self.assertTrue(alert["alert"])
        self.assertTrue(alert["stale"])
        self.assertIn("25h old", alert["reason"])

    def test_missing_and_malformed_status_alert(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "last_run_status.json")
            missing = get_run_status_alert(path=path)
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({"ok": True, "timestamp": "not-a-date"}, handle)
            malformed = get_run_status_alert(path=path)

        self.assertTrue(missing["alert"])
        self.assertTrue(malformed["alert"])

    def test_refresh_error_name_gets_distinct_reason(self) -> None:
        RefreshError = type("RefreshError", (Exception,), {})
        self.assertEqual(
            format_run_failure(RefreshError("invalid_grant")),
            "AUTH_EXPIRED: invalid_grant",
        )


if __name__ == "__main__":
    unittest.main()
