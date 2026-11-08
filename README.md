# AirTrack

Touch-free control of a laptop from across the room: the webcam watches your
hand, and a few deliberate gestures move the mouse and click.

Built for the hands-occupied case — you are washing dishes, your hands are wet,
or you are just not within reach of the keyboard.

```
python app.py                # run it; curl the hand into an "O" to take control
```

---

## What works today

| Piece | Status |
| --- | --- |
| Hand tracking from the webcam | working (MediaPipe HandLandmarker, Tasks API) |
| Long-range tracking (~10 ft) | ROI crop + upscale implemented; needs a real 3 m camera test |
| Cursor movement, distance independent | working, unit tested, measured |
| Shake / jitter rejection | working, unit tested, measured |
| Click | pinch (default) or dwell, unit tested |
| Arming / releasing control | working: "O" ring to arm, fist to release |
| State feedback | glowing border + HUD in the preview window |
| Real system cursor + click | PyAutoGUI (macOS + Windows) |
| Volume / media / app switching | not in the MVP |

---

## Gestures

| Pose | Where | What happens |
| --- | --- | --- |
| 👌 "O": whole hand curled into a ring, thumb tip on a fingertip, held ~0.5 s | ARMED | takes control (becomes ACTIVE) |
| ☝️ Index finger only | ACTIVE | moves the cursor |
| 🤏 Pinch (thumb to index) | ACTIVE | clicks once (needs a pointing frame just before it) |
| ✊ Fist, held ~0.35 s | ACTIVE | releases control (back to ARMED) |
| — Esc / `q` / Ctrl-C | any time | quits, control released |

There is also `--click dwell`: instead of pinching, hold the pointing hand still
for ~2 s and the cursor snaps to where it settled and clicks.

**Why a ring, and not the "OK" sign or the "heart"?** All three are thumb + index,
and two of them are gestures people make by accident. `is_o_shape()` therefore asks
for the whole hand to close into a circle, and checks three things:

1. the thumb tip meets a fingertip (`loop_gap` < `O_RATIO`, 0.30 palm-lengths) --
   the ring is actually closed;
2. **every** finger is curled -- so the "OK" sign (three fingers up) and the
   straight-index click pinch never take control (`test_ok_gesture_does_not_arm`);
3. the loop sits more than `O_LOOP_PALM` (0.40 palm-lengths) from the index
   knuckle -- a fist has the same curled fingers but keeps the thumb *down on the
   knuckles*, ~0.2 palm-lengths away, so the stop gesture can never arm
   (`test_ring_and_fist_never_overlap`).

Because a closed ring is also four curled fingers, the ring is classified before
the fist, and the knuckle distance is what keeps the two apart at 10 ft. Taking
control also suppresses clicks for one cooldown, so the ring that armed the app
never fires a click on the frame it succeeds (`test_arming_ring_never_clicks`). An
infinity sign is still a nice idea, but it is a motion, not a pose, and motion
gestures are harder to keep from firing accidentally.

### Interaction states

```
            "O" ring held 0.5 s                 fist held 0.35 s
   OFF  ---------------------->  ARMED  <------------------------->  ACTIVE
  (camera       (amber border,  (cursor        (green pulsing border,
   released)     "watching")      untouched)     gestures control the cursor)
                                   ^
                                   |  hand gone > 2 s  (safety timeout)
```

- **OFF** — nothing is read. Space toggles ARMED ↔ OFF while the preview is open.
- **ARMED** — tracking runs, the cursor is never touched, an amber border and a
  "watching" label show the app is alive.
- **ACTIVE** — a green pulsing border and a live pose/distance readout show that
  gestures are controlling the computer. This is the "it is armed and dangerous"
  cue; the screen-edge glow idea is here, but drawn around the preview window
  rather than the whole desktop.
- **Immediate stop** — any of: fist held, Esc/q, Ctrl-C, or PyAutoGUI failsafe
  (slam the pointer into a screen corner). Nothing keeps controlling the machine
  after the app exits.

---

## Running it

