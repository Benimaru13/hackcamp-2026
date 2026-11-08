"""instruction_panel.py -- the frosted-glass panel shown right after measuring.

It is drawn into a frame the app is already showing, so the "platform" look costs
no window, no browser and no focus. Calibration finishes, the tracker takes the
camera it already has, and the first thing the preview shows is this panel: what
was measured, and the four gestures in the order they are needed. It fades away
by itself the moment you take control, so it never sits between you and the
computer.

OpenCV has no backdrop blur, so the glass is an honest approximation rather than
the real thing: blur the pixels behind the panel, tint them, soften the edge and
light the top rim. Over a dark camera feed that reads as frosted glass.

    draw_instruction_panel(frame, profile, cfg)          # bottom-left
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
ACCENT = (212, 234, 94)      # the same teal the calibration screen uses
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
    canvas[:] = cv2.addWeighted(overlay, max(0.0, min(float(alpha), 1.0)), canvas,
                                1.0 - max(0.0, min(float(alpha), 1.0)), 0)
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


def _gestures(cfg):
    """The four things to do, with the holds this run is actually using."""
    arm = getattr(cfg, "arm_hold", 0.6)
    dwell = getattr(cfg, "dwell_time", 2.0)
    switch = getattr(cfg, "switch_hold", getattr(cfg, "swipe_hold", 0.55))
    return (
        ("1", "Open palm", f"{arm:.1f} s", "take control"),
        ("2", "Point", "", "cursor follows"),
        ("3", "Hold still", f"{dwell:.1f} s", "click"),
        ("4", "Two fingers", f"{switch:.1f} s", "switch space"),
    )


def _layout(shape, corner, nrows, s):
    """Panel box + the offsets the drawing pass will use. One source of truth."""
    h, w = shape[:2]
    pad = int(26 * s)
    title_h = int(30 * s)
    head_h = int(22 * s)
    rule_h = int(16 * s)
    row_h = int(30 * s)
    foot_h = int(30 * s)
    ph = pad * 2 + title_h + head_h + rule_h + row_h * nrows + foot_h
    pw = int(min(max(w * 0.47, 380 * s), w - 2 * pad))
    ph = int(min(ph, h - 2 * pad))
    if corner == "center":
        x0, y0 = (w - pw) // 2, (h - ph) // 2
    else:
        x0, y0 = pad, h - ph - pad
    return {"box": (x0, y0, x0 + pw, y0 + ph), "pad": pad, "title_h": title_h,
            "head_h": head_h, "rule_h": rule_h, "row_h": row_h, "foot_h": foot_h,
            "scale": s}


def draw_instruction_panel(frame, profile=None, cfg=None, alpha=1.0, corner="bl"):
    """Draw the panel onto `frame` and return it (a copy unless alpha <= 0)."""
    if frame is None or alpha <= 0:
        return frame
    out = frame.copy()
    h, w = out.shape[:2]
    s = h / 720.0
    head = _summary(profile)
    rows = _gestures(cfg) if cfg is not None else (
        ("1", "Open palm", "0.6 s", "take control"),
        ("2", "Point", "", "cursor follows"),
        ("3", "Hold still", "2.0 s", "click"),
        ("4", "Two fingers", "0.6 s", "switch space"))
    lay = _layout(out.shape, corner, len(rows), s)

    out = frosted(out, lay["box"], radius=int(16 * s), alpha=0.84 * float(alpha),
                  blur=max(3, int(25 * s)))
    x0, y0, x1, _ = lay["box"]
    x = x0 + lay["pad"]
    right = x1 - lay["pad"]
    y = y0 + lay["pad"] + int(20 * s)

    cv2.putText(out, "AIRTRACK READY", (x, y), FONT, 0.62 * s, ACCENT,
                max(1, int(2 * s)), cv2.LINE_AA)
    # "the camera is yours" is the one thing worth saying twice
    label = "raise an open palm" if profile is not None else "run calibrate.py"
    (tw, _), _ = cv2.getTextSize(label, FONT, 0.38 * s, 1)
    cv2.putText(out, label, (right - tw, y), FONT, 0.38 * s, MUTED, 1, cv2.LINE_AA)
    y += lay["title_h"]

    cv2.putText(out, head, (x, y), FONT, 0.40 * s, MUTED, 1, cv2.LINE_AA)
    y += lay["head_h"]

    cv2.line(out, (x, y - int(6 * s)), (right, y - int(6 * s)), (70, 66, 61), 1,
             cv2.LINE_AA)
    y += lay["rule_h"]

    for num, gesture, hold, effect in rows:
        cy = y - int(4 * s)
        cv2.circle(out, (x + int(9 * s), cy), int(9 * s), ACCENT, 1, cv2.LINE_AA)
        (nw, nh), _ = cv2.getTextSize(num, FONT, 0.34 * s, 1)
        cv2.putText(out, num, (x + int(9 * s) - nw // 2, cy + nh // 2), FONT,
                    0.34 * s, ACCENT, 1, cv2.LINE_AA)
        cv2.putText(out, gesture, (x + int(28 * s), y), FONT, 0.44 * s, INK, 1,
                    cv2.LINE_AA)
        (hw, _), _ = cv2.getTextSize(hold, FONT, 0.38 * s, 1)
        cv2.putText(out, hold, (x + int(196 * s) - hw, y), FONT, 0.38 * s, MUTED, 1,
                    cv2.LINE_AA)
        cv2.putText(out, effect, (x + int(212 * s), y), FONT, 0.38 * s, INK, 1,
                    cv2.LINE_AA)
        y += lay["row_h"]

    cv2.line(out, (x, y - int(10 * s)), (right, y - int(10 * s)), (70, 66, 61), 1,
             cv2.LINE_AA)
    cv2.putText(out, "fist releases  -  Esc quits  -  this panel fades", (x, y),
                FONT, 0.36 * s, MUTED, 1, cv2.LINE_AA)
    return out
