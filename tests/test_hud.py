"""Regression tests for the preview HUD (this is where a crash once hid: the
drawing path was only exercised with progress == 0, so the progress arc was never
executed until a hand actually appeared)."""
from __future__ import annotations

import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app                                                  # noqa: E402
from fake_hand import FakeHand                              # noqa: E402
from gesture_cursor import Config, ControlState, CursorController  # noqa: E402
from tracker import Frame                                   # noqa: E402

EXTRA = {"speed": 0.4, "min_speed": 1.0, "click": "hold still", "dry": True}


def blank():
    return np.full((360, 640, 3), 30, np.uint8)


class HudTests(unittest.TestCase):
    def setUp(self):
        self.lm = FakeHand(pose="point").at_distance(2.0).landmarks()
        self.out = CursorController(Config()).update(self.lm, now=1.0)

    def test_every_state_and_progress(self):
        fr = Frame(image=blank(), landmarks=self.lm, box=(100, 50, 300, 260),
                   zoom=2.0, fps=25, width=640, height=360)
        for state in ControlState:
            for progress in (0.0, 0.01, 0.5, 0.99, 1.0):
                self.out.state = state
                self.out.progress = progress
                img = app.draw_hud(blank(), self.out, fr, EXTRA)
                self.assertEqual(img.shape, (360, 640, 3))
                self.assertEqual(img.dtype, np.uint8)

    def test_without_hand_or_box(self):
        out = CursorController(Config()).update(None, now=1.0)
        fr = Frame(image=blank(), landmarks=None, box=None, width=640, height=360)
        img = app.draw_hud(blank(), out, fr, EXTRA)
        self.assertEqual(img.shape, (360, 640, 3))

    def test_display_is_mirrored_when_enabled(self):
        """The preview must flip with Config.mirror, otherwise the picture shows
        the hand moving the opposite way from the cursor."""
        ramp = np.repeat(np.linspace(0, 255, 640, dtype=np.uint8)[None, :, None], 360, 0)
        grad = np.repeat(ramp, 3, axis=2)
        fr = Frame(image=grad, landmarks=None, box=None, width=640, height=360)
        mirrored = app.draw_hud(grad.copy(), self.out, fr, EXTRA, mirror=True)
        plain = app.draw_hud(grad.copy(), self.out, fr, EXTRA, mirror=False)
        self.assertGreater(int(mirrored[180, 100, 0]), int(mirrored[180, 539, 0]) + 40)
        self.assertLess(int(plain[180, 100, 0]), int(plain[180, 539, 0]) - 40)

    def test_crop_up_and_down_scaling_shapes(self):
        """The HUD draws boxes in frame pixels; make sure odd/small boxes are fine."""
        for box in ((0, 0, 10, 10), (600, 340, 640, 360), (10, 10, 630, 350)):
            fr = Frame(image=blank(), landmarks=self.lm, box=box, width=640, height=360)
            img = app.draw_hud(blank(), self.out, fr, EXTRA)
            self.assertEqual(img.shape, (360, 640, 3))


if __name__ == "__main__":
    unittest.main(verbosity=2)
