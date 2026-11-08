"""calibrate.py -- the initial calibrator, run once where you actually sit.

    python calibrate.py               # with the camera
    python calibrate.py --no-preview  # terminal only
    python calibrate.py --simulate    # no camera: synthetic hand (rehearse/test)

Three measurements, and nothing to press: the wizard advances on its own timers,
so you can stand back and keep your hands in the air for the whole thing.

    1. raise an open palm      -- is the camera seeing a hand at all?
    2. hold still for 4 s      -- how much your hand shakes (the jitter score)
    3. keep pointing for 4 s   -- how big your hand looks from here (reference)

It writes profile.json next to this file. AirTrack itself is the other branches'
code and is untouched here, so applying the profile there is a three-line change
-- see CALIBRATION.md.
"""
from __future__ import annotations

import argparse
import sys
import time

import cv2
import numpy as np

from calibrate_profile import DEFAULT_PATH, Profile, save_profile
from calibration_math import JitterMeter
from gesture_cursor import Config, estimate_distance_cm, hand_scale, is_arm_pose

ARM_SECONDS = 0.6
STILL_SECONDS = 4.0
REF_SECONDS = 4.0
WIN = "AirTrack calibration"


class _Camera:
    """Real webcam + MediaPipe, through the same tracker app.py uses."""

    def __init__(self, camera=0, model=None, width=1280, height=720):
        from tracker import DEFAULT_MODEL, HandTracker
        self.tracker = HandTracker(camera=camera, width=width, height=height,
                                   model=model or DEFAULT_MODEL)
        self.width, self.height = self.tracker.width, self.tracker.height

    def read(self):
        fr = self.tracker.read()
        return fr.landmarks, fr.image, time.monotonic()

    def close(self):
        self.tracker.close()


class _Sim:
    """Synthetic hand, so the whole wizard runs with no camera at all."""

    def __init__(self, distance_m=3.0, jitter_px=2.0):
        from fake_hand import FakeHand, palm_for_distance
        self.width = self.height = 1280
        self.hand = FakeHand(pose="palm", palm=palm_for_distance(distance_m),
                             jitter=jitter_px / 1280.0, seed=5)
        self.now = 0.0

    def read(self):
        self.now += 1.0 / 30.0
        return self.hand.landmarks(), None, self.now

    def close(self):
        pass


def _bar(image, progress, text, color=(90, 255, 120)):
    """Progress strip along the bottom: the only UI the wizard needs."""
    h, w = image.shape[:2]
    cv2.rectangle(image, (0, h - 96), (w, h), (24, 24, 24), -1)
    cv2.putText(image, text, (24, h - 60), cv2.FONT_HERSHEY_DUPLEX, 0.62,
                (235, 235, 235), 1, cv2.LINE_AA)
    cv2.rectangle(image, (24, h - 40), (w - 24, h - 24), (60, 60, 60), -1)
    filled = int((w - 48) * max(0.0, min(progress, 1.0)))
    if filled > 0:
        cv2.rectangle(image, (24, h - 40), (24 + filled, h - 24), color, -1)
    return image


def run_calibration(camera=0, model=None, simulate=False, out_path=DEFAULT_PATH,
                    preview=True, width=1280, height=720, distance_m=3.0):
    """Run the wizard, save the profile, and return it (None if cancelled)."""
    src = _Sim(distance_m) if simulate else _Camera(camera, model, width, height)
    show = preview and not simulate
    cfg = Config()
    meter = JitterMeter()
    palms = []
    phase = "arm"
    phase_start = 0.0
    arm_since = None
    last_lm = None
    last_image = None

    if show:
        cv2.namedWindow(WIN, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(WIN, 900, 520)
    print("Calibrating. Raise an open palm toward the camera, then keep still "
          "when asked.\nNothing to press: each step moves on by itself.\n")

    try:
        while True:
            lm, image, now = src.read()
            if image is not None:
                last_image = image
            has_hand = lm is not None and hand_scale(lm) > 1e-6
            if has_hand:
                last_lm = lm

            if phase == "arm":
                if has_hand and is_arm_pose(lm):
                    if arm_since is None:
                        arm_since = now
                else:
                    arm_since = None
                progress = (0.0 if arm_since is None
                            else min((now - arm_since) / ARM_SECONDS, 1.0))
                hint = "Raise an open palm toward the camera"
                if progress >= 1.0:
                    phase, phase_start = "still", now
                    meter.reset()
                    print("[1/3] hand found")
            elif phase == "still":
                if has_hand:
                    meter.push(lm[8].x * width, lm[8].y * height)
                progress = min((now - phase_start) / STILL_SECONDS, 1.0)
                hint = "Hold still - measuring how much your hand shakes"
                if progress >= 1.0:
                    phase, phase_start = "ref", now
                    palms.clear()
                    print(f"[2/3] jitter {meter.rms:.2f} px ({meter.score}/100)")
            else:
                if has_hand:
                    palms.append(hand_scale(lm))
                progress = min((now - phase_start) / REF_SECONDS, 1.0)
                hint = "Keep pointing at the screen - measuring your distance"
                if progress >= 1.0:
                    break

            if show and last_image is not None:
                cv2.imshow(WIN, _bar(last_image, progress, hint))
                if (cv2.waitKey(1) & 0xFF) in (27, ord("q")):
                    print("Cancelled.")
                    return None
    finally:
        src.close()
        if show:
            cv2.destroyAllWindows()

    palm = float(np.median(palms)) if palms else 0.0375
    dist_cm = estimate_distance_cm(last_lm, width, cfg) if last_lm is not None else 0.0
    distance_ft = dist_cm / 30.48 if dist_cm > 0 else 10.0
    profile = Profile.from_measurement(palm=palm, jitter_px=meter.rms,
                                       distance_ft=distance_ft)
    save_profile(profile, out_path)
    print(f"[3/3] reference hand size {palm * 100:.2f}% of frame at "
          f"{distance_ft:.1f} ft")
    print(f"\nSaved {out_path}\n  {profile.summary()}")
    print("\nNext: python app.py   (AirTrack itself is on your teammates branch)")
    return profile


def main(argv=None):
    ap = argparse.ArgumentParser(description="Measure your hand, save profile.json")
    ap.add_argument("--camera", type=int, default=0)
    ap.add_argument("--model", default=None)
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=720)
    ap.add_argument("--out", default=DEFAULT_PATH)
    ap.add_argument("--no-preview", action="store_true")
    ap.add_argument("--simulate", action="store_true",
                    help="synthetic hand, no camera (rehearse or test)")
    ap.add_argument("--distance", type=float, default=3.0,
                    help="with --simulate: pretend to stand this far away (m)")
    args = ap.parse_args(argv)
    prof = run_calibration(camera=args.camera, model=args.model,
                           simulate=args.simulate, out_path=args.out,
                           preview=not args.no_preview,
                           width=args.width, height=args.height,
                           distance_m=args.distance)
    return 0 if prof else 1


if __name__ == "__main__":
    sys.exit(main())
