# sounds/

Spoken cues played by `voice.py`. They are generated once with ElevenLabs:

```bash
# create .env yourself (git-ignored): ELEVENLABS_API_KEY=sk_your_key
python generate_sounds.py
```

The key and voice id are read from `.env` (`ELEVENLABS_API_KEY`,
`ELEVENLABS_VOICE_ID`) or from the environment; neither is used at run time.

| clip | when it plays |
| --- | --- |
| `activated.wav` | the palm hold takes control (`ARMED` → `ACTIVE`) |
| `released.wav` | control is released (`ACTIVE` → `ARMED`) |

Missing files are simply silent, so the app runs fine without them. Commit the
WAVs if the demo machine should not need an API key — playback is local, no
network call happens at run time.
