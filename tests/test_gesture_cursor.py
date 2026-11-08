"""Unit tests for the AirTrack interaction logic. No camera needed.

    python -m unittest discover -s tests -v
"""
from __future__ import annotations

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fake_hand import FakeHand                             # noqa: E402
from gesture_cursor import (                               # noqa: E402
    Config, ControlState, CursorController, ScrollDetector, SwipeDetector,
    classify_pose, is_arm_pose, is_fist, is_open_palm, is_pointing, pinch_gap,
    thumb_direction, two_finger_direction)

DT = 1.0 / 30.0


class Rig:
    """Tiny helper that drives a controller with a hand for N frames."""

    def __init__(self, distance_m=1.0, **cfg_kw):
        cfg = Config(**cfg_kw)
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
        assert self.ctrl.state is ControlState.ACTIVE, "a raised palm should arm"


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

    def test_arm_pose_is_an_open_palm_held_up(self):
        """The arming pose has to survive at distance and still refuse the palm that
        is just lying around: an open hand, but only while it is raised."""
        for d in (1.0, 3.0):
            up = FakeHand(pose="palm").at_distance(d).landmarks()
            flat = FakeHand(pose="palm", angle=math.pi / 2).at_distance(d).landmarks()
            self.assertTrue(is_arm_pose(up), f"raised palm not armed at {d} m")
            self.assertTrue(is_open_palm(flat), "a sideways palm is still a palm")
            self.assertFalse(is_arm_pose(flat), f"flat palm armed at {d} m")

    def test_rotated_hand_still_recognised(self):
        for angle in (-0.5, 0.0, 0.5):
            hand = FakeHand(pose="point", angle=angle).at_distance(3.0)
            self.assertTrue(is_pointing(hand.landmarks()), f"angle {angle}")

    def test_two_finger_direction_at_1m_and_3m(self):
        cases = {"up": 0.0, "down": math.pi,
                 "right": -math.pi / 2, "left": math.pi / 2}
        for d in (1.0, 3.0):
            for expected, angle in cases.items():
                hand = FakeHand(pose="two", angle=angle).at_distance(d)
                self.assertEqual(two_finger_direction(hand.landmarks()),
                                 expected, (d, angle))

    def test_only_two_fingers_trigger(self):
        for pose in ("point", "palm", "fist", "pinch", "relaxed"):
            hand = FakeHand(pose=pose).at_distance(3.0)
            self.assertIsNone(two_finger_direction(hand.landmarks()), pose)

    def test_side_thumb_reads_both_ways_at_any_distance(self):
        """The screen switch has to be readable at 10 ft, so it is two big
        distances from the wrist, not a thumb-to-finger relationship."""
        for d in (1.0, 2.0, 3.0):
            right = FakeHand(pose="thumb_right").at_distance(d).landmarks()
            left = FakeHand(pose="thumb_left").at_distance(d).landmarks()
            self.assertEqual(thumb_direction(right), "right", d)
            self.assertEqual(thumb_direction(left), "left", d)
            self.assertEqual(classify_pose(right), "thumb_right", d)
            self.assertEqual(classify_pose(left), "thumb_left", d)

    def test_tucked_or_open_hands_are_not_a_thumb_direction(self):
        for pose in ("fist", "relaxed", "palm", "point", "two", "pinch"):
            hand = FakeHand(pose=pose).at_distance(3.0)
            self.assertIsNone(thumb_direction(hand.landmarks()), pose)


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

    def test_flat_palm_does_not_arm(self):
        """The palm's old failure: a hand lying around open armed the app. Requiring
        it to be held up fixes that without any thumb geometry."""
        rig = Rig(distance_m=3.0)
        rig.hand.angle = math.pi / 2
        out = rig.run("palm", 1.5)
        self.assertEqual(out.state, ControlState.ARMED, "a flat palm armed the app")
        self.assertEqual(out.progress, 0.0)

    def test_fist_does_not_arm(self):
        """The stop fist is not an open hand, so it must never take control."""
        rig = Rig(distance_m=3.0)
        out = rig.run("fist", 1.5)
        self.assertEqual(out.state, ControlState.ARMED, "a fist armed the app")

    def test_point_does_not_arm(self):
        rig = Rig(distance_m=3.0)
        out = rig.run("point", 1.5)
        self.assertEqual(out.state, ControlState.ARMED, "a point armed the app")

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

    def test_jitter_gives_one_click_at_most(self):
        """A still pointing hand *is* the click gesture, so the worst jitter can do
        is reach the single click; the post-click lock stops any repeat."""
        for d in (1.0, 3.0):
            rig = Rig(distance_m=d)
            rig.arm()
            rig.run("point", 0.2)
            rig.hand.jitter = 2.0 / 1280.0
            clicks = 0
            for _ in range(int(6.0 / DT)):
                clicks += rig.run("point", DT).action == "click"
            self.assertEqual(clicks, 1, f"{d} m: {clicks} clicks from one hover")

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
    def test_cursor_unsticks_from_the_anchor_after_a_click(self):
        """The dwell pins the cursor to its anchor; without an un-pinned position
        to measure against, the cursor stayed stuck there and a second hover could
        never click."""
        rig = Rig(distance_m=3.0)
        rig.arm()
        rig.run("point", 0.4)
        clicks = 0
        for _ in range(int(2.5 / DT)):
            clicks += rig.run("point", DT).action == "click"
        self.assertEqual(clicks, 1)
        before = rig.ctrl.pos
        rig.run("point", 0.6, dx=0.004)          # move away from the anchor
        self.assertGreater(abs(rig.ctrl.pos[0] - before[0]), 50)
        clicks = 0
        for _ in range(int(2.5 / DT)):
            clicks += rig.run("point", DT).action == "click"
        self.assertEqual(clicks, 1, "a second hover should click again")

    def test_dwell_releases_when_the_hand_moves_away(self):
        """A click locks the dwell; moving the hand (and so the cursor) to a new
        spot re-arms it, including after clicking near a screen edge."""
        rig = Rig(distance_m=1.0)
        rig.arm()
        rig.run("point", 0.2)
        rig.run("point", 0.3, dx=0.03)            # slam into the right edge
        clicks = 0
        for _ in range(int(2.5 / DT)):
            clicks += rig.run("point", DT).action == "click"
        self.assertEqual(clicks, 1)
        rig.run("point", 0.8, dx=-0.02)           # move back, away from that spot
        clicks = 0
        for _ in range(int(2.5 / DT)):
            clicks += rig.run("point", DT).action == "click"
        self.assertEqual(clicks, 1, "a fresh hover should click again")

    def test_holding_still_after_an_edge_click_never_clicks_again(self):
        """At an edge the cursor is pinned, so its distance from the anchor never
        reaches the radius: the lock has to be released by the hand moving away,
        not by the cursor, or one hover would keep clicking."""
        rig = Rig(distance_m=1.0)
        rig.arm()
        rig.run("point", 0.2)
        rig.run("point", 0.3, dx=0.03)            # slam into the right edge
        clicks = 0
        for _ in range(int(6.0 / DT)):
            clicks += rig.run("point", DT).action == "click"
        self.assertEqual(clicks, 1, "the same hover must not click twice")

    def test_a_single_misread_frame_does_not_cancel_the_dwell(self):
        """At 3 m a finger can flicker across its extension threshold for a frame.
        That must not wipe a half-finished countdown (or a click lock)."""
        rig = Rig(distance_m=3.0)
        rig.arm()
        rig.run("point", 1.9)
        rig.run("palm", DT)                       # one misread frame
        clicks = 0
        for _ in range(int(0.5 / DT)):
            clicks += rig.run("point", DT).action == "click"
        self.assertEqual(clicks, 1, "a one-frame misread must not restart the countdown")

    def test_a_small_nudge_does_not_rearm_the_click(self):
        """A couple of pixels of sensor-noise drift is not "moving to a new spot":
        the click must stay locked until the hand really travels."""
        rig = Rig(distance_m=3.0)
        rig.arm()
        rig.run("point", 0.2)
        clicks = 0
        for _ in range(int(2.5 / DT)):
            clicks += rig.run("point", DT).action == "click"
        self.assertEqual(clicks, 1)
        rig.run("point", 0.4, dx=0.0004)          # ~0.13 palm: under every threshold
        clicks = 0
        for _ in range(int(3.0 / DT)):
            clicks += rig.run("point", DT).action == "click"
        self.assertEqual(clicks, 0, "no second click without a real move")

    def test_click_needs_the_live_point_pose(self):
        """Only the pointing hand may click: a palm, fist or pinch must stay inert
        however long it is held."""
        for pose in ("palm", "fist", "pinch"):
            rig = Rig(distance_m=3.0)
            rig.arm()
            rig.run("point", 0.4)
            clicks = 0
            for _ in range(int(3.0 / DT)):
                clicks += rig.run(pose, DT).action == "click"
            self.assertEqual(clicks, 0, f"{pose} should never click")

    def test_dropping_the_point_pose_cancels_the_dwell(self):
        """A half-finished dwell must not fire after the pose is gone."""
        rig = Rig(distance_m=3.0)
        rig.arm()
        rig.run("point", 0.4)
        rig.run("point", 1.5)                  # 1.5 s into the 2 s dwell
        clicks = 0
        for _ in range(int(1.5 / DT)):          # change pose before it expires
            clicks += rig.run("palm", DT).action == "click"
        self.assertEqual(clicks, 0)
        rig.run("point", 0.4)                  # a fresh hover still works
        clicks = 0
        for _ in range(int(2.5 / DT)):
            clicks += rig.run("point", DT).action == "click"
        self.assertEqual(clicks, 1)

    def test_dwell_clicks_once_and_snaps_to_the_anchor(self):
        rig = Rig(distance_m=3.0)
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

    def test_a_two_second_point_hover_clicks_once(self):
        """The click gesture: hover the pointing hand ~2 s, nothing else."""
        ctrl = CursorController(Config())
        hand = FakeHand(pose="palm", seed=11).at_distance(3.0)
        t = 0.0
        for _ in range(int(1.0 / DT)):
            t += DT
            ctrl.update(hand.landmarks(), now=t)
        self.assertIs(ctrl.state, ControlState.ACTIVE)
        hand.pose = "point"
        clicks = 0
        for _ in range(int(3.0 / DT)):
            t += DT
            clicks += ctrl.update(hand.landmarks(), now=t).action == "click"
        self.assertEqual(clicks, 1, "a still pointing hand should click once")

    def test_arming_palm_never_clicks(self):
        """The frame that takes control must not also click."""
        rig = Rig(distance_m=3.0)
        clicks = 0
        for _ in range(int(1.5 / DT)):
            clicks += rig.run("palm", DT).action == "click"
        self.assertEqual(rig.ctrl.state, ControlState.ACTIVE)
        self.assertEqual(clicks, 0, "the arming palm clicked")

    def test_fist_never_clicks(self):
        """Closing the hand to stop must not also click."""
        rig = Rig(distance_m=3.0)
        rig.arm()
        rig.run("point", 0.4)                  # the context a click would need
        clicks = 0
        for _ in range(int(0.6 / DT)):
            clicks += rig.run("fist", DT).action == "click"
        self.assertEqual(rig.ctrl.state, ControlState.ARMED, "fist should release")
        self.assertEqual(clicks, 0, "closing the fist fired a click")


