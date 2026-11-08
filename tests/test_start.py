"""start.py is only the sequencing: calibrate, then control.

The wizard and the control loop have their own tests. What matters here is the
order, that measuring is the default even when an old profile.json exists, that
--use-saved is the only way to skip the wizard, that a cancelled wizard never
starts controlling, and that a simulated run never touches the pointer.
"""
from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from calibrate_profile import Profile, save_profile
from calibration_math import TremorProfile
import start
from start import run_sequence


class _Args:
    def __init__(self, profile, use_saved=False, save=False, simulate=False):
        self.profile = profile
        self.use_saved = use_saved
        self.save = save
        self.simulate = simulate
        self.camera = 0
        self.width = 1280
        self.height = 720
        self.no_preview = True
        self.dry_run = False
        self.verbose = False
        self.no_pointer_test = False


def _profile(tremor_hz=0.0):
    return Profile.from_measurement(palm=0.04, jitter_px=2.4, distance_ft=10.0,
                                    tremor=TremorProfile(freq_hz=tremor_hz,
                                                         amplitude_px=2.4))


def test_a_fresh_start_calibrates_first_and_then_controls():
    order = []
    profile = _profile()

    def calibrate(_args):
        order.append("calibrate")
        return profile

    def control(_args, prof):
        order.append(("control", prof.jitter_score))
        return 0

    code = run_sequence(_Args("/nowhere/profile.json"), calibrate, control,
                        exists=lambda _p: False)
    assert code == 0
    assert order == ["calibrate", ("control", profile.jitter_score)]


def test_welcome_message_plays_start_clip_and_waits(monkeypatch, capsys):
    calls = []

    class _Voice:
        def say(self, name, wait=False):
            calls.append((name, wait))

    monkeypatch.setattr(start, "Voice", _Voice)
    start.welcome_message()
    assert calls == [("start_message", True)]
    assert "begin gesture calibration" in capsys.readouterr().out


def test_start_wires_greeting_to_calibration_window_visibility(monkeypatch):
    captured = {}
    monkeypatch.setattr(start.wizard, "make_source", lambda **_kwargs: object())

    def run_calibration(**kwargs):
        captured.update(kwargs)
        return None

    monkeypatch.setattr(start.wizard, "run_calibration", run_calibration)
    start._calibrate(_Args("profile.json"))

    assert captured["on_window_visible"] is start.welcome_message


def test_a_saved_profile_never_replaces_measuring_this_hand():
    """The point of the branch: today's hand, not the one measured last week."""
    with tempfile.TemporaryDirectory() as tmp:
        path = save_profile(_profile(), os.path.join(tmp, "profile.json"))
        order = []
        fresh = _profile(tremor_hz=5.0)

        def calibrate(_args):
            order.append("calibrate")
            return fresh

        def control(_args, prof):
            order.append(("control", prof.tremor_hz))
            return 0

        code = run_sequence(_Args(path), calibrate, control)

    assert code == 0
    assert order == ["calibrate", ("control", 5.0)]


def test_use_saved_is_the_only_way_to_skip_the_wizard():
    with tempfile.TemporaryDirectory() as tmp:
        path = save_profile(_profile(), os.path.join(tmp, "profile.json"))
        order = []

        def calibrate(_args):
            order.append("calibrate")
            return _profile()

        def control(_args, _prof):
            order.append("control")
            return 0

        code = run_sequence(_Args(path, use_saved=True), calibrate, control)

    assert code == 0
    assert order == ["control"]


def test_use_saved_with_no_file_on_disk_still_measures():
    order = []
    code = run_sequence(_Args("/nowhere/profile.json", use_saved=True),
                        lambda _a: (order.append("calibrate"), _profile())[1],
                        lambda _a, _p: (order.append("control"), 0)[1],
                        exists=lambda _p: False)
    assert code == 0
    assert order == ["calibrate", "control"]


def test_a_cancelled_wizard_starts_nothing():
    started = []
    code = run_sequence(_Args("/nowhere/profile.json"),
                        lambda _a: None,
                        lambda _a, _p: started.append("control"),
                        exists=lambda _p: False)
    assert code == 1
    assert started == []


def test_a_simulated_run_calibrates_but_never_drives_the_pointer():
    started = []
    code = run_sequence(_Args("/nowhere/profile.json", simulate=True),
                        lambda _a: _profile(),
                        lambda _a, _p: started.append("control"),
                        exists=lambda _p: False)
    assert code == 0
    assert started == []
