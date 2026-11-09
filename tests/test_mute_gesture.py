"""The audio-guide toggle: the rock sign, its 0.75 s hold, and one toggle per hold.

Everything here runs on synthetic landmarks -- no camera, no audio device.
"""
from __future__ import annotations

import math
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fake_hand import FakeHand                              # noqa: E402
from gesture_cursor import (                                # noqa: E402
    Config, ControlState, CursorController, MuteDetector, classify_pose,
    is_rock_sign)
from voice import Voice                                     # noqa: E402

DT = 1.0 / 30.0


class MuteRig:
    """Feeds a detector frames at 30 fps, recording every toggle."""

    def __init__(self, hold=0.75, release=0.15, distance_m=3.0):
        self.det = MuteDetector(hold, release)
        self.hand = FakeHand(pose="rock", seed=4).at_distance(distance_m)
        self.t = 0.0
        self.fired: list[float] = []

    def run(self, pose="rock", seconds=1.0, blank=False):
        for _ in range(max(1, int(round(seconds / DT)))):
            self.t += DT
            lm = None if blank else self.hand.landmarks(pose)
            if self.det.update(lm, self.t):
                self.fired.append(self.t)
        return self.fired


class RockPoseTests(unittest.TestCase):
    def test_rock_sign_is_recognised_at_every_distance(self):
        for d in (1.0, 2.0, 3.0):
            hand = FakeHand(pose="rock").at_distance(d)
            self.assertTrue(is_rock_sign(hand.landmarks()), d)
            self.assertEqual(classify_pose(hand.landmarks()), "rock", d)

    def test_no_other_pose_reads_as_the_rock_sign(self):
        for pose in ("palm", "point", "two", "fist", "pinch", "thumb_left",
                     "thumb_right", "relaxed"):
            hand = FakeHand(pose=pose)
            self.assertFalse(is_rock_sign(hand.landmarks()), pose)
            self.assertNotEqual(classify_pose(hand.landmarks()), "rock", pose)

    def test_a_two_finger_v_in_any_direction_is_never_the_rock_sign(self):
        for angle in (0.0, math.pi, math.pi / 2, -math.pi / 2):
            hand = FakeHand(pose="two", angle=angle)
            self.assertFalse(is_rock_sign(hand.landmarks()), angle)


class MuteTimingTests(unittest.TestCase):
    def test_fires_only_after_the_hold(self):
        rig = MuteRig()
        rig.run("rock", 0.70)
        self.assertEqual(rig.fired, [], "the toggle must not fire before 0.75 s")
        rig.run("rock", 0.20)
        self.assertEqual(len(rig.fired), 1)
        self.assertGreaterEqual(rig.fired[0], 0.75)
        self.assertLessEqual(rig.fired[0], 0.85)

    def test_one_toggle_per_hold(self):
        rig = MuteRig()
        rig.run("rock", 3.0)
        self.assertEqual(len(rig.fired), 1,
                         "holding the sign must not flip the setting repeatedly")

    def test_letting_go_arms_the_next_toggle(self):
        rig = MuteRig()
        rig.run("rock", 1.0)
        rig.run(blank=True, seconds=0.5)
        rig.run("rock", 1.0)
        self.assertEqual(len(rig.fired), 2)

    def test_a_blink_does_not_rearm_the_toggle(self):
        rig = MuteRig()
        rig.run("rock", 1.0)
        rig.run(blank=True, seconds=0.1)     # shorter than the release time
        rig.run("rock", 1.0)
        self.assertEqual(len(rig.fired), 1)

    def test_dropped_frames_do_not_restart_the_hold(self):
        rig = MuteRig()
        rig.run("rock", 0.5)
        rig.run(blank=True, seconds=1 * DT)  # one dropped frame at 3 m
        rig.run("rock", 0.5)
        self.assertEqual(len(rig.fired), 1)
        self.assertGreaterEqual(rig.fired[0], 0.75)

    def test_other_poses_never_toggle(self):
        for pose in ("palm", "point", "two", "fist", "pinch", "relaxed"):
            rig = MuteRig()
            rig.run(pose, 3.0)
            self.assertEqual(rig.fired, [], pose)

    def test_progress_shows_the_hold_and_resets_when_the_sign_is_gone(self):
        rig = MuteRig()
        rig.run("rock", 0.4)
        progress = rig.det.progress(rig.t)
        self.assertGreater(progress, 0.3)
        self.assertLess(progress, 0.8)
        rig.run(blank=True, seconds=0.5)
        self.assertEqual(rig.det.progress(rig.t), 0.0)


class ControllerConflictTests(unittest.TestCase):
    def test_rock_sign_does_not_arm_control(self):
        ctrl = CursorController(Config())
        hand = FakeHand(pose="rock").at_distance(3.0)
        t = 0.0
        for _ in range(int(2.0 / DT)):
            t += DT
            ctrl.update(hand.landmarks(), now=t)
        self.assertIs(ctrl.state, ControlState.ARMED)

    def test_rock_sign_never_moves_clicks_or_releases(self):
        ctrl = CursorController(Config())
        hand = FakeHand(pose="palm").at_distance(3.0)
        t = 0.0
        for _ in range(30):
            t += DT
            ctrl.update(hand.landmarks("palm"), now=t)
        self.assertIs(ctrl.state, ControlState.ACTIVE)
        start = ctrl.pos
        actions = []
        for _ in range(int(3.0 / DT)):
            t += DT
            actions.append(ctrl.update(hand.landmarks("rock"), now=t).action)
        self.assertIs(ctrl.state, ControlState.ACTIVE)
        self.assertNotIn("click", actions)
        self.assertNotIn("release", actions)
        self.assertEqual(ctrl.pos, start)


class VoiceToggleTests(unittest.TestCase):
    def test_muting_stops_playback_and_unmuting_restores_the_cues(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "activated.wav").write_bytes(b"wav")
            v = Voice(directory=d)
            self.assertTrue(v.enabled)
            self.assertFalse(v.set_enabled(False))
            self.assertFalse(v.say("activated"))
            self.assertTrue(v.set_enabled(True))
            self.assertTrue(v.enabled)
            self.assertEqual(v.available(), ["activated"])


if __name__ == "__main__":
    unittest.main()
