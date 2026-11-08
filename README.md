# AirTrack

Touch-free control of a laptop from across the room: the webcam watches your
hand, and a few deliberate gestures move the mouse and click.

Built for the hands-occupied case — you are washing dishes, your hands are wet,
or you are just not within reach of the keyboard.

```
python app.py                # run it; raise an open palm to take control
```

---

## What works today

| Piece | Status |
| --- | --- |
| Hand tracking from the webcam | working (MediaPipe HandLandmarker, Tasks API) |
| Long-range tracking (~10 ft) | auto-zoom: the crop follows the hand so the hand fills ~55% of the model input at 1 m and at 4 m, plus a tile scan to acquire a far hand; needs a real 3 m camera test |
| Cursor movement, distance independent | working, unit tested, measured |
| Shake / jitter rejection | working, unit tested, measured |
| Click | only with the pointing hand: hold it still ~2 s, unit tested |
| Arming / releasing control | working: raised open palm to arm, fist to release |
| State feedback | full-screen click-through halo (PyObjC, macOS) + HUD in the preview window |
| Aiming reticle | grows with camera distance while the pointing hand is live (HUD only) |
| Real system cursor + click | PyAutoGUI (macOS + Windows) |
| Two-finger vertical, held | scrolls up/down, one wheel step every 0.15 s after a 0.2 s hold, ACTIVE only |
| Sideways thumb, held 0.75 s | sends ctrl+← / ctrl+→ (previous / next space), ACTIVE only |
| Volume / media keys | not in the MVP |

---

## Gestures

| Pose | Where | What happens |
| --- | --- | --- |
| 🖐 Open palm, raised: four fingers up, thumb out, hand held up ~0.5 s | ARMED | takes control (becomes ACTIVE) |
| ☝️ Index finger only | ACTIVE | moves the cursor |
| ☝️ Index finger, held still ~2 s | ACTIVE | one click, where it settled; move away to click again |
| ✊ Fist, held ~0.35 s | ACTIVE | releases control (back to ARMED) |
| ✌️ Two fingers, pointing up or down, held | ACTIVE | scrolls that way (a wheel step every 0.15 s, after a 0.2 s hold) |
| 👍 Thumb straight out to one side, other fingers curled, held ~0.75 s | ACTIVE | sends ctrl+← / ctrl+→ (previous / next space) |
| — Esc / `q` / Ctrl-C | any time | quits, control released |

Hovering is the only click, and it needs no extra pose: aim, stop moving, and after
~2 s it clicks **once**, where the cursor is. To click again you have to move the
hand (and so the cursor) away from that spot -- staying still never fires a second
click, and a couple of pixels of sensor noise are not a move. It runs only while the pointing pose is live, so
a fist, palm or pinch cancels the countdown instead of clicking on the way out of a
gesture.

**Why the open palm, after trying everything else?** The arming gesture has failed
in three ways, and this is the compromise that actually works on a demo table.
The **open palm** was too *common*: it turns up in ordinary desk posture and armed
the app by accident. The **"O" ring** and then the **thumbs up** were too
*strict*: both are thumb-versus-finger geometry, and at 3 m in a dim room the thumb
is a handful of pixels. They read as a fist, armed with one hand but not the other,
and turned the whole thing into a coin flip. The demo values a gesture that always
works over one that can never happen by accident, so the palm is back -- with one
cheap guard that costs nothing at distance.

`is_arm_pose()` asks for two things:

1. an **open palm**: all four fingers extended, thumb held away from the index
   finger -- so the pointing hand, a pinch, a fist and the two-finger V can never
   take control (`test_palm_and_pinch_never_overlap`, `test_point_does_not_arm`,
   `test_fist_does_not_arm`);
2. the hand **held up** (`palm_upright()`): the middle knuckle at least 0.35
   palm-lengths above the wrist. A palm raised to the camera is ~1.0; a hand
   resting flat on the desk, fingers pointing away, is ~0 and can never arm
   (`test_flat_palm_does_not_arm`).

Nothing here measures the thumb against anything, which is the part that collapsed
at 10 ft, and nothing depends on handedness -- left and right read identically, so
both thumbs are gone from the pipeline entirely. Taking control suppresses clicks
for one cooldown, so the frame that arms never also clicks
(`test_arming_palm_never_clicks`). The click is still a *still pointing hand*, so
no other pose can fire one.

