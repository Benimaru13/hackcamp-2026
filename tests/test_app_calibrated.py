"""The prototype's one piece of extra logic: the startup pointer self-test.

The gesture loop is app.py's, already covered by their tests; what this branch
adds is the load of a profile and a check that the OS really accepts mouse
events. That check is what tells "my hand is not being seen" apart from "the
events are being dropped", and it must not fire in a dry run.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app_calibrated import pointer_test


class _StubMouse:
    def __init__(self, obeys=True):
        self.pos = [100, 200]
        self.obeys = obeys

    def position(self):
        return tuple(self.pos)

    def moveTo(self, x, y, _pause=False):
        if self.obeys:
            self.pos = [x, y]


def test_pointer_test_passes_when_the_pointer_actually_moves():
    assert pointer_test(_StubMouse(), dry_run=False) is True


def test_pointer_test_fails_loudly_when_events_are_dropped():
    assert pointer_test(_StubMouse(obeys=False), dry_run=False) is False


def test_pointer_test_is_silent_in_a_dry_run():
    assert pointer_test(_StubMouse(), dry_run=True) is None


def test_pointer_test_skips_when_pyautogui_is_missing():
    assert pointer_test(None) is None
