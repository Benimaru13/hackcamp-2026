"""fake_hand.py  --  synthetic MediaPipe-style hands, no camera required.

Shared by tests/ and simulate.py. Coordinates are normalized frame
coordinates (0..1, y grows downward) so they drop straight into
gesture_cursor.py. Local hand geometry is in palm-lengths with the wrist at
the origin and the fingers pointing up (-y).
"""
from __future__ import annotations

import math
import random


class Point:
    """Same shape as a MediaPipe NormalizedLandmark: .x .y .z."""
    __slots__ = ("x", "y", "z")

    def __init__(self, x, y, z=0.0):
        self.x, self.y, self.z = x, y, z

    def __repr__(self):
        return f"Point({self.x:.4f}, {self.y:.4f})"


# knuckle position and outward direction (in palm-lengths, y up = negative)
_FINGERS = {
    "index": ((-0.36, -0.95), (-0.10, -1.00)),
    "middle": ((0.00, -1.00), (0.00, -1.00)),
    "ring": ((0.30, -0.92), (0.09, -1.00)),
    "pinky": ((0.56, -0.80), (0.20, -1.00)),
}

# which fingers are extended per pose
_EXTENDED = {
    "point": {"index"},
    "palm": {"index", "middle", "ring", "pinky"},
    "pinch": {"index"},
    "fist": set(),
    "relaxed": set(),
    "o": set(),                                   # ring: every finger curled
    "ok": {"middle", "ring", "pinky"},           # the OK sign: three fingers up
}

_THUMB_OPEN = [(0.30, 0.02), (0.62, -0.22), (0.86, -0.46), (1.06, -0.68)]
# A fist wraps the thumb across the front of the curled fingers, so its tip ends
# up between the index and middle knuckles -- close enough to the folded index tip
# to measure like a pinch. Only the knuckle distance keeps it out of the ring.
_THUMB_TUCK = [(0.30, 0.02), (0.50, -0.35), (0.10, -0.80), (-0.18, -1.02)]

# Poses where the thumb tip meets the index tip. Schematic: the thumb is drawn
# longer than a real one, but the two numbers that decide the classification are
# real -- the tip gap and the loop's distance from the index knuckle.
_O_THUMB = [(0.30, 0.02), (0.18, -0.55), (-0.05, -1.05), (0.13, -1.29)]
_O_INDEX = [(-0.36, -0.95), (-0.28, -1.33), (-0.10, -1.42), (0.12, -1.30)]
_OK_THUMB = [(0.30, 0.02), (0.20, -0.45), (-0.05, -0.95), (0.05, -1.20)]
_OK_INDEX = [(-0.36, -0.95), (-0.25, -1.30), (-0.10, -1.35), (0.04, -1.21)]
_LOOP = {"o": (_O_THUMB, _O_INDEX), "ok": (_OK_THUMB, _OK_INDEX)}


def hand_template_finger_tip(name="index"):
    """Tip of an extended finger, in palm-length units."""
    mcp, d = _FINGERS[name]
    n = math.hypot(*d)
    return (mcp[0] + d[0] / n * 1.02, mcp[1] + d[1] / n * 1.02)


def hand_template(pose="point"):
    """21 (x, y) points, wrist first, in palm-length units."""
    ext = _EXTENDED.get(pose, _EXTENDED["point"])
    pts = [(0.0, 0.0)]                      # 0 wrist

    loop_thumb, loop_index = _LOOP.get(pose, (None, None))
    if loop_thumb:
        thumb = list(loop_thumb)
    else:
        thumb = list(_THUMB_OPEN if pose != "fist" else _THUMB_TUCK)
    if pose == "pinch":
        # thumb tip meets the extended index tip, as in a real pinch
        index_tip = hand_template_finger_tip("index")
        thumb = [(0.30, 0.02), (0.20, -0.60), (-0.10, -1.35),
                 (index_tip[0] + 0.01, index_tip[1] + 0.01)]
    pts += thumb[:4]                        # 1..4 thumb

    for name in ("index", "middle", "ring", "pinky"):
        if name == "index" and loop_index:
            pts += list(loop_index)         # index folded into the circle
            continue
        mcp, d = _FINGERS[name]
        n = math.hypot(*d)
        ux, uy = d[0] / n, d[1] / n
        if name in ext:
            pip = (mcp[0] + ux * 0.50, mcp[1] + uy * 0.50)
            dip = (mcp[0] + ux * 0.78, mcp[1] + uy * 0.78)
            tip = (mcp[0] + ux * 1.02, mcp[1] + uy * 1.02)
        else:                                # curled: tip folds back toward the palm
            pip = (mcp[0] + ux * 0.42, mcp[1] + uy * 0.42)
            dip = (mcp[0] + ux * 0.28, mcp[1] + uy * 0.28)
            tip = (mcp[0] + ux * 0.10, mcp[1] + uy * 0.12)
        pts += [mcp, pip, dip, tip]         # mcp, pip, dip, tip

    return pts[:21]


_SLOT = {1: "thumb", 5: "index", 9: "middle", 13: "ring", 17: "pinky"}


def palm_for_distance(distance_m, visible_m_at_3m=2.4, palm_cm=9.0):
    """Normalized palm length for a hand `distance_m` from a 60 deg webcam.
    The frame is ~2.4 m wide at 3 m, so it scales linearly with depth."""
    visible_w = visible_m_at_3m * max(distance_m, 0.2) / 3.0
    return (palm_cm / 100.0) / visible_w


class FakeHand:
    """A hand you can pose, move and shake. `jitter` is in normalized units
    (per-axis gaussian sigma), which is how detector noise actually behaves:
    roughly constant in pixels at the camera, so it matters more far away."""

    def __init__(self, cx=0.5, cy=0.5, palm=0.075, pose="point", angle=0.0,
                 jitter=0.0, seed=1):
        self.cx, self.cy = cx, cy
        self.palm = palm
        self.pose = pose
        self.angle = angle
        self.jitter = jitter
        self._rng = random.Random(seed)

    def landmarks(self, pose=None):
        if pose is not None:
            self.pose = pose
        ca, sa = math.cos(self.angle), math.sin(self.angle)
        out = []
        for lx, ly in hand_template(self.pose):
            rx, ry = lx * ca - ly * sa, lx * sa + ly * ca
            x = self.cx + rx * self.palm
            y = self.cy + ry * self.palm
            if self.jitter:
                x += self._rng.gauss(0.0, self.jitter)
                y += self._rng.gauss(0.0, self.jitter)
            out.append(Point(x, y))
        return out

    def move(self, dx=0.0, dy=0.0):
        self.cx += dx
        self.cy += dy
        return self

    def at_distance(self, distance_m, **kw):
        """Resize the hand as if it were `distance_m` from the camera."""
        self.palm = palm_for_distance(distance_m, **kw)
        return self
