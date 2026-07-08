import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
SRC_DIR = os.path.join(ROOT_DIR, "src")

if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

import brand_switcher
import cache


def _write_manifest(brands_dir: str, brand_id: str, payload: dict) -> None:
    brand_dir = os.path.join(brands_dir, brand_id)
    os.makedirs(brand_dir, exist_ok=True)
    with open(os.path.join(brand_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f)


class BrandFolderLayoutTests(unittest.TestCase):
    """Brands live at brands/<brand_id>/manifest.json — verify the new
    folder-per-brand layout (Phase 2 restructure) resolves correctly."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.brands_dir = os.path.join(self._tmp.name, "brands")
        os.makedirs(self.brands_dir, exist_ok=True)
        self.active_brand_path = os.path.join(self._tmp.name, ".mp", "active_brand.json")

        _write_manifest(self.brands_dir, "alpha", {"channel_name": "Alpha Channel"})
        _write_manifest(self.brands_dir, "beta", {"channel_name": "Beta Channel"})

        # bootstrap_brand()/switch_brand() read+write the YouTube account
        # cache — redirect it into the temp dir so tests never touch the
        # real .mp/youtube.json.
        mp_dir = os.path.join(self._tmp.name, ".mp")
        os.makedirs(mp_dir, exist_ok=True)

        self._patches = [
            patch.object(brand_switcher, "BRANDS_DIR", self.brands_dir),
            patch.object(brand_switcher, "ACTIVE_BRAND_PATH", self.active_brand_path),
            patch.object(cache, "get_cache_path", return_value=mp_dir),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self) -> None:
        for p in self._patches:
            p.stop()
        self._tmp.cleanup()

    def test_brand_id_derives_from_folder_name_not_filename(self) -> None:
        brand = brand_switcher.load_brand("alpha")
        self.assertIsNotNone(brand)
        self.assertEqual(brand["brand_id"], "alpha")
        self.assertEqual(brand["channel_name"], "Alpha Channel")

    def test_explicit_brand_id_in_manifest_wins_over_folder_name(self) -> None:
        _write_manifest(self.brands_dir, "folder_name", {"brand_id": "explicit_id"})
        brand = brand_switcher.load_brand("explicit_id")
        self.assertIsNotNone(brand)
        self.assertEqual(brand["brand_id"], "explicit_id")

    def test_list_brands_finds_all_manifests(self) -> None:
        brands = brand_switcher.list_brands()
        ids = {b["brand_id"] for b in brands}
        self.assertEqual(ids, {"alpha", "beta"})

    def test_set_and_get_active_brand_round_trips(self) -> None:
        brand_switcher.set_active_brand("beta")
        self.assertEqual(brand_switcher.get_active_brand_id(), "beta")

    def test_unknown_brand_cannot_be_activated(self) -> None:
        with self.assertRaises(ValueError):
            brand_switcher.set_active_brand("does_not_exist")

    def test_switch_brand_returns_summary_with_warnings(self) -> None:
        summary = brand_switcher.switch_brand("alpha")
        self.assertEqual(summary["brand_id"], "alpha")
        self.assertEqual(summary["channel_name"], "Alpha Channel")
        # No firefox_profile configured for this fixture -> should warn.
        self.assertTrue(any("profile" in w.lower() for w in summary["warnings"]))


class ActiveBrandFallbackTests(unittest.TestCase):
    """get_active_brand_id() falls back to channel_config_file when no
    .mp/active_brand.json exists yet — verify it handles both the new
    brands/<id>/manifest.json layout and derives the right brand_id."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.brands_dir = os.path.join(self._tmp.name, "brands")
        os.makedirs(self.brands_dir, exist_ok=True)
        self.active_brand_path = os.path.join(self._tmp.name, ".mp", "active_brand.json")
        _write_manifest(self.brands_dir, "gamma", {"channel_name": "Gamma"})

        self._patches = [
            patch.object(brand_switcher, "BRANDS_DIR", self.brands_dir),
            patch.object(brand_switcher, "ACTIVE_BRAND_PATH", self.active_brand_path),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self) -> None:
        for p in self._patches:
            p.stop()
        self._tmp.cleanup()

    def test_falls_back_to_channel_config_file_folder_name(self) -> None:
        with patch(
            "config.get_channel_config_file",
            return_value="brands/gamma/manifest.json",
        ):
            self.assertEqual(brand_switcher.get_active_brand_id(), "gamma")


class RealBrandManifestsTests(unittest.TestCase):
    """Smoke-test the actual shipped brands/ directory (read-only — no
    cache writes), so a brand manifest with invalid JSON or an unresolvable
    content style fails CI/tests immediately rather than at runtime."""

    def test_all_shipped_brands_load_and_resolve_a_style(self) -> None:
        import content_styles

        brands = brand_switcher.list_brands()
        ids = {b["brand_id"] for b in brands}
        self.assertIn("the_strange_archive", ids)
        self.assertEqual(len(ids), 1)

        for b in brands:
            manifest = brand_switcher.load_brand(b["brand_id"])
            style = content_styles.get_content_style(manifest)
            self.assertIsNotNone(style)

    def test_the_strange_archive_resolves_to_weird_history_pilot_style(self) -> None:
        """The Strange Archive explicitly opts into the tighter weird_history
        style (see content_styles.py) via production.content_style — it no
        longer relies on the generic content_type: history mapping."""
        import content_styles

        manifest = brand_switcher.load_brand("the_strange_archive")
        self.assertEqual(content_styles.resolve_style_name(manifest), "weird_history")
        self.assertTrue(manifest.get("production", {}).get("ai_disclosure"))
        self.assertTrue(manifest.get("production", {}).get("pilot_mode"))


if __name__ == "__main__":
    unittest.main()
