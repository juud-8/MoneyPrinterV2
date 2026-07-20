import os
import sys
import unittest

ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
SRC_DIR = os.path.join(ROOT_DIR, "src")

if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

import radio_show


class DialogueParsingTests(unittest.TestCase):
    def test_parses_speaker_lines_and_ignores_noise(self) -> None:
        script = (
            "# A show\n"
            "HOST: Welcome back to the archive.\n"
            "some stage direction\n"
            "**CALLER:** Wait, that actually happened?\n"
            "  HOST : It did. In 1784.\n"
        )
        self.assertEqual(
            radio_show.parse_dialogue(script),
            [
                ("HOST", "Welcome back to the archive."),
                ("CALLER", "Wait, that actually happened?"),
                ("HOST", "It did. In 1784."),
            ],
        )

    def test_chunking_never_splits_a_line_and_respects_size(self) -> None:
        lines = [("HOST", "x" * 400), ("CALLER", "y" * 400), ("HOST", "z" * 400)]
        chunks = radio_show.chunk_dialogue(lines, max_chars=900)
        self.assertEqual(len(chunks), 2)
        self.assertTrue(chunks[0].startswith("HOST: xxx"))
        # Every line survives intact across the chunks.
        joined = "\n".join(chunks)
        for speaker, text in lines:
            self.assertIn(f"{speaker}: {text}", joined)


class PayloadTests(unittest.TestCase):
    def test_multispeaker_payload_maps_each_voice(self) -> None:
        payload = radio_show.build_tts_payload(
            "HOST: hi\nCALLER: hello", {"HOST": "Charon", "CALLER": "Kore"}
        )
        self.assertEqual(payload["generationConfig"]["responseModalities"], ["AUDIO"])
        configs = payload["generationConfig"]["speechConfig"][
            "multiSpeakerVoiceConfig"
        ]["speakerVoiceConfigs"]
        self.assertEqual(len(configs), 2)
        self.assertEqual(configs[0]["speaker"], "HOST")
        self.assertEqual(
            configs[0]["voiceConfig"]["prebuiltVoiceConfig"]["voiceName"], "Charon"
        )

    def test_show_prompt_carries_persona_and_sign_off(self) -> None:
        prompt = radio_show.build_show_prompt(
            "The Kettle War",
            {"name": "The Archivist", "description": "dry-witted curator"},
            15,
            sign_off="Filed. Until the next one.",
        )
        self.assertIn("The Archivist", prompt)
        self.assertIn("dry-witted curator", prompt)
        self.assertIn("Filed. Until the next one.", prompt)
        self.assertIn("2250 words", prompt)


class BedCommandTests(unittest.TestCase):
    def test_bed_command_shape(self) -> None:
        cmd = radio_show.build_bed_command("card.png", "show.wav", "out.mp4")
        self.assertEqual(cmd.count("-i"), 2)
        graph = cmd[cmd.index("-filter_complex") + 1]
        self.assertIn("showwaves", graph)
        self.assertIn("boxblur", graph)
        self.assertIn("-shortest", cmd)
        self.assertEqual(cmd[-1], "out.mp4")


if __name__ == "__main__":
    unittest.main()
