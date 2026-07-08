"""Tests for llm_provider Gemini→Ollama fallback."""

import os
import sys
import unittest
from unittest.mock import patch

ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
SRC_DIR = os.path.join(ROOT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

# test_cron_post_bridge.py registers a stub in sys.modules; ensure we load the real module.
sys.modules.pop("llm_provider", None)
import llm_provider  # noqa: E402


class TestGenerateTextFallback(unittest.TestCase):
    def test_gemini_failure_falls_back_to_ollama(self):
        llm_provider.select_model("llama3.2:3b")
        with (
            patch.object(llm_provider, "_generate_gemini", side_effect=RuntimeError("gemini down")),
            patch.object(llm_provider, "_generate_ollama", return_value="ollama ok") as ollama_mock,
            patch.object(llm_provider, "get_quality_llm_provider", return_value="gemini"),
            patch.object(llm_provider, "get_llm_provider", return_value="ollama"),
            patch.object(llm_provider, "get_verbose", return_value=False),
        ):
            result = llm_provider.generate_text("test prompt", quality=True)

        self.assertEqual(result, "ollama ok")
        ollama_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
