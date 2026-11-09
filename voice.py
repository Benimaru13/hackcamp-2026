"""Spoken status cues for AirTrack.

The clips in ``sounds/`` are generated once by ``generate_sounds.py`` (ElevenLabs
text-to-speech) and played from disk, so the running app needs no API key, no
network access and no extra dependency: Windows uses the built-in ``winsound``,
macOS and Linux shell out to the player that ships with the OS.

Audio is a nicety, never a requirement. A missing clip, a missing player or
``--mute`` all end up silent, and the demo keeps running.
"""
from __future__ import annotations

import io
import shutil
import subprocess
import sys
import wave
from pathlib import Path

SOUND_DIR = Path(__file__).with_name("sounds")
PCM_RATE = 22050            # matches ElevenLabs output_format=pcm_22050


def pcm_to_wav(pcm: bytes, rate: int = PCM_RATE) -> bytes:
    """Wrap headerless 16-bit mono PCM (what the API returns) in a WAV file."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


def player_command(path: Path):
    """argv for a command-line player, or None if this platform has none."""
    if sys.platform == "darwin":
        return ["afplay", str(path)]
    for exe, extra in (("paplay", []),
                       ("aplay", ["-q"]),
                       ("ffplay", ["-nodisp", "-autoexit", "-loglevel", "quiet"])):
        if shutil.which(exe):
            return [exe, *extra, str(path)]
    return None


class Voice:
    """Plays ``sounds/<name>.wav`` if it exists."""

    def __init__(self, directory=None, enabled: bool = True):
        self.directory = Path(directory) if directory else SOUND_DIR
        self.enabled = enabled
        self._proc = None

    def clip(self, name: str):
        path = self.directory / f"{name}.wav"
        return path if path.is_file() else None

    def available(self):
        """Names of the clips actually present, so startup can report them."""
        if not self.directory.is_dir():
            return []
        return sorted(p.stem for p in self.directory.glob("*.wav"))

    def say(self, name: str, wait: bool = False) -> bool:
        """Play ``name``. Optionally wait for it to finish; never raises."""
        if not self.enabled:
            return False
        path = self.clip(name)
        if path is None:
            return False
        try:
            if sys.platform == "win32":
                import winsound
                flags = winsound.SND_FILENAME | winsound.SND_NODEFAULT
                if not wait:
                    flags |= winsound.SND_ASYNC
                winsound.PlaySound(
                    str(path), flags)
                return True
            argv = player_command(path)
            if argv is None:
                return False
            self._stop()
            if wait:
                subprocess.run(argv, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, check=False)
            else:
                self._proc = subprocess.Popen(argv, stdout=subprocess.DEVNULL,
                                              stderr=subprocess.DEVNULL)
            return True
        except Exception:
            return False

    def set_enabled(self, on: bool) -> bool:
        """Mute or unmute from a gesture; returns the new state.

        Muting also stops whatever is playing right now, so a cue cannot outlive
        the gesture that silenced it. Never raises, same as say().
        """
        self.enabled = bool(on)
        if not self.enabled:
            self._stop()
            if sys.platform == "win32":
                try:
                    import winsound
                    winsound.PlaySound(None, 0)
                except Exception:
                    pass
        return self.enabled

    def _stop(self):
        if self._proc is not None and self._proc.poll() is None:
            try:
                self._proc.terminate()
            except Exception:
                pass
        self._proc = None
