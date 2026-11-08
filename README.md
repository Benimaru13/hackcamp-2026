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
| Click | only with the pointing hand: hold it still ~2 s, unit tested |
| Arming / releasing control | working: "O" ring to arm, fist to release |
| State feedback | full-screen click-through halo (PyObjC, macOS) + HUD in the preview window |
| Real system cursor + click | PyAutoGUI (macOS + Windows) |
| Two-finger vertical swipe | scrolls up/down, one wheel step per 0.15 s, ACTIVE only |
| Two-finger sideways swipe | sends ctrl+← / ctrl+→; currently fires in every state (see Known issues) |
| Volume / media keys | not in the MVP |

---

## Gestures

| Pose | Where | What happens |
| --- | --- | --- |
| 👌 "O": whole hand curled into a ring, thumb tip on a fingertip, held ~0.5 s | ARMED | takes control (becomes ACTIVE) |
| ☝️ Index finger only | ACTIVE | moves the cursor |
| ☝️ Index finger, held still ~2 s | ACTIVE | one click, where it settled; move away to click again |
| ✊ Fist, held ~0.35 s | ACTIVE | releases control (back to ARMED) |
| ✌️ Two fingers, pointing up/down | ACTIVE | scrolls (one wheel step every 0.15 s) |
| ✌️ Two fingers, sideways | any state | sends ctrl+← / ctrl+→ (see Known issues) |
| — Esc / `q` / Ctrl-C | any time | quits, control released |

Hovering is the only click, and it needs no extra pose: aim, stop moving, and after
~2 s it clicks **once**, where the cursor is. To click again you have to move the
hand (and so the cursor) away from that spot -- staying still never fires a second
click, and a couple of pixels of sensor noise are not a move. It runs only while the pointing pose is live, so
a fist, palm or pinch cancels the countdown instead of clicking on the way out of a
gesture.

**Why a ring, and not the "OK" sign or the "heart"?** All three are thumb + index,
and two of them are gestures people make by accident. `is_o_shape()` therefore asks
for the whole hand to close into a circle, and checks three things:

1. the thumb tip meets a fingertip (`loop_gap` < `O_RATIO`, 0.30 palm-lengths) --
   the ring is actually closed;
2. **every** finger is curled -- so the "OK" sign (three fingers up) and an open
   palm never take control (`test_ok_gesture_does_not_arm`,
   `test_open_palm_does_not_arm`);
3. the loop sits more than `O_LOOP_PALM` (0.40 palm-lengths) from the index
   knuckle -- a fist has the same curled fingers but keeps the thumb *down on the
   knuckles*, so the stop gesture can never arm
   (`test_ring_and_fist_never_overlap`).

Because a closed ring is also four curled fingers, the ring is classified before
the fist, and the knuckle distance is what keeps the two apart at 10 ft. Taking
control also suppresses clicks for one cooldown, so the ring that armed the app
never fires a click on the frame it succeeds (`test_arming_ring_never_clicks`).
The click is still a *still pointing hand*, so no other pose can fire one. An
infinity sign is still a nice idea, but it is a motion, not a pose, and motion
gestures are harder to keep from firing accidentally.

### Interaction states

```
            "O" ring held 0.5 s                 fist held 0.35 s
   OFF  ---------------------->  ARMED  <------------------------->  ACTIVE
  (camera       (amber halo,    (cursor        (green halo,
   released)     "watching")      untouched)     gestures control the cursor)
                                   ^
                                   |  hand gone > 2 s  (safety timeout)
```

- **OFF** — nothing is read. Space toggles ARMED ↔ OFF while the preview is open.
- **ARMED** — tracking runs, the cursor is never touched, an amber halo around the
  whole screen and a "watching" label in the preview show the app is alive.
- **ACTIVE** — a green halo around the whole screen plus a live pose/distance
  readout show that gestures are controlling the computer. This is the "it is armed
  and dangerous" cue, and it covers the desktop rather than the camera preview.
- **The halo is its own window** (`edge_glow.py`): a borderless AppKit window per
  display, transparent, always-on-top and click-through (PyObjC, macOS only), so
  clicks pass straight through to whatever is underneath. `--no-glow` turns it off
  and falls back to drawing the glow inside the preview window; off macOS, or
  without PyObjC, that fallback happens automatically.
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

`requirements.txt` includes PyObjC on macOS for the full-screen halo; if it is
missing the app still runs and draws the glow inside the preview instead.

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

Use `--dry-run` for the first setup pass: stand at 10 ft, watch the halo and the
`hand: … ft` readout, and confirm the states change — without anything clicking.

---

## Spoken cues (ElevenLabs)

The app can announce what it is doing, which matters when you are across the room
and not looking at the halo: `sounds/activated.wav` plays when the "O" ring
takes control, `sounds/released.wav` when control is released.

