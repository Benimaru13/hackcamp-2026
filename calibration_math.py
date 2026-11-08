"""calibration_math.py -- what the calibrator measures, and the tuning it derives.

Deliberately standalone: no cv2, no camera, no OS calls, and no imports from
gesture_cursor.py or app.py. The AirTrack pipeline belongs to the other branches;
this module only produces numbers it can consume.

The measurement is aimed at tremor, not generic noise. A shaky hand is not white
noise: it has one dominant periodic component, usually between 3 and 8 Hz. Finding
that frequency is what lets the smoothing sit below it instead of guessing from a
single RMS value -- and a filter cannot reject a tremor it was not told about.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


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


@dataclass
class TremorProfile:
    """The periodic part of a still hand: how fast it oscillates and how far."""

    freq_hz: float = 0.0        # 0 = nothing periodic found
    amplitude_px: float = 0.0   # peak amplitude of that component
    rms_px: float = 0.0         # overall shake, for the score
    score: int = 100

    def describe(self):
        if self.freq_hz <= 0:
            return f"{self.rms_px:.1f} px shake, steady ({self.score}/100)"
        return (f"{self.freq_hz:.1f} Hz tremor, {self.amplitude_px:.1f} px "
                f"({self.score}/100)")


def estimate_tremor(samples, min_hz=2.0, max_hz=12.0, step_hz=0.25):
    """Dominant periodic component of a still hand, in Hz and pixels.

    `samples` is [(t_seconds, x_px, y_px), ...] straight from the camera during
    the hold-still phase. A coarse DFT is enough: 41 frequencies x 2 axes over a
    couple of hundred points. Pure Python on purpose -- no numpy here, so this
    stays testable anywhere and keeps one implementation of the idea.

    The peak is only reported if it stands clearly above the noise floor; a flat
    spectrum means a steady hand, not a tremor at an arbitrary frequency.
    """
    pts = [p for p in samples if len(p) == 3]
    n = len(pts)
    if n < 24:
        return TremorProfile()
    t0 = pts[0][0]
    ts = [p[0] - t0 for p in pts]
    if ts[-1] - ts[0] <= 0.5:
        return TremorProfile()

    mx = sum(p[1] for p in pts) / n
    my = sum(p[2] for p in pts) / n
    xs = [p[1] - mx for p in pts]
    ys = [p[2] - my for p in pts]
    rms = math.sqrt(sum(x * x + y * y for x, y in zip(xs, ys)) / n)

    best_amp, best_hz = 0.0, 0.0
    steps = int(round((max_hz - min_hz) / step_hz))
    for i in range(steps + 1):
        f = min_hz + i * step_hz
        w = 2.0 * math.pi * f
        cos_part = [math.cos(w * t) for t in ts]
        sin_part = [math.sin(w * t) for t in ts]
        for series in (xs, ys):
            re = sum(v * c for v, c in zip(series, cos_part))
            im = sum(v * s for v, s in zip(series, sin_part))
            amp = 2.0 * math.hypot(re, im) / n
            if amp > best_amp:
                best_amp, best_hz = amp, f

    # White noise always has SOME spectral peak; only call it a tremor when it
    # clears an absolute floor as well as the noise level, or a steady hand would
    # be told it trembles at 5.5 Hz.
    if best_amp < max(1.2, 0.30 * rms):
        best_hz = 0.0               # nothing stands out: a steady hand
    return TremorProfile(freq_hz=round(best_hz, 1), amplitude_px=round(best_amp, 2),
                         rms_px=round(rms, 2), score=jitter_score(rms))


def tremor_severity(freq_hz, amplitude_px):
    """How much this tremor matters: its amplitude, weighted by staying periodic.

    Motion in the 2.5-9 Hz band counts fully, because that is the band a filter
    can reject without also killing deliberate movement. Motion outside it (slow
    drift, a jittery one-off) counts half as much.
    """
    amp = max(0.0, min(float(amplitude_px), 20.0))
    if 2.5 <= freq_hz <= 9.0:
        weight = 1.0
    elif freq_hz > 0:
        weight = 0.5
    else:
        weight = 0.6
    return amp * weight


def tune_from_tremor(tremor):
    """The measured tremor -> settings, floored at the team's own defaults.

    Every value starts at the hand-tuned default and only moves in the steadying
    direction, so calibrating can never make control twitchier than the branch it
    came from: a steady hand gets exactly the defaults back. As the tremor grows,
    the speed gate rises, the filter cutoff drops, beta stops the filter reopening
    on fast oscillation, and every hold (dwell, arm, swipe) lengthens.
    """
    sev = tremor_severity(tremor.freq_hz, tremor.amplitude_px)
    return {
        "min_speed": round(min(1.00 + 0.12 * sev, 2.20), 2),
        "min_cutoff": round(max(0.70 - 0.06 * sev, 0.30), 2),
        "beta": round(max(1.20 - 0.16 * sev, 0.30), 2),
        "dwell_time": round(min(2.00 + 0.10 * sev, 3.60), 2),
        "dwell_radius": round(min(0.20 + 0.02 * sev, 0.40), 3),
        "arm_hold": round(min(0.55 + 0.06 * sev, 1.60), 2),
        "swipe_hold": round(min(0.75 + 0.08 * sev, 2.20), 2),
    }


def tune_from_jitter(rms_px):
    """A bare RMS, when no frequency was measured: treated as unknown-frequency shake."""
    return tune_from_tremor(TremorProfile(amplitude_px=float(rms_px),
                                          rms_px=float(rms_px)))


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
