import io
import os
import sys
import tempfile
import unittest
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import generate_sounds                                    # noqa: E402
from voice import PCM_RATE, Voice, pcm_to_wav              # noqa: E402


class PcmToWavTest(unittest.TestCase):
    def test_wraps_headerless_pcm_as_16_bit_mono(self):
        pcm = b"\x00\x01" * 500                # 1000 bytes = 500 samples
        data = pcm_to_wav(pcm)
        self.assertTrue(data.startswith(b"RIFF"))
        with wave.open(io.BytesIO(data), "rb") as w:
            self.assertEqual(w.getnchannels(), 1)
            self.assertEqual(w.getsampwidth(), 2)
            self.assertEqual(w.getframerate(), PCM_RATE)
            self.assertEqual(w.getnframes(), 500)
            self.assertEqual(w.readframes(500), pcm)


class VoiceTest(unittest.TestCase):
    def test_missing_clip_is_silent_not_fatal(self):
        with tempfile.TemporaryDirectory() as d:
            v = Voice(directory=d)
            self.assertEqual(v.available(), [])
            self.assertFalse(v.say("activated"))

    def test_muted_voice_never_plays(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "activated.wav").write_bytes(pcm_to_wav(b"\x00\x00" * 10))
            v = Voice(directory=d, enabled=False)
            self.assertEqual(v.available(), ["activated"])
            self.assertFalse(v.say("activated"))

    def test_unknown_clip_name_is_ignored(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "activated.wav").write_bytes(b"x")
            self.assertFalse(Voice(directory=d).say("nope"))

    def test_missing_directory_is_silent(self):
        v = Voice(directory=Path(tempfile.gettempdir()) / "airtrack-no-such-dir")
        self.assertEqual(v.available(), [])
        self.assertFalse(v.say("activated"))


class ClipTableTest(unittest.TestCase):
    def test_activation_phrase_names_the_app(self):
        self.assertIn("airtrack", generate_sounds.CLIPS["activated"].lower())
        self.assertTrue(all(t.strip() for t in generate_sounds.CLIPS.values()))

    def test_missing_key_exits_with_a_hint(self):
        old = os.environ.pop("ELEVENLABS_API_KEY", None)
        try:
            with self.assertRaises(SystemExit):
                generate_sounds.api_key()
        finally:
            if old is not None:
                os.environ["ELEVENLABS_API_KEY"] = old


if __name__ == "__main__":
    unittest.main()
