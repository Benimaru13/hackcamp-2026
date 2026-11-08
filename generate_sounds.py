"""Generate AirTrack's spoken cues with ElevenLabs (run once, needs a key).

    ELEVENLABS_API_KEY=sk_... python generate_sounds.py

The app itself never calls the API: it plays the WAV files written here, so a
demo works offline and with no key on the machine. Re-run with --force to
regenerate after changing a phrase.

    python generate_sounds.py --list-voices     # pick a voice id
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

from voice import PCM_RATE, SOUND_DIR, pcm_to_wav

API = "https://api.elevenlabs.io/v1"
DEFAULT_VOICE = "21m00Tcm4TlvDq8ikWAM"      # "Rachel", ElevenLabs' default voice
DEFAULT_MODEL = "eleven_multilingual_v2"
ENV_FILE = Path(__file__).with_name(".env")

# One clip per app moment. Keep the text short: it plays while you are moving.
CLIPS = {
    "activated": "AirTrack activated.",
    "released": "Control released.",
}


def load_env_file(path: Path = ENV_FILE) -> None:
    """Read ``KEY=VALUE`` lines from ``.env`` into os.environ.

    Real environment variables win, so CI or a shell export is never overridden
    by a stale file. Missing file is fine: the key may also come from the shell.
    """
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip().removeprefix("export ").strip()
        if key and key not in os.environ:
            os.environ[key] = value.strip().strip("'\"")


def api_key() -> str:
    key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not key:
        sys.exit("ELEVENLABS_API_KEY is not set. Put it in .env as "
                 "ELEVENLABS_API_KEY=sk_... or export it; create a key at "
                 "elevenlabs.io -> Profile -> API keys.")
    return key


def voice_id(cli_value: str | None = None) -> str:
    """CLI flag > ELEVENLABS_VOICE_ID (.env or shell) > built-in default."""
    return (cli_value or os.environ.get("ELEVENLABS_VOICE_ID", "").strip()
            or DEFAULT_VOICE)


def _request(path: str, key: str, payload=None, accept="audio/pcm") -> bytes:
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"xi-api-key": key, "Accept": accept}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(API + path, data=data, method="POST",
                                 headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        body = exc.read()[:400].decode("utf-8", "replace")
        sys.exit(f"ElevenLabs HTTP {exc.code} on {path}: {body}")


def list_voices(key: str):
    req = urllib.request.Request(API + "/voices", headers={"xi-api-key": key})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode()).get("voices", [])
    except urllib.error.HTTPError as exc:
        sys.exit(f"ElevenLabs HTTP {exc.code} on /voices: "
                 f"{exc.read()[:400].decode('utf-8', 'replace')}")


def speak(text: str, voice_id: str, model: str, rate: int = PCM_RATE) -> bytes:
    """Return raw 16-bit mono PCM for ``text``."""
    raw = _request(f"/text-to-speech/{voice_id}?output_format=pcm_{rate}",
                   api_key(),
                   {"text": text, "model_id": model,
                    "voice_settings": {"stability": 0.5,
                                       "similarity_boost": 0.75,
                                       "style": 0.0,
                                       "use_speaker_boost": True}})
    if not raw or raw[:1] == b"{":
        sys.exit(f"unexpected response, not audio: {raw[:200]!r}")
    return raw


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Generate AirTrack's voice clips with ElevenLabs")
    ap.add_argument("--voice-id", default=None,
                    help="defaults to ELEVENLABS_VOICE_ID in .env, else Rachel")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--rate", type=int, default=PCM_RATE,
                    help="sample rate; must match a pcm_<rate> output format")
    ap.add_argument("--out", default=str(SOUND_DIR))
    ap.add_argument("--force", action="store_true", help="overwrite existing clips")
    ap.add_argument("--list-voices", action="store_true",
                    help="print available voice ids and exit")
    args = ap.parse_args(argv)

    load_env_file()
    key = api_key()
    chosen_voice = voice_id(args.voice_id)
    if args.list_voices:
        for v in list_voices(key)[:40]:
            print(f"{v.get('voice_id')}  {v.get('name')}  ({v.get('category', '?')})")
        return 0

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    print(f"voice: {chosen_voice}")
    for name, text in CLIPS.items():
        target = out / f"{name}.wav"
        if target.exists() and not args.force:
            print(f"skip {target.name} (exists; --force to regenerate)")
            continue
        pcm = speak(text, chosen_voice, args.model, args.rate)
        target.write_bytes(pcm_to_wav(pcm, args.rate))
        print(f"{target.name}: {len(pcm) / 2 / args.rate:.2f}s, "
              f"{target.stat().st_size} bytes  \"{text}\"")
    print("Done. Run the app to hear them; --mute turns the cues off.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
