"""simulate.py  --  AirTrack without a camera (uses synthetic landmarks).

This is the fastest way for anyone on the team (no camera, no Mac, no
permissions) to check the interaction logic and to measure the two things that
matter for the 10-foot demo:

  * shake tolerance  -- how far does the cursor drift when the hand is still
                        and the detector is noisy, at 1 m and at 3 m?
  * distance match   -- does the same physical hand sweep move the cursor the
                        same distance near and far?

Run:  python simulate.py            (all scenarios)
      python simulate.py still      (one scenario: still | move | tune | gestures |
                                     switch | scroll | focus | follow | cursor)
"""
from __future__ import annotations

import math
import sys
import time

from fake_hand import FakeHand, palm_for_distance
from gesture_cursor import Config, ControlState, CursorController


DT = 1.0 / 30.0
JITTER_PX = 2.0          # detector noise on a still hand, in 1280-px frame pixels


def _jitter_norm(px=JITTER_PX, frame_w=1280):
    return px / frame_w


def _new(distance_m=1.0, **cfg_kw):
    cfg = Config(**cfg_kw)
    ctrl = CursorController(cfg)
    hand = FakeHand(pose="point", jitter=_jitter_norm(), seed=7).at_distance(distance_m)
    return ctrl, hand, cfg


def scenario_still(distance_m, seconds=5.0):
    """Hand pointed at the screen and held still: the cursor must not wander."""
    ctrl, hand, cfg = _new(distance_m)
    t = 0.0
    for _ in range(int(0.9 / DT)):                  # arm with an open palm
        t += DT
        ctrl.update(hand.landmarks(pose="palm"), now=t)
    t += DT
    ctrl.update(hand.landmarks(pose="point"), now=t)
    start = ctrl.pos
    drift = total = 0.0
    clicks = 0
    frames = int(seconds / DT)
    px, py = start
    for _ in range(frames):
        t += DT
        out = ctrl.update(hand.landmarks(), now=t)
        drift = max(drift, ((out.x - start[0]) ** 2 + (out.y - start[1]) ** 2) ** 0.5)
        total += ((out.x - px) ** 2 + (out.y - py) ** 2) ** 0.5
        px, py = out.x, out.y
        clicks += out.action == "click"
    return {
        "distance_m": distance_m,
        "palm_norm": palm_for_distance(distance_m),
        "state": ctrl.state.value,
        "mean_step_px": total / max(frames, 1),
        "max_drift_px": drift,
        "clicks": clicks,
    }


def scenario_move(distance_m, travel_cm=15.0, **cfg_kw):
    """Same physical sweep, near and far: cursor travel should match."""
    ctrl, hand, cfg = _new(distance_m, **cfg_kw)
    t = 0.0
    for _ in range(30):                       # arm with an open palm
        t += DT
        ctrl.update(hand.landmarks(pose="palm"), now=t)
    start = None
    steps = 30                                # 1 s of deliberate sweeping
    visible_w_cm = 240.0 * distance_m / 3.0
    dx_norm = (travel_cm / visible_w_cm) / steps
    ctrl.update(hand.landmarks(pose="point"), now=t)
    start = ctrl.pos
    for i in range(steps * 2):
        t += DT
        if i < steps:
            hand.move(dx=dx_norm)
        out = ctrl.update(hand.landmarks(pose="point"), now=t)
    return {
        "distance_m": distance_m,
        "travel_cm": travel_cm,
        "cursor_travel_px": ((out.x - start[0]) ** 2 + (out.y - start[1]) ** 2) ** 0.5,
    }


def scenario_gestures(distance_m=3.0):
    """Full interaction: open palm to arm, point to move, hold still to click, fist to stop."""
    logs = []
    ctrl = CursorController(Config())
    hand = FakeHand(pose="palm", jitter=_jitter_norm(), seed=3).at_distance(distance_m)
    t = 0.0

    def run(pose, seconds, dx_per_frame=0.0):
        nonlocal t
        hand.pose = pose
        for _ in range(int(seconds / DT)):
            t += DT
            if dx_per_frame:
                hand.move(dx=dx_per_frame)
            out = ctrl.update(hand.landmarks(), now=t)
            if out.action in ("armed", "release", "click") or (
                    logs and logs[-1][1] != out.state.value):
                logs.append((round(t, 2), out.state.value, out.action or ""))
        return out

    run("point", 0.5)                 # ignored: nothing armed yet
    run("palm", 0.8)                  # arms
    run("point", 0.6, dx_per_frame=0.004)
    run("point", 2.5)                 # hold still: click
    run("point", 0.5, dx_per_frame=-0.004)   # move away to a new spot
    run("point", 2.5)                 # hold still again: second click
    run("point", 0.4)
    run("fist", 0.6)                  # releases
    run("palm", 0.4)                  # ignored: arm cooldown
    run("palm", 1.0)                  # re-arms
    return logs


