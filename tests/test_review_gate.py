from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
SRC_DIR = os.path.join(ROOT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

import review_gate


class ReviewGateTests(unittest.TestCase):
    @patch("review_gate.info")
    @patch("review_gate.warning")
    @patch("review_gate.get_production_setting", return_value=True)
    @patch("review_gate.get_publishing_config", return_value={})
    @patch("review_gate.get_review_before_upload", return_value=True)
    def test_unattended_pilot_run_can_stage_private_upload(
        self,
        _review_mock,
        _publishing_mock,
        _production_mock,
        warning_mock,
        info_mock,
    ) -> None:
        with patch.dict(os.environ, {"MPV2_UNATTENDED_UPLOAD": "1"}, clear=False):
            result = review_gate.should_proceed_with_upload(
                "video.mp4", "Title", "Description", interactive=False
            )

        self.assertTrue(result)
        warning_mock.assert_called_once()
        info_mock.assert_called_once()

    @patch("review_gate.warning")
    @patch("review_gate.get_production_setting", return_value=True)
    @patch("review_gate.get_publishing_config", return_value={})
    @patch("review_gate.get_review_before_upload", return_value=True)
    def test_unconfirmed_noninteractive_pilot_run_stays_blocked(
        self,
        _review_mock,
        _publishing_mock,
        _production_mock,
        warning_mock,
    ) -> None:
        with patch.dict(
            os.environ,
            {
                "MPV2_UNATTENDED_UPLOAD": "",
                "MPV2_PILOT_UPLOAD_CONFIRMED": "",
            },
            clear=False,
        ):
            result = review_gate.should_proceed_with_upload(
                "video.mp4", "Title", "Description", interactive=False
            )

        self.assertFalse(result)
        self.assertEqual(warning_mock.call_count, 2)


if __name__ == "__main__":
    unittest.main()
