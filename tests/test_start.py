"""start.py is only the sequencing: calibrate when needed, then control.

The wizard and the control loop have their own tests. What matters here is the
order, that a saved profile skips the wizard, that a cancelled wizard never
starts controlling, and that a simulated run never touches the pointer.
"""
from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from calibrate_profile import Profile, save_profile
from start import run_sequence


class _Args:
    def __init__(self, profile, recalibrate=False, simulate=False):
        self.profile = profile
        self.recalibrate = recalibrate
        self.simulate = simulate
        self.camera = 0
        self.width = 1280
        self.height = 720
        self.no_preview = True
        self.dry_run = False
        self.verbose = False
        self.no_pointer_test = False


def _profile():
    return Profile.from_measurement(palm=0.04, jitter_px=2.4, distance_ft=10.0)


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


def test_a_saved_profile_skips_the_wizard():
    with tempfile.TemporaryDirectory() as tmp:
        path = save_profile(_profile(), os.path.join(tmp, "profile.json"))
        order = []

        def calibrate(_args):
            order.append("calibrate")
            return _profile()

        def control(_args, _prof):
            order.append("control")
            return 0

        code = run_sequence(_Args(path), calibrate, control)

    assert code == 0
    assert order == ["control"]


def test_recalibrate_forces_the_wizard_even_with_a_saved_profile():
    order = []
    with tempfile.TemporaryDirectory() as tmp:
        path = save_profile(_profile(), os.path.join(tmp, "profile.json"))
        code = run_sequence(_Args(path, recalibrate=True),
                            lambda _a: (order.append("calibrate"), _profile())[1],
                            lambda _a, _p: (order.append("control"), 0)[1])
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