def scenario_scroll(distance_m=3.0, seconds=2.0):
    """Two-finger scroll held each way: same gesture upside down, same stream."""
    from gesture_cursor import ScrollDetector
    cfg = Config()
    rows = []
    for way, angle in (("up", 0.0), ("down", math.pi)):
        det = ScrollDetector(cfg.scroll_hold, cfg.scroll_interval)
        hand = FakeHand(pose="two", angle=angle).at_distance(distance_m)
        t = 0.0
        steps = []
        for _ in range(int(seconds / DT)):
            t += DT
            got = det.update(hand.landmarks(), t)
            if got:
                steps.append(round(t, 2))
        rows.append((way, steps))
    return rows


def scenario_switch(distance_m=3.0, seconds=3.0):
    """Screen switch: two fingers pointed left/right, held 0.55 s, then a 1 s rest.
    Three seconds held, so the hold + rest cadence is visible."""
    from gesture_cursor import SwitchDetector
    cfg = Config()
    rows = []
    for way in ("left", "right"):
        det = SwitchDetector(cfg.switch_hold, cfg.switch_cooldown)
        angle = math.pi / 2 if way == "left" else -math.pi / 2
        hand = FakeHand(pose="two", angle=angle).at_distance(distance_m)
        t = 0.0
        fired = []
        for _ in range(int(seconds / DT)):      # held the whole time
            t += DT
            got = det.update(hand.landmarks(), t)
            if got:
                fired.append((round(t, 2), got))
        rows.append((way, fired))
    return rows


def scenario_focus(frame_w=1280, frame_h=720):
    """Auto-zoom, camera-free: how much of the model's input does the hand fill
    with the new focus crop, versus a whole-frame scan and a scan tile? That share
    is what decides whether the detector can find the hand at all, and the crop
    keeps it constant instead of letting it shrink with distance."""
    from zoom import (TARGET_SIDE, box_of, hand_side, model_hand_share,
                      plan_crop, scan_tiles, upscale_for, view_rect)
    tiles = scan_tiles(frame_w, frame_h)
    tile_k = min(upscale_for(t.short) for t in tiles)
    rows = []
    for d in (1.0, 1.5, 2.0, 3.0, 4.0):
        box = box_of(FakeHand(pose="point").at_distance(d).landmarks(),
                     frame_w, frame_h)
        rect = plan_crop(box, frame_w, frame_h)
        whole = hand_side(box) * upscale_for(frame_h) / TARGET_SIDE
        rows.append({
            "distance_m": d,
            "hand_px": hand_side(box),
            "crop_px": rect.side,
            "zoom": upscale_for(rect.short),
            "focus": model_hand_share(box, rect),
            "whole": whole,
            "tile": hand_side(box) * tile_k / TARGET_SIDE,
            "preview": frame_w / view_rect(rect.center, rect.side, frame_w, frame_h).w,
        })
    return rows


def scenario_follow(frame_w=1280, frame_h=720, fps=30.0):
    """The preview window moving to the hand: the eased camera instead of a cut.

    A 160 px crop appears at the left edge, moves to the right edge at 1.5 s (the
    detector re-planned around a hand that moved), and is lost at 2.4 s. Samples
    every 0.1 s, plus the largest single-frame pan -- the number that reads as a
    jump when it is large.
    """
    from zoom import Rect, ViewFollow, view_rect
    dt = 1.0 / fps
    follow = ViewFollow()
    left = Rect(240.0, 280.0, 400.0, 440.0)
    right = Rect(880.0, 280.0, 1040.0, 440.0)
    every = max(1, int(round(0.1 * fps)))
    samples, max_step, prev = [], 0.0, None
    for i in range(int(3.0 * fps)):
        t = i * dt
        crop = None if t >= 2.4 else (left if t < 1.5 else right)
        view = follow.update(crop, frame_w, frame_h, dt)
        rect = view_rect(view[:2], view[2], frame_w, frame_h) if view else None
        cx = rect.center[0] if rect is not None else None
        if cx is not None and prev is not None:
            max_step = max(max_step, abs(cx - prev))
        prev = cx
        if i % every == 0:
            samples.append((t, cx, None if rect is None else rect.w, view is None))
    return samples, max_step


def scenario_cursor():
    """Aiming reticle radius against camera distance (what the HUD draws with the
    pointing hand live)."""
    from gesture_cursor import cursor_radius_px
    cfg = Config()
    return [(d, cursor_radius_px(d * 100.0, cfg)) for d in (0.5, 1.0, 1.5, 2.0, 3.0, 4.0)]


