"""AirTrack demo entry point.

    python app.py                 # run it, open palm to take control
    python app.py --dry-run       # detect + show the HUD, never touch the cursor

The window shows the camera (mirrored, so it reads like a mirror), the current
state as a glowing border, the pose it recognises, and an approximate distance.
Esc / q quits, space switches between ARMED and OFF. Spoken cues (if the WAVs
from generate_sounds.py are in sounds/) announce activation and release.
"""
from __future__ import annotations

import argparse
import math
import sys
import time

import cv2
import numpy as np

from gesture_cursor import Config, ControlState, CursorController
from voice import Voice

WIN = "AirTrack"
COLORS = {
    ControlState.ARMED: (0, 176, 255),     # amber
    ControlState.ACTIVE: (90, 255, 120),   # green
    ControlState.OFF: (120, 120, 120),     # grey
}


def _glow(frame, color, strength=1.0):
    """Screen-edge glow: a soft pulsing border that says which state we are in."""
    h, w = frame.shape[:2]
    layer = np.zeros_like(frame)
    for i in range(5):
        m = 4 + i * 5
        cv2.rectangle(layer, (m, m), (w - 1 - m, h - 1 - m), color, 3, cv2.LINE_AA)
    glow = cv2.GaussianBlur(layer, (0, 0), 9)
    return cv2.addWeighted(frame, 1.0, glow, 0.55 * strength, 0)


def _pill(frame, text, org, color, scale=0.62, thick=2):
    font = cv2.FONT_HERSHEY_DUPLEX
    (tw, th), base = cv2.getTextSize(text, font, scale, thick)
    x, y = org
    cv2.rectangle(frame, (x - 8, y - th - 8), (x + tw + 8, y + base + 4),
                  (20, 20, 20), -1, cv2.LINE_AA)
    cv2.rectangle(frame, (x - 8, y - th - 8), (x + tw + 8, y + base + 4),
                  color, 1, cv2.LINE_AA)
    cv2.putText(frame, text, (x, y), font, scale, color, thick, cv2.LINE_AA)


def _arc(img, center, radius, fraction, color, thickness=3):
    """Progress arc, drawn as a polyline on purpose: cv2.ellipse takes five
    positional angles/axes in a row, and an omitted startAngle silently shifts
    every later argument (that crashed the HUD once). This form cannot be
    mis-called and needs no version-specific overload."""
    frac = max(0.0, min(float(fraction), 1.0))
    if frac <= 0.0:
        return
    n = max(3, int(48 * frac) + 3)
    pts = [(int(center[0] + radius * math.cos(-math.pi / 2 + 2 * math.pi * frac * i / n)),
            int(center[1] + radius * math.sin(-math.pi / 2 + 2 * math.pi * frac * i / n)))
           for i in range(n + 1)]
    cv2.polylines(img, [np.array(pts, dtype=np.int32)], False, color, thickness,
                  cv2.LINE_AA)


