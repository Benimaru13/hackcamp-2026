"""simulate.py  --  AirTrack without a camera (uses synthetic landmarks).

This is the fastest way for anyone on the team (no camera, no Mac, no
permissions) to check the interaction logic and to measure the two things that
matter for the 10-foot demo:

  * shake tolerance  -- how far does the cursor drift when the hand is still
                        and the detector is noisy, at 1 m and at 3 m?
  * distance match   -- does the same physical hand sweep move the cursor the
                        same distance near and far?

Run:  python simulate.py            (all scenarios)
      python simulate.py still      (one scenario: still | move | tune | gestures)
"""
from __future__ import annotations

import sys
import time

from fake_hand import FakeHand, palm_for_distance
from gesture_cursor import Config, ControlState, CursorController


DT = 1.0 / 30.0
JITTER_PX = 2.0          # detector noise on a still hand, in 1280-px frame pixels


def _jitter_norm(px=JITTER_PX, frame_w=1280):
    return px / frame_w


def _new(distance_m=1.0, click_mode="pinch", **cfg_kw):
    cfg = Config(click_mode=click_mode, **cfg_kw)
    ctrl = CursorController(cfg)
    hand = FakeHand(pose="point", jitter=_jitter_norm(), seed=7).at_distance(distance_m)
    return ctrl, hand, cfg


def scenario_still(distance_m, seconds=5.0):
    """Hand pointed at the screen and held still: the cursor must not wander."""
    ctrl, hand, cfg = _new(distance_m)
    t = 0.0
    for _ in range(int(0.9 / DT)):                  # arm with a palm
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
    for _ in range(30):                       # arm with a palm
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
    """Full interaction: palm to arm, point to move, pinch to click, fist to stop."""
    logs = []
    ctrl = CursorController(Config(click_mode="pinch"))
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
    run("pinch", 0.3)                 # click
    run("point", 0.5)
    run("pinch", 0.3)                 # second click
    run("point", 0.4)
    run("fist", 0.6)                  # releases
    run("palm", 0.4)                  # ignored: arm cooldown
    run("palm", 1.0)                  # re-arms
    return logs


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
        print("still hand, 2 px detector noise, 5 s held:")
        for d in (1.0, 3.0):
            r = scenario_still(d)
            print(f"  {d:.0f} m (palm {r['palm_norm']*100:.1f}% of frame): "
                  f"state={r['state']}, drift={r['max_drift_px']:.1f} px, "
                  f"cursor step={r['mean_step_px']:.2f} px/frame, "
                  f"accidental clicks={r['clicks']}")
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

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
