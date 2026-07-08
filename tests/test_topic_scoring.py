import os
import sys
import unittest

ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
SRC_DIR = os.path.join(ROOT_DIR, "src")

if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from topic_scoring import pick_best, score_title


class ScoreTitleTests(unittest.TestCase):
    def test_specific_numeric_absurd_title_scores_higher_than_generic(self) -> None:
        specific = "The Pig That Was Put on Trial in 1386"
        generic = "Amazing Facts You Won't Believe"
        self.assertGreater(score_title(specific), score_title(generic))

    def test_absurd_contrast_keyword_increases_score(self) -> None:
        base = "The strange story of a village"
        with_keyword = "The strange war of a village"
        self.assertGreaterEqual(score_title(with_keyword), score_title(base))

    def test_slop_phrase_is_penalized(self) -> None:
        clean = "The War Started by a Bucket"
        sloppy = "You Won't Believe This War Started by a Bucket"
        self.assertGreater(score_title(clean), score_title(sloppy))

    def test_empty_title_scores_zero(self) -> None:
        self.assertEqual(score_title(""), 0.0)


class PickBestTests(unittest.TestCase):
    def test_returns_highest_scoring_candidate(self) -> None:
        candidates = [
            "Amazing Facts You Won't Believe",
            "The War Started by a Bucket in 1325",
            "A story",
        ]
        self.assertEqual(
            pick_best(candidates),
            "The War Started by a Bucket in 1325",
        )

    def test_falls_back_to_first_candidate_when_all_empty(self) -> None:
        self.assertEqual(pick_best(["", ""]), "")

    def test_single_candidate_returned_as_is(self) -> None:
        self.assertEqual(pick_best(["Only Option"]), "Only Option")


if __name__ == "__main__":
    unittest.main()