def draw_hud(frame, out, fr, extra, mirror=True):
    """mirror=True flips the picture horizontally so it reads like a mirror,
    which is the same convention the cursor mapping uses (Config.mirror in
    gesture_cursor.py). Keep the two in sync or the preview lies about which
    way your hand is pushing the cursor."""
    h, w = frame.shape[:2]
    if mirror:
        frame = cv2.flip(frame, 1)

    def X(x_norm):                     # frame x -> displayed x
        x_px = int(x_norm * w)
        return w - 1 - x_px if mirror else x_px

    pulse = 0.75 + 0.25 * np.sin(time.monotonic() * 5.0)
    frame = _glow(frame, COLORS[out.state],
                  strength=1.0 if out.state is ControlState.ACTIVE else 0.45 * pulse)

    if fr.box:
        xa, xb = X(fr.box[0]), X(fr.box[2])
        y0, y1 = int(fr.box[1]), int(fr.box[3])
        cv2.rectangle(frame, (min(xa, xb), y0), (max(xa, xb), y1),
                      COLORS[out.state], 1, cv2.LINE_AA)

    if fr.landmarks:
        for p in fr.landmarks:
            cv2.circle(frame, (X(p.x), int(p.y * h)), 2,
                       (255, 255, 255), -1, cv2.LINE_AA)
        tip = fr.landmarks[8]
        cx, cy = X(tip.x), int(tip.y * h)
        _arc(frame, (cx, cy), 30, out.progress, COLORS[out.state], 3)
        cv2.circle(frame, (cx, cy), 6, COLORS[out.state], -1, cv2.LINE_AA)

    label = {"armed": "ARMED  (watching)", "active": "ACTIVE  (controlling)",
             "off": "OFF"}[out.state.value]
    _pill(frame, label, (28, 44), COLORS[out.state], scale=0.8)
    _pill(frame, out.hint, (28, 84), (230, 230, 230), scale=0.55, thick=1)

    info = [f"pose: {out.pose or '-'}",
            f"hand: {out.distance_cm / 30.48:.1f} ft / {out.distance_cm:.0f} cm"
            if out.distance_cm else "hand: -",
            f"zoom: {fr.zoom:.1f}x",
            f"{fr.fps:.0f} fps",
            f"speed {extra['speed']:.2f}  min speed {extra['min_speed']:.2f}",
            f"click: {extra['click']}{'  [DRY RUN]' if extra['dry'] else ''}"]
    y = h - 20 - 22 * (len(info) - 1)
    for line in info:
        _pill(frame, line, (28, y), (200, 220, 230), scale=0.5, thick=1)
        y += 22

    _pill(frame, "Esc/q quit   space on/off   +/- speed   [ ] shake",
          (w - 470, h - 18), (170, 170, 170), scale=0.45, thick=1)
    return frame


