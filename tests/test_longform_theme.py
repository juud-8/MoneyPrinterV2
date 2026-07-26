import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import longform_theme


def episode(title, views=100, niche="weird but true history", fmt="short"):
    return {
        "title": title,
        "views": views,
        "niche": niche,
        "format": fmt,
        "url": f"https://www.youtube.com/watch?v={abs(hash(title)) % 10**11:011d}",
        "date": "2026-07-20",
    }


class PublishedEpisodeTests(unittest.TestCase):
    def test_filters_by_niche_format_and_publication(self):
        analytics = {
            "videos": [
                episode("A President Story"),
                episode("A Longform Thing", fmt="longform"),
                episode("Wrong Niche", niche="cooking"),
                {"title": "No URL", "niche": "history", "format": "short"},
                None,
            ]
        }
        titles = [e["title"] for e in longform_theme.published_episodes(analytics, "history")]
        self.assertEqual(titles, ["A President Story"])

    def test_deduplicates_titles_and_normalises_bad_views(self):
        analytics = {"videos": [
            episode("Same Title", views=5),
            episode("Same Title", views=9),
            episode("Bad Views", views=None),
            episode("Bool Views", views=True),
        ]}
        result = longform_theme.published_episodes(analytics, "history")
        self.assertEqual(len(result), 3)
        self.assertTrue(all(isinstance(e["views"], int) for e in result))
        self.assertEqual([e["views"] for e in result if e["title"] == "Bool Views"], [0])

    def test_missing_videos_list_is_not_fatal(self):
        self.assertEqual(longform_theme.published_episodes({}, "history"), [])


class ThemeSelectionTests(unittest.TestCase):
    def test_needs_a_minimum_cluster_before_offering_a_theme(self):
        analytics = {"videos": [episode("President One"), episode("President Two")]}
        self.assertIsNone(longform_theme.build_theme_subject(analytics, "history"))

    def test_builds_a_chaptered_subject_from_a_cluster(self):
        analytics = {"videos": [
            episode("How Cherries Killed President Taylor", views=70),
            episode("How a Destroyer Torpedoed Its Own President", views=500),
            episode("How a Carriage Got President Grant Arrested", views=300),
        ]}
        result = longform_theme.build_theme_subject(analytics, "history")
        self.assertEqual(result["theme"], "president")
        self.assertEqual(len(result["chapters"]), 3)
        # Highest-reach chapter leads.
        self.assertIn("Torpedoed", result["chapters"][0])
        # The subject must instruct chaptering and hold the line on accuracy.
        self.assertIn("chapter", result["subject"].lower())
        self.assertIn("factually accurate", result["subject"])
        for chapter in result["chapters"]:
            self.assertIn(chapter, result["subject"])

    def test_used_themes_are_not_offered_again(self):
        analytics = {"videos": [
            episode("President One", views=10),
            episode("President Two", views=10),
            episode("President Three", views=10),
            episode("Rabbits Attack Napoleon", views=90),
            episode("Rabbits Beat an Emperor", views=90),
            episode("Rabbits Overwhelm a Hunt", views=90),
        ]}
        first = longform_theme.build_theme_subject(analytics, "history")
        second = longform_theme.build_theme_subject(analytics, "history", used_themes={first["theme"]})
        self.assertNotEqual(first["theme"], second["theme"])

    def test_recorded_theme_from_a_previous_run_is_excluded(self):
        """End-to-end guard: a theme logged onto an analytics row by a previous
        --theme run must not be offered again. This is the pairing that broke —
        build_theme_preset() reads `longform_theme` off the entries, so if
        log_video() ever stops writing it, every run rebuilds the same episode.
        """
        videos = [
            episode("President One", views=10),
            episode("President Two", views=10),
            episode("President Three", views=10),
            episode("Rabbits Attack Napoleon", views=90),
            episode("Rabbits Beat an Emperor", views=90),
            episode("Rabbits Overwhelm a Hunt", views=90),
        ]
        analytics = {"videos": videos}
        first = longform_theme.build_theme_subject(analytics, "history")

        # Simulate what log_video() now persists for the episode just built.
        videos.append({
            "title": f"3 True Cases: {first['theme']}",
            "niche": "weird but true history",
            "format": "longform",
            "url": "https://youtu.be/compilation1",
            "views": 5,
            "date": "2026-07-26",
            "longform_theme": first["theme"],
        })

        # The same read build_theme_preset() performs in run_brand_longform.py.
        used = {
            str(entry.get("longform_theme") or "")
            for entry in analytics["videos"]
            if isinstance(entry, dict) and entry.get("longform_theme")
        }
        self.assertEqual(used, {first["theme"]})

        second = longform_theme.build_theme_subject(analytics, "history", used_themes=used)
        self.assertIsNotNone(second)
        self.assertNotEqual(second["theme"], first["theme"])

    def test_channel_furniture_words_do_not_become_themes(self):
        analytics = {"videos": [
            episode("Weird History Facts One"),
            episode("Weird History Facts Two"),
            episode("Weird History Facts Three"),
        ]}
        result = longform_theme.build_theme_subject(analytics, "history")
        if result:
            self.assertNotIn(result["theme"], longform_theme.STOPWORDS)


if __name__ == "__main__":
    unittest.main()
