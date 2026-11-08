"""calibration_math.py -- what the calibrator measures, and the tuning it derives.

Deliberately standalone: no cv2, no camera, no OS calls, and no imports from
gesture_cursor.py or app.py. The AirTrack pipeline belongs to the other branches;
this module only produces numbers it can consume.
"""
from __future__ import annotations

import math


class JitterMeter:
    """RMS of frame-to-frame acceleration of the raw hand point, in pixels.

    A still hand on a good webcam reads about 1 px; a hand at 3 m in poor light
    reads 6-10 px. Measured on the RAW signal, never the smoothed one, so it
    describes the camera and the user rather than any filter.
    """

    def __init__(self):
        self.reset()

    def reset(self):
        self._ema = 0.0
        self._n = 0
        self._prev = None
        self._prev_delta = None

    def push(self, x, y):
        if self._prev is not None:
            dx, dy = x - self._prev[0], y - self._prev[1]
            if self._prev_delta is not None:
                rx = (dx - self._prev_delta[0]) / 2.0
                ry = (dy - self._prev_delta[1]) / 2.0
                sq = rx * rx + ry * ry
                self._ema = sq if self._n == 0 else self._ema * 0.9 + sq * 0.1
                self._n += 1
            self._prev_delta = (dx, dy)
        self._prev = (x, y)

    @property
    def samples(self):
        return self._n

    @property
    def rms(self):
        return 0.0 if self._n == 0 else math.sqrt(self._ema)

    @property
    def score(self):
        return jitter_score(self.rms)


def jitter_score(rms_px):
    """0-100, 100 = rock steady (1 px ~ 85, 2.5 px ~ 66, 6 px ~ 37)."""
    return int(round(max(0.0, min(100.0, 100.0 * math.exp(-max(rms_px, 0.0) / 6.0)))))


def tune_from_jitter(rms_px):
    """Measured shake -> the settings that stop it dragging the cursor.

    A shaky hand needs a higher speed gate (so shake never passes it), a lower
    filter cutoff (so what does get through is smooth) and a longer dwell (so a
    wobble cannot fire a click). A steady hand keeps all its responsiveness.
    """
    rms = max(0.0, min(float(rms_px), 20.0))
    return {
        "min_speed": round(min(max(0.55 + rms * 0.18, 0.55), 1.80), 2),
        "min_cutoff": round(min(max(1.10 - rms * 0.08, 0.45), 1.10), 2),
        "beta": round(min(max(0.80 + rms * 0.12, 0.80), 1.80), 2),
        "dwell_time": round(min(max(1.40 + rms * 0.12, 1.40), 2.60), 2),
        "dwell_radius": round(min(max(0.14 + rms * 0.02, 0.14), 0.30), 3),
    }


def distance_ratio(palm, ref_palm):
    """How many times farther from the camera the hand is than at calibration."""
    if palm <= 1e-9 or ref_palm <= 1e-9:
        return 1.0
    return max(ref_palm / palm, 1e-3)


def cursor_ring_px(base_px, ratio, max_scale=2.4):
    """Radius of the cursor ring: 18 px at the calibrated distance, bigger farther.

    The OS pointer cannot change size, so this is the size signal: it grows as
    the hand moves away because at 4 m a 16 px pointer is not aimable. The 0.85
    exponent is gentler than linear (linear overshoots past 3 m) and the result
    is clamped so the ring never becomes unusable.
    """
    scale = min(max(ratio ** 0.85, 0.85), max_scale)
    return base_px * scale