def scenario_tune():
    """Shake threshold vs steady behaviour: how much does the cursor wander in
    10 s of a still, shaky hand, and does a real sweep still move the cursor?"""
    rows = []
    for ms in (0.25, 0.5, 0.8, 1.2):
        drift = {}
        for d in (1.0, 3.0):
            ctrl, hand, _ = _new(d, min_speed=ms)
            t = 0.0
            for _ in range(int(0.9 / DT)):
                t += DT
                ctrl.update(hand.landmarks(pose="palm"), now=t)
            start = ctrl.pos
            for _ in range(int(10.0 / DT)):
                t += DT
                out = ctrl.update(hand.landmarks(pose="point"), now=t)
            drift[d] = ((out.x - start[0]) ** 2 + (out.y - start[1]) ** 2) ** 0.5
        sweep = scenario_move(3.0, min_speed=ms)
        rows.append((ms, drift[1.0], drift[3.0], sweep["cursor_travel_px"]))
    return rows


def main(argv):
    which = (argv[1] if len(argv) > 1 else "all").lower()
    print("AirTrack simulation (synthetic landmarks, no camera)\n")

    if which in ("all", "still"):
        print("still pointing hand, 2 px detector noise, 5 s held "
              "(one hover click is the gesture, not an accident):")
        for d in (1.0, 3.0):
            r = scenario_still(d)
            print(f"  {d:.0f} m (palm {r['palm_norm']*100:.1f}% of frame): "
                  f"state={r['state']}, drift={r['max_drift_px']:.1f} px, "
                  f"cursor step={r['mean_step_px']:.2f} px/frame, "
                  f"hover clicks={r['clicks']}")
        print()

    if which in ("all", "move"):
        print("same 15 cm hand sweep, near vs far -- travel_px should match")
        rows = [scenario_move(d) for d in (1.0, 3.0)]
        for r in rows:
            print(f"  {r['distance_m']:.0f} m: cursor travelled "
                  f"{r['cursor_travel_px']:.0f} px")
        a, b = rows[0]["cursor_travel_px"], rows[1]["cursor_travel_px"]
        if max(a, b) > 0:
            print(f"  difference: {abs(a - b) / max(a, b) * 100:.1f} %")
        print()

    if which in ("all", "tune"):
        print("shake threshold vs cursor drift after 10 s of a still, shaky hand")
        for ms, near, far, sweep in scenario_tune():
            print(f"  min speed {ms:.2f} palm/s: drift {near:5.1f} px @1m, "
                  f"{far:5.1f} px @3m, 15 cm/s sweep still moves {sweep:.0f} px")
        print()

    if which in ("all", "gestures"):
        print("gesture sequence at 3 m (time, state, action)")
        for t, state, action in scenario_gestures():
            print(f"  {t:5.2f}s  {state:<7} {action}")
        print()

    if which in ("all", "scroll"):
        print("two-finger scroll at 3 m, 2 s held each way (wheel steps)")
        for way, steps in scenario_scroll():
            first = f"{steps[0]:.2f}s" if steps else "never"
            print(f"  {way:<4}: {len(steps):2d} steps, first at {first}")
        print()

    if which in ("all", "switch"):
        print("screen switch: two fingers pointed left/right at 3 m, held 3 s "
              "(0.55 s hold, then a 1 s rest)")
        for way, fired in scenario_switch():
            if fired:
                when = ", ".join(f"{t:.2f}s" for t, _ in fired)
                print(f"  two {way:<5}: {len(fired)} command(s) at {when}")
            else:
                print(f"  two {way:<5}: never fired")
        print()

    if which in ("all", "focus"):
        print("auto-zoom at 1280x720 (share = how much of the model input the hand "
              "fills, which is what decides if it is findable)")
        for r in scenario_focus():
            print(f"  {r['distance_m']:.1f} m: hand {r['hand_px']:4.0f} px -> crop "
                  f"{r['crop_px']:4.0f} px at {r['zoom']:.1f}x: fills "
                  f"{r['focus'] * 100:3.0f}%  (whole-frame scan "
                  f"{r['whole'] * 100:3.0f}%, one scan tile {r['tile'] * 100:3.0f}%), "
                  f"preview {r['preview']:.1f}x")
        print()

    if which in ("all", "follow"):
        print("preview zoom easing at 1280x720 (window every 0.1 s; a cut would "
              "cover the whole distance in one frame)")
        samples, step = scenario_follow()
        for t, cx, w, whole in samples:
            if whole:
                print(f"  {t:4.1f}s  whole frame")
            else:
                print(f"  {t:4.1f}s  side {w:4.0f} px  centre x {cx:4.0f}  "
                      f"({1280.0 / w:.1f}x)")
        print(f"  largest single-frame pan: {step:.1f} px\n")

    if which in ("all", "cursor"):
        print("aiming reticle radius vs distance (HUD, pointing hand, ACTIVE only)")
        for d, r in scenario_cursor():
            print(f"  {d:.1f} m: {r:4.1f} px radius")
        print()

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
