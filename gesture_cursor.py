"""
gesture_cursor.py  --  AirTrack core logic (no camera, no OS calls)

Pipeline:  MediaPipe landmarks
        -> pose classification (point / palm / fist / pinch)
        -> state machine   ARMED --(open palm held)--> ACTIVE --(fist held)--> ARMED
        -> hand position converted to palm-lengths (identical at every distance)
        -> One Euro smoothing + deadzone in that space (shake tolerance)
        -> relative cursor movement + pinch click (or dwell click)

Everything here is pure Python and landmark-agnostic: a landmark is any object
with .x and .y in normalized frame coordinates (0..1). That means the whole
interaction can be unit tested, simulated, and shared with teammates who have no
camera, no Mac and no pyautogui. Only app.py talks to the webcam and the cursor.

Why palm-lengths: the hand is ~30 px wide at 3 m and ~130 px at 1 m. Dividing
every movement and threshold by the wrist-to-knuckle distance makes them the same
physical size, so one set of numbers works at any distance from the camera.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass
from enum import Enum

PINCH_RATIO = 0.38        # thumb-index gap / palm length below which it is a pinch


# ---------------------------------------------------------------- config
@dataclass
class Config:
    """All tunables. Hand movement is measured in "palm lengths" (wrist ->
    middle knuckle, about 9 cm on an adult hand), so one number works at 1 m and
    at 3 m."""
    screen_w: int = 1440
    screen_h: int = 900
    frame_w: int = 1280          # camera frame width, only for the distance readout

    # --- cursor movement (relative / mouse-like) ---------------------------
    # Screen widths the cursor travels per palm-length the hand travels.
    # 0.40 => ~25 cm of hand travel crosses a 1440 px wide screen.
    speed: float = 0.40
    # Hand speed (palm-lengths per second) that must be exceeded before the
    # cursor moves at all -- the main shake tolerance knob. 0.5 palm-lengths/s
    # is about 4-5 cm of hand movement per second: below that, nothing moves.
    min_speed: float = 1.00
    mirror: bool = True          # webcam preview is mirrored: hand right = cursor right
    grab_point: int = 8          # landmark that drives the cursor (8 = index tip)
    max_jump_px: float = 140.0   # per-frame clamp: a tracking glitch cannot teleport
    # Keep the cursor this many pixels away from the screen edges. PyAutoGUI's
    # fail-safe trips on the exact corner pixels, so gesture control must never
    # park there -- it would kill the app in normal use instead of on purpose.
    edge_margin: int = 8

    # --- One Euro smoothing, applied in PALM-LENGTHS (distance independent) --
    # Cutoffs are in hand-lengths per second, not pixels, so the same value
    # gives the same feel near and far.
    min_cutoff: float = 0.7      # lower = steadier when still, but laggier
    beta: float = 1.2            # higher = less lag during fast movement
    d_cutoff: float = 0.4        # velocity smoothing; lower = steadier threshold

    # --- click: pinch ----------------------------------------------------
    click_mode: str = "pinch"    # "pinch" (deliberate) or "dwell" (holds still)
    pinch_ratio: float = PINCH_RATIO
    pinch_context: float = 0.50  # pinch only counts just after a pointing frame
    click_cooldown: float = 0.45

    # --- click: dwell ----------------------------------------------------
    dwell_time: float = 2.0
    dwell_radius: float = 0.20   # wobble allowed while dwelling (palm-lengths)
    stick_after: float = 0.5     # snap to the anchor so the click lands where intended
    post_click_lock: bool = True

    # --- state machine ---------------------------------------------------
    arm_hold: float = 0.55       # open palm held this long arms control
    stop_hold: float = 0.35      # fist held this long releases control
    arm_cooldown: float = 0.60   # ignore the arm gesture right after a release
    lost_timeout: float = 2.0    # hand gone this long while ACTIVE => release control
    enter_frames: int = 3        # debounce: fast to accept a pose
    exit_frames: int = 4         # slow to drop it (handles 1-2 dropped frames)

    # --- misc ------------------------------------------------------------
    palm_cm: float = 9.0         # assumed palm length, only for the distance readout
    hfov_deg: float = 60.0       # assumed horizontal FOV, only for the readout


# ---------------------------------------------------------------- One Euro filter
class OneEuro:
    """Adaptive low-pass filter: heavy smoothing when still (removes jitter),
    light smoothing when moving fast (keeps latency low)."""

    def __init__(self, min_cutoff, beta, d_cutoff=1.0):
        self.min_cutoff, self.beta, self.d_cutoff = min_cutoff, beta, d_cutoff
        self.reset()

    def reset(self):
        self.x_prev = self.dx_prev = self.t_prev = None

    @staticmethod
    def _alpha(cutoff, dt):
        tau = 1.0 / (2 * math.pi * cutoff)
        return 1.0 / (1.0 + tau / dt)

    def __call__(self, x, t):
        # x_hat: smoothed position.  v_hat: smoothed velocity in units/second
        # (the filter already tracks it, so it is the natural speed signal).
        if self.t_prev is None:
            self.x_prev, self.dx_prev, self.t_prev = x, 0.0, t
            self.x_hat, self.v_hat = x, 0.0
            return x
        dt = max(t - self.t_prev, 1e-6)
        dx = (x - self.x_prev) / dt
        a_d = self._alpha(self.d_cutoff, dt)
        dx_hat = a_d * dx + (1 - a_d) * self.dx_prev
        cutoff = self.min_cutoff + self.beta * abs(dx_hat)
        a = self._alpha(cutoff, dt)
        x_hat = a * x + (1 - a) * self.x_prev
        self.x_prev, self.dx_prev, self.t_prev = x_hat, dx_hat, t
        self.x_hat, self.v_hat = x_hat, dx_hat
        return x_hat


# ---------------------------------------------------------------- landmark helpers
# MediaPipe hand landmark indices
WRIST = 0
THUMB_IP, THUMB_TIP = 3, 4
INDEX_MCP, INDEX_PIP, INDEX_TIP = 5, 6, 8
MIDDLE_MCP, MIDDLE_PIP, MIDDLE_TIP = 9, 10, 12
RING_MCP, RING_PIP, RING_TIP = 13, 14, 16
PINKY_MCP, PINKY_PIP, PINKY_TIP = 17, 18, 20

# (tip, pip) pairs for the four fingers that carry the pose information
_FINGERS = (
    (INDEX_TIP, INDEX_PIP),
    (MIDDLE_TIP, MIDDLE_PIP),
    (RING_TIP, RING_PIP),
    (PINKY_TIP, PINKY_PIP),
)


def _d(a, b):
    return math.hypot(a.x - b.x, a.y - b.y)


def hand_scale(lm):
    """Wrist -> middle knuckle. Shrinks with distance from the camera, so
    dividing by it makes every threshold distance independent."""
    return _d(lm[WRIST], lm[MIDDLE_MCP])


def _extended(lm, tip, pip, k=1.12):
    """Finger is extended when the tip is clearly farther from the wrist than the
    middle joint. Distance to the wrist, not raw y, so it survives hand rotation
    and a camera that is above eye level."""
    w = lm[WRIST]
    return _d(lm[tip], w) > _d(lm[pip], w) * k


def _curled(lm, tip, pip, k=1.02):
    return _d(lm[tip], lm[WRIST]) < _d(lm[pip], lm[WRIST]) * k


def fingers_up(lm):
    return tuple(_extended(lm, tip, pip) for tip, pip in _FINGERS)


def is_pointing(lm):
    """Index extended, other three curled = the cursor pose."""
    idx, mid, ring, pink = fingers_up(lm)
    return idx and not (mid or ring or pink)


def pinch_gap(lm):
    """Thumb-tip to index-tip distance, normalized by palm length.
    Distance independent: ~0 when pinched, >1.5 for a flat open hand."""
    return _d(lm[THUMB_TIP], lm[INDEX_TIP]) / max(hand_scale(lm), 1e-6)


def is_open_palm(lm):
    """All four fingers extended and the thumb held away from the index finger.
    Deliberately excludes the pinch (thumb tip meets index tip), which is the
    click pose -- the reason the "heart" gesture is not used for arming."""
    if not all(fingers_up(lm)):
        return False
    return pinch_gap(lm) > 0.55


def is_fist(lm):
    """All four fingers curled and the fingertips tucked near the palm."""
    if any(fingers_up(lm)):
        return False
    if not all(_curled(lm, tip, pip) for tip, pip in _FINGERS):
        return False
    s = max(hand_scale(lm), 1e-6)
    return all(_d(lm[tip], lm[WRIST]) < 1.45 * s for tip, _ in _FINGERS)


def classify_pose(lm):
    """Single label for the HUD. Precedence: fist (stop) beats pinch (click)
    beats palm (arm) beats point (move)."""
    if lm is None:
        return ""
    if is_fist(lm):
        return "fist"
    if pinch_gap(lm) < PINCH_RATIO:
        return "pinch"
    if is_open_palm(lm):
        return "palm"
    if is_pointing(lm):
        return "point"
    return "hand"


def estimate_distance_cm(lm, frame_w, cfg: Config | None = None):
    """Rough camera distance from apparent hand size, for the HUD only.
    Assumes a ~60 degree webcam lens and a ~9 cm palm; good to about +-25%."""
    cfg = cfg or Config()
    s = hand_scale(lm)
    if s <= 1e-6 or frame_w <= 0:
        return 0.0
    f_px = (frame_w / 2.0) / math.tan(math.radians(cfg.hfov_deg) / 2.0)
    return f_px * cfg.palm_cm / (s * frame_w)


# ---------------------------------------------------------------- debouncer
class Gate:
    """Frame debouncer: fast to enter, slow to leave, optional hold time.
    A pose must be seen `enter_frames` times (and stay for `hold` seconds) to
    open, and must be gone for `exit_frames` frames to close."""

    def __init__(self, enter_frames=3, exit_frames=4):
        self.enter_frames, self.exit_frames = enter_frames, exit_frames
        self.reset()

    def reset(self):
        self.on = False
        self.rose = False        # True only on the frame the gate opens
        self._n_on = self._n_off = 0
        self._t0 = -1e9

    def update(self, now, active, hold=0.0):
        self.rose = False
        if active:
            self._n_off = 0
            if self._n_on == 0:
                self._t0 = now
            self._n_on += 1
            if not self.on and self._n_on >= self.enter_frames and now - self._t0 >= hold:
                self.on = True
                self.rose = True
        else:
            self._n_on = 0
            self._n_off += 1
            if self.on and self._n_off >= self.exit_frames:
                self.on = False
        return self.on

    def hold_fraction(self, now, hold):
        """0..1 feedback while a hold gesture is being performed."""
        if not self.on and self._n_on >= max(self.enter_frames, 1) and hold > 0:
            return min(max((now - self._t0) / hold, 0.0), 1.0)
        return 0.0


# ---------------------------------------------------------------- output
class ControlState(Enum):
    OFF = "off"          # not watching (camera released / user quit)
    ARMED = "armed"      # watching for the arm gesture, cursor untouched
    ACTIVE = "active"    # gestures move and click the real cursor


@dataclass
class Output:
    state: ControlState
    x: float = 0.0
    y: float = 0.0
    action: str | None = None   # "move" | "click" | "release" | "armed" | None
    progress: float = 0.0       # 0..1 feedback for the current hold / dwell
    pose: str = ""
    distance_cm: float = 0.0
    hint: str = ""


# ---------------------------------------------------------------- controller
class CursorController:
    """Landmarks in, state + cursor position + click out. Call update() once per
    frame. It never blocks, never sleeps and does no I/O."""

    def __init__(self, cfg: Config | None = None):
        self.cfg = cfg or Config()
        self.gain = self.cfg.speed * self.cfg.screen_w      # px per palm-length
        self.state = ControlState.ARMED
        self.pos = (self.cfg.screen_w / 2.0, self.cfg.screen_h / 2.0)
        self._reset_tracking()
        self._last_seen = -1e9
        self._pose_t = -1e9
        self._last_click = -1e9
        self._arm_ready_at = -1e9
        self._reset_gates()
        self._reset_dwell()

    # ---- state helpers
    def _reset_tracking(self):
        c = self.cfg
        self._filt_x = OneEuro(c.min_cutoff, c.beta, c.d_cutoff)
        self._filt_y = OneEuro(c.min_cutoff, c.beta, c.d_cutoff)
        self._last_t = None            # previous frame time, for dt

    def _reset_gates(self):
        c = self.cfg
        self._g_palm = Gate(c.enter_frames, c.exit_frames)
        self._g_fist = Gate(c.enter_frames, c.exit_frames)
        self._g_point = Gate(c.enter_frames, c.exit_frames)
        self._g_pinch = Gate(c.enter_frames, c.exit_frames)

    def _reset_dwell(self):
        self._anchor = None
        self._t0 = 0.0
        self._locked = False

    def disarm(self):
        """Off: stop watching. Safe to call from anywhere."""
        self.state = ControlState.OFF
        self._reset_gates()
        self._reset_dwell()

    def arm(self, now=None):
        now = time.monotonic() if now is None else now
        self.state = ControlState.ARMED
        self._reset_tracking()
        self._arm_ready_at = now + 0.3
        self._reset_gates()
        self._reset_dwell()

    def release(self, now=None):
        """Active -> armed. The cursor stays where it is; nothing else is touched."""
        self.arm(now)
        self._arm_ready_at = (time.monotonic() if now is None else now) + self.cfg.arm_cooldown

    def _enter_active(self, now):
        self.state = ControlState.ACTIVE
        self._reset_tracking()
        self._reset_gates()
        self._reset_dwell()

    # ---- cursor movement
    def _move_relative(self, lm, now, apply=True):
        """Mouse-style movement: the hand pushes the cursor, so the same hand
        travel covers the same screen distance at 1 m and at 3 m.

        The fingertip is converted to palm-lengths first, then smoothed. Doing it
        in that order matters: smoothing raw frame positions would filter a signal
        whose noise is 4x bigger at 3 m, so a filter tuned near would still shake
        far away. In palm-lengths the noise is the same everywhere, and it is
        small enough for the deadzone to swallow.
        """
        c = self.cfg
        s = max(hand_scale(lm), 1e-6)
        hx = (lm[c.grab_point].x - 0.5) / s
        hy = (lm[c.grab_point].y - 0.5) / s
        if c.mirror:
            hx = -hx
        fx, fy = self._filt_x(hx, now), self._filt_y(hy, now)   # smooth position
        dt = 0.0 if self._last_t is None else max(now - self._last_t, 0.0)
        self._last_t = now
        if not apply or dt <= 0:
            return False                  # frozen (pinching/idle): drop, never queue up

        # Threshold on hand SPEED, not on a frame-to-frame jump: a shaking hand
        # has near-zero average speed, so it never passes the threshold, while a
        # deliberate move passes it immediately. Jump detection needed a large
        # threshold to reject noise; speed does not, so slow aiming still works.
        vx, vy = self._filt_x.v_hat, self._filt_y.v_hat
        speed = math.hypot(vx, vy)
        if speed <= c.min_speed:
            return False
        k = (speed - c.min_speed) / speed
        step_x, step_y = vx * k * self.gain * dt, vy * k * self.gain * dt

        m = math.hypot(step_x, step_y)
        if m > c.max_jump_px:             # glitch clamp
            step_x *= c.max_jump_px / m
            step_y *= c.max_jump_px / m
        mx = max(0, min(c.edge_margin, c.screen_w // 4))
        my = max(0, min(c.edge_margin, c.screen_h // 4))
        self.pos = (min(max(self.pos[0] + step_x, mx), c.screen_w - 1 - mx),
                    min(max(self.pos[1] + step_y, my), c.screen_h - 1 - my))
        return True

    # ---- dwell click
    def _dwell(self, x, y, now):
        c = self.cfg
        r = c.dwell_radius * self.gain
        if self._anchor is None:
            self._anchor, self._t0 = (x, y), now
            return x, y, 0.0, False
        ax, ay = self._anchor
        if math.hypot(x - ax, y - ay) > r:
            self._anchor, self._t0, self._locked = (x, y), now, False
            return x, y, 0.0, False
        if self._locked:
            return ax, ay, 0.0, False
        elapsed = now - self._t0
        if elapsed >= c.dwell_time:
            self._locked = c.post_click_lock
            if not c.post_click_lock:
                self._t0 = now
            return ax, ay, 1.0, True
        if elapsed >= c.stick_after:
            return ax, ay, elapsed / c.dwell_time, False
        return x, y, elapsed / c.dwell_time, False

    # ---- main entry point: call once per frame
    def update(self, lm, now=None) -> Output:
        now = time.monotonic() if now is None else now
        c = self.cfg
        pose = classify_pose(lm)
        has_hand = lm is not None and hand_scale(lm) > 1e-6
        dist = estimate_distance_cm(lm, c.frame_w, c) if has_hand else 0.0

        if self.state is ControlState.OFF:
            return Output(self.state, *self.pos)

        # every gate advances every frame, whatever the state
        if has_hand:
            self._last_seen = now
        self._g_palm.update(now, pose == "palm", c.arm_hold)
        self._g_fist.update(now, pose == "fist", c.stop_hold)
        self._g_point.update(now, pose == "point")
        self._g_pinch.update(now, has_hand and pinch_gap(lm) < c.pinch_ratio)

        # ------------------------------------------------ ARMED
        if self.state is ControlState.ARMED:
            if self._g_palm.rose and now >= self._arm_ready_at:
                self._enter_active(now)
                return Output(self.state, *self.pos, action="armed", pose=pose,
                              distance_cm=dist, hint="control taken")
            prog = 0.0
            hint = "hold an open palm to take control"
            if pose == "palm" and now >= self._arm_ready_at:
                prog = self._g_palm.hold_fraction(now, c.arm_hold)
                hint = "keep holding..."
            return Output(self.state, *self.pos, progress=prog, pose=pose,
                          distance_cm=dist, hint=hint)

        # ------------------------------------------------ ACTIVE
        if self._g_fist.rose:
            self.release(now)
            return Output(self.state, *self.pos, action="release", pose=pose,
                          distance_cm=dist, hint="control released")
        if not has_hand and now - self._last_seen > c.lost_timeout:
            self.release(now)
            return Output(self.state, *self.pos, action="release", pose="",
                          hint="hand lost -> control released")

        # a pinch freezes the cursor: the fingers meeting must not drag the pointer.
        # Uses the raw pose, not the debounced one, so the very first pinch frame
        # already stops movement.
        frozen = c.click_mode == "pinch" and has_hand and pinch_gap(lm) < c.pinch_ratio
        if self._g_point.on:
            self._pose_t = now

        action = None
        progress = 0.0
        if has_hand:
            if self._move_relative(lm, now, apply=self._g_point.on and not frozen):
                action = "move"

        if c.click_mode == "pinch":
            if has_hand:
                gap = pinch_gap(lm)
                progress = max(0.0, min(1.0, 1.0 - gap / max(c.pinch_ratio, 1e-6)))
            if (self._g_pinch.rose
                    and now - self._pose_t < c.pinch_context
                    and now - self._last_click > c.click_cooldown):
                self._last_click = now
                action = "click"
                self._reset_dwell()
            elif self._g_point.on:
                self._reset_dwell()
        else:  # dwell
            if has_hand and self._g_point.on:
                x, y, progress, clicked = self._dwell(*self.pos, now)
                self.pos = (x, y)
                if clicked and now - self._last_click > c.click_cooldown:
                    self._last_click = now
                    action = "click"
            else:
                self._reset_dwell()

        hint = ("point to move, pinch to click" if c.click_mode == "pinch"
                else "point to move, hold still to click")
        return Output(self.state, *self.pos, action=action, progress=progress,
                      pose=pose, distance_cm=dist, hint=hint)
