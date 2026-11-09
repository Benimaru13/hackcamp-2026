"""app_calibrated.py -- a copy of app.py that runs on a calibration measurement.

Same gesture logic as app.py, character for character, plus four additions: the
measurement is applied to the Config at startup (or handed over in memory by
start.py), the HUD shows the measured tremor and the holds it tuned, a ring marks
the fingertip at the size your hand reads from the distance you calibrated at,
and --verbose prints what is blocking the cursor. app.py itself is untouched.

This is the loop `python start.py` actually runs, so it is the shipping control
path. The gesture logic still lives in gesture_cursor.py, unchanged: this file
only decides what to draw and when to talk to the OS. `pointer_test()` runs once
at startup to prove the OS accepts synthetic mouse events, which is the
difference between "the demo is broken" and "the Accessibility permission is
missing".

AirTrack demo entry point.

    python app.py                 # run it, raise an open palm to take control
    python app.py --dry-run       # detect + show the HUD, never touch the cursor

The window shows the camera (mirrored, so it reads like a mirror), the current
state, the pose it recognises, and an approximate distance. The state cue itself is
the full-screen halo (edge_glow.py) -- a click-through border around the whole
desktop -- because at 10 ft you are looking at the screen, not at this window.
Esc / q quits, space switches between ARMED and OFF. Spoken cues (if the WAVs
from generate_sounds.py are in sounds/) announce activation and release.
"""
from __future__ import annotations

import argparse
import math
import os
import sys
import time

import cv2
import numpy as np

from gesture_cursor import (Config, ControlState, CursorController, MuteDetector,
                            ScrollDetector, SwitchDetector, cursor_radius_px,
                            hand_scale)
from instruction_panel import draw_manual, in_rect
from voice import Voice
from zoom import ViewFollow, view_rect

WIN = "AirTrack (calibrated)"
RING_BASE_PX = 18.0   # ring radius at the distance you calibrated at (frame px)
COLORS = {
    ControlState.ARMED: (0, 176, 255),     # amber
    ControlState.ACTIVE: (90, 255, 120),   # green
    ControlState.OFF: (120, 120, 120),     # grey
}

# Two-finger vertical scroll: ScrollDetector emits one step per interval, so the
# speed does not depend on the camera frame rate. SCROLL_STEP is how far one
# wheel step moves; on macOS the sign follows System Settings > natural scrolling.
SCROLL_STEP = 1
MANUAL_HOLD = 1.0   # s a fingertip must stay on OK before the manual closes


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


def _pill_right(frame, text, y, color, scale=0.55, thick=2):
    """_pill anchored to the right edge: the audio-guide indicator lives there."""
    font = cv2.FONT_HERSHEY_DUPLEX
    (tw, _), _ = cv2.getTextSize(text, font, scale, thick)
    _pill(frame, text, (frame.shape[1] - tw - 28, y), color, scale, thick)


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


def manual_point(fr, view, mirror, width, height):
    """Where the fingertip is, in the pixels `draw_manual` draws into.

    The preview is a zoomed, mirrored picture, so a raw landmark cannot be used:
    this repeats the mapping draw_hud uses for the reticle (view crop first, then
    mirror) so the hand points at the button exactly where the button appears.
    Keep the two in step -- if one flips and the other does not, aiming at OK
    lands on the opposite side of the screen.
    """
    if not fr.landmarks:
        return None
    fw = float(fr.width or width)
    fh = float(getattr(fr, "height", 0) or height)
    vx, vy, vw, vh = 0.0, 0.0, fw, fh
    if view is not None:
        v = view_rect(view[:2], view[2], fw, fh)
        if v.w < fw and v.h > 1:
            vx, vy, vw, vh = v.x0, v.y0, v.w, v.h
    tip = fr.landmarks[8]
    x = int((tip.x * fw - vx) * (width / max(vw, 1.0)))
    y = int((tip.y * fh - vy) * (height / max(vh, 1.0)))
    return (width - 1 - x if mirror else x), y


