"""
gesture_cursor.py  --  all cursor-coordinate logic

Pipeline: MediaPipe landmarks -> "index finger up" check -> fingertip coordinate
          -> ROI-to-screen mapping -> One Euro filter (jitter removal)
          -> dwell detection (click) -> PyAutoGUI

The core class CursorController does not depend on mediapipe, pyautogui or cv2,
so teammates on Windows can test it with fake landmark data. Only run_demo() at
the bottom talks to the Mac webcam and the real cursor.
"""
import math
import time
from dataclasses import dataclass


# ---------------------------------------------------------------- config
@dataclass
class Config:
    screen_w: int = 1440
    screen_h: int = 900

    # ROI: the region of the camera frame where the hand actually moves
    # (normalized 0-1). A smaller ROI means a small hand movement travels
    # farther on screen (less effort at long range), but jitter is amplified too.
    roi_cx: float = 0.5
    roi_cy: float = 0.5
    roi_w: float = 0.45
    roi_h: float = 0.35
    mirror: bool = True          # webcam image is mirrored: hand right = cursor right

    # One Euro filter (output units: screen pixels)
    min_cutoff: float = 1.0      # lower = steadier when still, but laggier at slow speeds
    beta: float = 0.015          # higher = less lag during fast movement

    # Dwell click
    dwell_time: float = 3.0      # seconds of holding still that count as a click
    base_radius_px: float = 45   # "still" radius when the hand is close to the camera
    max_radius_scale: float = 2.5
    hand_size_ref: float = 0.15  # normalized hand size when close (wrist -> middle MCP)
    stick_after: float = 0.6     # after this long still, snap the cursor to the anchor
                                 # so the click lands where the user intended
    post_click_lock: bool = True # after a click, must leave the radius before clicking again

    # Gesture debouncing (in frames / seconds)
    enter_frames: int = 3
    exit_frames: int = 6
    lost_grace: float = 0.4      # brief hand-tracking dropouts do not interrupt control


# ---------------------------------------------------------------- One Euro filter
class OneEuro:
    """Adaptive low-pass filter: heavy smoothing when still (removes jitter),
    light smoothing when moving fast (keeps latency low)."""

    def __init__(self, min_cutoff, beta, d_cutoff=1.0):
        self.min_cutoff, self.beta, self.d_cutoff = min_cutoff, beta, d_cutoff
        self.x_prev = self.dx_prev = self.t_prev = None

    @staticmethod
    def _alpha(cutoff, dt):
        tau = 1.0 / (2 * math.pi * cutoff)
        return 1.0 / (1.0 + tau / dt)

    def reset(self):
        self.x_prev = self.dx_prev = self.t_prev = None

    def __call__(self, x, t):
        if self.t_prev is None:
            self.x_prev, self.dx_prev, self.t_prev = x, 0.0, t
            return x
        dt = max(t - self.t_prev, 1e-6)
        dx = (x - self.x_prev) / dt
        a_d = self._alpha(self.d_cutoff, dt)
        dx_hat = a_d * dx + (1 - a_d) * self.dx_prev
        cutoff = self.min_cutoff + self.beta * abs(dx_hat)
        a = self._alpha(cutoff, dt)
        x_hat = a * x + (1 - a) * self.x_prev
        self.x_prev, self.dx_prev, self.t_prev = x_hat, dx_hat, t
        return x_hat


# ---------------------------------------------------------------- landmark helpers
# MediaPipe Hands landmark indices
WRIST, INDEX_MCP, INDEX_PIP, INDEX_TIP = 0, 5, 6, 8
MIDDLE_MCP, MIDDLE_PIP, MIDDLE_TIP = 9, 10, 12
RING_PIP, RING_TIP = 14, 16
PINKY_PIP, PINKY_TIP = 18, 20


def _d(a, b):
    return math.hypot(a.x - b.x, a.y - b.y)


def hand_size(lm):
    """Wrist -> middle-finger base, used as a proxy for distance to the camera
    (smaller = farther away)."""
    return _d(lm[WRIST], lm[MIDDLE_MCP])


def is_pointing(lm):
    """Index finger extended, other three fingers curled. Uses distance to the
    wrist rather than raw y, so it still works when the hand is rotated or tilted."""
    w = lm[WRIST]
    index_up = _d(lm[INDEX_TIP], w) > _d(lm[INDEX_PIP], w) * 1.15
    others_down = all(
        _d(lm[tip], w) < _d(lm[pip], w) * 1.05
        for tip, pip in ((MIDDLE_TIP, MIDDLE_PIP), (RING_TIP, RING_PIP), (PINKY_TIP, PINKY_PIP))
    )
    return index_up and others_down


# ---------------------------------------------------------------- controller
@dataclass
class Output:
    pointing: bool          # whether the "index finger up" control state is active
    x: float                # screen coordinate (pixels)
    y: float
    progress: float         # dwell progress 0-1 (drive a progress ring in the UI)
    clicked: bool           # True on the frame a click fires


