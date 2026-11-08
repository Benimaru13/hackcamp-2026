"""
gesture_cursor.py  --  AirTrack core logic (no camera, no OS calls)

Pipeline:  MediaPipe landmarks
        -> pose classification (palm / point / fist / pinch)
        -> state machine   ARMED --(open palm held)--> ACTIVE --(fist held)--> ARMED
        -> hand position converted to palm-lengths (identical at every distance)
        -> One Euro smoothing + deadzone in that space (shake tolerance)
        -> relative cursor movement + dwell click (pointing hand held still)

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
PALM_UPRIGHT = 0.35       # cos(tilt): knuckles this far above the wrist count as upright
THUMB_SIDE_REACH = 0.65   # thumb tip this far from the wrist = held straight out


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

    # --- click: the pointing hand held still -----------------------------
    # This is the only click, and it needs the live point pose, so no other pose
    # can fire one. click_cooldown is a belt-and-braces guard against a double
    # fire from a wrist-twitch at the click moment.
    click_cooldown: float = 0.45

    # --- click: dwell ----------------------------------------------------
    dwell_time: float = 2.0
    dwell_radius: float = 0.20   # wobble allowed before the countdown restarts (palm-lengths)
    still_palm: float = 0.15     # hand travel that must back a cursor move (palm-lengths)
    post_click_lock: bool = True

    # --- aiming reticle that grows with distance (HUD only) ----------------
    # At 3-4 m a 6 px dot is invisible from the sofa, and up close a huge ring would
    # just hide the thing being pointed at. The reticle is lerped between these two
    # sizes by the camera distance, so it is small at 1 m and big at 4 m.
    cursor_near_px: float = 14.0   # radius at cursor_near_cm or closer
    cursor_far_px: float = 46.0    # radius at cursor_far_cm or further
    cursor_near_cm: float = 80.0
    cursor_far_cm: float = 320.0

    # --- state machine ---------------------------------------------------
    arm_hold: float = 0.55       # the open palm held this long arms control
    palm_upright: float = PALM_UPRIGHT  # how upright an arming palm has to be
    stop_hold: float = 0.35      # fist held this long releases control
    arm_cooldown: float = 0.60   # ignore the arm gesture right after a release
    lost_timeout: float = 1.2    # hand gone this long while ACTIVE => release control
    enter_frames: int = 3        # debounce: fast to accept a pose
    exit_frames: int = 4         # slow to drop it (handles 1-2 dropped frames)

    # --- two-finger scroll ------------------------------------------------
    scroll_hold: float = 0.20    # hold the V up/down this long before scrolling
    scroll_interval: float = 0.15  # then one wheel step this often

    # --- screen switch: two fingers pointing left or right ----------------
    # The sideways thumb that used to sit here is gone: a thumb held out is also a
    # curled hand, so it kept reading as the stop fist and released control halfway
    # through its own hold. Two extended fingers are the one thing that still reads
    # at 3-4 m, and pointing them sideways is the scroll gesture turned a quarter
    # turn, so the two can never be confused.
    switch_hold: float = 0.55     # hold the sideways V this long for one command
    switch_cooldown: float = 1.0  # then rest this long before input counts again

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


def two_finger_direction(lm):
    """Which way an index+middle V points: "up", "down", "left" or "right".

    Up/down is the slow scroll; left/right is the screen switch, so one pose
    carries both and the direction decides which one you get. Requiring exactly
    those two fingers to be extended keeps an open palm, a fist and a
    single-finger point from ever triggering either.
    """
    if lm is None:
        return None
    idx, mid, ring, pink = fingers_up(lm)
    # Only an OPEN palm is excluded (ring AND pinky up). Requiring them to be
    # perfectly curled rejected a real V pointing down, where the folded fingers
    # foreshorten and read as extended -- that is why scrolling down did nothing.
    if not (idx and mid) or (ring and pink):
        return None
    scale = max(hand_scale(lm), 1e-6)
    dx = ((lm[INDEX_TIP].x - lm[INDEX_MCP].x)
          + (lm[MIDDLE_TIP].x - lm[MIDDLE_MCP].x)) / 2.0
    dy = ((lm[INDEX_TIP].y - lm[INDEX_MCP].y)
          + (lm[MIDDLE_TIP].y - lm[MIDDLE_MCP].y)) / 2.0
    # Image y grows downward, so a negative dy points up. The camera image is
    # not mirrored: the user's right is the image's left (dx < 0).
    if abs(dy) > abs(dx):
        # Vertical is deliberately the lenient axis: the V is the scroll gesture
        # and pointing it down costs the most projection, so demanding a perfectly
        # upright finger read made down fail while up worked.
        if abs(dy) < 0.45 * scale or abs(dx) > 0.7 * scale:
            return None
        return "up" if dy < 0 else "down"
    if abs(dx) < 0.6 * scale or abs(dy) > 0.6 * scale:
        return None
    return "right" if dx < 0 else "left"


def thumb_direction(lm, reach=THUMB_SIDE_REACH):
    """Which way a thumb held straight out to one side points: "left", "right"
    or None. This is the screen-switch gesture.

    Built out of two large, forgiving measurements -- how far the thumb tip is
    from the wrist, and how sideways it sits -- because that is what still reads
    at 3 m in dim light. Fine thumb-to-finger geometry (the one thing the curved
    poses below need) is what kept collapsing. A relaxed or tucked fist keeps
    its thumb close to the wrist, so it never reads as a direction.
    """
    if lm is None or any(fingers_up(lm)):
        return None
    s = max(hand_scale(lm), 1e-6)
    dx = lm[THUMB_TIP].x - lm[WRIST].x
    dy = lm[THUMB_TIP].y - lm[WRIST].y
    if abs(dx) < reach * s or abs(dy) > 0.6 * abs(dx):
        return None
    # The camera image is not mirrored: the user's right is the image's left.
    return "right" if dx < 0 else "left"


def pinch_gap(lm):
    """Thumb-tip to index-tip distance, normalized by palm length.
    Distance independent: ~0 when pinched, >1.5 for a flat open hand."""
    return _d(lm[THUMB_TIP], lm[INDEX_TIP]) / max(hand_scale(lm), 1e-6)


def is_open_palm(lm):
    """All four fingers extended and the thumb held away from the index finger:
    the gesture that takes control.

    Four extended fingers is the one thing the detector still gets right at 10 ft
    in bad light -- thumb geometry (the "O" ring, then the thumbs up) turned to
    mush past about 2 m and read as a fist. The demo values a gesture that always
    works over one that can never happen by accident.
    """
    if not all(fingers_up(lm)):
        return False
    return pinch_gap(lm) > 0.55


def palm_upright(lm, k=PALM_UPRIGHT):
    """cos(tilt) of the palm, from wrist to middle knuckle: ~1.0 for a hand raised
    to the camera, ~0 for a hand resting flat on the desk with the fingers pointing
    away. Generous on purpose (0.35 is about 70 degrees of tilt) -- it only has to
    stop the palm that is lying around in ordinary desk posture, not grade a wave.
    """
    s = max(hand_scale(lm), 1e-6)
    return (lm[WRIST].y - lm[MIDDLE_MCP].y) / s >= k


def is_arm_pose(lm):
    """The arming gesture: an open palm, raised toward the camera.

    The open palm alone was too easy to hit by accident, so it is paired with the
    cheapest, most reliable discriminator there is: is the hand holding itself up?
    No thumb geometry, nothing that collapses at distance.
    """
    return is_open_palm(lm) and palm_upright(lm)


def is_fist(lm):
    """All four fingers curled and the fingertips tucked near the palm."""
    if any(fingers_up(lm)):
        return False
    if not all(_curled(lm, tip, pip) for tip, pip in _FINGERS):
        return False
    s = max(hand_scale(lm), 1e-6)
    return all(_d(lm[tip], lm[WRIST]) < 1.45 * s for tip, _ in _FINGERS)


def classify_pose(lm):
    """Single label for the HUD. Precedence: side thumb, then the two-finger
    screen switch, then fist (stop), pinch, palm (arm), point (move).

    The side thumb still comes before the fist even though the switch is now the
    two-finger point: a thumb held out is also a curled hand, and reading it as a
    fist releases control for nothing. The palm is reported whenever the hand is open;
    whether it is upright enough to actually arm is checked separately
    (is_arm_pose), the same way the fist is only the stop gesture while ACTIVE.
    """
    if lm is None:
        return ""
    side = thumb_direction(lm)
    if side:
        return "thumb_" + side
    v = two_finger_direction(lm)
    if v in ("left", "right"):
        return "two_" + v
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


def cursor_radius_px(distance_cm, cfg: Config | None = None):
    """Radius of the HUD aiming reticle, in frame pixels: small near the camera,
    large far away, eased between `cursor_near_cm` and `cursor_far_cm` and clamped
    outside that range so it never vanishes up close or swallows the screen.

    HUD only, and pure maths: app.py draws the number this returns while the
    pointing hand is live, so the guide you aim with stays visible from 3-4 m.
    (The OS pointer itself belongs to the system and cannot be resized.)
    """
    cfg = cfg or Config()
    lo, hi = cfg.cursor_near_cm, cfg.cursor_far_cm
    if not distance_cm or distance_cm <= 0:
        return cfg.cursor_near_px
    if hi <= lo:
        return cfg.cursor_far_px
    t = min(max((distance_cm - lo) / (hi - lo), 0.0), 1.0)
    t = t * t * (3.0 - 2.0 * t)          # ease in/out: no visible jump at either end
    return cfg.cursor_near_px + t * (cfg.cursor_far_px - cfg.cursor_near_px)


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
            self._n_off += 1
            # A hold gesture survives a couple of dropped frames: at 3 m the
            # landmarks flicker, and restarting the hold on every blink would
            # make the hold impossible to complete.
            if self._n_off >= self.exit_frames:
                self._n_on = 0
                self.on = False
        return self.on

    def hold_fraction(self, now, hold):
        """0..1 feedback while a hold gesture is being performed."""
        if not self.on and self._n_on >= max(self.enter_frames, 1) and hold > 0:
            return min(max((now - self._t0) / hold, 0.0), 1.0)
        return 0.0


class SwitchDetector:
    """Screen switch: point two fingers left or right, hold, get one command.

    This gesture has to be a HOLD, not a stroke. The two earlier versions fired on
    strokes and both misread the hand: firing on the angle of the two-finger V
    fired with the hand standing still, and firing on sideways travel fired on the
    return stroke too -- the hand comes back to where it started within a second,
    so one swipe became two commands, or the wrong one if the first was missed. A
    hold has no return stroke to misread.

    The sideways thumb that replaced those strokes is gone as well: a thumb held
    out is also a curled hand, so it read as the stop fist and released control
    halfway through its own hold. Two extended fingers never read as a fist, and
    they are the gesture that still survives at 4 m.

    Sequence: point the V left or right and hold `hold` seconds -> one command.
    Then the detector rests for `cooldown` seconds, ignoring input entirely, before
    it starts looking again -- so keeping the V up repeats the command every
    hold + cooldown (0.55 s + 1 s) and letting go costs nothing. A direction flip
    restarts the hold, and a couple of dropped frames (`grace`) do not.
    """

    def __init__(self, hold=0.55, cooldown=1.0, grace=0.2):
        self.hold, self.cooldown, self.grace = hold, cooldown, grace
        self._dir = None
        self._t0 = 0.0
        self._seen = -1e9
        self._ready_at = -1e9

    def reset(self):
        self._dir = None
        self._t0 = 0.0
        self._seen = -1e9

    def progress(self, now):
        """0..1 of the hold in progress, for the HUD."""
        if self._dir is None or self.hold <= 0:
            return 0.0
        return min(max((now - self._t0) / self.hold, 0.0), 1.0)

    def update(self, lm, now):
        """"left" / "right" on the frame the hold completes, else None."""
        way = two_finger_direction(lm)
        if way not in ("left", "right"):
            if self._dir is not None and now - self._seen <= self.grace:
                return None                # a blink at 3 m, not a release
            self.reset()
            return None
        if now < self._ready_at:
            self.reset()                   # resting: input is not being looked at
            return None
        if way != self._dir:
            self._dir, self._t0, self._seen = way, now, now
            return None                    # a direction flip restarts the hold
        self._seen = now
        if now - self._t0 < self.hold:
            return None
        # Fired. The rest starts now: nothing counts until it is over, so a hand
        # left pointing switches again every hold + cooldown and no faster.
        self._ready_at = now + self.cooldown
        self.reset()
        return way


class ScrollDetector:
    """Two-finger vertical scroll as a HELD direction with a steady cadence.

    The old version re-timed from the frame the direction was first seen, so one
    flickered frame (constant at 3 m) restarted the cadence and the stream
    stuttered. Worse, the pose test it sat on required the ring and pinky to be
    cleanly curled, which they are not when the V points down: the folded fingers
    foreshorten and read as extended, so down never scrolled at all while up
    worked. Now a short blink keeps the stream alive, the pose only has to not be
    an open palm, and up and down are the same gesture upside down.
    """

    def __init__(self, hold=0.20, interval=0.15, grace=0.15):
        self.hold, self.interval, self.grace = hold, interval, grace
        self.direction = None
        self._t0 = 0.0
        self._seen = -1e9
        self._next = 0.0

    def reset(self):
        self.direction = None
        self._t0 = 0.0
        self._seen = -1e9
        self._next = 0.0

    def progress(self, now):
        """0..1 of the hold before the first step, for the HUD."""
        if self.direction is None or self.hold <= 0:
            return 0.0
        return min(max((now - self._t0) / self.hold, 0.0), 1.0)

    def update(self, lm, now):
        """+1 for one wheel step up, -1 for one down, 0 for none this frame."""
        way = two_finger_direction(lm)
        if way not in ("up", "down"):
            if self.direction is not None and now - self._seen <= self.grace:
                return 0                  # a blink, not a stop
            self.reset()
            return 0
        if way != self.direction:
            self.direction, self._t0, self._seen = way, now, now
            self._next = now + self.hold + self.interval
            return 0                      # re-hold before reversing
        self._seen = now
        if now < self._next:
            return 0
        self._next = now + self.interval
        # One wheel NOTCH per tick, not two: the cadence (interval) sets the speed,
        # so the step size stays 1 and app.py multiplies it by SCROLL_STEP. Returning
        # 2 here silently doubled the scroll rate and broke the cadence tests.
        return 1 if way == "up" else -1


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
        self._prev_f = None            # previous smoothed hand position
        self._hand = (0.0, 0.0)        # smoothed fingertip, normalized frame coords
        self._scale = 1.0              # palm length (normalized) this frame

    def _reset_gates(self):
        c = self.cfg
        self._g_palm = Gate(c.enter_frames, c.exit_frames)
        self._g_fist = Gate(c.enter_frames, c.exit_frames)
        self._g_point = Gate(c.enter_frames, c.exit_frames)

    def _reset_dwell(self, keep_lock=False):
        self._anchor = None        # cursor position where the hover began
        self._hand_at_anchor = (0.0, 0.0)   # fingertip (normalized) at the anchor
        self._anchor_scale = 1.0   # palm length at the anchor
        self._t0 = 0.0
        self._not_point = 0        # consecutive frames without the point pose
        if not keep_lock:
            self._locked = False   # clicked here already: move away to click again

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
        # the pose that opened control must not fire a click on the same frame
        self._last_click = now

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
        self._scale = s
        # Smooth the fingertip in NORMALIZED frame units, not divided by the palm
        # length: dividing an off-centre hand by a noisy scale amplifies that noise
        # by the offset (up to 10x near a frame edge at 3 m), which made a still hand
        # look like it was moving. The palm length is applied to the smoothed
        # DISPLACEMENT instead, where the same noise is only a small relative error.
        sign = -1.0 if c.mirror else 1.0
        fx = self._filt_x(lm[c.grab_point].x, now)
        fy = self._filt_y(lm[c.grab_point].y, now)
        self._hand = (fx, fy)
        dt = 0.0 if self._last_t is None else max(now - self._last_t, 0.0)
        self._last_t = now
        prev, self._prev_f = self._prev_f, (fx, fy)
        if not apply or dt <= 0:
            return False                  # frozen (non-point pose): never queue up

        # Threshold on hand SPEED, in palm-lengths per second: a shaking hand has
        # near-zero average speed, so it never passes the threshold, while a
        # deliberate move passes it immediately.
        speed = math.hypot(self._filt_x.v_hat, self._filt_y.v_hat) / s
        if speed <= c.min_speed or prev is None:
            return False
        # Move by DISPLACEMENT, not by velocity. Integrating the filter's velocity
        # made the cursor coast a couple of hundred pixels after the hand stopped
        # (v_hat decays slowly), which also kept restarting the click countdown.
        step_x = sign * (fx - prev[0]) * self.gain / s
        step_y = (fy - prev[1]) * self.gain / s

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
    def _dwell(self, now):
        """One click per hover, at the spot where the pointing hand came to rest.

        Stillness is judged on the CURSOR, which the speed gate holds still, so
        detector jitter cannot restart the countdown -- the raw fingertip is far too
        noisy for that (2 px is ~0.04 palm-lengths per axis at 3 m). But the gate
        does leak a frame now and then at 3 m, so every judgement that matters is
        corroborated by the smoothed HAND: a move only restarts the countdown if the
        hand travelled with it. "hold still = exactly one click" is then independent
        of gate noise, and the click lands at a true 2 s.

        The lock survives a pose gap: dropping the point pose and pointing again at
        the same spot must not click a second time, because the spot never changed.
        """
        c = self.cfg
        x, y = self.pos
        hx, hy = self._hand
        r = c.dwell_radius * self.gain          # radius in screen pixels
        if self._anchor is None:
            self._anchor, self._hand_at_anchor = (x, y), (hx, hy)
            self._anchor_scale, self._t0 = self._scale, now
            return x, y, 0.0, False
        ax, ay = self._anchor
        moved = (math.hypot(x - ax, y - ay) > r
                 and math.hypot(hx - self._hand_at_anchor[0],
                                hy - self._hand_at_anchor[1])
                 / max(self._anchor_scale, 1e-6) > c.still_palm)
        if moved:
            # A real move to a new spot: restart the countdown, re-arm a used click.
            self._locked = False
            self._anchor, self._hand_at_anchor = (x, y), (hx, hy)
            self._anchor_scale, self._t0 = self._scale, now
            return x, y, 0.0, False
        if self._locked:
            return x, y, 0.0, False             # clicked here already: move away
        elapsed = now - self._t0
        if elapsed >= c.dwell_time:
            self._locked = c.post_click_lock
            self._hand_at_anchor, self._anchor_scale = (hx, hy), self._scale
            self._t0 = now
            return x, y, 1.0, True
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
        self._g_palm.update(now, pose == "palm" and palm_upright(lm, c.palm_upright),
                            c.arm_hold)
        self._g_fist.update(now, pose == "fist", c.stop_hold)
        self._g_point.update(now, pose == "point")

        # ------------------------------------------------ ARMED
        if self.state is ControlState.ARMED:
            if self._g_palm.rose and now >= self._arm_ready_at:
                self._enter_active(now)
                return Output(self.state, *self.pos, action="armed", pose=pose,
                              distance_cm=dist, hint="control taken")
            prog = 0.0
            hint = "raise an open palm to take control"
            if (pose == "palm" and palm_upright(lm, c.palm_upright)
                    and now >= self._arm_ready_at):
                prog = self._g_palm.hold_fraction(now, c.arm_hold)
                hint = "keep holding the palm up..."
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

        action = None
        progress = 0.0
        if has_hand:
            if self._g_point.rose:
                # Unfolding the palm into a point moves the fingertip half a palm in
                # one frame; re-seed the smoothing so it cannot jump the cursor.
                self._reset_tracking()
            # Follow the LIVE point pose, not the debounced gate: the gate keeps
            # itself open for a few frames after the pose changes, and landmark 8
            # jumps half a hand when the fingers fold, so changing gesture used to
            # yank the pointer by up to max_jump_px per frame on the way out.
            if self._move_relative(lm, now,
                                   apply=self._g_point.on and pose == "point"):
                action = "move"

        # The click belongs to the point gesture only, so the dwell runs on the
        # LIVE pose, not on the debounced gate: a fist, palm or pinch cancels a
        # half-finished countdown instead of letting it fire a frame or two after
        # the pose changed (the gate's exit hysteresis allowed exactly that).
        if has_hand and pose == "point":
            self._not_point = 0
            x, y, progress, clicked = self._dwell(now)
            self.pos = (x, y)
            if clicked and now - self._last_click > c.click_cooldown:
                self._last_click = now
                action = "click"
        else:
            # One misread frame must not wipe a half-finished countdown or a click
            # lock: at 3 m a curled finger can flicker across its "extended"
            # threshold and read as palm/hand/pinch for a frame. Cancel with the
            # same hysteresis the pose gates use, so a real pose change still cancels
            # within ~4 frames but sensor flicker does not.
            self._not_point += 1
            if self._not_point >= c.exit_frames:
                self._reset_dwell(keep_lock=True)

        return Output(self.state, *self.pos, action=action, progress=progress,
                      pose=pose, distance_cm=dist,
                      hint="point to move, hold still to click")
