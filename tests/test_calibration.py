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
from types import SimpleNamespace

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


def test_the_card_score_describes_the_pixels_printed_next_to_it():
    """The card prints `jitter_px` and `jitter_score` on the same line, so the score
    has to come from that px value -- not from the tremor RMS, which also counts the
    arm drifting across the 3.5 s hold (7.2 px of drift once read as 30/100 next to
    a 0.9 px reading).
    """
    tremor = TremorProfile(freq_hz=0.0, amplitude_px=1.0, rms_px=7.2, score=30)
    profile = Profile.from_measurement(palm=0.037, jitter_px=0.9,
                                       distance_ft=3.0, tremor=tremor)
    assert profile.jitter_px == 0.9
    assert profile.jitter_score == jitter_score(0.9)
    assert profile.jitter_score >= 85


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
    # The screen-switch hold is swipe_hold on older branches, switch_hold on the
    # current one; whichever the branch has is the one that must be floored.
    holds = [n for n in ("swipe_hold", "switch_hold") if hasattr(base, n)]
    assert holds, "Config has no screen-switch hold at all"
    for jitter in (0.0, 1.0, 3.0, 20.0):
        cfg = apply_to_config(Config(), Profile.from_measurement(
            palm=0.04, jitter_px=jitter, distance_ft=10.0))
        assert cfg.min_speed >= base.min_speed
        assert cfg.dwell_time >= base.dwell_time
        assert cfg.dwell_radius >= base.dwell_radius
        assert cfg.arm_hold >= base.arm_hold
        for name in holds:
            assert getattr(cfg, name) >= getattr(base, name)
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
            "arm_hold"} <= names
    assert {"swipe_hold", "switch_hold"} & names, "screen-switch hold missing"

    profile = Profile.from_measurement(
        palm=0.04, jitter_px=6.0, distance_ft=8.0,
        tremor=TremorProfile(freq_hz=5.0, amplitude_px=6.0, rms_px=6.0, score=37))
    cfg = apply_to_config(Config(), profile)
    assert cfg.arm_hold == pytest.approx(profile.arm_hold)
    hold = "swipe_hold" if hasattr(cfg, "swipe_hold") else "switch_hold"
    assert getattr(cfg, hold) == pytest.approx(profile.swipe_hold)


