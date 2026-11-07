"""Unit tests for the AirTrack interaction logic. No camera needed.

    python -m unittest discover -s tests -v
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fake_hand import FakeHand, palm_for_distance          # noqa: E402
from gesture_cursor import (                               # noqa: E402
    Config, ControlState, CursorController, classify_pose, is_fist, is_open_palm,
    is_pointing, pinch_gap)

DT = 1.0 / 30.0


class Rig:
    """Tiny helper that drives a controller with a hand for N frames."""

    def __init__(self, distance_m=1.0, click_mode="pinch", **cfg_kw):
        cfg = Config(click_mode=click_mode, **cfg_kw)
        self.ctrl = CursorController(cfg)
        self.cfg = cfg
        self.hand = FakeHand(pose="point", seed=5).at_distance(distance_m)
        self.t = 0.0
        self.out = None

    def run(self, pose=None, seconds=0.2, dx=0.0, dy=0.0, jitter=0.0):
        if pose:
            self.hand.pose = pose
        self.hand.jitter = jitter
        for _ in range(max(1, int(round(seconds / DT)))):
            self.t += DT
            if dx or dy:
                self.hand.move(dx, dy)
            self.out = self.ctrl.update(self.hand.landmarks(), now=self.t)
        return self.out

    def arm(self):
        self.run("palm", 0.9)
        assert self.ctrl.state is ControlState.ACTIVE, "palm hold should arm"


class PoseTests(unittest.TestCase):
    def test_poses_classified_at_1m_and_3m(self):
        for d in (1.0, 3.0):
            hand = FakeHand(pose="point").at_distance(d)
            self.assertEqual(classify_pose(hand.landmarks("point")), "point", d)
            self.assertEqual(classify_pose(hand.landmarks("palm")), "palm", d)
            self.assertEqual(classify_pose(hand.landmarks("fist")), "fist", d)
            self.assertEqual(classify_pose(hand.landmarks("pinch")), "pinch", d)

    def test_predicates_are_scale_invariant(self):
        for name, pred in (("point", is_pointing), ("palm", is_open_palm),
                           ("fist", is_fist)):
            near = FakeHand(pose=name).at_distance(1.0).landmarks()
            far = FakeHand(pose=name).at_distance(3.0).landmarks()
            self.assertTrue(pred(near), name)
            self.assertTrue(pred(far), name + " far")

    def test_palm_and_pinch_never_overlap(self):
        """The 'heart' pose collision: a pinch must never read as an open palm,
        otherwise a click could arm or stop the controller."""
        for d in (1.0, 3.0):
            pinch = FakeHand(pose="pinch").at_distance(d).landmarks()
            self.assertFalse(is_open_palm(pinch), f"pinch read as palm at {d} m")
            self.assertFalse(is_fist(pinch))
            self.assertLess(pinch_gap(pinch), 0.38)

    def test_rotated_hand_still_recognised(self):
        for angle in (-0.5, 0.0, 0.5):
            hand = FakeHand(pose="point", angle=angle).at_distance(3.0)
            self.assertTrue(is_pointing(hand.landmarks()), f"angle {angle}")


class StateMachineTests(unittest.TestCase):
    def test_starts_armed_and_ignores_pointing(self):
        rig = Rig(distance_m=3.0)
        for _ in range(60):
            out = rig.run("point", DT)
            self.assertEqual(out.state, ControlState.ARMED)
        self.assertEqual(rig.ctrl.pos, (rig.cfg.screen_w / 2, rig.cfg.screen_h / 2))

    def test_palm_hold_arms_after_hold_time(self):
        rig = Rig(distance_m=3.0)
        out = rig.run("palm", 0.3)
        self.assertEqual(out.state, ControlState.ARMED, "armed too early")
        self.assertGreater(out.progress, 0.0)
        rig.run("palm", 0.4)
        self.assertEqual(rig.ctrl.state, ControlState.ACTIVE)

    def test_fist_releases_and_arm_cooldown_applies(self):
        rig = Rig(distance_m=3.0)
        rig.arm()
        rig.run("fist", 0.6)
        self.assertEqual(rig.ctrl.state, ControlState.ARMED, "fist should release")
        rig.run("palm", 0.4)                    # inside the cooldown
        self.assertEqual(rig.ctrl.state, ControlState.ARMED)
        rig.run("palm", 1.0)
        self.assertEqual(rig.ctrl.state, ControlState.ACTIVE)

    def test_hand_lost_releases_control(self):
        rig = Rig(distance_m=3.0)
        rig.arm()
        rig.run(None, 0.5)
        self.assertEqual(rig.ctrl.state, ControlState.ACTIVE, "brief dropout is tolerated")
        for _ in range(90):
            rig.t += DT
            rig.out = rig.ctrl.update(None, now=rig.t)
        self.assertEqual(rig.ctrl.state, ControlState.ARMED)

    def test_disarm_stops_everything(self):
        rig = Rig()
        rig.arm()
        rig.ctrl.disarm()
        out = rig.run("point", 0.5, dx=0.01)
        self.assertEqual(out.state, ControlState.OFF)
        self.assertIsNone(out.action)


class DistanceTests(unittest.TestCase):
    def test_same_hand_sweep_moves_cursor_the_same_distance(self):
        travel_cm = 15.0
        results = {}
        for d in (1.0, 3.0):
            rig = Rig(distance_m=d)
            rig.arm()
            rig.run("point", 0.1)
            start = rig.ctrl.pos
            visible_w_cm = 240.0 * d / 3.0
            dx = (travel_cm / visible_w_cm) / 30.0
            rig.run("point", 1.0, dx=dx)
            results[d] = abs(rig.ctrl.pos[0] - start[0])
        near, far = results[1.0], results[3.0]
        self.assertGreater(far, 50, f"far sweep barely moved the cursor: {results}")
        self.assertLess(abs(near - far) / max(near, far), 0.05, results)

    def test_cursor_never_parks_on_a_screen_corner(self):
        """PyAutoGUI's fail-safe raises when the pointer sits on a corner pixel, so
        a full-screen sweep must stop short of the edges."""
        rig = Rig(distance_m=1.0)
        rig.arm()
        rig.run("point", 0.2)
        rig.run("point", 3.0, dx=0.03, dy=-0.03)     # hard sweep one way
        x, y = rig.ctrl.pos
        self.assertGreaterEqual(x, rig.cfg.edge_margin)
        self.assertGreaterEqual(y, rig.cfg.edge_margin)
        rig.run("point", 6.0, dx=-0.03, dy=0.03)     # and the other way
        x, y = rig.ctrl.pos
        self.assertLessEqual(x, rig.cfg.screen_w - 1 - rig.cfg.edge_margin)
        self.assertLessEqual(y, rig.cfg.screen_h - 1 - rig.cfg.edge_margin)

    def test_distance_estimate_roughly_matches(self):
        for d in (1.0, 2.0, 3.0):
            hand = FakeHand(pose="point").at_distance(d)
            out = CursorController(Config()).update(hand.landmarks(), now=0.0)
            self.assertAlmostEqual(out.distance_cm / 100.0, d, delta=d * 0.35)


class ShakeTests(unittest.TestCase):
    def test_still_hand_does_not_move_the_cursor(self):
        """2 px of detector noise on a still hand: the cursor must stay put."""
        for d in (1.0, 3.0):
            rig = Rig(distance_m=d)
            rig.arm()
            rig.run("point", 0.2)
            start = rig.ctrl.pos
            rig.hand.jitter = 2.0 / 1280.0
            rig.run("point", 5.0)
            drift = ((rig.ctrl.pos[0] - start[0]) ** 2
                     + (rig.ctrl.pos[1] - start[1]) ** 2) ** 0.5
            self.assertLess(drift, 12.0, f"{d} m: cursor drifted {drift:.1f} px")

    def test_still_hand_never_clicks_in_pinch_mode(self):
        for d in (1.0, 3.0):
            rig = Rig(distance_m=d)
            rig.arm()
            rig.run("point", 0.2)
            rig.hand.jitter = 2.0 / 1280.0
            clicks = 0
            for _ in range(int(6.0 / DT)):
                t_out = rig.run("point", DT)
                clicks += t_out.action == "click"
            self.assertEqual(clicks, 0, f"{d} m: false click from jitter")

    def test_slow_hand_motion_below_threshold_is_ignored(self):
        rig = Rig(distance_m=3.0)
        rig.arm()
        rig.run("point", 0.2)
        start = rig.ctrl.pos
        # ~0.1 palm-lengths per second: quietly below the 0.5 threshold
        rig.run("point", 3.0, dx=0.000125)
        moved = abs(rig.ctrl.pos[0] - start[0])
        self.assertLess(moved, 6.0, f"threshold leaked {moved:.1f} px")

    def test_movement_response_is_not_killed_by_the_smoothing(self):
        rig = Rig(distance_m=3.0)
        rig.arm()
        rig.run("point", 0.2)
        start = rig.ctrl.pos
        rig.run("point", 1.0, dx=0.01)
        self.assertGreater(abs(rig.ctrl.pos[0] - start[0]), 200)


class ClickTests(unittest.TestCase):
    def test_pinch_clicks_once_per_pinch(self):
        rig = Rig(distance_m=3.0)
        rig.arm()
        rig.run("point", 0.4)
        clicks = 0
        for _ in range(int(0.4 / DT)):         # held pinch
            clicks += rig.run("pinch", DT).action == "click"
        self.assertEqual(clicks, 1, "one pinch should be exactly one click")
        rig.run("point", 0.6)
        clicks = 0
        for _ in range(int(0.4 / DT)):
            clicks += rig.run("pinch", DT).action == "click"
        self.assertEqual(clicks, 1, "second pinch should click again")

    def test_no_click_when_pinch_has_no_pointing_context(self):
        """Showing up already pinched (or waving with a pinch) must never click."""
        rig = Rig(distance_m=3.0)
        rig.arm()
        clicks = 0
        for _ in range(int(2.0 / DT)):
            clicks += rig.run("pinch", DT).action == "click"
        self.assertEqual(clicks, 0)

    def test_pinch_freezes_the_cursor(self):
        rig = Rig(distance_m=3.0)
        rig.arm()
        rig.run("point", 0.4)
        before = rig.ctrl.pos
        rig.run("pinch", 0.4, dx=0.01)
        moved = ((rig.ctrl.pos[0] - before[0]) ** 2
                 + (rig.ctrl.pos[1] - before[1]) ** 2) ** 0.5
        self.assertLess(moved, 20.0, f"cursor moved {moved:.1f} px while pinching")

    def test_dwell_clicks_once_and_snaps_to_the_anchor(self):
        rig = Rig(distance_m=3.0, click_mode="dwell")
        rig.arm()
        rig.run("point", 0.4)
        anchor = rig.ctrl.pos
        clicks = 0
        for _ in range(int(3.5 / DT)):
            clicks += rig.run("point", DT).action == "click"
        self.assertEqual(clicks, 1, "holding still should click exactly once")
        dist = ((rig.ctrl.pos[0] - anchor[0]) ** 2
                + (rig.ctrl.pos[1] - anchor[1]) ** 2) ** 0.5
        self.assertLess(dist, 20.0)

    def test_palm_pose_does_not_click_in_pinch_mode(self):
        rig = Rig(distance_m=3.0)
        rig.arm()
        clicks = 0
        for _ in range(int(2.0 / DT)):
            clicks += rig.run("palm", DT).action == "click"
        self.assertEqual(clicks, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
