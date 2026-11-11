# macOS packaging (maintainer notes)

Goal: a tester downloads one file, double-clicks, and runs AirTrack without
installing Python or dependencies. This directory adds that packaging layer only —
gesture behaviour, controls, tests and the `start.py` development path are
unchanged from `main`.

## Files

| File | Purpose |
| --- | --- |
| `airtrack_entry.py` | What runs inside `AirTrack.app`: `--self-check`, first-run permission guidance, a visible error alert, then `start.main()`. |
| `airtrack.spec` | PyInstaller build definition: entry point, bundled model/sounds, PyObjC + MediaPipe collection, `Info.plist`. |
| `build_macos.sh` | Reproducible build: isolated build venv, pinned PyInstaller, arch + asset checks, packaged smoke tests, `ditto` archive. |
| `TESTER_GUIDE.md` | Short first-run instructions (Gatekeeper, Camera, Accessibility) and the feedback checklist. |
| `RELEASE_NOTES.md` | Draft release notes for the tester build. |

Supporting source changes (small, shared with development):

- `resources.py` (new) — one place that resolves bundled assets in a source
  checkout and inside the `.app`, plus the writable Application Support folder.
- `tracker.py` — `DEFAULT_MODEL` now uses `resources`; the bundled model means no
  first-run download. A missing bundle model falls back to a writable path.
- `voice.py` — `SOUND_DIR` resolves through `resources`, so the cue WAVs are found
  inside the bundle. Missing clips remain silent, as before.
- `calibrate_profile.py` — a packaged app saves `profile.json` in
  `~/Library/Application Support/AirTrack/` instead of inside the bundle (the
  bundle can be read-only, and App Translocation moves quarantined apps).

## Build

```bash
packaging/build_macos.sh
# or pin the interpreter:
PYTHON=/opt/homebrew/bin/python3.14 packaging/build_macos.sh
```

It creates `build/packaging-venv` (so your `.venv` is untouched), installs
`requirements.txt` + PyInstaller 6.22.3, downloads the 7.8 MB model into
git-ignored `models/` if needed, then produces:

```
dist/AirTrack.app
dist/AirTrack-0.1.0-macos-arm64.zip
```

`build/` and `dist/` are git-ignored. The archive is made with `ditto`, which
preserves the bundle structure and permissions.

## What the build verifies

`build_macos.sh` fails the build if any of these fail:

1. `Contents/MacOS/AirTrack` exists and every Mach-O file in the bundle matches
   the build architecture (`lipo -archs`).
2. `AirTrack --self-check` — model present and loadable by MediaPipe, all three
   cue WAVs present, cv2/mediapipe/numpy/pyautogui/PyObjC import, and the profile
   folder is writable.
3. `AirTrack --simulate` — a full calibration run on a synthetic hand, with no
   camera, no pointer and no window, then a clean exit.
4. The tester archive round-trip: extract the `.zip`, verify its code signature,
   then run checks 2 and 3 from the extracted copy — so the artifact that is
   actually downloaded is the one tested.

What the script cannot verify: the real camera, TCC prompts, the pointer
actually moving, and Gatekeeper on a downloaded copy. Those need a Mac with a
person in front of it — see the release checklist below.

### Result on the build machine (2026-11-11)

- Apple Silicon (arm64), macOS 27.2.1; Python 3.14.10; PyInstaller 6.22.3.
- `dist/AirTrack.app` is 325 MB and the tester archive is 127 MB; every Mach-O
  file in the bundle is arm64.
- The extracted archive passes `codesign --verify --deep --strict`, so its
  ad-hoc signature is complete and bound to `Info.plist`/resources.
- Self-check passed: model present (7.5 MB) and loaded by MediaPipe, all three
  cue sounds found, cv2/mediapipe/numpy/pyautogui/PyObjC imported, profile
  folder writable. Accessibility reported as not granted, as expected before a
  human grants it.
- `--simulate` completed a synthetic calibration and exited 0.
- `python start.py --simulate` still works from the checkout.
- The repo's pytest suite has one **pre-existing** failure on `main`
  (`test_hud.py::test_display_is_mirrored_when_enabled`); it reproduces on a
  clean `main` worktree and is unrelated to packaging. The other 131 tests pass.

One environment note: this checkout lives under iCloud-managed `Documents`, and
macOS's file provider re-attaches Finder/fileprovider xattrs to the `.app`
inside `dist/` even after `xattr -cr`. `codesign --verify` on that local copy
therefore reports "resource fork, Finder information… not allowed", although the
bundle is signed. The build stages and signs in `$TMPDIR` and makes the `.zip`
from there; the extracted archive verifies, which is what testers receive. Copy
the `.zip` or the `.app` to a non-synced folder (e.g. `/Applications`) before
re-checking its signature locally.

## macOS permissions: what the app actually does

- **Camera** — no pre-check API is bundled; macOS prompts on the first
  `cv2.VideoCapture`. `NSCameraUsageDescription` in `Info.plist` is required, or
  TCC terminates the app instead of prompting. The wording says video stays local.
- **Accessibility** — PyAutoGUI posts synthetic mouse events but never asks for
  permission, so without a grant the app runs and silently moves nothing. The
  packaged entry point checks `AXIsProcessTrusted()` (via ctypes, no new
  dependency), prints the result, and opens the Accessibility pane when the
  grant is missing. `app_calibrated.pointer_test()` remains the runtime proof:
  it moves the pointer 80 px and back and reports failure.
- Quitting and relaunching after granting Accessibility is required by macOS;
  the guide says so.

## Architectures

The pinned native wheels are arm64-only on macOS and carry their own floors
(`opencv-python` macOS 13, `numpy` macOS 14). Consequences:

- This build is **Apple Silicon only**, minimum macOS 14 (also encoded as
  `LSMinimumSystemVersion`).
- A universal2 build is not possible with these dependencies. For Intel testers,
  build separately on an Intel Mac (or an Intel CI runner) and do not reuse this
  artifact.
- `build_macos.sh` names the archive with `uname -m`, so two builds will not
  overwrite each other.

## Release checklist (none of these were executed)

1. Build on each target architecture, on that architecture's hardware.
2. Run the packaged app on a clean Mac account: Gatekeeper, Camera, Accessibility,
   calibration, pointer movement, fist/quit stop.
3. Fill in the verified-by/known-issues section of `RELEASE_NOTES.md`.
4. Publish `dist/AirTrack-<version>-macos-<arch>.zip` as a Release asset and
   include the SHA-256 printed by the build script.
5. Tell testers the architecture in the download name and link
   `TESTER_GUIDE.md`.

The build is **ad-hoc signed but not Developer ID signed or notarised**, which is
why testers see Gatekeeper. The explicit `codesign --sign -` step exists because
PyInstaller's own ad-hoc signature left `Sealed Resources=none`; without it, a
downloaded copy can be reported as "damaged" rather than unidentified.
Signing/notarising properly needs an Apple Developer ID and must be done before a
wider release; it is out of scope for this usability test.

## Development path is unchanged

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python start.py        # calibrated path, downloads the model once if needed
python app.py --dry-run
```

`resources.py` returns the repository directory when not frozen, so
`profile.json`, `models/` and `sounds/` behave exactly as documented in the main
README.

## Known limitations of this build

- No code signing or notarisation; Gatekeeper needs right-click → Open.
- Apple Silicon only, macOS 14+.
- `dist/AirTrack.app` is large (OpenCV, MediaPipe, NumPy and the model); that is
  the cost of "no Python install".
- The existing GitHub Actions workflow tests on Ubuntu only. A macOS packaging
  job is a sensible follow-up but is not part of this change.