```bash
cd hackcamp-2026
python -m venv .venv && source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

The first run downloads the 7.8 MB hand model into `models/` (git-ignored). No
video, frames or landmarks ever leave the machine, and nothing is written to disk.

**macOS permissions** (both are required, both are asked for on first use):

1. *Camera*: System Settings → Privacy & Security → Camera → allow your terminal
   (or Python/VS Code) — otherwise the camera opens but every frame is black.
2. *Accessibility*: System Settings → Privacy & Security → Accessibility → allow
   the same app — without it PyAutoGUI moves nothing, silently.

PyAutoGUI on recent macOS versions also needs the terminal to be the *active*
application on the first run.

**Windows** needs no permissions for the cursor; only a free camera.

### Safe ways to try it

```bash
python app.py --dry-run        # detects and shows the HUD, never touches the cursor
python app.py --no-preview     # no window (for a headless machine / CI-ish smoke test)
python app.py --dry-run --no-preview --frames 60   # 60 frames then exit + summary
python simulate.py             # no camera at all (see below)
```

Use `--dry-run` for the first setup pass: stand at 10 ft, watch the border and the
`hand: … ft` readout, and confirm the states change — without anything clicking.

---

## Spoken cues (ElevenLabs)

The app can announce what it is doing, which matters when you are across the room
and not looking at the border: `sounds/activated.wav` plays when the "O" ring
takes control, `sounds/released.wav` when control is released.

The audio is generated once and played from disk, so the demo itself needs no API
key, no network and no extra Python package:

```bash
copy .env.example .env                # then paste your key / voice id into .env
python generate_sounds.py             # writes sounds/activated.wav, sounds/released.wav
python generate_sounds.py --list-voices   # find a voice id you like
```

- The key and voice id live in `.env` (git-ignored): `ELEVENLABS_API_KEY` and
  optional `ELEVENLABS_VOICE_ID`. A real environment variable wins over the file;
  `--voice-id` wins over both.
- Change the wording in `CLIPS` in `generate_sounds.py`, then re-run with `--force`.
- `--mute` silences the cues; missing WAVs are silently skipped, so the app always runs.
- Commit the generated WAVs if the demo machine should need no key: playback is
  local, so no request leaves the machine at run time.

## Tuning for a distance / shaky hands

Live keys in the preview window:

| Key | Effect |
| --- | --- |
| `+` / `-` | cursor speed (screen widths per palm-length of hand travel) |
| `[` / `]` | how much hand speed is needed before the cursor moves (shake threshold) |
| `space` | ARMED ↔ OFF |
| `Esc` / `q` | quit |

CLI equivalents: `--speed`, `--min-speed`, `--click pinch|dwell`, `--no-zoom`.

If the cursor **shakes**: raise `]` (`--min-speed`). If it feels **sticky or slow
to start**: lower it. If the cursor is **too fast to aim**: lower `-` (`--speed`).

---

## Why it works far away, and why it does not shake

Three separate problems, solved separately:

1. **The hand is tiny at 10 ft.** In a 720p frame the hand is only ~30–60 px tall,
   and the detector starts missing it. `tracker.py` keeps a box around the last
   hand, crops it, and scales that crop to 512 px before detection, then maps the
   landmarks back to full-frame coordinates. When the hand is lost it rescans the
   whole frame (downscaled, so it is cheap) to reacquire.
2. **Distance changes sensitivity.** Every position and threshold is converted to
   **palm-lengths** (wrist → middle knuckle, ~9 cm). The same 15 cm hand sweep
   therefore moves the cursor the same number of pixels at 1 m and at 3 m.
3. **A shaking hand must not move the cursor or click.** The fingertip is
   smoothed *in palm-lengths* (One Euro filter) and then gated on **hand speed**,
   not on frame-to-frame jump size: a shaking hand has near-zero *average* speed,
   so it never crosses the threshold, while a deliberate move crosses it
   immediately. A pinch freezes the cursor completely, and the click needs a
   pointing frame within the previous 0.5 s, so gesticulating while pinched does
   not click.

These are measured, not asserted — `simulate.py` runs synthetic hands with
pixel-level detector noise (2 px per landmark per frame, which is roughly what
MediaPipe produces on a still hand):

```
still hand, 2 px detector noise, 5 s held:
  1 m (palm 11.2% of frame): drift=0.0 px, accidental clicks=0
  3 m (palm  3.8% of frame): drift=0.0 px, accidental clicks=0