**Why a held thumb for the switch?** Two earlier swipes failed for the same
reason: a swipe is a *stroke*, and a stroke has a return. Firing on the angle of
the two-finger V fired with the hand standing still. Firing on sideways travel
then fired on the return stroke as well — the hand comes back to where it started
within a second, so one swipe became two commands, or the opposite one if the
first was missed. A **hold** has nothing to misread: thumb straight out to the
left or right, other fingers curled, held 0.75 s, one command. After that the
hand has to drop the pose and a 1 s cooldown has to pass, so leaving the thumb up
cannot repeat and putting your hand back cannot fire anything. It is built out of
two big distances from the wrist (how far the thumb reaches, how sideways it
sits), not fine joint angles, which makes it the one gesture here that gets
*easier* to hit when you are deliberate. Because the pose is also a curled fist,
`classify_pose()` reads the thumb before the fist — otherwise the switch would
release control halfway through its own hold.

### Interaction states

```
            palm held up 0.5 s                  fist held 0.35 s
   OFF  ---------------------->  ARMED  <------------------------->  ACTIVE
  (camera       (amber halo,    (cursor        (green halo,
   released)     "watching")      untouched)     gestures control the cursor)
                                   ^
                                   |  hand gone > 1.2 s  (safety timeout)
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
and not looking at the halo: `sounds/activated.wav` plays when an open palm
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

1. **The hand is tiny at 10 ft.** The detector resizes its input to a fixed size,
   so what decides whether a hand is findable is how much of that input it fills:
   about **10% at 3 m** in a whole 720p frame, against **30% at 1 m**. The same
   gesture gets harder the further you stand. `tracker.py` therefore **auto-zooms**:
   `zoom.py` plans a square crop just big enough to hold the hand, the crop is
   upscaled and *that* is what the model gets, so the hand fills the same ~55% of
   the input at 1 m and at 4 m. The crop follows the hand and is held unchanged
   while the hand rests in its middle, so the zoom does not shiver. While nothing
   is tracked the frame is cut into overlapping tiles and one tile per frame is
   tried at full upscale, which is how a hand too small for a whole-frame detection
   gets acquired in the first place; the whole frame stays as the last resort.
   Landmarks are mapped back to full-frame coordinates, so the mirrored preview and
   the cursor mapping behave exactly as before. `python simulate.py focus` prints
   the numbers, and the HUD shows `zoom: 3.9x  hand 55% of crop` next to the crop
   rectangle -- literally what the model is looking at.
2. **Distance changes sensitivity.** Every position and threshold is converted to
   **palm-lengths** (wrist → middle knuckle, ~9 cm). The same 15 cm hand sweep
   therefore moves the cursor the same number of pixels at 1 m and at 3 m.
3. **Bad light must not look like a missing hand.** In a dim room `tracker.py`
   brightens the crop it feeds the model (a gamma curve aimed at mid-grey, preview
   untouched), and the tracked box always falls back to a full-frame scan, so a
   hand that leaves the box is not dropped for a frame.
4. **A shaking hand must not move the cursor or click.** The fingertip is
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
python -m unittest discover -s tests -v   # 86 tests, no camera needed
python simulate.py                        # measured behaviour + a tuning table
python simulate.py gestures               # palm → point → hover click → fist → palm
python simulate.py switch                 # thumb hold: when it fires, and no repeat
python simulate.py scroll                 # two-finger scroll: up vs down cadence
python simulate.py focus                  # auto-zoom: hand share of the model input, 1-4 m
python simulate.py cursor                 # aiming reticle size vs distance
```