def draw_hud(frame, out, fr, extra, mirror=True, halo=True):
    """mirror=True flips the picture horizontally so it reads like a mirror,
    which is the same convention the cursor mapping uses (Config.mirror in
    gesture_cursor.py). Keep the two in sync or the preview lies about which
    way your hand is pushing the cursor."""
    h, w = frame.shape[:2]

    # The preview shows the auto-zoom crop, blown up to the window, so the feed
    # visibly zooms in and pans with the hand like a camera focusing on it. This is
    # pure drawing: the detector already works in full-frame coordinates, so only
    # what is displayed (and the map from frame pixels to display pixels) changes.
    fw = float(fr.width or w)
    fh = float(getattr(fr, "height", 0) or h)
    view = None
    want = extra.get("view")                 # (cx, cy, side) in frame px, smoothed
    if want is not None:
        v = view_rect(want[:2], want[2], fw, fh)
        x0, y0, x1, y1 = v.ints()
        if x1 - x0 > 1 and y1 - y0 > 1 and v.w < fw:
            frame = cv2.resize(frame[y0:y1, x0:x1], (w, h),
                               interpolation=cv2.INTER_LINEAR)
            view = v
    if mirror:
        frame = cv2.flip(frame, 1)

    # Frame PIXELS -> displayed pixels, through the view window. tracker.py reports
    # boxes in frame pixels and the window can be a different size, so scale first:
    # treating a pixel box as normalized drew it thousands of px off-screen.
    vx = view.x0 if view is not None else 0.0
    vy = view.y0 if view is not None else 0.0
    vw = view.w if view is not None else fw
    vh = view.h if view is not None else fh
    sx, sy = w / max(vw, 1.0), h / max(vh, 1.0)

    def XPx(px):
        x_px = int((px - vx) * sx)
        return w - 1 - x_px if mirror else x_px

    def YPx(py):
        return int((py - vy) * sy)

    def X(x_norm):                     # normalized frame x -> displayed x
        return XPx(x_norm * fw)

    def Y(y_norm):                     # normalized frame y -> displayed y
        return YPx(y_norm * fh)

    pulse = 0.75 + 0.25 * np.sin(time.monotonic() * 5.0)
    if halo:   # fallback only: with the full-screen overlay the preview stays clean
        frame = _glow(frame, COLORS[out.state],
                      strength=1.0 if out.state is ControlState.ACTIVE else 0.45 * pulse)

    if fr.box:
        xa, xb = XPx(fr.box[0]), XPx(fr.box[2])
        cv2.rectangle(frame, (min(xa, xb), YPx(fr.box[1])), (max(xa, xb), YPx(fr.box[3])),
                      COLORS[out.state], 1, cv2.LINE_AA)

    if fr.landmarks:
        for p in fr.landmarks:
            cv2.circle(frame, (X(p.x), Y(p.y)), 2,
                       (255, 255, 255), -1, cv2.LINE_AA)
        tip = fr.landmarks[8]
        cx, cy = X(tip.x), Y(tip.y)
        r_px = extra.get("cursor_px") or 0
        if r_px:
            # Aiming reticle: the radius comes from gesture_cursor.cursor_radius_px,
            # so the guide grows with the camera distance and stays visible from
            # across the room. Only drawn while the pointing hand is live.
            # r_px is measured in frame pixels, so convert it to display pixels:
            # otherwise the zoomed preview would magnify the reticle as well.
            r = int(min(max(r_px * (w / fw), 8.0), h * 0.22))
            cv2.circle(frame, (cx, cy), r, COLORS[out.state], 2, cv2.LINE_AA)
            for ang in (0, 90, 180, 270):
                a = math.radians(ang)
                cv2.line(frame,
                         (int(cx + (r - 4) * math.cos(a)), int(cy + (r - 4) * math.sin(a))),
                         (int(cx + (r + 8) * math.cos(a)), int(cy + (r + 8) * math.sin(a))),
                         COLORS[out.state], 2, cv2.LINE_AA)
            cv2.circle(frame, (cx, cy), 3, (255, 255, 255), -1, cv2.LINE_AA)
            _arc(frame, (cx, cy), r + 10, out.progress, COLORS[out.state], 3)
        else:
            _arc(frame, (cx, cy), 30, out.progress, COLORS[out.state], 3)
            cv2.circle(frame, (cx, cy), 6, COLORS[out.state], -1, cv2.LINE_AA)
        # Calibrated ring: the size the hand reads at the distance it was
        # measured from, so stepping back visibly grows the target. Drawn in
        # frame pixels like the reticle, then scaled to the zoomed preview.
        ring_px = float(extra.get("ring", 0.0))
        if ring_px > 0:
            k_px = w / fw
            cv2.circle(frame, (cx, cy), int(RING_BASE_PX * k_px), (100, 100, 100), 1,
                       cv2.LINE_AA)
            cv2.circle(frame, (cx, cy), int(ring_px * k_px), COLORS[out.state], 2,
                       cv2.LINE_AA)
        # Screen-switch hold: a second ring between the two fingertips, so a hold
        # that is half done is visible from across the room.
        switch_progress = float(extra.get("switch", 0.0))
        if switch_progress > 0.0:
            a, b = fr.landmarks[8], fr.landmarks[12]
            _arc(frame, (X((a.x + b.x) / 2.0), Y((a.y + b.y) / 2.0)), 22,
                 switch_progress, (0, 220, 255), 3)
        # Audio-guide hold: the same progress idea for the rock sign, drawn
        # between the two raised fingertips so a half-done hold is visible.
        mute_progress = float(extra.get("mute", 0.0))
        if mute_progress > 0.0:
            a, b = fr.landmarks[8], fr.landmarks[20]
            _arc(frame, (X((a.x + b.x) / 2.0), Y((a.y + b.y) / 2.0)), 26,
                 mute_progress, (0, 220, 255), 3)

    label = {"armed": "ARMED  (watching)", "active": "ACTIVE  (controlling)",
             "off": "OFF"}[out.state.value]
    _pill(frame, label, (28, 44), COLORS[out.state], scale=0.8)
    _pill(frame, out.hint, (28, 84), (230, 230, 230), scale=0.55, thick=1)
    # Audio-guide indicator: whether the app will talk to you is a state you have
    # to be able to check from across the room, so it is always on screen --
    # green for ACTIVE, amber for MUTED.
    audio_on = bool(extra.get("audio", True))
    _pill_right(frame, "AUDIO GUIDE ACTIVE" if audio_on else "AUDIO GUIDE MUTED",
                44, (90, 255, 120) if audio_on else (0, 176, 255))

    info = [f"pose: {out.pose or '-'}",
            f"hand: {out.distance_cm / 30.48:.1f} ft / {out.distance_cm:.0f} cm"
            if out.distance_cm else "hand: -",
            (f"zoom: {fr.zoom:.1f}x  hand {fr.fill * 100:.0f}% of crop"
             f"  preview {fw / max(vw, 1.0):.1f}x"
             if fr.focused else "zoom: - (whole frame)"),
            f"{fr.fps:.0f} fps",
            "switch: two fingers left/right, hold 0.55 s, then 1 s rest",
            f"scroll: {extra.get('scroll', '-')}",
            f"speed {extra['speed']:.2f}  min speed {extra['min_speed']:.2f}",
            f"click: {extra['click']}{'  [DRY RUN]' if extra['dry'] else ''}",
            f"calib: {extra.get('calib', 'defaults')}"]
    y = h - 20 - 22 * (len(info) - 1)
    for line in info:
        _pill(frame, line, (28, y), (200, 220, 230), scale=0.5, thick=1)
        y += 22

    _pill(frame, "Esc/q quit   space on/off   +/- speed   [ ] shake",
          (w - 470, h - 18), (170, 170, 170), scale=0.45, thick=1)
    return frame


