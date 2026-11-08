"""calibrate.py -- the initial calibrator, run once where you actually sit.

    python calibrate.py               # with the camera
    python calibrate.py --no-preview  # terminal only
    python calibrate.py --simulate    # no camera: synthetic hand (rehearse/test)

Three measurements, and nothing to press: the wizard advances on its own timers,
so you can stand back and keep your hands in the air for the whole thing.

    1. raise an open palm      -- is the camera seeing a hand at all?
    2. hold still, pointing    -- 3.5 s: how much you shake, and your hand size

The shake and the hand size are caught in the same window on purpose. Two
separate four-second holds added four seconds of dead time between launching the
program and the cursor responding, and the palm length (wrist to middle knuckle)
is the same whether the fingertip is trembling or not -- so there is nothing to
gain by measuring it twice.

It writes profile.json next to this file unless --no-save is given. `python
start.py` runs this wizard on every start and drops straight into controlling the
computer when it finishes, keeping the measurement in memory so no file has to
exist for the calibrated run to be the real one.

The screen keeps the reading of the web mock: near-black canvas, one teal accent,
a status panel listing the three steps with a single large instruction, and a
countdown ring on your fingertip.
"""
from __future__ import annotations

import argparse
import math
import sys
import time

import cv2
import numpy as np

from calibrate_profile import DEFAULT_PATH, Profile, save_profile
from calibration_math import JitterMeter, estimate_tremor
from gesture_cursor import Config, estimate_distance_cm, hand_scale, is_arm_pose

ARM_SECONDS = 0.6
MEASURE_SECONDS = 3.5
WIN = "AirTrack calibration"

# --- the look ---------------------------------------------------------------
BG = (18, 14, 11)         # near-black with a faint blue cast (BGR)
PANEL = (31, 27, 23)
INK = (240, 238, 234)
MUTED = (150, 145, 138)
DIM = (70, 66, 61)
RULE = (46, 41, 36)
ACCENT = (212, 234, 94)   # teal
VIOLET = (250, 159, 176)
FONT = cv2.FONT_HERSHEY_DUPLEX

STEPS = (
    ("Raise an open palm", "camera check - stand about 3 m back"),
    ("Hold still, pointing", "shake + hand size, 3.5 s"),
)


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


# ------------------------------------------------------------------ drawing
def _arc(img, center, radius, fraction, color, thickness=3):
    """Progress ring, drawn as a polyline (cv2.ellipse's angle args are a trap)."""
    frac = max(0.0, min(float(fraction), 1.0))
    if frac <= 0.0:
        return
    n = max(3, int(48 * frac) + 3)
    pts = [(int(center[0] + radius * math.cos(-math.pi / 2 + 2 * math.pi * frac * i / n)),
            int(center[1] + radius * math.sin(-math.pi / 2 + 2 * math.pi * frac * i / n)))
           for i in range(n + 1)]
    cv2.polylines(img, [np.array(pts, dtype=np.int32)], False, color, thickness,
                  cv2.LINE_AA)


def _fit(img, w, h):
    """Letterbox an image into a w x h area: returns (canvas, x0, y0, scale)."""
    ih, iw = img.shape[:2]
    k = min(w / max(iw, 1), h / max(ih, 1))
    nw, nh = max(1, int(iw * k)), max(1, int(ih * k))
    out = np.full((h, w, 3), BG, np.uint8)
    x0, y0 = (w - nw) // 2, (h - nh) // 2
    out[y0:y0 + nh, x0:x0 + nw] = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_AREA)
    return out, x0, y0, k


def _check(img, x, y, color):
    pts = np.array([(x - 4, y), (x - 1, y + 3), (x + 5, y - 4)], dtype=np.int32)
    cv2.polylines(img, [pts], False, color, 2, cv2.LINE_AA)


def _wrap(text, width):
    lines, cur = [], ""
    for word in text.split():
        if len(cur) + len(word) + 1 > width:
            lines.append(cur)
            cur = word
        else:
            cur = (cur + " " + word).strip()
    if cur:
        lines.append(cur)
    return lines


