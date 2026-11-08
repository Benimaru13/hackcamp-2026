# Calibration

AirTrack measures *your* hand at *your* distance before it controls anything, then
tunes itself from that measurement. The wizard lives in `calibrate.py`, the saved
result in `calibrate_profile.py`, the maths in `calibration_math.py`, and the
control loop that consumes it in `app_calibrated.py`. `start.py` decides the order:
measure, then hand the same open camera to the tracker.

Nothing here needs a mouse, a keyboard or an API key.

## Run it

| Command | What happens |
|---|---|
| `python start.py` | Measure this hand, then control the computer. **The normal one.** |
| `python start.py --dry-run --verbose` | Safe first run: pointer untouched, state printed twice a second. |
| `python start.py --save` | Keep this measurement in `profile.json` for later. |
| `python start.py --use-saved` | Reuse `profile.json` instead of measuring. |
| `python start.py --simulate` | Rehearse the wizard on a synthetic hand, then stop. |
| `python calibrate.py` | The wizard alone. |
| `python calibrate.py --simulate --no-preview` | No camera, no window: good for CI or a smoke test. |
| `python calibrate.py --no-save` | Measure without writing `profile.json`. |

Measuring is the default on every start, and nothing is written to disk unless
`--save` is passed: the measurement is handed to the control loop **in memory**.
(`python calibrate.py` on its own is the exception: it writes `profile.json`
unless you pass `--no-save`.)

## The two timed steps

The wizard advances on its own timers, so you stand back and keep your hand up —
there is nothing to press until the very end.

| Step | Gesture | Time | Measures |
|---|---|---|---|
| 1 | Raise an open palm | 0.6 s (`ARM_SECONDS`) | that the camera can see a hand at all |
| 2 | Hold still, pointing | 3.5 s (`MEASURE_SECONDS`) | your shake **and** your hand size |

The shake and the hand size come from the same window on purpose: the palm length
(wrist → middle knuckle) does not change while the fingertip trembles, and a second
four-second hold was four seconds of waiting for nothing. If the hand is lost during
step 2 the window restarts, so a measurement is never taken across a gap.

## The "Calibrated" card

When step 2 finishes, the wizard shows a summary card with a **CONFIRM** button
(`render_done()`): tremor/shake, the tuned dwell and minimum speed, and the
calibrated distance. It stays up until you acknowledge it — click CONFIRM, or press
Enter/Space — and Esc/`q` still cancels. This is the deliberate pause between
"measured" and "in control": the next window can move the real mouse pointer, so it
does not open behind your back.

## No gap between measuring and controlling

The wizard's camera is kept open and passed to the tracker, so nothing reopens a
webcam at the moment the cursor is supposed to appear:

- `run_calibration(..., source=src, keep_open=True)` leaves the `_Camera` (and its
  `HandTracker`) alive;
- `start.py` stashes it in `_HANDOFF["tracker"]`;
- `app_calibrated.main(profile=…, tracker=…)` accepts both, so the profile is applied
  in memory and the camera is never released.

Measured end to end on the demo machine: **~4.1 s** (0.6 s arm + 3.5 s measuring)
from launch to controlling. That figure is a documented stopwatch reading from a
development run, not a benchmark this repository re-times.

## What the wizard shows

- **The measurement window is a mirror**, the same convention as the tracker's
  preview: the picture is flipped *and* the landmark dots are mapped with it. The
  dots used to be flipped on their own, which put every landmark on the wrong side
  of the frame — the fingertip ring sat on the empty half of the image while the
  real hand had no dots on it at all.
- **Only this frame's landmarks are drawn.** At 3 m a frame is missed regularly, and
  drawing the last detected set left stale dots on a moving hand.
- The right-hand panel lists both steps, the live jitter score, hand size as a share
  of the frame, and the estimated distance, with a progress bar along the bottom.

## What the numbers do

- **tremor_hz / tremor_px** — the dominant periodic component of a still hand, found
  with a coarse DFT over the hold-still window (2–12 Hz in 0.25 Hz steps). A steady
  hand reports `0 Hz`; white noise is not promoted to a tremor.
- **jitter_px / jitter_score** — RMS of frame-to-frame acceleration of the raw point
  (measured before any filtering). `100` = rock steady, ~85 at 1 px, ~66 at 2.5 px,
  ~37 at 6 px, so a still hand reads in the 80s–100. **The score is computed from
  this same px value**, which is why the two numbers on the card always agree. The
  tremor RMS (the fingertip's spread around its own mean over the hold) also counts
  your arm slowly drifting across those 3.5 s, so it is reported, never scored —
  scoring it read a motionless hand as ~30/100.
- **palm** — your hand's normalized size at the calibrated distance (median over the
  window). The fingertip ring is `18 px × (distance_ratio ** 0.85)`, clamped to 0.85–2.4×,
  so it grows as you step back (the OS pointer itself cannot resize).
- **Tuned settings** — `min_speed` rises with tremor (1.00 → 2.20), the One Euro
  `min_cutoff` drops (0.70 → 0.30) and `beta` is capped (1.20 → 0.30) so a fast
  wobble cannot reopen the filter, and the holds lengthen: dwell 2.00 → 3.60 s,
  dwell radius 0.20 → 0.40 palm-lengths, arm hold 0.55 → 1.60 s, switch hold
  0.75 → 2.20 s.
- **Every setting is floored at the team's own default**, so calibrating can never
  make control twitchier than the defaults; a steady hand gets exactly the defaults
  back.

## How it is applied

`profile.json` uses the tracker's own `Config` field names, and
`apply_to_config()` only sets attributes that already exist (duck-typed, so the
modules stay uncoupled):

```python
from calibrate_profile import DEFAULT_PATH, apply_to_config, load_profile

apply_to_config(cfg, load_profile(DEFAULT_PATH))   # after cfg = Config(...)
```

The screen-switch hold was called `swipe_hold` before it became `switch_hold`;
`_FIELD_ALIASES` sets whichever name the `Config` actually has, so an old profile
keeps working. Every field is clamped on load (`_LIMITS`), so a hand-edited or
stale file can never make the cursor unusable.

`app_calibrated.py` also checks, once at startup, that the OS really accepts
synthetic mouse events (`pointer_test()`): on macOS a missing *Accessibility*
grant lets PyAutoGUI import and report a screen size while dropping every event.
`--no-pointer-test` skips it.

## Tests

```bash
.venv/bin/python -m pytest tests/test_calibration.py tests/test_start.py \
    tests/test_app_calibrated.py -q
```

Pure logic: no camera, no GUI, no mediapipe. `tests/test_hud.py` needs `mediapipe`
installed and belongs to the tracker.

## Branch note

`main` is the version that ships and keeps the CONFIRM card. `airtrack-desktop` is
the feature branch and replaces the card with a modal instruction manual that
teaches the gestures before control starts; that panel (`instruction_panel.py`) is
**not** part of `main`.
