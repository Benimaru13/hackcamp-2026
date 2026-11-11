"""airtrack_entry.py -- the executable inside AirTrack.app.

This is deliberately thin. It exists to do the things that only matter once the
app is a bundle that someone double-clicks, and then hands control to the same
``start.main()`` that ``python start.py`` uses:

1. **Self-check** (``--self-check``) -- prove that the model, sounds, native
   libraries and PyObjC made it into the bundle without opening the camera.
   This is the first command to ask a tester for when a build misbehaves.
2. **First-run permission guidance** -- macOS attributes Camera and
   Accessibility grants to the ``.app``, not to a terminal. Accessibility has no
   automatic prompt from PyAutoGUI, so the app would otherwise run and silently
   never move the cursor. We check it and point the tester at the right pane.
3. **A visible failure** -- launched from Finder there is no terminal, so an
   unhandled exception would look like "nothing happened". Errors are logged to
   Application Support and shown in a native alert.

Camera access cannot be pre-checked without AVFoundation; the packaged
``Info.plist`` carries ``NSCameraUsageDescription``, so the first
``cv2.VideoCapture`` makes macOS show its own prompt.

Every step here is defensive: the app must still start if a check itself fails.
"""
from __future__ import annotations

import argparse
import os
import platform
import subprocess
import sys
import traceback
from pathlib import Path

# Running the entry point from a checkout (`python packaging/airtrack_entry.py`)
# needs the repo root importable. In a bundle PyInstaller has already collected
# the modules, and sys.path must not be touched.
if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

APP_NAME = "AirTrack"
APP_VERSION = "0.1.0"
BUNDLE_ID = "com.airtrack.airtrack"

REQUIRED_SOUNDS = ("start_message", "activated", "released")


def _accessibility_trusted():
    """Whether this process may post synthetic mouse events, or None if unknown.

    Uses the ApplicationServices C API through ctypes. PyObjC's Quartz package
    does not expose AXIsProcessTrusted, and adding a separate PyObjC framework
    just for this check would be another dependency to bundle.
    """
    if sys.platform != "darwin":
        return None
    try:
        import ctypes

        framework = ("/System/Library/Frameworks/ApplicationServices.framework/"
                     "ApplicationServices")
        lib = ctypes.cdll.LoadLibrary(framework)
        lib.AXIsProcessTrusted.restype = ctypes.c_bool
        return bool(lib.AXIsProcessTrusted())
    except Exception:
        return None


