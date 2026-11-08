"""Calibration tests: pure logic, no camera, no GUI, no OS calls.

Covers what the demo leans on -- the tremor estimate, the tuning derived from it,
the floors that stop calibration ever making control twitchier than the team's
defaults, the ring that grows with distance, a profile that survives a round trip
and cannot be poisoned by a hand-edited file -- plus one end-to-end run of the
wizard in simulate mode, which writes a real profile.json.

Nothing here imports the tracker's controller or changes its behaviour; the only
contact is a check that the profile's field names exist on its Config.
"""
from __future__ import annotations

import dataclasses
import math
import os
import random
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from calibrate_profile import Profile, apply_to_config, load_profile, save_profile
from calibration_math import (JitterMeter, TremorProfile, cursor_ring_px,
                              distance_ratio, estimate_tremor, jitter_score,
                              tune_from_tremor)
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


def test_a_five_hz_tremor_is_measured_as_five_hz():
    samples = []
    for i in range(120):
        t = i / 30.0
        samples.append((t,
                        500.0 + 4.0 * math.sin(2 * math.pi * 5.0 * t),
                        400.0 + 2.0 * math.cos(2 * math.pi * 5.0 * t)))
    tremor = estimate_tremor(samples)
    assert 4.3 <= tremor.freq_hz <= 5.7
    assert tremor.amplitude_px > 2.0
    assert tremor.rms_px > 1.0
    assert 0 <= tremor.score <= 100


def test_a_steady_hand_reports_nothing_periodic():
    samples = [(i / 30.0, 500.0, 400.0) for i in range(120)]
    tremor = estimate_tremor(samples)
    assert tremor.freq_hz == 0.0
    assert tremor.score == 100


def test_a_bigger_tremor_steadies_the_filter_and_lengthens_every_hold():
    calm = tune_from_tremor(TremorProfile(freq_hz=5.0, amplitude_px=0.5))
    wild = tune_from_tremor(TremorProfile(freq_hz=5.0, amplitude_px=6.0))
    assert wild["min_speed"] > calm["min_speed"]      # shake ignored
    assert wild["beta"] < calm["beta"]                # filter stops reopening
    assert wild["min_cutoff"] < calm["min_cutoff"]    # more smoothing
    assert wild["dwell_time"] > calm["dwell_time"]    # hold longer to click
    assert wild["arm_hold"] > calm["arm_hold"]        # hold longer to arm
    assert wild["swipe_hold"] > calm["swipe_hold"]    # hold longer to switch


def test_calibration_can_never_be_twitchier_than_the_defaults():
    from gesture_cursor import Config

    base = Config()
    for jitter in (0.0, 1.0, 3.0, 20.0):
        cfg = apply_to_config(Config(), Profile.from_measurement(
            palm=0.04, jitter_px=jitter, distance_ft=10.0))
        assert cfg.min_speed >= base.min_speed
        assert cfg.dwell_time >= base.dwell_time
        assert cfg.dwell_radius >= base.dwell_radius
        assert cfg.arm_hold >= base.arm_hold
        assert cfg.swipe_hold >= base.swipe_hold
        assert cfg.beta <= base.beta
        assert cfg.min_cutoff <= base.min_cutoff


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
    profile = Profile.from_measurement(
        palm=0.0375, jitter_px=2.4, distance_ft=10.0,
        tremor=TremorProfile(freq_hz=5.2, amplitude_px=3.0, rms_px=2.4, score=66))
    path = save_profile(profile, str(tmp_path / "profile.json"))
    back = load_profile(path)

    assert back.tremor_hz == pytest.approx(5.2)
    assert back.tremor_px == pytest.approx(3.0)
    assert back.arm_hold == pytest.approx(profile.arm_hold)
    assert back.swipe_hold == pytest.approx(profile.swipe_hold)
    assert back.dwell_time == pytest.approx(profile.dwell_time)

    bad = tmp_path / "bad.json"
    bad.write_text('{"min_speed": 99, "dwell_time": -4, "palm": 0, '
                   '"jitter_score": 900, "tremor_hz": 999, "arm_hold": 99}')
    loaded = load_profile(str(bad))
    assert loaded.min_speed <= 3.0
    assert loaded.dwell_time >= 0.6
    assert loaded.palm >= 0.004
    assert loaded.jitter_score <= 100
    assert loaded.tremor_hz <= 20.0
    assert loaded.arm_hold <= 3.0


def test_profile_keys_match_the_tracker_config():
    """Adoption is a 3-line patch, so the keys must be Config's own fields."""
    from gesture_cursor import Config

    names = {field.name for field in dataclasses.fields(Config)}
    assert {"min_speed", "min_cutoff", "beta", "dwell_time", "dwell_radius",
            "arm_hold", "swipe_hold"} <= names

    profile = Profile.from_measurement(
        palm=0.04, jitter_px=6.0, distance_ft=8.0,
        tremor=TremorProfile(freq_hz=5.0, amplitude_px=6.0, rms_px=6.0, score=37))
    cfg = apply_to_config(Config(), profile)
    assert cfg.arm_hold == pytest.approx(profile.arm_hold)
    assert cfg.swipe_hold == pytest.approx(profile.swipe_hold)


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
    assert 0.0 <= saved.tremor_hz <= 12.0
    assert saved.arm_hold >= 0.55


def test_random_shake_is_not_reported_as_a_tremor():
    """White noise has a spectral peak at some frequency; it is not a tremor."""
    for seed in (11, 12, 13):
        rng = random.Random(seed)
        samples = [(i / 30.0, 500.0 + rng.gauss(0, 2.0), 400.0 + rng.gauss(0, 2.0))
                   for i in range(120)]
        tremor = estimate_tremor(samples)
        assert tremor.freq_hz == 0.0, f"seed {seed} invented {tremor.freq_hz} Hz"
