"""Tests for topic retry when grounded research fails."""

import os
import sys
import unittest
from unittest.mock import Mock, patch

ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
SRC_DIR = os.path.join(ROOT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from classes.YouTube import YouTube


class ResearchRetryTests(unittest.TestCase):
    def test_is_retryable_research_error(self) -> None:
        self.assertTrue(
            YouTube._is_retryable_research_error(
                RuntimeError(
                    "Grounded research found only 1 usable source(s) for 'beetles'; "
                    "refusing to generate an unverified nonfiction script."
                )
            )
        )
        self.assertTrue(
            YouTube._is_retryable_research_error(
                RuntimeError("Research quality gate failed: need 3 claims")
            )
        )
        self.assertFalse(
            YouTube._is_retryable_research_error(
                RuntimeError("Voiceover still 90.0s (cap 60s) after shorter-script retries")
            )
        )

    def test_retries_new_topic_after_thin_sources(self) -> None:
        yt = YouTube.__new__(YouTube)
        yt.subject = ""
        yt._research_rejected_topics = []
        yt.research_notes = ""
        yt.research_brief = {}
        yt.research_brief_path = ""
        calls = {"topic": 0, "research": 0}

        def gen_topic() -> str:
            calls["topic"] += 1
            yt.subject = f"topic-{calls['topic']}"
            return yt.subject

        def gen_research() -> str:
            calls["research"] += 1
            if calls["research"] == 1:
                raise RuntimeError(
                    "Grounded research found only 1 usable source(s) for 'topic-1'; "
                    "refusing to generate an unverified nonfiction script."
                )
            yt.research_notes = "ok"
            return "ok"

        yt.generate_topic = gen_topic  # type: ignore[method-assign]
        yt.generate_research = gen_research  # type: ignore[method-assign]

        with (
            patch("classes.YouTube.log_topic_rejection") as log_rej,
            patch("classes.YouTube.load_active_brand", return_value={"brand_id": "alpha"}),
            patch("classes.YouTube.recent_research_gate_rejections", return_value=[]),
            patch("classes.YouTube.warning"),
            patch("classes.YouTube.info"),
        ):
            yt._generate_topic_and_research(max_attempts=3)

        self.assertEqual(yt.subject, "topic-2")
        self.assertEqual(calls["topic"], 2)
        self.assertEqual(calls["research"], 2)
        self.assertIn("topic-1", yt._research_rejected_topics)
        log_rej.assert_called_once()
        self.assertEqual(log_rej.call_args.kwargs["matched"], "research_gate")

    def test_seeds_prior_research_gate_rejections(self) -> None:
        """A fresh run blocks topics that failed the research gate in prior runs."""
        yt = YouTube.__new__(YouTube)
        yt.subject = ""
        yt._research_rejected_topics = []
        yt.research_notes = ""
        yt.research_brief = {}
        yt.research_brief_path = ""
        seen_rejected: list[list[str]] = []

        def gen_topic() -> str:
            seen_rejected.append(list(yt._research_rejected_topics))
            yt.subject = "fresh topic"
            return yt.subject

        def gen_research() -> str:
            yt.research_notes = "ok"
            return "ok"

        yt.generate_topic = gen_topic  # type: ignore[method-assign]
        yt.generate_research = gen_research  # type: ignore[method-assign]

        with (
            patch("classes.YouTube.load_active_brand", return_value={"brand_id": "alpha"}),
            patch(
                "classes.YouTube.recent_research_gate_rejections",
                return_value=["unverifiable mummified cats topic"],
            ) as prior,
            patch("classes.YouTube.warning"),
            patch("classes.YouTube.info"),
        ):
            yt._generate_topic_and_research(max_attempts=3)

        prior.assert_called_once_with("alpha")
        self.assertEqual(
            seen_rejected[0], ["unverifiable mummified cats topic"]
        )

    def test_seeding_failure_does_not_block_generation(self) -> None:
        yt = YouTube.__new__(YouTube)
        yt.subject = ""
        yt._research_rejected_topics = []
        yt.research_notes = ""
        yt.research_brief = {}
        yt.research_brief_path = ""

        def gen_topic() -> str:
            yt.subject = "fresh topic"
            return yt.subject

        def gen_research() -> str:
            yt.research_notes = "ok"
            return "ok"

        yt.generate_topic = gen_topic  # type: ignore[method-assign]
        yt.generate_research = gen_research  # type: ignore[method-assign]

        with (
            patch("classes.YouTube.load_active_brand", return_value={"brand_id": "alpha"}),
            patch(
                "classes.YouTube.recent_research_gate_rejections",
                side_effect=OSError("analytics unreadable"),
            ),
            patch("classes.YouTube.warning") as warn,
            patch("classes.YouTube.info"),
        ):
            yt._generate_topic_and_research(max_attempts=3)

        self.assertEqual(yt.subject, "fresh topic")
        warn.assert_called_once()

    def test_preset_topic_does_not_silently_switch(self) -> None:
        yt = YouTube.__new__(YouTube)
        yt.subject = "Forced Beetle Lawsuit Topic"
        yt._research_rejected_topics = []

        def gen_topic() -> str:
            return yt.subject

        def gen_research() -> str:
            raise RuntimeError(
                "Grounded research found only 1 usable source(s) for 'Forced Beetle Lawsuit Topic'"
            )

        yt.generate_topic = gen_topic  # type: ignore[method-assign]
        yt.generate_research = gen_research  # type: ignore[method-assign]

        with self.assertRaises(RuntimeError) as ctx:
            yt._generate_topic_and_research(max_attempts=3)
        self.assertIn("only 1 usable source", str(ctx.exception))
        self.assertEqual(yt.subject, "Forced Beetle Lawsuit Topic")


class TopicDenylistTests(unittest.TestCase):
    def test_trump_candidate_is_rejected_and_logged_before_selection(self) -> None:
        yt = YouTube.__new__(YouTube)
        yt.subject = ""
        yt._research_rejected_topics = []
        yt._niche = "weird history"
        yt.generate_response = Mock(
            side_effect=[
                "How Trump Won a $3 Lawsuit in 1986",
                "How a Town Put Its Own Bell on Trial in 1510",
            ]
        )
        style = {
            "uses_episode_hint": False,
            "topic_prompt": lambda _niche, _hint: "Pitch a topic",
            "topic_candidate_count": 1,
        }

        with (
            patch("classes.YouTube.get_content_style", return_value=style),
            patch(
                "classes.YouTube.load_active_brand",
                return_value={"brand_id": "alpha"},
            ),
            patch("classes.YouTube.build_topic_strategy_block", return_value=""),
            patch("classes.YouTube.recent_topic_labels", return_value=["Older topic"]),
            patch("classes.YouTube.find_near_duplicate", return_value=None),
            patch(
                "topic_discovery_loop.trending_topics_enabled",
                return_value=False,
            ),
            patch("classes.YouTube.get_verbose", return_value=False),
            patch("classes.YouTube.warning"),
            patch("classes.YouTube.log_topic_rejection") as log_rejection,
            patch("classes.YouTube.emit_stage"),
        ):
            selected = yt.generate_topic()

        self.assertEqual(selected, "How a Town Put Its Own Bell on Trial in 1510")
        log_rejection.assert_called_once()
        self.assertEqual(
            log_rejection.call_args.kwargs["candidate"],
            "How Trump Won a $3 Lawsuit in 1986",
        )
        self.assertEqual(
            log_rejection.call_args.kwargs["matched"],
            "denylist:trump",
        )


if __name__ == "__main__":
    unittest.main()
