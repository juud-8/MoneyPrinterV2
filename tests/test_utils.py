import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
SRC_DIR = os.path.join(ROOT_DIR, "src")

if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

import utils


class RemTempFilesTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.mp_dir = os.path.join(self._tmp.name, ".mp")
        os.makedirs(self.mp_dir)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _run(self) -> None:
        with patch.object(utils, "ROOT_DIR", self._tmp.name):
            utils.rem_temp_files()

    def test_removes_non_json_files(self) -> None:
        for name in ("scratch.wav", "frame.png", "clip.mp4", "subs.srt"):
            with open(os.path.join(self.mp_dir, name), "w") as f:
                f.write("x")

        self._run()

        self.assertEqual(os.listdir(self.mp_dir), [])

    def test_keeps_json_files(self) -> None:
        with open(os.path.join(self.mp_dir, "analytics.json"), "w") as f:
            f.write("{}")

        self._run()

        self.assertTrue(os.path.isfile(os.path.join(self.mp_dir, "analytics.json")))

    def test_keeps_subdirectories_and_their_contents(self) -> None:
        # .mp/logs (metrics refresh logs) and .mp/analysis are persistent;
        # os.remove() on a directory also raises PermissionError on Windows.
        logs_dir = os.path.join(self.mp_dir, "logs")
        os.makedirs(logs_dir)
        log_file = os.path.join(logs_dir, "metrics_refresh.log")
        with open(log_file, "w") as f:
            f.write("[2026-07-11] Starting metrics refresh\n")
        with open(os.path.join(self.mp_dir, "scratch.wav"), "w") as f:
            f.write("x")

        self._run()

        self.assertTrue(os.path.isfile(log_file))
        self.assertFalse(os.path.exists(os.path.join(self.mp_dir, "scratch.wav")))


if __name__ == "__main__":
    unittest.main()
