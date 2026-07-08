import os

import requests
import soundfile as sf
from kittentts import KittenTTS as KittenModel

from config import (
    ROOT_DIR,
    get_elevenlabs_api_key,
    get_elevenlabs_model,
    get_elevenlabs_voice_id,
    get_fishaudio_api_key,
    get_fishaudio_model,
    get_fishaudio_voice_id,
    get_tts_provider,
    get_tts_voice,
)
from status import warning

KITTEN_MODEL = "KittenML/kitten-tts-mini-0.8"
KITTEN_SAMPLE_RATE = 24000
ELEVENLABS_SAMPLE_RATE = 44100


class TTS:
    def __init__(self) -> None:
        self._provider = get_tts_provider()
        self._voice = get_tts_voice()
        self._kitten = None
        if self._provider == "kittentts":
            self._kitten = KittenModel(KITTEN_MODEL)

    def _synthesize_elevenlabs(self, text: str, output_file: str) -> str:
        api_key = get_elevenlabs_api_key()
        voice_id = get_elevenlabs_voice_id()
        if not api_key or not voice_id:
            raise RuntimeError(
                "ElevenLabs selected but elevenlabs_api_key or elevenlabs_voice_id missing."
            )

        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
        headers = {
            "xi-api-key": api_key,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        }
        payload = {
            "text": text,
            "model_id": get_elevenlabs_model(),
            "voice_settings": {
                "stability": 0.45,
                "similarity_boost": 0.75,
                "style": 0.35,
                "use_speaker_boost": True,
            },
        }
        response = requests.post(url, headers=headers, json=payload, timeout=120)
        response.raise_for_status()

        # ElevenLabs returns MP3; MoviePy reads MP3 directly
        mp3_path = output_file if output_file.endswith(".mp3") else output_file.replace(".wav", ".mp3")
        with open(mp3_path, "wb") as f:
            f.write(response.content)
        return mp3_path

    def _synthesize_fishaudio(self, text: str, output_file: str) -> str:
        api_key = get_fishaudio_api_key()
        voice_id = get_fishaudio_voice_id()
        if not api_key or not voice_id:
            raise RuntimeError(
                "Fish Audio selected but fishaudio_api_key or fishaudio_voice_id missing."
            )

        response = requests.post(
            "https://api.fish.audio/v1/tts",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "model": get_fishaudio_model(),
            },
            json={
                "text": text,
                "reference_id": voice_id,
                "format": "mp3",
            },
            timeout=120,
        )
        response.raise_for_status()

        # Fish Audio returns MP3; MoviePy reads MP3 directly
        mp3_path = output_file if output_file.endswith(".mp3") else output_file.replace(".wav", ".mp3")
        with open(mp3_path, "wb") as f:
            f.write(response.content)
        return mp3_path

    def _synthesize_kitten(self, text: str, output_file: str) -> str:
        if self._kitten is None:
            self._kitten = KittenModel(KITTEN_MODEL)
        audio = self._kitten.generate(text, voice=self._voice)
        sf.write(output_file, audio, KITTEN_SAMPLE_RATE)
        return output_file

    def synthesize(self, text, output_file=os.path.join(ROOT_DIR, ".mp", "audio.wav")):
        if self._provider == "fishaudio":
            try:
                return self._synthesize_fishaudio(text, output_file)
            except Exception as e:
                if get_elevenlabs_api_key():
                    warning(f"Fish Audio failed ({e}); falling back to ElevenLabs.")
                    try:
                        return self._synthesize_elevenlabs(text, output_file)
                    except Exception as e2:
                        warning(f"ElevenLabs failed ({e2}); falling back to KittenTTS.")
                        return self._synthesize_kitten(text, output_file)
                warning(f"Fish Audio failed ({e}); falling back to KittenTTS.")
                return self._synthesize_kitten(text, output_file)
        if self._provider == "elevenlabs":
            try:
                return self._synthesize_elevenlabs(text, output_file)
            except Exception as e:
                warning(f"ElevenLabs failed ({e}); falling back to KittenTTS.")
                return self._synthesize_kitten(text, output_file)
        return self._synthesize_kitten(text, output_file)
