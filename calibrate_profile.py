"""calibrate_profile.py -- the saved result of a calibration, and how it is used.

One person measured at one distance: how much their hand shakes, at what
frequency, how big their hand looks from there, and the tuning all of that
implies. The keys are the tracker's own Config field names, so applying it is a
three-line addition to app.py -- a file this branch deliberately does not modify.

Plain JSON so a teammate can copy it, and every number is clamped on load: a
hand-edited or stale file must never be able to make the cursor unusable. A
profile saved before tremor was measured still loads -- the new fields simply
default to the team's own settings.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass

from calibration_math import TremorProfile, jitter_score, tune_from_tremor

DEFAULT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "profile.json")

# field -> accepted range on load (anything outside is clamped, not trusted)
_LIMITS = {
    "jitter_px": (0.0, 40.0),
    "jitter_score": (0, 100),
    "palm": (0.004, 0.5),
    "distance_ft": (0.5, 40.0),
    "tremor_hz": (0.0, 20.0),
    "tremor_px": (0.0, 40.0),
    "min_speed": (0.20, 3.0),
    "min_cutoff": (0.20, 3.0),
    "beta": (0.10, 4.0),
    "dwell_time": (0.60, 4.0),
    "dwell_radius": (0.05, 0.60),
    "arm_hold": (0.20, 3.0),
    "swipe_hold": (0.20, 3.5),
}


@dataclass
class Profile:
    """Everything one calibration measured, plus what it tuned.

    The defaults are the tracker's own defaults on purpose: an empty profile, or
    one saved before tremor was measured, changes nothing.
    """

    name: str = "Default"
    jitter_px: float = 2.0
    jitter_score: int = 72
    palm: float = 0.0375          # normalized palm length at `distance_ft`
    distance_ft: float = 10.0
    tremor_hz: float = 0.0        # dominant oscillation of a still hand
    tremor_px: float = 0.0        # its amplitude
    min_speed: float = 1.00
    min_cutoff: float = 0.70
    beta: float = 1.20
    dwell_time: float = 2.00
    dwell_radius: float = 0.20
    arm_hold: float = 0.55
    swipe_hold: float = 0.75
    created_at: str = ""

    @classmethod
    def from_measurement(cls, palm, jitter_px, distance_ft, name=None,
                         created_at="", tremor=None):
        tremor = tremor or TremorProfile(amplitude_px=float(jitter_px),
                                         rms_px=float(jitter_px))
        return cls(
            name=name or f"Calibrated {time.strftime('%H:%M')}",
            jitter_px=round(max(0.0, min(float(jitter_px), 40.0)), 2),
            jitter_score=jitter_score(tremor.rms_px or jitter_px),
            palm=float(palm),
            distance_ft=round(float(distance_ft), 1),
            tremor_hz=float(tremor.freq_hz),
            tremor_px=float(tremor.amplitude_px),
            created_at=created_at or time.strftime("%Y-%m-%dT%H:%M:%S"),
            **tune_from_tremor(tremor),
        )

    def summary(self) -> str:
        if self.tremor_hz > 0:
            hand = (f"tremor {self.tremor_hz:.1f} Hz / {self.tremor_px:.1f} px "
                    f"({self.jitter_score}/100)")
        else:
            hand = f"shake {self.jitter_px:.1f} px ({self.jitter_score}/100)"
        return (f"{self.name}: {hand}, dwell {self.dwell_time:.2f} s, "
                f"arm hold {self.arm_hold:.2f} s, min speed {self.min_speed:.2f}, "
                f"calibrated at {self.distance_ft:.1f} ft")


# profile field -> attribute names to try on the branch's Config, in order.
# The screen-switch hold was called swipe_hold and is switch_hold now; older
# branches still have the old name, newer ones the new one. Whichever exists is
# the one that gets set, so the same profile works on both.
_FIELD_ALIASES = {
    "swipe_hold": ("swipe_hold", "switch_hold"),
}


def apply_to_config(cfg, profile: Profile):
    """Copy the profile's tuning onto a tracker Config (duck-typed).

    Deliberately imports nothing from gesture_cursor: any object with these
    attributes works, so the branches stay uncoupled. Settings the branch does
    not have (a newer `ref_palm`, say) are skipped rather than crashing.
    """
    for attr in ("min_speed", "min_cutoff", "beta", "dwell_time", "dwell_radius",
                 "arm_hold", "swipe_hold"):
        value = float(getattr(profile, attr))
        for name in _FIELD_ALIASES.get(attr, (attr,)):
            if hasattr(cfg, name):
                setattr(cfg, name, value)
                break
    cfg.dwell_radius = min(max(float(cfg.dwell_radius), 0.05), 0.60)
    if hasattr(cfg, "ref_palm"):
        cfg.ref_palm = min(max(float(profile.palm), 0.004), 0.5)
    return cfg


def save_profile(profile: Profile, path=DEFAULT_PATH) -> str:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(asdict(profile), fh, indent=2, sort_keys=True)
        fh.write("\n")
    return path


def load_profile(path=DEFAULT_PATH) -> Profile:
    """Read a profile, clamping every field. Raises on unreadable JSON."""
    with open(path, encoding="utf-8") as fh:
        raw = json.load(fh)
    if not isinstance(raw, dict):
        raise ValueError("profile is not an object")
    kwargs = {}
    for field, (lo, hi) in _LIMITS.items():
        value = raw.get(field)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        clamped = min(max(float(value), lo), hi)
        kwargs[field] = int(round(clamped)) if field == "jitter_score" else clamped
    if isinstance(raw.get("name"), str) and raw["name"].strip():
        kwargs["name"] = raw["name"].strip()[:60]
    if isinstance(raw.get("created_at"), str):
        kwargs["created_at"] = raw["created_at"]
    return Profile(**kwargs)
