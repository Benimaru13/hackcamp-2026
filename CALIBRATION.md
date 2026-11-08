# Calibration (additive — touches none of the tracker)

`gesture_cursor.py`, `app.py`, `tracker.py` and `simulate.py` are the other
branches' code and are **not modified here**. This adds the missing first step:
a calibrator that measures *your* hand at *your* distance, and a copy of the
tracker loop (`app_calibrated.py`) that runs on the result.

## Run it

- **`python start.py`** — measure this hand, then control the computer. This is
  the normal one: measuring is the default, so a weak hand and a shaking hand
  each get numbers from *today*.
- `python start.py --dry-run --verbose` — safe first run, pointer untouched.
- `python start.py --save` — keep this measurement in `profile.json`.
- `python start.py --use-saved` — reuse that file instead of measuring.
- `python calibrate.py` — the wizard on its own (writes `profile.json`).
- `python calibrate.py --simulate --no-preview` — no camera, synthetic hand.

Two timed steps, nothing to press (so it works standing back from the laptop):

| Step | Gesture | Measures |
|---|---|---|
| 1 | raise an open palm | that the camera sees a hand at all |
| 2 | hold still, pointing, 3.5 s | your shake (Hz and px) **and** your hand size |

The shake and the hand size come from the same window on purpose: the palm
length (wrist to middle knuckle) does not change while the fingertip trembles,
and a second four-second hold was four seconds of waiting for nothing.

**No gap between measuring and controlling.** The wizard's camera is kept open
and handed to the tracker, so nothing reopens a webcam at the moment the cursor
is supposed to appear. Measured end to end: **~4.1 s** (0.6 s arm + 3.5 s
measuring) from launch to controlling, against ~10 s before.

## The look

- **The measurement window is a mirror**, the same convention as the tracker's
  preview: the picture is flipped *and* the landmark dots are mapped with it. The
  dots used to be flipped on their own, which put every landmark on the wrong
  side of the frame — the fingertip ring sat on the empty half of the image while
  the real hand had no dots on it at all.
- **The tracker's preview eases to the hand** (`ViewFollow` in `zoom.py`) instead
  of cutting to the detected box: it zooms in from the whole frame, glides when
  the hand moves, and eases back out when the hand is lost — the Centre Stage
  feel. The easing runs on real time, so a 15 fps camera pans at the same speed as
  a 60 fps one and a dropped frame cannot teleport the picture. Only a crop built
  around the hand is followed; a scan tile is not, or the window whipped across
  the frame before settling. See it without a camera: `python simulate.py follow`.

## What the numbers do

- **tremor_hz / tremor_px** — the dominant periodic component of a still hand,
  found with a coarse DFT over the hold-still window (2–12 Hz). A steady hand
  reports `0 Hz`; white noise is not promoted to a tremor.
- **jitter_px / jitter_score** — RMS of frame-to-frame acceleration of the raw
  point. 100 = rock steady.
- **min_speed** — the hand must exceed this (palm-lengths/s) before the cursor
  moves, so shake never passes it. Starts at the team default (1.00) and rises
  with the measured tremor, capped at 2.20.
- **min_cutoff / beta** — One Euro smoothing. A tremor lowers the cutoff and
  *caps beta*, so a fast wobble cannot reopen the filter the way it does at the
  default beta.
- **dwell_time / dwell_radius** — how long the point must hold, and how much
  wobble restarts it. Both rise with tremor.
- **arm_hold / swipe_hold** — how long the palm and the thumb must be held to
  arm and to switch screens. Both rise with tremor.
- **Every setting is floored at the team's own default**, so calibrating can
  never make control twitchier than the branch it came from; a steady hand gets
  the defaults back.
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
`start.py` already does exactly this, in memory, on every launch.

## Tests

`python -m pytest tests/test_calibration.py tests/test_start.py tests/test_app_calibrated.py`
— pure logic, no camera, no GUI. `tests/test_hud.py` belongs to the tracker
branch and needs `mediapipe` installed.
