"""start.py -- one command: calibrate if needed, then control the computer.

    python start.py                # calibrate once, then take control immediately
    python start.py --recalibrate  # measure again first
    python start.py --dry-run      # never touch the pointer (safe first run)
    python start.py --simulate     # wizard rehearsal, then stop

With a profile.json already saved it skips the wizard, so the second start is a
single step. The work is in calibrate.py (the wizard) and app_calibrated.py (the
tracker's loop, duplicated on this branch so the team's app.py stays untouched);
this file only decides which runs and in what order.
"""
from __future__ import annotations

import argparse
import os
import sys

import app_calibrated as control_app
import calibrate as wizard
from calibrate_profile import DEFAULT_PATH, load_profile


def _calibrate(args):
    return wizard.run_calibration(camera=args.camera, simulate=args.simulate,
                                  out_path=args.profile, preview=not args.no_preview,
                                  width=args.width, height=args.height)


def _control(args, profile):
    argv = ["--profile", args.profile]
    if args.dry_run:
        argv.append("--dry-run")
    if args.no_preview:
        argv.append("--no-preview")
    if args.verbose:
        argv.append("--verbose")
    if args.no_pointer_test:
        argv.append("--no-pointer-test")
    if args.camera:
        argv += ["--camera", str(args.camera)]
    return control_app.main(argv)


def run_sequence(args, calibrate_fn=None, control_fn=None, exists=os.path.exists,
                 load=load_profile):
    """Calibrate when needed, then hand straight over. Returns an exit code.

    A cancelled wizard (Esc) returns 1 and never starts controlling: handing the
    computer over after a half-finished measurement is the one thing worse than
    handing it over with default numbers.
    """
    calibrate_fn = calibrate_fn or _calibrate
    control_fn = control_fn or _control
    profile_path = getattr(args, "profile", None) or DEFAULT_PATH

    profile = None
    if not getattr(args, "recalibrate", False) and exists(profile_path):
        try:
            profile = load(profile_path)
        except Exception as exc:
            print(f"saved profile ignored ({exc})")

    if profile is None:
        profile = calibrate_fn(args)
        if profile is None:
            print("Calibration cancelled - nothing started.")
            return 1
        print("\nCalibrated. Taking control...\n")
    else:
        print(f"Using saved calibration: {profile.summary()}")
        print("   Measure again:  python start.py --recalibrate")
        print("   (VS Code: Run and Debug -> 'AirTrack: recalibrate')\n")

    if getattr(args, "simulate", False):
        print("Simulated measurement only. Run 'python start.py' without "
              "--simulate to control the computer.")
        return 0
    return control_fn(args, profile)


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="AirTrack: calibrate your hand, then control the computer")
    ap.add_argument("--profile", default=DEFAULT_PATH,
                    help="where profile.json lives (and is written)")
    ap.add_argument("--recalibrate", action="store_true",
                    help="measure again even if a profile exists")
    ap.add_argument("--camera", type=int, default=0)
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=720)
    ap.add_argument("--dry-run", action="store_true",
                    help="never move the real cursor")
    ap.add_argument("--no-preview", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--simulate", action="store_true",
                    help="run the wizard with a synthetic hand, then stop")
    ap.add_argument("--no-pointer-test", action="store_true")
    args = ap.parse_args(argv)
    return run_sequence(args)


if __name__ == "__main__":
    sys.exit(main())
