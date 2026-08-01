"""Tests for the grounded-research retry loop in classes/YouTube.py.

A marginal brief (three claims when the gate wants four) is a sampling
outcome, not proof that a topic is ungroundable — especially when the quality
LLM is unavailable and generation has fallen back to a smaller local model.
No network, Selenium, or LLM calls: generate_response is stubbed.
"""

import json
import os
import sys
import unittest
from unittest.mock import patch

ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
SRC_DIR = os.path.join(ROOT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from classes.YouTube import YouTube  # noqa: E402

SOURCES = [
    {"id": "S1", "title": "One", "url": "https://one", "excerpt": "First"},
    {"id": "S2", "title": "Two", "url": "https://two", "excerpt": "Second"},
]


def _brief_json(claim_count: int) -> str:
    return json.dumps(
        {
            "summary": "An angle",
            "claims": [
                {"text": f"Claim {index}", "source_ids": ["S1", "S2"]}
                for index in range(claim_count)
            ],
            "disputed_points": [],
            "visual_leads": [],
        }
    )


def _make_youtube(responses):
    yt = YouTube.__new__(YouTube)
    yt._niche = "test niche"
    yt.prompts = list(responses)
    yt.sent_prompts = []

    def fake_generate_response(prompt, model_name=None, quality=False):
        yt.sent_prompts.append(prompt)
        return yt.prompts.pop(0)

    yt.generate_response = fake_generate_response
    return yt


class GroundedBriefRetryTests(unittest.TestCase):
    def test_accepts_a_passing_brief_without_retrying(self):
        yt = _make_youtube([_brief_json(4)])
        brief = yt._generate_grounded_brief("Topic", SOURCES)
        self.assertEqual(len(brief["claims"]), 4)
        self.assertEqual(len(yt.sent_prompts), 1)

    def test_reprompts_with_feedback_after_a_thin_brief(self):
        yt = _make_youtube([_brief_json(3), _brief_json(5)])
        with patch("classes.YouTube.warning"):
            brief = yt._generate_grounded_brief("Topic", SOURCES)
        self.assertEqual(len(brief["claims"]), 5)
        self.assertEqual(len(yt.sent_prompts), 2)
        self.assertNotIn("previous attempt was rejected", yt.sent_prompts[0])
        self.assertIn("fewer than 4 source-mapped claims", yt.sent_prompts[1])

    def test_unparseable_output_is_retried_rather_than_crashing(self):
        yt = _make_youtube(["not json at all", _brief_json(4)])
        with patch("classes.YouTube.warning"):
            brief = yt._generate_grounded_brief("Topic", SOURCES)
        self.assertEqual(len(brief["claims"]), 4)
        self.assertEqual(len(yt.sent_prompts), 2)

    def test_raises_the_retryable_gate_error_after_exhausting_attempts(self):
        yt = _make_youtube([_brief_json(2)] * 3)
        with patch("classes.YouTube.warning"):
            with self.assertRaises(RuntimeError) as caught:
                yt._generate_grounded_brief("Topic", SOURCES)
        message = str(caught.exception)
        self.assertIn("Research quality gate failed", message)
        self.assertEqual(len(yt.sent_prompts), 3)
        # The topic-level retry in _generate_topic_and_research keys off this
        # message, so exhausting attempts must stay classified as retryable.
        self.assertTrue(YouTube._is_retryable_research_error(caught.exception))


if __name__ == "__main__":
    unittest.main()