same 15 cm hand sweep (15 cm/s), near vs far:
  1 m: cursor travelled 720 px
  3 m: cursor travelled 720 px     difference: 0.0 %
```

Worst case across the three random seeds used while picking the smoothing
constants: **under 20 px of drift over 10 s at 3 m** (1.4% of a 1440 px screen),
with the cursor still covering the full screen for a normal hand sweep.

---

## Verifying it

```bash
python -m unittest discover -s tests -v   # 39 tests, no camera needed
python simulate.py                        # measured behaviour + a tuning table
python simulate.py gestures               # "O" → point → pinch → fist → "O"
```

The tests cover: pose classification at 1 m and 3 m (including a rotated hand),
the ring never reading as a fist and vice versa, the "OK" sign and an open palm
never arming, the arming ring never clicking, a fist never clicking, arming only
after the hold time, the arm
cooldown after a release, the lost-hand safety release, the same sweep moving the
cursor the same distance near and far, no drift and no false clicks from a shaky
still hand, pinch = exactly one click, pinch never clicking without a pointing
context, pinch freezing the cursor, and dwell clicking once and snapping to its
anchor.

What is **not** verified yet: an actual person at 10 ft with a real webcam. The
tracking pipeline runs on this machine (camera + model + frames), but the
accuracy numbers above come from synthetic landmarks, so the 10 ft claim still
needs a camera test with lighting, framing and a person. Tune `--min-speed` there
and record what you see.

---

## Files

| File | What it is |
| --- | --- |
| `gesture_cursor.py` | all interaction logic: poses, states, mapping, smoothing, clicks. No camera, no OS calls — this is the part anyone can test anywhere. |
| `tracker.py` | camera + MediaPipe HandLandmarker + long-range ROI zoom |
| `app.py` | the demo: wiring, PyAutoGUI control, HUD and edge glow |
| `fake_hand.py` | synthetic hands (tests and simulation) |
| `simulate.py` | camera-free simulator and measurement harness |
| `voice.py` | plays the spoken cue WAVs (stdlib only; never raises) |
| `generate_sounds.py` | one-time ElevenLabs text-to-speech generator for `sounds/*.wav` |
| `sounds/` | generated cue clips, see `sounds/README.md` |
| `tests/test_voice.py` | WAV wrapping and silent-fallback tests |
| `tests/test_gesture_cursor.py` | unit tests |
| `mediapipe-setup.py` | camera sanity check (does the webcam open at all?) |
| ~~`gesture_detector.py`, `test_run.py`~~ | teammate prototype of a dwell-click detector, removed from the working tree (it used `mp.solutions.hands`, which mediapipe 1.2.2 no longer provides). Recoverable from the `gesture-control` commit if needed. |

Teammates without a camera or a Mac can do all the logic, UI and reliability work
against `simulate.py` + the tests; only the macOS-specific permission/control
path has to be checked on a MacBook.

---

## Privacy

Frames are processed in memory and discarded. Nothing is recorded, stored or
transmitted; the only network access is the one-time model download. The app
reads the camera only while it is running, and stops on exit.

---

## Credits

- [MediaPipe Hand Landmarker](https://ai.google.dev/edge/mediapipe/solutions/vision/hand_landmarker) for hand landmarks.
- [PyAutoGUI](https://pyautogui.readthedocs.io/) for cursor and click control.
- Inspired by [jayant1211/gesture-controlled-mouse](https://github.com/jayant1211/gesture-controlled-mouse); the One Euro filter and dwell-click ideas came from that family of projects, the state machine and distance handling here are ours.
- One Euro filter: Casiez, Roussel, Vogel (2012).

## Next steps

- Test and tune at 10 ft with a real camera, and write down the reliability numbers.
- A full-screen edge glow overlay (always-on-top, click-through) instead of the
  preview border.
- Media keys (play/pause, volume) for the "I am washing dishes" case — this is
  the most valuable non-cursor control and needs no mouse precision.
- Verify the macOS Accessibility path on the demo MacBook.
- Ask five people which gestures they actually prefer; the pose set here is a
  starting point, not a conclusion.
