import os
import sys
import unittest
from unittest.mock import patch

ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
SRC_DIR = os.path.join(ROOT_DIR, "src")

if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

import asset_strategy


class AssetStrategyTests(unittest.TestCase):
    def test_default_strategy_is_standard_for_every_role(self) -> None:
        with patch.object(asset_strategy, "get_production_setting", return_value={}):
            self.assertEqual(asset_strategy.tier_for_shot_role("hook"), "standard")
            self.assertEqual(asset_strategy.tier_for_shot_role("default"), "standard")

    def test_brand_can_opt_a_role_into_premium_video(self) -> None:
        with patch.object(
            asset_strategy,
            "get_production_setting",
            return_value={"hook": "premium_video"},
        ):
            self.assertEqual(asset_strategy.tier_for_shot_role("hook"), "premium_video")
            # Unconfigured roles stay on the engine default.
            self.assertEqual(asset_strategy.tier_for_shot_role("default"), "standard")

    def test_invalid_tier_value_is_ignored(self) -> None:
        with patch.object(
            asset_strategy,
            "get_production_setting",
            return_value={"hook": "ultra_mega_tier"},
        ):
            self.assertEqual(asset_strategy.tier_for_shot_role("hook"), "standard")

    def test_non_dict_strategy_value_is_ignored(self) -> None:
        with patch.object(asset_strategy, "get_production_setting", return_value="oops"):
            strategy = asset_strategy.get_asset_strategy()
            self.assertEqual(strategy, asset_strategy.DEFAULT_ASSET_STRATEGY)

    def test_unrecognized_role_falls_back_to_default_tier(self) -> None:
        with patch.object(
            asset_strategy,
            "get_production_setting",
            return_value={"default": "premium_image"},
        ):
            self.assertEqual(asset_strategy.tier_for_shot_role("twist"), "premium_image")


class ShotRoleForIndexTests(unittest.TestCase):
    def test_only_first_shot_is_the_hook(self) -> None:
        self.assertEqual(asset_strategy.shot_role_for_index(0), "hook")
        self.assertEqual(asset_strategy.shot_role_for_index(1), "default")
        self.assertEqual(asset_strategy.shot_role_for_index(5), "default")


if __name__ == "__main__":
    unittest.main()
