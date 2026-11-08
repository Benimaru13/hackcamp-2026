# sounds/

Spoken cues played by `voice.py`. They are generated once with ElevenLabs:

```bash
export ELEVENLABS_API_KEY=sk_...        # PowerShell: $env:ELEVENLABS_API_KEY="sk_..."
python generate_sounds.py
```

| clip | when it plays |
| --- | --- |
| `activated.wav` | the palm hold takes control (`ARMED` → `ACTIVE`) |
| `released.wav` | control is released (`ACTIVE` → `ARMED`) |

Missing files are simply silent, so the app runs fine without them. Commit the
WAVs if the demo machine should not need an API key — playback is local, no
network call happens at run time.