def main(argv=None):
    ap = argparse.ArgumentParser(description="AirTrack: gesture control for your computer")
    ap.add_argument("--camera", type=int, default=0)
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=720)
    ap.add_argument("--model", default=None, help="path to hand_landmarker.task")
    ap.add_argument("--click", choices=("pinch", "dwell"), default="pinch")
    ap.add_argument("--speed", type=float, default=Config.speed,
                    help="screen widths travelled per palm-length of hand movement")
    ap.add_argument("--min-speed", type=float, default=Config.min_speed,
                    help="hand speed in palm-lengths/s needed to move the cursor "
                         "(bigger = steadier, smaller = more sensitive)")
    ap.add_argument("--no-zoom", action="store_true", help="disable ROI upscaling")
    ap.add_argument("--dry-run", action="store_true",
                    help="never move the real cursor (safe testing)")
    ap.add_argument("--no-preview", action="store_true")
    ap.add_argument("--frames", type=int, default=0, help="stop after N frames (testing)")
    ap.add_argument("--mute", action="store_true", help="no spoken state cues")
    args = ap.parse_args(argv)

    from tracker import HandTracker, DEFAULT_MODEL

    gui = not args.no_preview
    pyautogui = None
    if not args.dry_run:
        try:
            import pyautogui
            pyautogui.FAILSAFE = True   # slam the pointer into a corner = emergency stop
            pyautogui.PAUSE = 0
        except Exception as exc:        # pragma: no cover - platform dependent
            print(f"pyautogui unavailable ({exc}); running dry.")
            args.dry_run = True

    if pyautogui is not None:
        sw, sh = pyautogui.size()
    else:
        sw, sh = Config.screen_w, Config.screen_h

    cfg = Config(screen_w=sw, screen_h=sh, speed=args.speed,
                 min_speed=args.min_speed, click_mode=args.click)
    ctrl = CursorController(cfg)

    try:
        tracker = HandTracker(camera=args.camera, width=args.width, height=args.height,
                              model=args.model or DEFAULT_MODEL, zoom=not args.no_zoom)
    except Exception as exc:
        print(f"camera/model error: {exc}")
        return 1
    cfg.frame_w = tracker.width

    if gui:
        cv2.namedWindow(WIN, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(WIN, 960, 540)
        try:
            cv2.setWindowProperty(WIN, cv2.WND_PROP_TOPMOST, 1)
        except Exception:
            pass

    print(f"AirTrack running ({tracker.width}x{tracker.height}).")
    print("ARMED: hold an open palm for half a second to take control.")
    if args.dry_run:
        print("DRY RUN: the cursor will not move.")

    voice = Voice(enabled=not args.mute)
    if args.mute:
        print("Voice: muted (--mute).")
    elif voice.available():
        print(f"Voice: clips in sounds/ ({', '.join(voice.available())}).")
    else:
        print("Voice: silent -- no clips in sounds/. Run 'python generate_sounds.py' "
              "with ELEVENLABS_API_KEY set to add them.")

    frames = detections = clicks = 0
    state = None
    t_start = time.monotonic()
    try:
        while True:
            fr = tracker.read()
            if fr.image is None:
                continue
            out = ctrl.update(fr.landmarks, time.monotonic())
            frames += 1
            detections += bool(fr.detected)

            if out.state is not state:
                was_active = state is ControlState.ACTIVE
                state = out.state
                print(f"[{time.monotonic() - t_start:6.1f}s] {state.value.upper()}"
                      f"  ({out.hint})")
                if state is ControlState.ACTIVE:
                    voice.say("activated")
                elif was_active and state is ControlState.ARMED:
                    voice.say("released")
            if out.action == "click":
                clicks += 1
                print(f"[{time.monotonic() - t_start:6.1f}s] click at "
                      f"({out.x:.0f}, {out.y:.0f})")

            if not args.dry_run and pyautogui is not None:
                try:
                    if out.action == "move":
                        pyautogui.moveTo(int(out.x), int(out.y), _pause=False)
                    elif out.action == "click":
                        pyautogui.click(_pause=False)
                except pyautogui.FailSafeException:
                    # Deliberate emergency stop (the real pointer is in a corner).
                    # Exit cleanly instead of dying with a traceback.
                    print("\nEMERGENCY STOP: pointer in a screen corner, "
                          "control released.")
                    ctrl.disarm()
                    break

            if gui:
                frame = draw_hud(fr.image, out, fr, {
                    "speed": cfg.speed, "min_speed": cfg.min_speed,
                    "click": cfg.click_mode, "dry": args.dry_run},
                    mirror=cfg.mirror)
                cv2.imshow(WIN, frame)
                key = cv2.waitKey(1) & 0xFF
                if key in (27, ord("q")):
                    break
                elif key == ord(" "):
                    if ctrl.state is ControlState.OFF:
                        ctrl.arm()
                    else:
                        ctrl.disarm()
                elif key in (ord("+"), ord("=")):
                    cfg.speed = round(min(cfg.speed + 0.05, 2.0), 2)
                    ctrl.gain = cfg.speed * cfg.screen_w
                elif key == ord("-"):
                    cfg.speed = round(max(cfg.speed - 0.05, 0.05), 2)
                    ctrl.gain = cfg.speed * cfg.screen_w
                elif key == ord("]"):
                    cfg.min_speed = round(min(cfg.min_speed + 0.05, 2.0), 2)
                elif key == ord("["):
                    cfg.min_speed = round(max(cfg.min_speed - 0.05, 0.05), 2)

            if args.frames and frames >= args.frames:
                break
    except KeyboardInterrupt:
        print("\nInterrupted.")
    finally:
        ctrl.disarm()
        tracker.close()
        if gui:
            cv2.destroyAllWindows()

    dur = max(time.monotonic() - t_start, 1e-6)
    print(f"\n{frames} frames in {dur:.1f}s ({frames / dur:.1f} fps), "
          f"hand found in {detections}/{frames} frames, {clicks} clicks.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
