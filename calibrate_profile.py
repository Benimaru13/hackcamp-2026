"""calibrate_profile.py -- the saved result of a calibration, and how it is used.

One person measured at one distance: how much their hand shakes, how big their
hand looks from there, and the tuning both imply. The keys are the tracker's own
Config field names, so applying it is a three-line addition to app.py -- a file
this branch deliberately does not modify.

Plain JSON so a teammate can copy it, and every number is clamped on load: a
hand-edited or stale file must never be able to make the cursor unusable.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass

from calibration_math import jitter_score, tune_from_jitter

DEFAULT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "profile.json")

# field -> accepted range on load (anything outside is clamped, not trusted)
_LIMITS = {
    "jitter_px": (0.0, 40.0),
    "jitter_score": (0, 100),
    "palm": (0.004, 0.5),
    "distance_ft": (0.5, 40.0),
    "min_speed": (0.20, 3.0),
    "min_cutoff": (0.20, 3.0),
    "beta": (0.10, 4.0),
    "dwell_time": (0.60, 4.0),
    "dwell_radius": (0.05, 0.60),
}


@dataclass
class Profile:
    """Everything one calibration measured, plus what it tuned."""

    name: str = "Default"
    jitter_px: float = 2.0
    jitter_score: int = 72
    palm: float = 0.0375          # normalized palm length at `distance_ft`
    distance_ft: float = 10.0
    min_speed: float = 1.0
    min_cutoff: float = 0.7
    beta: float = 1.2
    dwell_time: float = 2.0
    dwell_radius: float = 0.20
    created_at: str = ""

    @classmethod
    def from_measurement(cls, palm, jitter_px, distance_ft, name=None, created_at=""):
        jitter = max(0.0, min(float(jitter_px), 40.0))
        return cls(
            name=name or f"Calibrated {time.strftime('%H:%M')}",
            jitter_px=round(jitter, 2),
            jitter_score=jitter_score(jitter),
            palm=float(palm),
            distance_ft=round(float(distance_ft), 1),
            created_at=created_at or time.strftime("%Y-%m-%dT%H:%M:%S"),
            **tune_from_jitter(jitter),
        )

    def summary(self) -> str:
        return (f"{self.name}: jitter {self.jitter_px:.1f} px ({self.jitter_score}/100), "
                f"dwell {self.dwell_time:.2f} s, min speed {self.min_speed:.2f}, "
                f"calibrated at {self.distance_ft:.1f} ft")


def apply_to_config(cfg, profile: Profile):
    """Copy the profile's measurements onto a tracker Config (duck-typed).

    Deliberately imports nothing from gesture_cursor: any object with these
    attributes works, so this can be adopted without coupling the branches.
    """
    cfg.min_speed = float(profile.min_speed)
    cfg.min_cutoff = float(profile.min_cutoff)
    cfg.beta = float(profile.beta)
    cfg.dwell_time = float(profile.dwell_time)
    cfg.dwell_radius = min(max(float(profile.dwell_radius), 0.05), 0.60)
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