def pointer_test(pyautogui, dry_run=False):
    """Prove the OS is actually accepting synthetic mouse events.

    A missing 'Accessibility' grant (macOS), a sandbox, or a security tool lets
    pyautogui import cleanly and report a screen size while silently dropping
    every event. The app then looks broken although its logic is perfect. Move
    the pointer 80 px, check it arrived, put it back, and report the result.
    """
    if dry_run or pyautogui is None:
        return None
    try:
        x, y = pyautogui.position()[:2]
        pyautogui.moveTo(x + 80, y, _pause=False)
        moved_x = pyautogui.position()[0]
        pyautogui.moveTo(x, y, _pause=False)
    except Exception as exc:
        print(f"Pointer test: FAILED ({exc})")
        return False
    if abs(moved_x - (x + 80)) <= 2:
        print("Pointer test: OK -- this process can move the real cursor.")
        return True
    print("Pointer test: FAILED -- the pointer did not move. On macOS grant the "
          "terminal 'Accessibility' in System Settings > Privacy & Security.")
    return False


def main(argv=None, profile=None, tracker=None):
    """`profile` and `tracker` let start.py hand over what it just used.

    Passing the tracker in means the camera is never closed and reopened between
    measuring and controlling: that reopen was a second or two of nothing
    happening right when the cursor is supposed to appear.
    """
    ap = argparse.ArgumentParser(description="AirTrack: gesture control for your computer")
    ap.add_argument("--camera", type=int, default=0)
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=720)
    ap.add_argument("--model", default=None, help="path to hand_landmarker.task")
    ap.add_argument("--speed", type=float, default=Config.speed,
                    help="screen widths travelled per palm-length of hand movement")
    ap.add_argument("--min-speed", type=float, default=Config.min_speed,
                    help="hand speed in palm-lengths/s needed to move the cursor "
                         "(bigger = steadier, smaller = more sensitive)")
    ap.add_argument("--no-zoom", action="store_true",
                    help="disable the auto-zoom crop (whole-frame detection only)")
    ap.add_argument("--dry-run", action="store_true",
                    help="never move the real cursor (safe testing)")
    ap.add_argument("--no-preview", action="store_true")
    ap.add_argument("--frames", type=int, default=0, help="stop after N frames (testing)")
    ap.add_argument("--profile", default=None,
                    help="calibration profile.json (default: next to this file)")
    ap.add_argument("--verbose", action="store_true",
                    help="print state/pose/distance twice a second, to see what "
                         "is blocking the cursor")
    ap.add_argument("--no-pointer-test", action="store_true",
                    help="skip the startup check that the OS accepts mouse events")
    ap.add_argument("--mute", action="store_true", help="no spoken state cues")
    ap.add_argument("--no-glow", action="store_true",
                    help="no full-screen halo (the preview border is used instead)")
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
        if not args.no_pointer_test:
            pointer_test(pyautogui, args.dry_run)
    else:
        sw, sh = Config.screen_w, Config.screen_h

    cfg = Config(screen_w=sw, screen_h=sh, speed=args.speed,
                 min_speed=args.min_speed)

    # --- calibration: the one thing this copy adds to app.py ----------------
    from calibrate_profile import DEFAULT_PATH, apply_to_config, load_profile
    from calibration_math import cursor_ring_px, distance_ratio
    profile_path = args.profile or DEFAULT_PATH
    if profile is not None:
        # Passed in by start.py: measured on this run, so nothing is on disk.
        apply_to_config(cfg, profile)
        print(f"Calibrated this run: {profile.summary()}")
    elif os.path.exists(profile_path):
        try:
            profile = load_profile(profile_path)
            apply_to_config(cfg, profile)
            print(f"Calibrated: {profile.summary()}")
        except Exception as exc:
            print(f"profile ignored ({exc}); using the built-in defaults.")
    else:
        print(f"No profile at {profile_path}. Run 'python calibrate.py' first; "
              f"this run uses the built-in defaults.")

    ctrl = CursorController(cfg)
    print(f"Config: min_speed {cfg.min_speed:.2f}  min_cutoff {cfg.min_cutoff:.2f}  "
          f"beta {cfg.beta:.2f}  dwell {cfg.dwell_time:.2f}s  "
          f"speed {cfg.speed:.2f}  screen {cfg.screen_w}x{cfg.screen_h}")
    if args.dry_run:
        print("*** DRY RUN: the cursor will NOT move. Drop --dry-run to control "
              "the computer. ***")

    try:
        if tracker is None:
            tracker = HandTracker(camera=args.camera, width=args.width,
                                  height=args.height,
                                  model=args.model or DEFAULT_MODEL,
                                  zoom=not args.no_zoom)
        else:
            print("Camera kept open from the calibration: no reopen, no wait.")
    except Exception as exc:
        print(f"camera/model error: {exc}")
        return 1
    cfg.frame_w = tracker.width


    # Manual state survives frames: open until OK, then out of the way.
    ui = {"open": True, "hover": False, "clicked": False,
          "ok_rect": (0, 0, 0, 0), "frame_w": 1280.0,
          "hold": 0.0, "progress": 0.0, "t_last": 0.0}

    def _on_mouse(event, mx, my, _flags, _param):
        # The window can be resized, so the button rect (frame pixels) is scaled
        # by how much the displayed image was shrunk.
        try:
            win = cv2.getWindowImageRect(WIN)
            scale = ui["frame_w"] / max(float(win[2]), 1.0)
        except Exception:
            scale = 1.0
        fx, fy = mx * scale, my * scale
        ui["hover"] = bool(ui["open"]) and in_rect(ui["ok_rect"], fx, fy)
        if event == cv2.EVENT_LBUTTONUP and ui["hover"]:
            ui["clicked"] = True

    if gui:
        cv2.namedWindow(WIN, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(WIN, 1280, 720)
        try:
            cv2.setWindowProperty(WIN, cv2.WND_PROP_TOPMOST, 1)
        except Exception:
            pass
        try:
            cv2.setMouseCallback(WIN, _on_mouse)
        except Exception:
            pass

    # The halo is a macOS AppKit window (edge_glow.py); without it, or off macOS,
    # the preview border is the fallback.
    glow = None
    if args.no_glow:
        print("Screen halo: off (--no-glow); the preview border is used.")
    elif not gui:
        print("Screen halo: off (no preview window).")
    else:
        from edge_glow import EdgeGlow
        glow = EdgeGlow(enabled=True)
        print("Screen halo: full screen, click-through (edge_glow.py)."
              if glow.available else
              "Screen halo: unavailable; the preview border is used instead.")
    halo_in_preview = glow is None or not glow.available

    print(f"AirTrack running ({tracker.width}x{tracker.height}).")
    print("ARMED: raise an open palm toward the camera for half a second to "
          "take control.")
    print("Click: hold the pointing hand still for ~2 s (pointing pose only).")
    print("Switch space: point two fingers left or right, hold 0.55 s (ACTIVE "
          "only), then a 1 s rest before it looks for input again.")
    print("Audio guide: the rock sign (index + pinky up, middle fingers curled) "
          "held 0.75 s mutes / unmutes the spoken cues (ARMED too).")
    print("Auto-zoom: on -- the crop follows the hand, like a camera focusing on it,"
          " so the hand fills the model's input at any distance."
          if tracker.zoom else "Auto-zoom: off (--no-zoom), whole-frame detection only.")
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
    diag_next = 0.0
    t_start = time.monotonic()
    switch_det = SwitchDetector(cfg.switch_hold, cfg.switch_cooldown)
    scroll_det = ScrollDetector(cfg.scroll_hold, cfg.scroll_interval)
    mute_det = MuteDetector(cfg.mute_hold, cfg.mute_release)
    scroll_dir = None
    reticle = None                 # smoothed aiming-reticle radius
    follow = ViewFollow()          # eased preview zoom (Centre Stage style)
    view = None                    # window the preview showed last frame
    view_last = None               # monotonic time of the last eased step
    
    try:
        while True:
            fr = tracker.read()
            if fr.image is None:
                continue
            out = ctrl.update(fr.landmarks, time.monotonic())
            frames += 1
            if ui["open"] and ctrl.state is not ControlState.OFF:
                ctrl.disarm()   # a palm raised behind the manual must not arm

            detections += bool(fr.detected)

            current_time = time.monotonic()

            if args.verbose and current_time >= diag_next:
                diag_next = current_time + 0.5
                print(f"  [{current_time - t_start:5.1f}s] {out.state.value:6s} "
                      f"pose={out.pose or '-':10s} hand={out.distance_cm:4.0f}cm "
                      f"action={(out.action or '-'):6s} "
                      f"min_speed={cfg.min_speed:.2f} dwell={out.progress:.2f}")

            if glow is not None:
                # The halo carries the audio-guide badge too: it is the one cue
                # that survives another app being in front of the preview.
                glow.update(out.state.value, current_time, audio=voice.enabled)

            # Two-finger vertical: hold the V pointing up/down to scroll. The
            # detector emits at a fixed cadence (per second, not per frame) and
            # treats the two directions identically, so down is simply the gesture
            # upside down. ACTIVE only: ARMED stays hands-off.
            if out.state is ControlState.ACTIVE:
                scroll_step = scroll_det.update(fr.landmarks, current_time)
            else:
                scroll_det.reset()
                scroll_step = 0
            if scroll_step and not ui["open"] and pyautogui is not None and not args.dry_run:
                pyautogui.scroll(SCROLL_STEP * scroll_step)
            if scroll_det.direction != scroll_dir:
                scroll_dir = scroll_det.direction
                if scroll_dir:
                    print(f"[{current_time - t_start:6.1f}s] ✌️ "
                          f"two fingers {scroll_dir} -> scrolling {scroll_dir}")
                else:
                    print(f"[{current_time - t_start:6.1f}s] ✌️ scroll stopped")

            # Screen switch: two fingers pointed left or right, HELD 0.55 s, then
            # a 1 s rest. ACTIVE only, and the detector is not even run otherwise:
            # a hold completed in ARMED used to become the first switch of the
            # session. It is a hold, not a swipe, so no return stroke is input.
            if out.state is ControlState.ACTIVE:
                switch = switch_det.update(fr.landmarks, current_time)
            else:
                switch_det.reset()
                switch = None
            if switch and not ui["open"]:
                where = "previous" if switch == "left" else "next"
                print(f"[{current_time - t_start:6.1f}s] ✌️ TWO FINGERS "
                      f"{switch.upper()} -> {where} space")
                if pyautogui is not None and not args.dry_run:
                    pyautogui.hotkey("ctrl", switch)
            switch_progress = switch_det.progress(current_time)
            # Audio guide: the rock sign held 0.75 s toggles the spoken cues. It
            # runs in ARMED too, because the cues fire the moment control is taken
            # -- muting has to be possible before that. One hold is one toggle;
            # letting go of the sign is what arms the next one.
            if out.state is not ControlState.OFF:
                if mute_det.update(fr.landmarks, current_time):
                    voice.set_enabled(not voice.enabled)
                    print(f"[{current_time - t_start:6.1f}s] ROCK SIGN -> "
                          f"audio guide "
                          f"{'ACTIVE' if voice.enabled else 'MUTED'}")
            else:
                mute_det.reset()
            mute_progress = mute_det.progress(current_time)
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

            # Aiming reticle: only while the pointing hand is live, and sized by the
            # camera distance so it stays visible at 3-4 m without hiding anything
            # up close. Smoothed, because the distance readout itself jitters.
            cursor_px = None
            if (out.state is ControlState.ACTIVE and out.pose == "point"
                    and out.distance_cm):
                want = cursor_radius_px(out.distance_cm, cfg)
                reticle = want if reticle is None else 0.85 * reticle + 0.15 * want
                cursor_px = reticle
            else:
                reticle = None

            # Preview zoom: the window is EASED to the hand like a camera on a
            # gimbal (the Centre Stage feel) instead of being cut to it. It zooms
            # in from the whole frame, glides when the hand moves and eases back
            # out when the hand is lost. ViewFollow works in real time, so the pan
            # looks the same on a 15 fps camera as on a 60 fps one, and only a
            # crop built around the hand is ever a target -- following a scan tile
            # whipped the picture across the frame before settling on the hand.
            view_dt = 0.0 if view_last is None else current_time - view_last
            view_last = current_time
            view = follow.update(fr.focus_crop,
                                 float(fr.width or tracker.width),
                                 float(fr.height or tracker.height), view_dt)

            if not ui["open"] and not args.dry_run and pyautogui is not None:
                try:
                    if out.action in ("move", "click"):
                        # The click lands on the hover anchor, not wherever the
                        # cursor drifted: move first, then click.
                        pyautogui.moveTo(int(out.x), int(out.y), _pause=False)
                    if out.action == "click":
                        pyautogui.click(_pause=False)
                except pyautogui.FailSafeException:
                    # Deliberate emergency stop (the real pointer is in a corner).
                    # Exit cleanly instead of dying with a traceback.
                    print("\nEMERGENCY STOP: pointer in a screen corner, "
                          "control released.")
                    ctrl.disarm()
                    break

            if gui:
                ring_px, ratio = 0.0, 1.0
                if profile is not None and fr.landmarks:
                    ratio = distance_ratio(hand_scale(fr.landmarks), profile.palm)
                    ring_px = cursor_ring_px(RING_BASE_PX, ratio)
                tremor = (f"{profile.tremor_hz:.1f}Hz " if profile is not None
                          and profile.tremor_hz > 0 else "")
                calib = ("defaults" if profile is None else
                         f"{tremor}{profile.jitter_score}/100, "
                         f"dwell {profile.dwell_time:.2f}s, "
                         f"arm {profile.arm_hold:.2f}s, ring "
                         f"{ring_px:.0f}px @{ratio:.1f}x")
                frame = draw_hud(fr.image, out, fr, {
                    "ring": ring_px, "calib": calib,
                    "speed": cfg.speed, "min_speed": cfg.min_speed,
                    "switch": switch_progress,
                    "mute": mute_progress,
                    "audio": voice.enabled,
                    "view": view,
                    "scroll": scroll_det.direction or "-",
                    "cursor_px": cursor_px,
                    "click": "hold still", "dry": args.dry_run},
                    mirror=cfg.mirror, halo=halo_in_preview)
                # The manual: a modal glass card that says how the app works
                # before anything can move the cursor. Three ways out -- point at
                # OK and hold (the camera is right there, so no mouse needed),
                # click it, or press space/enter. 'm' brings it back.
                if ui["open"]:
                    pt = manual_point(fr, view, cfg.mirror, frame.shape[1],
                                      frame.shape[0])
                    on_ok = pt is not None and in_rect(ui["ok_rect"], pt[0], pt[1])
                    dt = 0.0 if not ui["t_last"] else max(0.0, current_time - ui["t_last"])
                    ui["t_last"] = current_time
                    ui["hold"] = ui["hold"] + dt if on_ok else 0.0
                    ui["progress"] = min(1.0, ui["hold"] / MANUAL_HOLD)
                    if ui["progress"] >= 1.0 or ui["clicked"]:
                        ui["clicked"] = False
                        ui["open"] = False
                        ui["hold"] = ui["progress"] = 0.0
                        print("Manual dismissed: raise an open palm to take control.")
                    else:
                        frame, ok_rect = draw_manual(
                            frame, profile, cfg, hover=ui["hover"] or on_ok,
                            progress=ui["progress"] if on_ok else 0.0)
                        ui["ok_rect"] = ok_rect
                        ui["frame_w"] = float(frame.shape[1])
                cv2.imshow(WIN, frame)
                key = cv2.waitKey(1) & 0xFF
                if key in (27, ord("q")):
                    break
                if ui["open"]:
                    if key in (13, 32, ord("m")):
                        ui["open"] = False
                        print("Manual dismissed: raise an open palm to take control.")
                    continue
                if key == ord(" "):
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
                elif key == ord("m"):
                    ui["open"] = True
                    ui["hold"] = ui["progress"] = 0.0

            if args.frames and frames >= args.frames:
                break
    except KeyboardInterrupt:
        print("\nInterrupted.")
    finally:
        ctrl.disarm()
        tracker.close()
        if glow is not None:
            glow.close()
        if gui:
            cv2.destroyAllWindows()

    dur = max(time.monotonic() - t_start, 1e-6)
    print(f"\n{frames} frames in {dur:.1f}s ({frames / dur:.1f} fps), "
          f"hand found in {detections}/{frames} frames, {clicks} clicks.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
