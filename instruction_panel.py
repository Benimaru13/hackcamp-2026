"""instruction_panel.py -- the frosted tutorial panel shown after measuring.

It answers "what do I do now?" without leaving the app: what was measured, what
ARMED and ACTIVE mean, and every gesture with the hold this run is actually
using. It is drawn into a frame the app already shows, so it costs no window, no
browser and no focus -- calibration finishes, the tracker takes the camera it
already has, and the first thing the preview shows is this. It fades away by
itself the moment you take control, so it never sits between you and the
computer.

OpenCV has no backdrop blur, so the glass is an honest approximation: blur the
pixels behind the panel, tint them, soften the edge and light the top rim. Over a
dark camera feed that reads as frosted glass.

    draw_instruction_panel(frame, profile, cfg)          # bottom, centred
    draw_instruction_panel(frame, profile, cfg, corner="center")
"""
from __future__ import annotations

import cv2
import numpy as np

TINT = (30, 26, 22)          # panel body, BGR
RIM = (118, 114, 108)        # 1 px edge
RIM_LIGHT = (198, 194, 188)  # top rim, where the light catches
INK = (240, 238, 234)
MUTED = (152, 147, 140)
ACCENT = (212, 234, 94)      # the calibration screen's teal
AMBER = (0, 176, 255)        # the app's ARMED colour
GREEN = (90, 255, 120)       # the app's ACTIVE colour
FONT = cv2.FONT_HERSHEY_DUPLEX