The tests cover: pose classification at 1 m and 3 m (including a rotated hand),
two-finger direction at 1 m and 3 m (and that no other pose triggers it), the
raised palm arming and a flat palm never doing so, a point and a fist never arming,
the arming frame never clicking, arming only after the hold time, the arm
cooldown after a release, the lost-hand safety release, the same sweep moving the
cursor the same distance near and far, no cursor drift from a shaky still hand, a
2 s point hover clicking once where it settled, staying put never clicking twice,
palm/fist/pinch never clicking, and dropping the pointing pose cancelling a
half-finished dwell. The screen switch is tested on its own: a held thumb fires
exactly once in each direction at 1 m, 2 m and 3 m, it does not fire before
0.75 s, no other pose can fire it, a held thumb never repeats, a direction flip
or a release restarts it, and a couple of dropped frames do not. Scroll is tested
the same way: up and down stream the same number of wheel steps, down works at all,
a reversal waits for its hold, no other pose scrolls, and a blink does not stop
the stream. The auto-zoom is tested as geometry, no camera involved: the planned
crop gives the hand the same share of the model input at 1, 1.5, 2, 3 and 4 m, it
stays square and inside the frame at the frame edges, it is reused unchanged while
the hand rests and re-centred when the hand leaves the middle, it resizes when the
hand changes distance, the upscale is capped, the scan tiles cover the frame with
the middle one first, and a far hand ends up several times larger in the model
input than a whole-frame scan would make it. The reticle is covered too: bigger
with distance, clamped at both ends, monotonic, and configurable.

What is **not** verified yet: an actual person at 10 ft with a real webcam. The
tracking pipeline runs on this machine (camera + model + frames), but the
accuracy numbers above come from synthetic landmarks, so the 10 ft claim still
needs a camera test with lighting, framing and a person. Tune `--min-speed` there
and record what you see.

---

## Known issues

- **The screen switch is a hold, not a swipe.** Thumb out to one side, other
  fingers curled, held 0.75 s; the hand must drop the pose before it can fire
  again. If it feels strict at 10 ft, lower `Config.swipe_hold`; if it fires while
  you are just holding your hand, raise it. `Config.swipe_cooldown` is the 1 s
  pause afterwards.
- **Scroll follows macOS natural scrolling.** If the page moves the opposite way
to the direction you point, flip the sign of `pyautogui.scroll(...)` in `app.py`
(one line). The HUD now shows the direction the app currently reads
(`scroll: up`/`down`), which is the fastest way to tell a detection problem from a
sign problem.
- **The magnifier is the HUD reticle, not the system pointer.** macOS owns the
  pointer and it cannot be resized; what grows with distance is the ring drawn at
  the fingertip in the preview -- `cursor_radius_px()` in `gesture_cursor.py`,
  tuned by `cursor_near_px` / `cursor_far_px` in `Config`. It only appears while
  the pointing hand is live in ACTIVE, so it never covers anything otherwise.
- **A thumb held out is also a curled fist.** When the thumb does not reach far
  enough from the wrist, `thumb_direction()` gives up and the pose falls through to
  `fist`, which releases control mid-attempt -- which is why the screen-switch
  gesture is being replaced with a two-finger one. Until then, hold the thumb
  clearly out to the side; `THUMB_SIDE_REACH` in `gesture_cursor.py` is how far it
  has to reach.
- **Dim rooms still cost accuracy.** `tracker.py` brightens the frame handed to the
  model and always retries a full-frame scan, but a detector is still a detector:
  face a lamp, not a window, during the demo.
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
| `tracker.py` | camera + MediaPipe HandLandmarker + the auto-zoom pipeline |
| `zoom.py` | auto-zoom planning: follow-crop around the hand, acquire-scan tiles (pure maths, no camera) |
| `edge_glow.py` | the full-screen click-through state halo (PyObjC/AppKit, macOS; optional, falls back to the preview border) |
| `app.py` | the demo: wiring, PyAutoGUI control, HUD and screen halo |
| `fake_hand.py` | synthetic hands (tests and simulation) |
| `simulate.py` | camera-free simulator and measurement harness |
| `voice.py` | plays the spoken cue WAVs (stdlib only; never raises) |
| `generate_sounds.py` | one-time ElevenLabs text-to-speech generator for `sounds/*.wav` |
| `sounds/` | generated cue clips, see `sounds/README.md` |
| `tests/test_voice.py` | WAV wrapping and silent-fallback tests |
| `tests/test_gesture_cursor.py` | unit tests |
| `tests/test_zoom.py` | auto-zoom geometry tests |
| `tests/test_magnifier.py` | distance-scaled reticle tests |
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
