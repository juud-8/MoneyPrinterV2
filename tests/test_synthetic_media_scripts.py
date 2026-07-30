from __future__ import annotations

import os
import sys
import unittest

ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from audit_synthetic_media import disclosure_gaps
from backfill_synthetic_media import _preserved_status


class SyntheticMediaScriptTests(unittest.TestCase):
    def test_disclosure_gaps_treats_false_and_absent_as_gaps(self) -> None:
        videos = [
            {"id": "true", "status": {"containsSyntheticMedia": True}},
            {"id": "false", "status": {"containsSyntheticMedia": False}},
            {"id": "absent", "status": {}},
        ]
        self.assertEqual(
            [video["id"] for video in disclosure_gaps(videos)],
            ["false", "absent"],
        )

    def test_backfill_preserves_every_writable_status_field(self) -> None:
        current = {
            "uploadStatus": "processed",
            "privacyStatus": "unlisted",
            "license": "youtube",
            "embeddable": False,
            "publicStatsViewable": False,
            "selfDeclaredMadeForKids": False,
            "containsSyntheticMedia": False,
        }
        updated = _preserved_status(current)

        self.assertEqual(updated["privacyStatus"], "unlisted")
        self.assertEqual(updated["license"], "youtube")
        self.assertIs(updated["embeddable"], False)
        self.assertIs(updated["publicStatsViewable"], False)
        self.assertIs(updated["selfDeclaredMadeForKids"], False)
        self.assertIs(updated["containsSyntheticMedia"], True)
        self.assertNotIn("uploadStatus", updated)


if __name__ == "__main__":
    unittest.main()