class ScrollTests(unittest.TestCase):
    """Two-finger vertical scroll. Down used to do nothing while up worked: the
    pose test wanted the ring and pinky cleanly curled, and pointing the V down
    makes those folded fingers read as extended. Both directions are now the same
    gesture upside down, and a blink no longer restarts the cadence."""

    def stream(self, way, seconds=1.5, distance_m=3.0):
        det = ScrollDetector()
        angle = 0.0 if way == "up" else math.pi
        hand = FakeHand(pose="two", angle=angle).at_distance(distance_m)
        t = 0.0
        steps = []
        for _ in range(int(seconds / DT)):
            t += DT
            got = det.update(hand.landmarks(), t)
            if got:
                steps.append(got)
        return steps

    def test_up_and_down_both_stream(self):
        up, down = self.stream("up"), self.stream("down")
        self.assertGreaterEqual(len(up), 5, "up did not stream")
        self.assertGreaterEqual(len(down), 5, "pointing down must scroll too")
        self.assertEqual(set(up), {1})
        self.assertEqual(set(down), {-1})

    def test_the_two_directions_match(self):
        self.assertEqual(len(self.stream("up")), len(self.stream("down")))

    def test_the_hold_is_required_before_the_first_step(self):
        det = ScrollDetector()
        hand = FakeHand(pose="two").at_distance(3.0)
        out = [det.update(hand.landmarks(), i * DT) for i in range(8)]
        self.assertFalse(any(out), "scrolled before the 0.2 s hold finished")

    def test_only_two_fingers_scroll(self):
        for pose in ("point", "palm", "fist", "pinch", "relaxed"):
            det = ScrollDetector()
            hand = FakeHand(pose=pose).at_distance(3.0)
            out = [det.update(hand.landmarks(), i * DT) for i in range(90)]
            self.assertFalse(any(out), f"{pose} scrolled")

    def test_a_dropped_frame_does_not_stop_the_stream(self):
        det = ScrollDetector()
        hand = FakeHand(pose="two", angle=math.pi).at_distance(3.0)
        t = 0.0
        steps = []
        for i in range(int(1.5 / DT)):
            t += DT
            got = det.update(None if i % 12 == 0 else hand.landmarks(), t)
            if got:
                steps.append(got)
        self.assertGreaterEqual(len(steps), 5, "blinks restarted the cadence")
        self.assertEqual(set(steps), {-1})

    def test_reversing_takes_a_short_hold(self):
        det = ScrollDetector()
        hand = FakeHand(pose="two", angle=0.0).at_distance(3.0)
        t = 0.0
        for _ in range(int(0.5 / DT)):
            t += DT
            det.update(hand.landmarks(), t)
        hand.angle = math.pi
        steps = []
        for _ in range(int(0.2 / DT)):            # inside the 0.2 s hold
            t += DT
            steps.append(det.update(hand.landmarks(), t))
        self.assertFalse(any(steps), "a reversal fired immediately")


