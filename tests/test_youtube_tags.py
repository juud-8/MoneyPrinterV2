"""Tests for YouTube tag helpers."""

import os
import sys
import unittest

ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
SRC_DIR = os.path.join(ROOT_DIR, "src")

if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from youtube_tags import (
    build_tags_from_llm_response,
    merge_video_tags,
    parse_llm_tags,
    studio_tags_char_count,
    tag_to_hashtag,
    topic_hashtags_for_description,
)


class ParseTagsTests(unittest.TestCase):
    def test_parses_json_payload(self) -> None:
        raw = '{"tags": ["French Revolution", "Bastille 1789"]}'
        self.assertEqual(
            parse_llm_tags(raw),
            ["French Revolution", "Bastille 1789"],
        )

    def test_parses_comma_fallback(self) -> None:
        self.assertEqual(
            parse_llm_tags("napoleon rabbits, 1807 hunt"),
            ["napoleon rabbits", "1807 hunt"],
        )


class MergeTagsTests(unittest.TestCase):
    def test_merges_dedupes_and_enforces_limits(self) -> None:
        defaults = ["strange history", "weird history"]
        generated = ["Weird History", "french revolution", "x" * 40]
        merged = merge_video_tags(defaults, generated, max_tags=5)
        self.assertEqual(merged[0], "strange history")
        self.assertEqual(merged[1], "weird history")
        self.assertEqual(merged[2], "french revolution")
        self.assertLessEqual(studio_tags_char_count(merged), 500)

    def test_build_tags_from_llm_response_normalizes(self) -> None:
        tags = build_tags_from_llm_response('{"tags": ["  French Revolution ", "#Bastille"]}')
        self.assertIn("french revolution", tags)
        self.assertIn("bastille", tags)


class HashtagTests(unittest.TestCase):
    def test_topic_hashtags_skip_staples(self) -> None:
        tags = ["strange history", "french revolution", "bastille 1789"]
        extras = topic_hashtags_for_description(
            tags,
            ["strange history"],
            max_count=2,
        )
        self.assertIn("#FrenchRevolution", extras)
        self.assertNotIn("#StrangeHistory", extras)

    def test_tag_to_hashtag(self) -> None:
        self.assertEqual(tag_to_hashtag("cod wars"), "#CodWars")
        self.assertEqual(tag_to_hashtag("history"), "#History")


if __name__ == "__main__":
    unittest.main()