The audio is generated once and played from disk, so the demo itself needs no API
key, no network and no extra Python package:

There is no `.env.example` in the repo any more (it was removed after a real key was
committed in it). Create `.env` yourself -- it is git-ignored:

```bash
printf 'ELEVENLABS_API_KEY=sk_your_key\nELEVENLABS_VOICE_ID=21m00Tcm4TlvDq8ikWAM\n' > .env
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

CLI equivalents: `--speed`, `--min-speed`, `--no-zoom`, `--no-glow`.

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
   smoothed (One Euro filter), its displacement converted to palm-lengths, then
   gated on **hand speed**, not on frame-to-frame jump size: a shaking hand has
   near-zero *average* speed, so it never crosses the threshold, while a
   deliberate move crosses it immediately. The click is a *still* pointing hand:
   the countdown runs on the cursor (which the speed gate holds still) and fires
   at 2 s, only while that pose is live, and a move only restarts it if the hand
   really travelled -- so gesticulating, shaking, a flickered pose frame or a
   dropped pose never clicks.

These are measured, not asserted — `simulate.py` runs synthetic hands with
pixel-level detector noise (2 px per landmark per frame, which is roughly what
MediaPipe produces on a still hand):

```
still pointing hand, 2 px detector noise, 5 s held (one hover click is the gesture):
  1 m (palm 11.2% of frame): drift=0.0 px, hover clicks=1
  3 m (palm  3.8% of frame): drift=0.0 px, hover clicks=1

same 15 cm hand sweep (15 cm/s), near vs far:
  1 m: cursor travelled 710 px
  3 m: cursor travelled 709 px     difference: 0.1 %
```

Same measurement over 8 noise seeds at 1 m, 2 m and 3 m, 10 s of a still hand
each: **0.0 px of drift** in all 24 runs, and every one of them clicked **exactly
once, at ~2.0 s**. That matters because the click is a hold: a cursor that crept
into the dwell radius on its own would either restart the countdown or fire a
second time, so stillness is judged on the cursor *and* corroborated by hand
travel before any of it counts as a move.

---

## Verifying it

```bash
python -m unittest discover -s tests -v   # 45 tests, no camera needed
python simulate.py                        # measured behaviour + a tuning table
python simulate.py gestures               # palm → point → hover click → fist → palm
```

The tests cover: pose classification at 1 m and 3 m (including a rotated hand),
two-finger direction at 1 m and 3 m (and that no other pose triggers it),
the ring never reading as a fist and vice versa, the "OK" sign and an open palm
never arming, the arming ring never clicking, a fist never clicking, arming only
after the hold time, the arm
cooldown after a release, the lost-hand safety release, the same sweep moving the
cursor the same distance near and far, no cursor drift from a shaky still hand, a
2 s point hover clicking once where it settled, staying put never clicking twice,
palm/fist/pinch never clicking, and dropping the pointing pose cancelling a
half-finished dwell.

What is **not** verified yet: an actual person at 10 ft with a real webcam. The
tracking pipeline runs on this machine (camera + model + frames), but the
accuracy numbers above come from synthetic landmarks, so the 10 ft claim still
needs a camera test with lighting, framing and a person. Tune `--min-speed` there
and record what you see.

---

## Known issues

- **The horizontal two-finger swipe ignores the state machine.** It runs whenever a
  hand is visible, so `ctrl+←` / `ctrl+→` can fire while the app is ARMED or OFF. It
  needs the same ACTIVE gate the vertical scroll already has.
- **App switching is not the same on macOS and Windows.** `ctrl+←` / `→` switches
  Spaces on macOS and jumps a word on Windows; switching *apps* is ⌘-Tab on macOS and
  Alt-Tab on Windows, which the swipe does not send yet.
- **The AppKit halo is verified on a teammate's Mac only.** Click-through over
  full-screen apps and the pulsing border should be confirmed on the demo MacBook.

---

## Files

| File | What it is |
| --- | --- |
| `gesture_cursor.py` | all interaction logic: poses, states, mapping, smoothing, clicks. No camera, no OS calls — this is the part anyone can test anywhere. |
| `tracker.py` | camera + MediaPipe HandLandmarker + long-range ROI zoom |
| `edge_glow.py` | the full-screen click-through state halo (PyObjC/AppKit, macOS; optional, falls back to the preview border) |
| `app.py` | the demo: wiring, PyAutoGUI control, HUD and screen halo |
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
- Check the halo on the demo MacBook: click-through, on top of full-screen apps, and
  never stealing focus.
- Media keys (play/pause, volume) for the "I am washing dishes" case — this is
  the most valuable non-cursor control and needs no mouse precision.
- Verify the macOS Accessibility path on the demo MacBook.
- Ask five people which gestures they actually prefer; the pose set here is a
  starting point, not a conclusion.
