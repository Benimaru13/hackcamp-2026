# sounds/

Spoken cues played by `voice.py`. They are generated once with ElevenLabs:

```bash
# create .env yourself (git-ignored): ELEVENLABS_API_KEY=sk_your_key
python generate_sounds.py
```

The key and voice id are read from `.env` (`ELEVENLABS_API_KEY`,
`ELEVENLABS_VOICE_ID`) or from the environment; neither is used at run time —
the app only reads the WAV files in this directory.

| clip | when it plays |
| --- | --- |
| `start_message.wav` | `start.py` greets you as the calibration window appears |
| `activated.wav` | an open palm takes control (`ARMED` → `ACTIVE`) |
| `released.wav` | control is released (`ACTIVE` → `ARMED`) |

Playback is the OS's own player, so no Python audio package is needed: `afplay`
on macOS, the built-in `winsound` module on Windows, and `paplay` / `aplay` /
`ffplay` on Linux. Missing files, a missing player, or `--mute` all end up silent,
so the app runs fine without any of this. Commit the WAVs if the demo machine
should not need an API key — nothing leaves the machine at run time.