def render(image, step, progress, hint, chips=None, landmarks=None, mirror=True):
    """The calibration screen: camera on the left, status panel on the right."""
    chips = chips or {}
    h, w = (image.shape[:2] if image is not None else (720, 1280))
    canvas = np.full((h, w, 3), BG, np.uint8)
    pw = max(300, min(int(w * 0.36), 430))
    vw = max(w - pw, 1)

    if image is not None:
        fitted, x0, y0, k = _fit(image, vw, h)
        canvas[:, :vw] = (fitted * 0.86).astype(np.uint8)
        src_h, src_w = image.shape[:2]
        if landmarks:
            pts = []
            for p in landmarks:
                fx = (1.0 - p.x) if mirror else p.x
                pts.append((x0 + int(fx * src_w * k), y0 + int(p.y * src_h * k)))
            for (px_, py_) in pts:
                cv2.circle(canvas, (px_, py_), 2, (250, 250, 250), -1, cv2.LINE_AA)
            cx, cy = pts[8]
            cv2.circle(canvas, (cx, cy), 36, ACCENT, 2, cv2.LINE_AA)
            _arc(canvas, (cx, cy), 36, progress, ACCENT, 3)
            cv2.circle(canvas, (cx, cy), 5, ACCENT, -1, cv2.LINE_AA)

    px0 = vw
    cv2.rectangle(canvas, (px0, 0), (w, h), PANEL, -1)
    cv2.line(canvas, (px0, 0), (px0, h), RULE, 1)
    pad = 26
    cv2.putText(canvas, "AIRTRACK", (px0 + pad, pad + 20), FONT, 0.66, ACCENT, 2,
                cv2.LINE_AA)
    cv2.putText(canvas, "CALIBRATION", (px0 + pad, pad + 44), FONT, 0.42, MUTED, 1,
                cv2.LINE_AA)

    y = pad + 100
    for i, (title, sub) in enumerate(STEPS):
        done, active = step > i, step == i
        mark = ACCENT if active else (VIOLET if done else DIM)
        cv2.circle(canvas, (px0 + pad + 13, y - 5), 13, mark,
                   -1 if (active or done) else 1, cv2.LINE_AA)
        if done:
            _check(canvas, px0 + pad + 13, y - 5, BG)
        else:
            num = str(i + 1)
            (tw, th), _ = cv2.getTextSize(num, FONT, 0.40, 1)
            cv2.putText(canvas, num, (px0 + pad + 13 - tw // 2, y - 5 + th // 2),
                        FONT, 0.40, INK if active else MUTED, 1, cv2.LINE_AA)
        cv2.putText(canvas, title, (px0 + pad + 38, y), FONT, 0.52,
                    INK if active else ((200, 196, 190) if done else MUTED), 1,
                    cv2.LINE_AA)
        cv2.putText(canvas, sub, (px0 + pad + 38, y + 18), FONT, 0.36, MUTED, 1,
                    cv2.LINE_AA)
        y += 58

    y += 10
    cv2.line(canvas, (px0 + pad, y - 14), (w - pad, y - 14), RULE, 1)
    for line in _wrap(hint, 26)[:3]:
        cv2.putText(canvas, line, (px0 + pad, y + 10), FONT, 0.58, INK, 1, cv2.LINE_AA)
        y += 26

    cy = h - 88
    for key, value in chips.items():
        text = f"{key}  {value}"
        (tw, th), _ = cv2.getTextSize(text, FONT, 0.40, 1)
        cv2.rectangle(canvas, (px0 + pad, cy - th - 8),
                      (px0 + pad + tw + 20, cy + 8), (44, 39, 34), -1, cv2.LINE_AA)
        cv2.rectangle(canvas, (px0 + pad, cy - th - 8),
                      (px0 + pad + tw + 20, cy + 8), (60, 55, 49), 1, cv2.LINE_AA)
        cv2.putText(canvas, text, (px0 + pad + 10, cy), FONT, 0.40, INK, 1,
                    cv2.LINE_AA)
        cy -= 32

    by = h - 30
    cv2.rectangle(canvas, (px0 + pad, by), (w - pad, by + 6), (52, 47, 42), -1)
    span = max((w - pad) - (px0 + pad), 1)
    filled = int(span * max(0.0, min(progress, 1.0)))
    if filled > 0:
        cv2.rectangle(canvas, (px0 + pad, by), (px0 + pad + filled, by + 6), ACCENT, -1)
    cv2.putText(canvas, "nothing to press  -  Esc cancels", (px0 + pad, by - 12),
                FONT, 0.34, MUTED, 1, cv2.LINE_AA)
    return canvas


def render_done(image, profile):
    """The card shown for a moment after the third measurement."""
    h, w = (image.shape[:2] if image is not None else (720, 1280))
    if image is not None:
        fitted, _, _, _ = _fit(image, w, h)
        canvas = (fitted * 0.30).astype(np.uint8)
    else:
        canvas = np.full((h, w, 3), BG, np.uint8)
    cx = w // 2
    ty = h // 2 - 60
    rows = (
        ("Calibrated", ty, 1.15, ACCENT, 2),
        ((f"{profile.tremor_hz:.1f} Hz tremor   -   {profile.tremor_px:.1f} px   -   "
          f"{profile.jitter_score}/100 steady" if profile.tremor_hz > 0 else
          f"{profile.jitter_px:.1f} px of shake   -   {profile.jitter_score}/100 steady"),
         ty + 46, 0.52, INK, 1),
        (f"dwell {profile.dwell_time:.2f} s   -   min speed {profile.min_speed:.2f}"
         f"   -   {profile.distance_ft:.1f} ft", ty + 76, 0.46, MUTED, 1),
        ("Taking control of your computer...", ty + 126, 0.52, INK, 1),
    )
    for text, y, scale, color, thick in rows:
        (tw, _), _ = cv2.getTextSize(text, FONT, scale, thick)
        cv2.putText(canvas, text, (cx - tw // 2, y), FONT, scale, color, thick,
                    cv2.LINE_AA)
    return canvas


# ------------------------------------------------------------------ wizard
def make_source(camera=0, model=None, width=1280, height=720, simulate=False,
                distance_m=3.0):
    """The frame source, exposed so start.py can keep it open after measuring."""
    return _Sim(distance_m) if simulate else _Camera(camera, model, width, height)


def run_calibration(camera=0, model=None, simulate=False, out_path=DEFAULT_PATH,
                    preview=True, width=1280, height=720, distance_m=3.0,
                    save=True, source=None, keep_open=False):
    """Run the wizard and return the profile (None if cancelled).

    `save=False` keeps the measurement in memory only: start.py measures on
    every run and hands the profile straight to the tracker, so writing a file
    is a convenience (--save), never a requirement.

    `source` + `keep_open` are how the camera survives the handover: reopening a
    webcam costs a second or two and sometimes takes two tries, so start.py
    passes the source it already has and takes it back still open.
    """
    src = source if source is not None else make_source(
        camera, model, width, height, simulate, distance_m)
    show = preview and not simulate
    cfg = Config()
    meter = JitterMeter()
    palms = []
    samples = []        # (t, x_px, y_px) of the fingertip, for the tremor estimate
    phase = "arm"
    phase_start = 0.0
    arm_since = None
    last_lm = None
    last_image = None
    step_index = {"arm": 0, "measure": 1}

    if show:
        cv2.namedWindow(WIN, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(WIN, 1040, 585)
        try:
            cv2.setWindowProperty(WIN, cv2.WND_PROP_TOPMOST, 1)
        except Exception:
            pass
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
                hint = "Raise an open palm toward the camera. Stand about 3 m back."
                if progress >= 1.0:
                    phase, phase_start = "measure", now
                    meter.reset()
                    print("[1/2] hand found")
            else:
                # One window does both jobs: the fingertip gives the tremor, the
                # wrist-to-knuckle span gives the distance. Nothing is asked of
                # the user beyond holding still, which is the point.
                if has_hand:
                    sx, sy = lm[8].x * width, lm[8].y * height
                    meter.push(sx, sy)
                    samples.append((now, sx, sy))
                    palms.append(hand_scale(lm))
                progress = min((now - phase_start) / MEASURE_SECONDS, 1.0)
                hint = "Hold still and keep pointing - measuring your hand."
                if progress >= 1.0:
                    break

            if show and last_image is not None:
                chips = {}
                if phase == "measure":
                    chips["jitter"] = f"{meter.rms:.1f} px   {meter.score}/100"
                    if last_lm is not None:
                        chips["hand"] = f"{hand_scale(last_lm) * 100:.1f}% of frame"
                if last_lm is not None:
                    dist = estimate_distance_cm(last_lm, width, cfg) / 30.48
                    if dist > 0:
                        chips["distance"] = f"{dist:.1f} ft"
                cv2.imshow(WIN, render(last_image, step_index[phase], progress,
                                       hint, chips, last_lm))
                if (cv2.waitKey(1) & 0xFF) in (27, ord("q")):
                    print("Cancelled.")
                    src.close()
                    return None

        palm = float(np.median(palms)) if palms else 0.0375
        tremor = estimate_tremor(samples)
        dist_cm = estimate_distance_cm(last_lm, width, cfg) if last_lm is not None else 0.0
        distance_ft = dist_cm / 30.48 if dist_cm > 0 else 10.0
        profile = Profile.from_measurement(palm=palm, jitter_px=meter.rms,
                                           distance_ft=distance_ft, tremor=tremor)
        print(f"[2/2] {tremor.describe()}  -  hand {palm * 100:.2f}% of frame "
              f"at {distance_ft:.1f} ft")
        if save:
            save_profile(profile, out_path)
            print(f"\nSaved {out_path}\n  {profile.summary()}")
        else:
            print(f"\nMeasured, not written to disk ('--save' keeps it)\n"
                  f"  {profile.summary()}")

        if show and last_image is not None:
            for _ in range(15):          # flash the card ~0.3 s, then hand over
                cv2.imshow(WIN, render_done(last_image, profile))
                if (cv2.waitKey(20) & 0xFF) in (27, ord("q")):
                    break
        return profile
    finally:
        if not keep_open:
            src.close()
        if show:
            cv2.destroyAllWindows()


def main(argv=None):
    ap = argparse.ArgumentParser(description="Measure your hand, save profile.json")
    ap.add_argument("--camera", type=int, default=0)
    ap.add_argument("--model", default=None)
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=720)
    ap.add_argument("--out", default=DEFAULT_PATH)
    ap.add_argument("--save", dest="save", action="store_true", default=True,
                    help="keep the measurement in profile.json (this is the default)")
    ap.add_argument("--no-save", dest="save", action="store_false",
                    help="measure without writing anything to disk")
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
                           distance_m=args.distance, save=args.save)
    return 0 if prof else 1


if __name__ == "__main__":
    sys.exit(main())