class SwipeTests(unittest.TestCase):
    """Screen switch: a sideways thumb HELD for 0.75 s. The two stroke-based
    readings before it (the V's angle, then sideways travel) both misread the
    hand: one fired with no movement, the other fired again on the return."""

    def hold(self, way, seconds=1.2, distance_m=3.0):
        det = SwipeDetector()
        hand = FakeHand(pose="thumb_" + way, seed=2).at_distance(distance_m)
        t = 0.0
        fired = []
        for _ in range(int(seconds / DT)):
            t += DT
            fired.append(det.update(hand.landmarks(), t))
        return [f for f in fired if f]

    def test_a_held_thumb_fires_once_each_way(self):
        self.assertEqual(self.hold("right"), ["right"])
        self.assertEqual(self.hold("left"), ["left"])

    def test_the_hold_has_to_finish(self):
        self.assertEqual(self.hold("right", seconds=0.6), [], "fired before 0.75 s")
        self.assertEqual(self.hold("right", seconds=0.9), ["right"])

    def test_the_switch_works_from_up_close_to_10ft(self):
        for d in (1.0, 2.0, 3.0):
            self.assertEqual(self.hold("left", distance_m=d), ["left"], f"{d} m")
            self.assertEqual(self.hold("right", distance_m=d), ["right"], f"{d} m")

    def test_no_other_pose_can_fire_it(self):
        for pose in ("palm", "fist", "point", "two", "pinch", "relaxed"):
            det = SwipeDetector()
            hand = FakeHand(pose=pose).at_distance(3.0)
            out = [det.update(hand.landmarks(), i * DT) for i in range(90)]
            self.assertFalse(any(out), f"{pose} fired the screen switch")

    def test_a_held_thumb_never_repeats(self):
        """The complaint that started this: leaving the hand up must not send a
        second command, and a return stroke must not exist at all."""
        self.assertEqual(self.hold("right", seconds=3.0), ["right"])

    def test_the_thumb_never_releases_control(self):
        """It is also a curled hand. If it counted as the stop fist, the switch
        would drop control halfway through its own hold."""
        rig = Rig(distance_m=3.0)
        rig.arm()
        out = rig.run("thumb_right", 1.5)
        self.assertEqual(out.state, ControlState.ACTIVE)
        self.assertEqual(out.pose, "thumb_right")

    def test_direction_flip_restarts_the_hold(self):
        det = SwipeDetector()
        hand = FakeHand(pose="thumb_right").at_distance(3.0)
        t = 0.0
        fired = []
        for pose in ("thumb_right", "thumb_left"):
            hand.pose = pose
            for _ in range(int(0.5 / DT)):
                t += DT
                fired.append(det.update(hand.landmarks(), t))
        self.assertFalse(any(fired), "flipping direction counted as a hold")

    def test_a_blink_does_not_restart_the_hold(self):
        det = SwipeDetector()
        hand = FakeHand(pose="thumb_right").at_distance(3.0)
        t = 0.0
        fired = []
        for _ in range(int(0.5 / DT)):
            t += DT
            fired.append(det.update(hand.landmarks(), t))
        for _ in range(2):                     # two dropped frames at 3 m
            t += DT
            fired.append(det.update(None, t))
        for _ in range(int(0.5 / DT)):
            t += DT
            fired.append(det.update(hand.landmarks(), t))
        self.assertEqual([f for f in fired if f], ["right"])

    def test_a_second_hold_after_release_fires_again(self):
        det = SwipeDetector()
        hand = FakeHand(pose="thumb_right").at_distance(3.0)
        t = 0.0
        fired = []
        for pose, seconds in (("thumb_right", 1.2), ("fist", 0.3),
                              ("thumb_right", 1.2)):
            hand.pose = pose
            for _ in range(int(seconds / DT)):
                t += DT
                fired.append(det.update(hand.landmarks(), t))
        self.assertEqual([f for f in fired if f], ["right", "right"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
