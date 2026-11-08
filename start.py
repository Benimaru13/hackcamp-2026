"""start.py -- one command: calibrate this hand, then control the computer.

    python start.py               # measure every time, then take control
    python start.py --use-saved   # reuse profile.json instead of measuring
    python start.py --save        # keep this run's measurement for --use-saved
    python start.py --dry-run     # never touch the pointer (safe first run)
    python start.py --simulate    # wizard rehearsal, then stop

Calibration runs on every start unless --use-saved is passed. That is deliberate:
the numbers describe the hand as it is right now, and a shaky hand is not
identical from one session to the next. Nothing is written to disk unless --save
is given -- the measurement is handed to the tracker in memory, so no
profile.json has to exist for the calibrated run to be the real one.

The work is in calibrate.py (the wizard) and app_calibrated.py (the tracker's
loop, duplicated on this branch so the team's app.py stays untouched); this file
only decides which runs and in what order.
"""
from __future__ import annotations

import argparse
import os
import sys

import app_calibrated as control_app
import calibrate as wizard
from calibrate_profile import DEFAULT_PATH, load_profile


# The wizard's camera, kept open across the handover: reopening a webcam costs a
# second or two and sometimes fails outright, exactly when the cursor is supposed
# to appear. Nothing else in this file is stateful.
_HANDOFF = {}


def _calibrate(args):
    source = wizard.make_source(camera=args.camera, simulate=args.simulate,
                                width=args.width, height=args.height)
    profile = wizard.run_calibration(camera=args.camera, simulate=args.simulate,
                                     out_path=args.profile,
                                     preview=not args.no_preview,
                                     width=args.width, height=args.height,
                                     save=getattr(args, "save", False),
                                     source=source, keep_open=True)
    if profile is not None:
        _HANDOFF["tracker"] = getattr(source, "tracker", None)
    return profile


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
    return control_app.main(argv, profile=profile,
                            tracker=_HANDOFF.get("tracker"))


def run_sequence(args, calibrate_fn=None, control_fn=None, exists=os.path.exists,
                 load=load_profile):
    """Calibrate, then hand straight over. Returns an exit code.

    A cancelled wizard (Esc) returns 1 and never starts controlling: handing the
    computer over after a half-finished measurement is the one thing worse than
    handing it over with default numbers.
    """
    calibrate_fn = calibrate_fn or _calibrate
    control_fn = control_fn or _control
    profile_path = getattr(args, "profile", None) or DEFAULT_PATH

    profile = None
    if getattr(args, "use_saved", False) and exists(profile_path):
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
        print("   Measure this hand instead:  python start.py\n")

    if getattr(args, "simulate", False):
        print("Simulated measurement only. Run 'python start.py' without "
              "--simulate to control the computer.")
        return 0
    return control_fn(args, profile)


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="AirTrack: calibrate your hand, then control the computer")
    ap.add_argument("--profile", default=DEFAULT_PATH,
                    help="path of the profile --use-saved reads and --save writes")
    ap.add_argument("--use-saved", action="store_true",
                    help="skip the wizard and reuse profile.json from a past run")
    ap.add_argument("--save", action="store_true",
                    help="write this run's measurement to profile.json")
    ap.add_argument("--recalibrate", action="store_true",
                    help="accepted for older shortcuts: measuring is the default now")
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
