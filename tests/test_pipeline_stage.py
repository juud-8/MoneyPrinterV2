import io
import json
import os
import sys
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import pipeline_stage  # noqa: E402


class EmitStageTests(unittest.TestCase):
    def test_silent_when_env_var_unset(self):
        buf = io.StringIO()
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MPV2_STAGE_EVENTS", None)
            with redirect_stdout(buf):
                pipeline_stage.emit_stage("topic", topic="Example")
        self.assertEqual(buf.getvalue(), "")

    def test_silent_when_env_var_not_exactly_one(self):
        buf = io.StringIO()
        with patch.dict(os.environ, {"MPV2_STAGE_EVENTS": "true"}):
            with redirect_stdout(buf):
                pipeline_stage.emit_stage("topic")
        self.assertEqual(buf.getvalue(), "")

    def test_emits_well_formed_json_line_when_enabled(self):
        buf = io.StringIO()
        with patch.dict(os.environ, {"MPV2_STAGE_EVENTS": "1"}):
            with redirect_stdout(buf):
                pipeline_stage.emit_stage("assets", index=2, total=5)
        output = buf.getvalue().strip()
        self.assertTrue(output.startswith(pipeline_stage.STAGE_TAG))
        payload = json.loads(output[len(pipeline_stage.STAGE_TAG):])
        self.assertEqual(payload, {"stage": "assets", "index": 2, "total": 5})


if __name__ == "__main__":
    unittest.main()
