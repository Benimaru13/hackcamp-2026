# Calibration (additive — touches none of the tracker)

`gesture_cursor.py`, `app.py`, `tracker.py` and `simulate.py` are the other
branches' code and are **not modified here**. This adds the missing first step:
a calibrator that measures *your* hand at *your* distance and writes
`profile.json`.

## Run it

- VS Code: **F5 → "AirTrack: calibrate"**
- Terminal: `python calibrate.py`
- No camera: `python calibrate.py --simulate --no-preview`

Three timed steps, nothing to press (so it works standing back from the laptop):

| Step | Gesture | Measures |
|---|---|---|
| 1 | raise an open palm | that the camera sees a hand at all |
| 2 | hold still, 4 s | jitter, in pixels → the 0-100 score |
| 3 | keep pointing, 4 s | your hand size, the reference for distance |

Output: `profile.json` (gitignored — it is personal).

## What the numbers do

- **jitter score** — RMS of frame-to-frame acceleration of the raw point.
  100 = rock steady. It drives everything below.
- **min_speed** — the hand must exceed this (palm-lengths/s) before the cursor
  moves, so shake never passes it. Rises with jitter.
- **min_cutoff / beta** — One Euro smoothing. Shaky hands get a lower cutoff.
- **dwell_time / dwell_radius** — how long the point must hold, and how much
  wobble restarts it. Rises with jitter.
- **palm** — your hand's normalized size at the calibrated distance. The ring
  size is `18 px × (distance_ratio ** 0.85)`, clamped to 2.4×, so it grows as
  you step back (the OS pointer itself cannot resize).

## Applying it to the tracker (one 3-line patch, by whoever owns app.py)

`profile.json` uses the tracker's own `Config` field names:

```python
from calibrate_profile import DEFAULT_PATH, apply_to_config, load_profile

apply_to_config(cfg, load_profile(DEFAULT_PATH))   # after cfg = Config(...)
```

`apply_to_config` imports nothing from `gesture_cursor`; it only sets attributes
that `Config` already has (`ref_palm` is skipped if the branch lacks it).

## Tests

`python -m pytest tests/test_calibration.py` — pure logic, no camera, no GUI.
