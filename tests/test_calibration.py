"""Calibration tests: pure logic, no camera, no GUI, no OS calls.

Covers the numbers the demo leans on -- the jitter score, the tuning derived from
it, the ring that grows with distance, a profile that survives a round trip and
cannot be poisoned by a hand-edited file -- plus one end-to-end run of the wizard
in simulate mode, which writes a real profile.json.

Nothing here imports the tracker's controller or touches its behaviour; the only
contact is a check that the profile's field names exist on its Config.
"""
from __future__ import annotations

import dataclasses
import os
import random
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from calibrate_profile import Profile, apply_to_config, load_profile, save_profile
from calibration_math import (JitterMeter, cursor_ring_px, distance_ratio,
                              jitter_score, tune_from_jitter)
from fake_hand import palm_for_distance


def test_jitter_meter_separates_a_steady_hand_from_a_shaky_one():
    steady = JitterMeter()
    for _ in range(120):
        steady.push(500.0, 400.0)
    assert steady.rms == 0.0
    assert steady.score == 100

    rng = random.Random(3)
    shaky = JitterMeter()
    for _ in range(180):
        shaky.push(500.0 + rng.gauss(0, 3), 400.0 + rng.gauss(0, 3))
    assert shaky.rms > 2.0
    assert shaky.score < 70


def test_jitter_score_is_bounded_and_monotonic():
    assert jitter_score(0.0) == 100
    assert 0 <= jitter_score(1000.0) <= 100
    scores = [jitter_score(r) for r in (0.5, 1.0, 3.0, 6.0, 12.0)]
    assert scores == sorted(scores, reverse=True)


def test_tuning_gets_steadier_as_jitter_rises_and_stays_in_range():
    calm, wild = tune_from_jitter(0.5), tune_from_jitter(9.0)
    assert wild["min_speed"] > calm["min_speed"]      # shake ignored
    assert wild["min_cutoff"] < calm["min_cutoff"]    # more smoothing
    assert wild["dwell_time"] > calm["dwell_time"]    # longer hold to click

    for extreme in (0.0, 1000.0, -5.0):
        tune = tune_from_jitter(extreme)
        assert 0.55 <= tune["min_speed"] <= 1.80
        assert 0.45 <= tune["min_cutoff"] <= 1.10
        assert 1.40 <= tune["dwell_time"] <= 2.60


def test_ring_grows_with_distance_and_is_clamped():
    cal = palm_for_distance(3.0)
    at_cal = cursor_ring_px(18, distance_ratio(cal, cal))
    nearer = cursor_ring_px(18, distance_ratio(palm_for_distance(1.0), cal))
    farther = cursor_ring_px(18, distance_ratio(palm_for_distance(4.5), cal))

    assert at_cal == pytest.approx(18.0)
    assert farther > at_cal > nearer
    assert cursor_ring_px(18, 50) <= 18 * 2.4 + 1e-6
    assert cursor_ring_px(18, 0.01) >= 18 * 0.85 - 1e-6


def test_profile_round_trip_and_a_poisoned_file(tmp_path):
    profile = Profile.from_measurement(palm=0.0375, jitter_px=2.4, distance_ft=10.0)
    path = save_profile(profile, str(tmp_path / "profile.json"))
    back = load_profile(path)

    assert back.jitter_score == profile.jitter_score
    assert back.min_speed == pytest.approx(profile.min_speed)
    assert back.palm == pytest.approx(profile.palm)
    assert back.name == profile.name

    bad = tmp_path / "bad.json"
    bad.write_text('{"min_speed": 99, "dwell_time": -4, "palm": 0, "jitter_score": 900}')
    loaded = load_profile(str(bad))
    assert loaded.min_speed <= 3.0
    assert loaded.dwell_time >= 0.6
    assert loaded.palm >= 0.004
    assert loaded.jitter_score <= 100


def test_profile_keys_match_the_tracker_config():
    """The adoption path is a 3-line patch, so the keys must be Config's own."""
    from gesture_cursor import Config

    names = {field.name for field in dataclasses.fields(Config)}
    assert {"min_speed", "min_cutoff", "beta", "dwell_time", "dwell_radius"} <= names

    cfg = apply_to_config(Config(),
                          Profile.from_measurement(palm=0.04, jitter_px=3.0,
                                                   distance_ft=8.0))
    assert cfg.min_speed > 0
    assert cfg.dwell_time > 0


def test_the_wizard_runs_headless_and_writes_a_profile(tmp_path):
    from calibrate import run_calibration

    out = tmp_path / "profile.json"
    profile = run_calibration(simulate=True, out_path=str(out), preview=False)

    assert profile is not None
    assert out.exists()
    saved = load_profile(str(out))
    assert saved.jitter_px > 0
    assert 0 <= saved.jitter_score <= 100
    assert 0.004 <= saved.palm <= 0.5
    assert saved.distance_ft > 0
