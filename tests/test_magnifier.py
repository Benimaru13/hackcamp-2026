"""Unit tests for the distance-scaled aiming reticle (HUD only, no camera)."""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fake_hand import FakeHand                                   # noqa: E402
from gesture_cursor import Config, cursor_radius_px, estimate_distance_cm   # noqa: E402


class ReticleTests(unittest.TestCase):
    def setUp(self):
        self.cfg = Config()

    def test_grows_with_distance(self):
        near = cursor_radius_px(100, self.cfg)
        far = cursor_radius_px(300, self.cfg)
        self.assertGreater(near, 0)
        self.assertGreater(far, near * 2.0)

    def test_monotonic(self):
        radii = [cursor_radius_px(cm, self.cfg) for cm in range(40, 460, 10)]
        for a, b in zip(radii, radii[1:]):
            self.assertLessEqual(a, b)

    def test_clamped_below_and_above_the_range(self):
        self.assertAlmostEqual(cursor_radius_px(10, self.cfg), self.cfg.cursor_near_px)
        self.assertAlmostEqual(cursor_radius_px(2000, self.cfg), self.cfg.cursor_far_px)

    def test_no_or_zero_distance_uses_the_near_size(self):
        for d in (0, 0.0, None):
            self.assertAlmostEqual(cursor_radius_px(d, self.cfg), self.cfg.cursor_near_px)

    def test_midpoint_is_between_the_ends(self):
        mid = (self.cfg.cursor_near_cm + self.cfg.cursor_far_cm) / 2.0
        r = cursor_radius_px(mid, self.cfg)
        self.assertGreater(r, self.cfg.cursor_near_px + 1)
        self.assertLess(r, self.cfg.cursor_far_px - 1)

    def test_configurable(self):
        cfg = Config(cursor_near_px=10.0, cursor_far_px=20.0,
                     cursor_near_cm=100.0, cursor_far_cm=200.0)
        self.assertAlmostEqual(cursor_radius_px(150, cfg), 15.0)
        # a degenerate range must not divide by zero
        degenerate = Config(cursor_near_cm=200.0, cursor_far_cm=200.0)
        self.assertAlmostEqual(cursor_radius_px(150, degenerate),
                               degenerate.cursor_far_px)

    def test_a_hand_three_metres_away_gets_a_visible_reticle(self):
        """End to end through the real distance estimate: the ring has to be
        clearly bigger than the old fixed 6 px dot by the back of the room."""
        cfg = Config()
        near = FakeHand(pose="point").at_distance(1.0).landmarks()
        far = FakeHand(pose="point").at_distance(3.0).landmarks()
        r_near = cursor_radius_px(estimate_distance_cm(near, cfg.frame_w, cfg), cfg)
        r_far = cursor_radius_px(estimate_distance_cm(far, cfg.frame_w, cfg), cfg)
        self.assertGreater(r_far, r_near * 1.4)
        self.assertGreaterEqual(r_far, 24.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
