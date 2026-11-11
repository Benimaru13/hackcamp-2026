# AirTrack 0.1.0 — macOS usability test build

A first downloadable build of AirTrack for a small group of testers. AirTrack
uses your Mac's webcam to track your hand and control the pointer from a
distance — useful when your hands are wet, busy, or simply not near the keyboard.

This is a test build for feedback, not a finished product.

## What's in it

- The shipping `main` feature set: calibrated start (`start.py`), open-palm
  arming, pointing to move, hold-still to click, fist to release, two-finger
  scroll and desktop switching, the full-screen state border and spoken cues.
- Everything needed to run: Python, OpenCV, MediaPipe, NumPy, PyAutoGUI, the
  7.8 MB hand model and the three cue sounds. No Python install and no network
  connection is required to launch.
- No instruction panel and no startup/latency work from the `airtrack-desktop`
  branch — those are intentionally not part of this build.

## Download

`AirTrack-0.1.0-macos-arm64.zip`

- **Apple Silicon only** (M1/M2/M3/M4). It will not run on an Intel Mac.
- Requires macOS 14 or later.
- The build is unsigned, so the first launch needs right-click → **Open**, or
  **System Settings → Privacy & Security → Open Anyway**.

Full instructions, including Camera and Accessibility permissions, are in
`TESTER_GUIDE.md` in this folder.

## What we'd like to hear

Setup time and confusion, accidental moves/clicks, whether each gesture felt
reliable at your distance, and whether stopping control felt quick enough. The
feedback checklist at the end of `TESTER_GUIDE.md` lists the exact questions.
Please include your Mac model and macOS version.

## Privacy

Frames are processed in memory and discarded. Nothing is recorded, saved or
transmitted, and this build makes no network requests. The only file AirTrack
writes is its calibration profile in
`~/Library/Application Support/AirTrack/profile.json` when you ask it to save one.

## Known limitations

- Unsigned and not notarised: Gatekeeper warning on first launch.
- Apple Silicon only; an Intel build would have to be produced separately.
- Gesture tuning is still being measured with real people at 10 ft; some gestures
  may need tuning at your distance.
- macOS only in this build. Windows controls and packaging are not included.

## Verification

<!-- Fill in after the human run on a Mac. -->
- Built on: Apple Silicon, macOS 27.2 (26B131) — recorded by the build machine.
- Packaged smoke tests: bundle self-check and simulated calibration pass; see
  `packaging/README.md`.
- Still to check by hand: Gatekeeper on a downloaded copy, Camera and
  Accessibility prompts, real camera tracking, pointer movement, and the
  fist/Esc stop.