def _show_permission_alert() -> None:
    """Explain the missing grant in a dialog, because Finder launches have no
    terminal to print to. Uses osascript so it works even if PyObjC is missing.
    """
    script = (
        'display alert "AirTrack needs Accessibility permission" message '
        '"Before AirTrack can move the pointer, it must be allowed in System '
        'Settings > Privacy & Security > Accessibility. That pane opens next: '
        'switch on AirTrack, then relaunch it.\\n\\nThe camera prompt is '
        'separate -- choose Allow so AirTrack can see your hand." '
        'buttons {"OK"} default button "OK"'
    )
    try:
        subprocess.run(["osascript", "-e", script], check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def _open_accessibility_settings() -> None:
    """Open the exact System Settings pane the tester needs.

    `open` is part of macOS; the URL scheme is the documented way to deep-link
    into a Privacy pane. Failure here is non-fatal -- the printed instructions
    still name the path.
    """
    url = ("x-apple.systempreferences:com.apple.preference.security"
           "?Privacy_Accessibility")
    try:
        subprocess.run(["open", url], check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def preflight_permissions(open_settings: bool = True) -> None:
    """Explain the two required grants before the first gesture is attempted."""
    if sys.platform != "darwin":
        return

    print("macOS permissions: AirTrack needs Camera (to see your hand) and "
          "Accessibility (to move the pointer).")
    trusted = _accessibility_trusted()
    if trusted is None:
        print("  Accessibility: could not be checked automatically. If the "
              "pointer never moves, grant AirTrack Accessibility in System "
              "Settings > Privacy & Security.")
        return
    if trusted:
        print("  Accessibility: granted.")
        return

    print("  Accessibility: NOT granted. The camera will work, but the pointer "
          "will not move until AirTrack is enabled in System Settings > "
          "Privacy & Security > Accessibility.")
    if open_settings:
        import resources

        # Only the packaged app gets the dialog; from a terminal the printed
        # guidance is enough and a modal would interrupt scripted runs.
        if resources.is_frozen():
            _show_permission_alert()
        print("  Opening that pane now: switch on AirTrack, then relaunch.")
        _open_accessibility_settings()


def self_check() -> int:
    """Verify the bundle without a camera, a pointer or a network connection."""
    import resources

    failures: list[str] = []

    def report(label: str, ok: bool, detail: str = "") -> None:
        print(f"  [{'OK' if ok else 'FAIL'}] {label}{(': ' + detail) if detail else ''}")
        if not ok:
            failures.append(label)

    print(f"{APP_NAME} {APP_VERSION} self-check")
    print(f"  packaged: {resources.is_frozen()}")
    print(f"  executable: {sys.executable}")
    print(f"  machine: {platform.machine()}   macOS: {platform.mac_ver()[0] or 'unknown'}")

    # --- assets -----------------------------------------------------------
    model = resources.resource_path("models", "hand_landmarker.task")
    size_mb = model.stat().st_size / (1024 * 1024) if model.is_file() else 0.0
    report("hand model present", model.is_file() and size_mb > 1.0,
           f"{model} ({size_mb:.1f} MB)")

    sounds_dir = resources.resource_path("sounds")
    found = sorted(p.stem for p in sounds_dir.glob("*.wav")) if sounds_dir.is_dir() else []
    missing = [name for name in REQUIRED_SOUNDS if name not in found]
    report("spoken cues present", not missing,
           f"{sounds_dir} -> {', '.join(found) or 'none'}")

    # --- libraries --------------------------------------------------------
    try:
        import cv2
        import mediapipe
        import numpy
        import pyautogui  # noqa: F401  (imported for the bundle, not used here)
        report("cv2 / mediapipe / numpy / pyautogui import", True,
               f"opencv {cv2.__version__}, mediapipe {mediapipe.__version__}, "
               f"numpy {numpy.__version__}")
    except Exception as exc:
        report("cv2 / mediapipe / numpy / pyautogui import", False, repr(exc))

    try:
        from AppKit import NSApplication  # noqa: F401
        from Quartz import CALayer  # noqa: F401
        report("PyObjC (full-screen halo) import", True)
    except Exception as exc:
        # The app deliberately falls back to the preview border when PyObjC is
        # unavailable, so this is reported but never treated as fatal.
        print(f"  [warn] PyObjC unavailable ({exc!r}); the halo falls back to "
              f"the preview border.")

    # --- the model actually loads ----------------------------------------
    try:
        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision

        options = vision.HandLandmarkerOptions(
            base_options=mp_python.BaseOptions(model_asset_path=str(model)),
            running_mode=vision.RunningMode.IMAGE,
            num_hands=1,
        )
        landmarker = vision.HandLandmarker.create_from_options(options)
        landmarker.close()
        report("MediaPipe loads the bundled model", True)
    except Exception as exc:
        report("MediaPipe loads the bundled model", False, repr(exc))

    # --- writable state ---------------------------------------------------
    try:
        import calibrate_profile

        folder = Path(calibrate_profile.DEFAULT_PATH).parent
        probe = folder / ".airtrack-write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        report("profile folder writable", True, str(folder))
    except Exception as exc:
        report("profile folder writable", False, repr(exc))

    trusted = _accessibility_trusted()
    print(f"  [{'note' if trusted else 'warn'}] Accessibility permission: "
          f"{'granted' if trusted else ('not granted' if trusted is False else 'unknown')}")

    if failures:
        print(f"\n{len(failures)} check(s) failed: {', '.join(failures)}")
        return 1
    print("\nAll bundle checks passed.")
    return 0


def _report_fatal(exc: BaseException) -> None:
    """Log a crash and show it, because a Finder launch has no terminal."""
    detail = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    log_path = None
    try:
        import resources

        log_path = resources.user_data_dir() / "airtrack-error.log"
        log_path.write_text(detail, encoding="utf-8")
    except Exception:
        log_path = None

    print(detail, file=sys.stderr)
    message = (f"Details were saved to:\n{log_path}" if log_path
               else "No log file could be written.")
    script = (
        'display alert "AirTrack stopped unexpectedly" message '
        f'"{message}" as critical'
    )
    try:
        subprocess.run(["osascript", "-e", script], check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def main(argv=None) -> int:
    # parse_known_args: the rest of the command line belongs to start.py. The
    # only flags this entry point owns are the two below.
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--self-check", action="store_true")
    parser.add_argument("--skip-permission-check", action="store_true")
    own, passthrough = parser.parse_known_args(argv)

    if own.self_check:
        return self_check()

    # A simulated rehearsal is non-interactive (the build script's smoke test,
    # a headless check), so it must not open dialogs or steal focus.
    if "--simulate" not in passthrough:
        preflight_permissions(open_settings=not own.skip_permission_check)

    try:
        import start

        return start.main(passthrough)
    except SystemExit:
        raise
    except BaseException as exc:          # noqa: BLE001 - last line of defence
        _report_fatal(exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