def test_the_calibration_preview_flips_the_picture_with_the_dots():
    """The wizard mapped the landmark dots as a mirror (x -> 1 - x) but left the
    picture unflipped, so every dot landed on the opposite side of the frame: the
    fingertip ring sat on the empty half of the image and the real hand had no
    dots on it at all. Picture and dots have to be flipped together."""
    np = pytest.importorskip("numpy")
    pytest.importorskip("cv2")
    import calibrate

    h, w = 720, 1280
    image = np.zeros((h, w, 3), np.uint8)
    image[:, : w // 2] = 255                      # a bright LEFT half

    lm = [SimpleNamespace(x=0.1, y=0.5, z=0.0) for _ in range(21)]
    frame = calibrate.render(image, 1, 0.0, "hold still", {}, lm, mirror=True)

    pw = max(300, min(int(w * 0.36), 430))
    vw = w - pw                                   # the camera column

    # The picture is flipped with the dots: the bright half is now on the right.
    assert frame[h // 2, vw // 4].mean() < frame[h // 2, vw - vw // 4].mean()

    # A landmark at x = 0.1 is drawn where the mirrored hand is: near the right.
    accent = np.array(calibrate.ACCENT, dtype=np.uint8)
    ys, xs = np.nonzero(np.all(frame[:, :vw] == accent, axis=2))
    assert xs.size > 50, "the fingertip ring was not drawn"
    assert xs.mean() > vw * 0.6, f"ring at x={xs.mean():.0f} of {vw}: not mirrored"
    assert abs(ys.mean() - h / 2) < 12, "the ring is not on the landmark's row"


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


class _RealTimeSource:
    """A frame source on the real clock, so wall time is actually measured."""

    width = 1280
    height = 720

    def __init__(self, jitter_px=2.0):
        import time
        from fake_hand import FakeHand
        self._time = time
        self.hand = FakeHand(pose="palm", palm=palm_for_distance(3.0),
                             jitter=jitter_px / 1280.0, seed=4)
        self.closed = False

    def read(self):
        self._time.sleep(1 / 60.0)          # a camera cadence, not a busy loop
        return self.hand.landmarks("palm"), None, self._time.monotonic()

    def close(self):
        self.closed = True


def test_the_whole_wizard_takes_about_four_seconds(tmp_path):
    """The budget that matters: the cursor should appear, not keep waiting."""
    import time
    from calibrate import run_calibration

    src = _RealTimeSource()
    started = time.monotonic()
    profile = run_calibration(source=src, out_path=str(tmp_path / "profile.json"),
                              preview=False, save=False, keep_open=True)
    elapsed = time.monotonic() - started

    assert profile is not None
    assert elapsed < 6.0, f"calibration took {elapsed:.1f}s"
    assert elapsed >= 3.5, f"measured only {elapsed:.1f}s of a 3.5 s window"
    assert profile.palm > 0.0
    assert src.closed is False           # kept open for the tracker


def test_the_camera_is_closed_when_nobody_takes_it_over(tmp_path):
    from calibrate import run_calibration

    src = _RealTimeSource()
    profile = run_calibration(source=src, out_path=str(tmp_path / "profile.json"),
                              preview=False, save=False)
    assert profile is not None
    assert src.closed is True


def test_a_cancelled_wizard_does_not_leak_the_camera():
    """Esc must close the source even though keep_open was asked for."""
    import numpy as np

    import calibrate

    class Source(_RealTimeSource):
        def read(self):
            return (self.hand.landmarks("palm"),
                    np.full((120, 160, 3), 20, np.uint8),
                    self._time.monotonic())

    src = Source()
    gui = ("namedWindow", "resizeWindow", "setWindowProperty", "imshow",
           "waitKey", "destroyAllWindows")
    saved_gui = {name: getattr(calibrate.cv2, name) for name in gui}
    for name in gui:
        setattr(calibrate.cv2, name, lambda *a, **k: None)
    calibrate.cv2.waitKey = lambda *a, **k: 27          # Esc on the first frame
    try:
        profile = calibrate.run_calibration(source=src, preview=True, save=False,
                                            keep_open=True)
    finally:
        for name, fn in saved_gui.items():
            setattr(calibrate.cv2, name, fn)

    assert profile is None
    assert src.closed is True


def test_window_visible_callback_runs_after_first_preview_frame(monkeypatch):
    import numpy as np

    import calibrate

    class Source(_RealTimeSource):
        def read(self):
            return (self.hand.landmarks("palm"),
                    np.full((120, 160, 3), 20, np.uint8),
                    self._time.monotonic())

    src = Source()
    events = []
    monkeypatch.setattr(calibrate.cv2, "namedWindow", lambda *a, **k: None)
    monkeypatch.setattr(calibrate.cv2, "resizeWindow", lambda *a, **k: None)
    monkeypatch.setattr(calibrate.cv2, "setWindowProperty", lambda *a, **k: None)
    monkeypatch.setattr(calibrate.cv2, "imshow", lambda *a, **k: events.append("frame"))
    keys = iter((0, 27))
    monkeypatch.setattr(calibrate.cv2, "waitKey", lambda *_a: next(keys))
    monkeypatch.setattr(calibrate.cv2, "destroyAllWindows", lambda: None)

    calibrate.run_calibration(source=src, preview=True, save=False,
                              on_window_visible=lambda: events.append("visible"))

    assert events[:2] == ["frame", "visible"]
    assert events.count("visible") == 1
    assert src.closed is True


def test_headless_calibration_does_not_invoke_window_visible_callback():
    from calibrate import make_source, run_calibration

    called = []
    profile = run_calibration(source=make_source(simulate=True), preview=False,
                              save=False,
                              on_window_visible=lambda: called.append(True))

    assert profile is not None
    assert called == []


def test_random_shake_is_not_reported_as_a_tremor():
    """White noise has a spectral peak at some frequency; it is not a tremor."""
    for seed in (11, 12, 13):
        rng = random.Random(seed)
        samples = [(i / 30.0, 500.0 + rng.gauss(0, 2.0), 400.0 + rng.gauss(0, 2.0))
                   for i in range(120)]
        tremor = estimate_tremor(samples)
        assert tremor.freq_hz == 0.0, f"seed {seed} invented {tremor.freq_hz} Hz"