class CursorController:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.fx = OneEuro(cfg.min_cutoff, cfg.beta)
        self.fy = OneEuro(cfg.min_cutoff, cfg.beta)
        self.pointing = False
        self._on_cnt = self._off_cnt = 0
        self._last_seen = 0.0
        self._pos = (cfg.screen_w / 2, cfg.screen_h / 2)
        self._reset_dwell()

    # ---- coordinate mapping
    def map_to_screen(self, nx, ny):
        c = self.cfg
        if c.mirror:
            nx = 1.0 - nx
        u = (nx - (c.roi_cx - c.roi_w / 2)) / c.roi_w
        v = (ny - (c.roi_cy - c.roi_h / 2)) / c.roi_h
        u = min(max(u, 0.0), 1.0)          # outside the ROI: clamp to the edge, never off-screen
        v = min(max(v, 0.0), 1.0)
        return u * (c.screen_w - 1), v * (c.screen_h - 1)

    # ---- dwell
    def _reset_dwell(self):
        self._anchor = None
        self._t0 = 0.0
        self._locked = False

    def _radius(self, size):
        c = self.cfg
        scale = min(max(c.hand_size_ref / max(size, 1e-3), 1.0), c.max_radius_scale)
        return c.base_radius_px * scale     # smaller hand (farther away) = larger tolerance

    def _dwell(self, x, y, size, now):
        c = self.cfg
        r = self._radius(size)
        if self._anchor is None:
            self._anchor, self._t0 = (x, y), now
            return x, y, 0.0, False
        ax, ay = self._anchor
        if math.hypot(x - ax, y - ay) > r:          # moved outside the radius: restart the timer
            self._anchor, self._t0, self._locked = (x, y), now, False
            return x, y, 0.0, False
        elapsed = now - self._t0
        if self._locked:                             # just clicked: wait for the user to move away
            return ax, ay, 0.0, False
        if elapsed >= c.dwell_time:
            self._locked = c.post_click_lock
            if not c.post_click_lock:
                self._t0 = now
            return ax, ay, 1.0, True
        if elapsed >= c.stick_after:                 # snap: click at the anchor, not at a jittery position
            return ax, ay, elapsed / c.dwell_time, False
        return x, y, elapsed / c.dwell_time, False

    # ---- main entry point: call once per frame
    def update(self, lm, now=None) -> Output:
        now = time.monotonic() if now is None else now
        c = self.cfg
        pointing_now = bool(lm) and is_pointing(lm)

        # Gesture debouncing (fast to enter, slow to exit)
        if pointing_now:
            self._on_cnt, self._off_cnt = self._on_cnt + 1, 0
            self._last_seen = now
        else:
            self._off_cnt += 1
            self._on_cnt = 0
        if not self.pointing and self._on_cnt >= c.enter_frames:
            self.pointing = True
            self.fx.reset(); self.fy.reset()
            self._reset_dwell()
        elif self.pointing and self._off_cnt >= c.exit_frames \
                and now - self._last_seen > c.lost_grace:
            self.pointing = False
            self._reset_dwell()

        if not (self.pointing and pointing_now):
            return Output(self.pointing, *self._pos, 0.0, False)

        sx, sy = self.map_to_screen(lm[INDEX_TIP].x, lm[INDEX_TIP].y)
        sx, sy = self.fx(sx, now), self.fy(sy, now)
        x, y, prog, clicked = self._dwell(sx, sy, hand_size(lm), now)
        self._pos = (x, y)
        return Output(True, x, y, prog, clicked)


# ---------------------------------------------------------------- demo (needs a Mac + webcam)
def run_demo():
    import cv2
    import mediapipe as mp
    import pyautogui

    pyautogui.FAILSAFE = True    # slam the mouse into a screen corner = emergency stop
    pyautogui.PAUSE = 0
    sw, sh = pyautogui.size()
    ctrl = CursorController(Config(screen_w=sw, screen_h=sh))

    cap = cv2.VideoCapture(0)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)    # long range: higher resolution keeps the hand clear
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    hands = mp.solutions.hands.Hands(
        max_num_hands=1, model_complexity=1,
        min_detection_confidence=0.5, min_tracking_confidence=0.5)

    while True:
        ok, frame = cap.read()
        if not ok:
            break
        res = hands.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        lm = res.multi_hand_landmarks[0].landmark if res.multi_hand_landmarks else None
        out = ctrl.update(lm)
        if out.pointing and lm:
            pyautogui.moveTo(out.x, out.y, _pause=False)
            if out.clicked:
                pyautogui.click()
        cv2.putText(frame, f"pointing={out.pointing} dwell={out.progress:.0%}",
                    (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
        cv2.imshow("debug", frame)
        if cv2.waitKey(1) & 0xFF == 27:        # Esc to quit
            break
    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    run_demo()