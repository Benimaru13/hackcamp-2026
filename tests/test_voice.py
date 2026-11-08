import io
import os
import sys
import tempfile
import unittest
import wave
from unittest import mock
from types import SimpleNamespace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import generate_sounds                                    # noqa: E402
import voice as voice_module                              # noqa: E402
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

    def test_wait_mode_uses_blocking_player(self):
        calls = []
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "start_message.wav").write_bytes(b"wav")
            with mock.patch.object(voice_module.sys, "platform", "linux"), \
                 mock.patch.object(voice_module, "player_command",
                                   lambda _path: ["player", "clip"]), \
                 mock.patch.object(voice_module.subprocess, "run",
                                   lambda *args, **kwargs: calls.append(
                                       (args, kwargs))):
                self.assertTrue(Voice(directory=d).say("start_message", wait=True))
        self.assertEqual(calls[0][0], (["player", "clip"],))
        self.assertFalse(calls[0][1]["check"])

    def test_wait_mode_uses_synchronous_winsound_on_windows(self):
        calls = []
        fake_winsound = SimpleNamespace(
            SND_FILENAME=1,
            SND_NODEFAULT=2,
            SND_ASYNC=4,
            PlaySound=lambda path, flags: calls.append((path, flags)),
        )
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "start_message.wav").write_bytes(b"wav")
            with mock.patch.object(voice_module.sys, "platform", "win32"):
                with mock.patch.dict(sys.modules, {"winsound": fake_winsound}):
                    self.assertTrue(
                        Voice(directory=d).say("start_message", wait=True))
        self.assertEqual(calls[0][1], fake_winsound.SND_FILENAME |
                         fake_winsound.SND_NODEFAULT)


class EnvFileTest(unittest.TestCase):
    def test_env_file_supplies_key_and_voice_without_overriding_the_shell(self):
        names = ("ELEVENLABS_API_KEY", "ELEVENLABS_VOICE_ID", "AIRTRA\x43K_TEST")
        saved = {k: os.environ.pop(k, None) for k in names}
        os.environ["AIRTRA\x43K_TEST"] = "from-shell"
        try:
            with tempfile.TemporaryDirectory() as d:
                env = Path(d) / ".env"
                env.write_text('# a comment\n'
                               'ELEVENLABS_API_KEY="sk_test_123"\n'
                               'ELEVENLABS_VOICE_ID=voice42\n'
                               'AIRTRA\x43K_TEST=from-file\n', encoding="utf-8")
                generate_sounds.load_env_file(env)
                self.assertEqual(os.environ["ELEVENLABS_API_KEY"], "sk_test_123")
                self.assertEqual(os.environ["ELEVENLABS_VOICE_ID"], "voice42")
                self.assertEqual(os.environ["AIRTRA\x43K_TEST"], "from-shell")
                self.assertEqual(generate_sounds.voice_id(), "voice42")
                self.assertEqual(generate_sounds.voice_id("explicit"), "explicit")
        finally:
            for k, v in saved.items():
                os.environ.pop(k, None)
                if v is not None:
                    os.environ[k] = v

    def test_missing_env_file_is_not_an_error(self):
        generate_sounds.load_env_file(
            Path(tempfile.gettempdir()) / "airtrack-no-such.env")


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
