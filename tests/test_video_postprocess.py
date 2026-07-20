import os
import sys
import unittest

ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
SRC_DIR = os.path.join(ROOT_DIR, "src")

if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

import video_postprocess


class WatermarkStripTests(unittest.TestCase):
    def test_strip_height_is_even(self) -> None:
        # 1920 * 0.073 = 140.16 -> 140 (already even)
        self.assertEqual(video_postprocess.watermark_strip_px(1920, 0.073), 140)
        # 1920 * 0.078 = 149.76 -> rounds to 150 (even)
        self.assertEqual(video_postprocess.watermark_strip_px(1920, 0.078), 150)
        # Odd rounding results are forced down to even.
        self.assertEqual(video_postprocess.watermark_strip_px(1080, 0.075), 80)

    def test_rejects_destructive_crop_values(self) -> None:
        with self.assertRaises(ValueError):
            video_postprocess.watermark_strip_px(1920, 0.5)
        with self.assertRaises(ValueError):
            video_postprocess.watermark_strip_px(1920, -0.1)


class DebrandFilterTests(unittest.TestCase):
    def test_crop_mode_cuts_strip_then_covers_target(self) -> None:
        chain = video_postprocess.build_debrand_filter(
            1920, 0.073, 1080, 1920, mode="crop"
        )
        self.assertIn("crop=iw:1780:0:0", chain)
        self.assertIn("scale=1080:1920:force_original_aspect_ratio=increase", chain)
        self.assertIn("crop=1080:1920", chain)
        self.assertIn("format=yuv420p", chain)

    def test_cover_mode_paints_bar_without_cutting(self) -> None:
        chain = video_postprocess.build_debrand_filter(
            1920, 0.073, 1080, 1920, mode="cover", cover_color="#1C1410"
        )
        self.assertIn("drawbox=x=0:y=ih-140:w=iw:h=140:color=0x1C1410:t=fill", chain)
        self.assertNotIn("crop=iw:1780", chain)

    def test_zero_crop_skips_debrand_but_still_normalizes(self) -> None:
        chain = video_postprocess.build_debrand_filter(1920, 0.0, 1080, 1920)
        self.assertNotIn("crop=iw:", chain)
        self.assertNotIn("drawbox", chain)
        self.assertIn("scale=1080:1920", chain)

    def test_invalid_mode_raises(self) -> None:
        with self.assertRaises(ValueError):
            video_postprocess.build_debrand_filter(1920, 0.08, 1080, 1920, mode="blur")


class FinishCommandTests(unittest.TestCase):
    def test_without_outro_uses_simple_vf(self) -> None:
        cmd = video_postprocess.build_finish_command(
            "in.mp4", "out.mp4", src_h=1920, target_w=1080, target_h=1920
        )
        self.assertEqual(cmd.count("-i"), 1)
        self.assertIn("-vf", cmd)
        self.assertNotIn("-filter_complex", cmd)
        self.assertIn("+faststart", cmd)
        self.assertEqual(cmd[-1], "out.mp4")

    def test_with_outro_concats_two_inputs(self) -> None:
        cmd = video_postprocess.build_finish_command(
            "in.mp4", "out.mp4", src_h=1920, target_w=1080, target_h=1920,
            outro_path="outro.mp4", outro_has_audio=True,
        )
        self.assertEqual(cmd.count("-i"), 2)
        graph = cmd[cmd.index("-filter_complex") + 1]
        self.assertIn("concat=n=2:v=1:a=1", graph)
        self.assertIn("[1:a]", graph)
        self.assertNotIn("anullsrc", graph)

    def test_silent_outro_gets_synthesized_audio(self) -> None:
        cmd = video_postprocess.build_finish_command(
            "in.mp4", "out.mp4", src_h=1920, target_w=1080, target_h=1920,
            outro_path="outro.mp4", outro_has_audio=False, outro_duration=3.221,
        )
        graph = cmd[cmd.index("-filter_complex") + 1]
        self.assertIn("anullsrc", graph)
        self.assertIn("atrim=0:3.221", graph)
        self.assertNotIn("[1:a]", graph)


class DefaultTargetTests(unittest.TestCase):
    def test_portrait_finishes_as_vertical_short(self) -> None:
        self.assertEqual(video_postprocess.default_target(1080, 1920), (1080, 1920))
        self.assertEqual(video_postprocess.default_target(720, 1280), (1080, 1920))

    def test_landscape_finishes_as_1080p(self) -> None:
        self.assertEqual(video_postprocess.default_target(1920, 1080), (1920, 1080))
        self.assertEqual(video_postprocess.default_target(1280, 720), (1920, 1080))


if __name__ == "__main__":
    unittest.main()
