import os
import sys
import unittest
from unittest.mock import patch

ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
SRC_DIR = os.path.join(ROOT_DIR, "src")

if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

import content_funnel


class BuildDescriptionTests(unittest.TestCase):
    def _patched(self, cfg_funnel=None, channel_funnel=None, channel_cfg=None):
        return (
            patch.object(content_funnel, "get_channel_funnel_config", return_value=cfg_funnel or {}),
            patch.object(content_funnel, "get_channel_funnel", return_value=channel_funnel or {}),
            patch.object(
                content_funnel,
                "load_channel_config",
                return_value=channel_cfg
                or {"channel_name": "Test Channel", "default_hashtags": "#Test"},
            ),
        )

    def test_includes_affiliate_link_and_disclosure_first(self) -> None:
        p1, p2, p3 = self._patched(
            channel_funnel={
                "affiliate_link": "https://example.com/store",
                "affiliate_disclosure": "#ad",
            }
        )
        with p1, p2, p3:
            description = content_funnel.build_description("Body text.", include_affiliate=True)

        lines = description.splitlines()
        self.assertIn("https://example.com/store", lines[0])
        self.assertEqual(lines[1], "#ad")

    def test_include_affiliate_false_omits_link_even_if_configured(self) -> None:
        p1, p2, p3 = self._patched(
            channel_funnel={"affiliate_link": "https://example.com/store"}
        )
        with p1, p2, p3:
            description = content_funnel.build_description("Body text.", include_affiliate=False)

        self.assertNotIn("https://example.com/store", description)

    def test_brand_funnel_overrides_config_funnel(self) -> None:
        p1, p2, p3 = self._patched(
            cfg_funnel={"affiliate_link": "https://config-level.example.com"},
            channel_funnel={"affiliate_link": "https://brand-level.example.com"},
        )
        with p1, p2, p3:
            description = content_funnel.build_description("Body.", include_affiliate=True)

        self.assertIn("https://brand-level.example.com", description)
        self.assertNotIn("https://config-level.example.com", description)

    def test_lead_magnet_and_tagline_appear_when_configured(self) -> None:
        p1, p2, p3 = self._patched(
            channel_funnel={
                "lead_magnet_url": "https://example.com/freebie",
                "lead_magnet_cta": "Grab the freebie",
            },
            channel_cfg={
                "channel_name": "Test Channel",
                "tagline": "Cool stuff, fast.",
                "default_hashtags": "#Test",
            },
        )
        with p1, p2, p3:
            description = content_funnel.build_description("Body.", include_affiliate=True)

        self.assertIn("Grab the freebie: https://example.com/freebie", description)
        self.assertIn("Test Channel: Cool stuff, fast.", description)

    def test_shorts_description_links_are_worded_as_not_clickable(self) -> None:
        """Shorts description links haven't been clickable since Aug 2023 —
        copy must point viewers at the channel bio/Links panel instead of
        implying the description URL itself is tappable."""
        p1, p2, p3 = self._patched(
            channel_funnel={"affiliate_link": "https://example.com/store"}
        )
        with p1, p2, p3:
            short_description = content_funnel.build_description(
                "Body.", format_type="short", include_affiliate=True
            )
            longform_description = content_funnel.build_description(
                "Body.", format_type="longform", include_affiliate=True
            )

        self.assertIn("not clickable here on Shorts", short_description)
        self.assertNotIn("not clickable here on Shorts", longform_description)
        # The URL itself must still be present in both, for compliance/searchability.
        self.assertIn("https://example.com/store", short_description)
        self.assertIn("https://example.com/store", longform_description)

    def test_hashtags_always_appended(self) -> None:
        p1, p2, p3 = self._patched(channel_cfg={"default_hashtags": "#Foo #Bar"})
        with p1, p2, p3:
            description = content_funnel.build_description("Body.")

        self.assertTrue(description.strip().endswith("#Foo #Bar"))


if __name__ == "__main__":
    unittest.main()