# ------------------------------------------------------------------ geometry
def _rounded_mask(h, w, radius):
    """Soft-edged rounded rectangle, 0..1, to composite the glass through."""
    r = int(max(0, min(radius, min(h, w) // 2)))
    m = np.zeros((h, w), np.uint8)
    if r == 0:
        m[:] = 255
    else:
        cv2.rectangle(m, (r, 0), (w - r, h), 255, -1)
        cv2.rectangle(m, (0, r), (w, h - r), 255, -1)
        for cx, cy in ((r, r), (w - r, r), (r, h - r), (w - r, h - r)):
            cv2.circle(m, (cx, cy), r, 255, -1, cv2.LINE_AA)
    m = cv2.GaussianBlur(m, (5, 5), 0)
    return m.astype(np.float32) / 255.0


def _rounded_path(x0, y0, x1, y1, r):
    """Rounded-rectangle outline as a polyline (cv2.ellipse angles are a trap)."""
    r = int(max(0, min(r, (x1 - x0) // 2, (y1 - y0) // 2)))
    pts = []
    for cx, cy, a0 in ((x0 + r, y0 + r, 180), (x1 - r, y0 + r, 270),
                       (x1 - r, y1 - r, 0), (x0 + r, y1 - r, 90)):
        for i in range(9):
            a = np.deg2rad(a0 + 90.0 * i / 8.0)
            pts.append((int(cx + r * np.cos(a)), int(cy + r * np.sin(a))))
    return np.array(pts, np.int32)


# ------------------------------------------------------------------ glass
def frosted(canvas, box, radius=16, alpha=0.84, blur=25, tint=TINT):
    """Composite a frosted panel into `box` on `canvas` (in place, returns it)."""
    h, w = canvas.shape[:2]
    x0, y0, x1, y1 = box
    x0, y0 = max(0, int(x0)), max(0, int(y0))
    x1, y1 = min(w, int(x1)), min(h, int(y1))
    if x1 - x0 < 4 or y1 - y0 < 4 or alpha <= 0:
        return canvas

    roi = canvas[y0:y1, x0:x1]
    k = int(blur) | 1
    backdrop = cv2.GaussianBlur(roi, (k, k), 0).astype(np.float32)
    body = backdrop * 0.40 + np.array(tint, np.float32) * 0.60
    mask = _rounded_mask(y1 - y0, x1 - x0, int(radius))[..., None] * float(alpha)
    mixed = roi.astype(np.float32) * (1.0 - mask) + body * mask
    canvas[y0:y1, x0:x1] = np.clip(mixed, 0, 255).astype(np.uint8)

    path = _rounded_path(x0, y0, x1, y1, int(radius))
    overlay = canvas.copy()
    cv2.polylines(overlay, [path], True, RIM, 1, cv2.LINE_AA)
    cv2.line(overlay, (x0 + int(radius), y0 + 1), (x1 - int(radius), y0 + 1),
             RIM_LIGHT, 1, cv2.LINE_AA)
    k_alpha = max(0.0, min(float(alpha), 1.0))
    canvas[:] = cv2.addWeighted(overlay, k_alpha, canvas, 1.0 - k_alpha, 0)
    return canvas


# ------------------------------------------------------------------ content
def _summary(profile):
    """One line of what was actually measured, or an honest 'defaults'."""
    if profile is None:
        return "nothing measured - built-in defaults"
    if getattr(profile, "tremor_hz", 0.0) > 0:
        return (f"shake {profile.tremor_px:.1f} px  |  {profile.tremor_hz:.1f} Hz"
                f"  |  {profile.jitter_score}/100  |  {profile.distance_ft:.1f} ft")
    return (f"shake {profile.jitter_px:.1f} px  |  {profile.jitter_score}/100"
            f"  |  {profile.distance_ft:.1f} ft")


def _states():
    """What the two live states mean, in the colours the halo uses."""
    return (
        ("ARMED", AMBER, "watching - your cursor is untouched"),
        ("ACTIVE", GREEN, "gestures are driving the computer"),
    )


def _gestures(cfg):
    """What to do, with the holds and thresholds this run is actually using."""
    arm = getattr(cfg, "arm_hold", 0.6)
    dwell = getattr(cfg, "dwell_time", 2.0)
    switch = getattr(cfg, "switch_hold", getattr(cfg, "swipe_hold", 0.55))
    stop = getattr(cfg, "stop_hold", 0.35)
    return (
        ("1", "Open palm", f"hold {arm:.1f} s", "take control"),
        ("2", "Point", "", "move the cursor"),
        ("3", "Point, still", f"hold {dwell:.1f} s", "one click"),
        ("4", "Two fingers up/down", "hold", "scroll"),
        ("5", "Two fingers left/right", f"hold {switch:.1f} s", "switch space"),
        ("6", "Fist", f"hold {stop:.2f} s", "release"),
    )


def _layout(shape, corner, n_states, n_rows, s):
    """Panel box + the vertical rhythm the drawing pass uses. One source of truth."""
    h, w = shape[:2]
    pad = int(26 * s)
    title_h = int(36 * s)
    head_h = int(34 * s)
    row_h = int(30 * s)
    state_h = int(52 * s)
    foot_h = int(34 * s)
    body_h = max(state_h * n_states, row_h * n_rows)
    ph = int(min(pad * 2 + title_h + head_h + body_h + foot_h, h - 2 * pad))
    pw = int(min(max(w * 0.80, 640 * s), w - 2 * pad))
    if corner == "center":
        x0, y0 = (w - pw) // 2, (h - ph) // 2
    elif corner == "bl":
        x0, y0 = pad, h - ph - pad
    else:
        x0, y0 = (w - pw) // 2, h - ph - pad
    return {"box": (x0, y0, x0 + pw, y0 + ph), "pad": pad, "title_h": title_h,
            "head_h": head_h, "row_h": row_h, "state_h": state_h,
            "foot_h": foot_h, "body_h": body_h, "left_w": int(pw * 0.38),
            "scale": s}


# ------------------------------------------------------------------ panel
def draw_instruction_panel(frame, profile=None, cfg=None, alpha=1.0,
                           corner="bottom"):
    """Draw the tutorial panel onto `frame` and return it (a copy unless alpha<=0)."""
    if frame is None or alpha <= 0:
        return frame
    out = frame.copy()
    s = out.shape[0] / 720.0
    states = _states()
    gestures = _gestures(cfg) if cfg is not None else (
        ("1", "Open palm", "hold 0.6 s", "take control"),
        ("2", "Point", "", "move the cursor"),
        ("3", "Point, still", "hold 2.0 s", "one click"),
        ("4", "Two fingers up/down", "hold", "scroll"),
        ("5", "Two fingers left/right", "hold 0.6 s", "switch space"),
        ("6", "Fist", "hold 0.35 s", "release"))
    lay = _layout(out.shape, corner, len(states), len(gestures), s)

    out = frosted(out, lay["box"], radius=int(16 * s),
                  alpha=0.86 * float(alpha), blur=max(3, int(25 * s)))
    x0, y0, x1, _ = lay["box"]
    x = x0 + lay["pad"]
    right = x1 - lay["pad"]
    s = lay["scale"]
    y = y0 + lay["pad"] + int(22 * s)

    # Title row: name, what this is, and what it measured.
    cv2.putText(out, "AIRTRACK", (x, y), FONT, 0.60 * s, ACCENT,
                max(1, int(2 * s)), cv2.LINE_AA)
    (tw, _), _ = cv2.getTextSize("AIRTRACK", FONT, 0.60 * s, max(1, int(2 * s)))
    cv2.putText(out, "how to use it", (x + tw + int(14 * s), y), FONT, 0.42 * s,
                INK, 1, cv2.LINE_AA)
    summary = _summary(profile)
    (sw_, _), _ = cv2.getTextSize(summary, FONT, 0.38 * s, 1)
    cv2.putText(out, summary, (right - sw_, y), FONT, 0.38 * s, MUTED, 1,
                cv2.LINE_AA)
    y += lay["title_h"]
    cv2.line(out, (x, y - int(10 * s)), (right, y - int(10 * s)), (70, 66, 61), 1,
             cv2.LINE_AA)

    # Column headings.
    left_x = x
    right_x = x + lay["left_w"]
    cv2.putText(out, "STATES", (left_x, y + int(12 * s)), FONT, 0.34 * s, MUTED, 1,
                cv2.LINE_AA)
    cv2.putText(out, "GESTURES", (right_x, y + int(12 * s)), FONT, 0.34 * s, MUTED,
                1, cv2.LINE_AA)
    y += lay["head_h"]

    # Left: ARMED / ACTIVE, in the halo's own colours.
    for i, (name, color, meaning) in enumerate(states):
        sy = y + i * lay["state_h"] + int(12 * s)
        cv2.circle(out, (left_x + int(6 * s), sy - int(4 * s)), int(6 * s), color,
                   -1, cv2.LINE_AA)
        cv2.putText(out, name, (left_x + int(20 * s), sy), FONT, 0.46 * s, color, 1,
                    cv2.LINE_AA)
        cv2.putText(out, meaning, (left_x, sy + int(20 * s)), FONT, 0.33 * s, MUTED,
                    1, cv2.LINE_AA)

    # Right: one line per gesture, effect flush right so the list reads as a table.
    for i, (num, gesture, hold, effect) in enumerate(gestures):
        gy = y + i * lay["row_h"] + int(14 * s)
        cv2.circle(out, (right_x + int(9 * s), gy - int(4 * s)), int(9 * s), ACCENT,
                   1, cv2.LINE_AA)
        (nw, nh), _ = cv2.getTextSize(num, FONT, 0.32 * s, 1)
        cv2.putText(out, num, (right_x + int(9 * s) - nw // 2, gy - int(4 * s) + nh // 2),
                    FONT, 0.32 * s, ACCENT, 1, cv2.LINE_AA)
        cv2.putText(out, gesture, (right_x + int(26 * s), gy), FONT, 0.40 * s, INK, 1,
                    cv2.LINE_AA)
        if hold:
            (gw, _), _ = cv2.getTextSize(gesture, FONT, 0.40 * s, 1)
            cv2.putText(out, hold, (right_x + int(34 * s) + gw, gy), FONT, 0.34 * s,
                        MUTED, 1, cv2.LINE_AA)
        (ew, _), _ = cv2.getTextSize(effect, FONT, 0.36 * s, 1)
        cv2.putText(out, effect, (right - ew, gy), FONT, 0.36 * s, INK, 1, cv2.LINE_AA)

    # Footer.
    fy = y0 + lay["pad"] + lay["title_h"] + lay["head_h"] + lay["body_h"]
    cv2.line(out, (x, fy + int(2 * s)), (right, fy + int(2 * s)), (70, 66, 61), 1,
             cv2.LINE_AA)
    cv2.putText(out, "space toggles control  -  Esc or q quits  -  this panel "
                     "fades when you take control",
                (x, fy + int(22 * s)), FONT, 0.34 * s, MUTED, 1, cv2.LINE_AA)
    return out
