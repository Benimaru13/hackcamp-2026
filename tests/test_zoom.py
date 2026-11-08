"""Unit tests for the auto-zoom planning (zoom.py). Pure geometry, no camera.

    python -m unittest discover -s tests -v
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fake_hand import FakeHand                                  # noqa: E402
from zoom import (FILL, MAX_UPSCALE, MIN_CROP, TARGET_SIDE, Rect,   # noqa: E402
                  box_of, hand_fill, hand_side, model_hand_share, plan_crop,
                  scan_tiles, upscale_for)


class FocusCropTests(unittest.TestCase):
    FRAME_W, FRAME_H = 1280, 720

    def box(self, distance_m, pose="point", cx=0.5, cy=0.5):
        lm = FakeHand(cx=cx, cy=cy, pose=pose).at_distance(distance_m).landmarks()
        return box_of(lm, self.FRAME_W, self.FRAME_H)

    def test_the_hand_fills_the_same_share_of_the_model_input_at_every_distance(self):
        """The whole point of the auto-zoom: detection quality stops depending on
        how far away you stand."""
        shares = []
        for d in (1.0, 1.5, 2.0, 2.5, 3.0, 4.0):
            box = self.box(d)
            rect = plan_crop(box, self.FRAME_W, self.FRAME_H)
            share = model_hand_share(box, rect)
            self.assertAlmostEqual(share, FILL, places=2, msg=f"{d} m")
            shares.append(share)
        self.assertLess(max(shares) - min(shares), 0.02)

    def test_the_hand_really_does_shrink_in_the_frame(self):
        """Sanity check on the fixture: the crop is what keeps the share constant,
        the picture is getting smaller with distance."""
        near = hand_side(self.box(1.0))
        far = hand_side(self.box(3.0))
        self.assertGreater(near, far * 2.5)

    def test_crop_is_square_and_inside_the_frame(self):
        rect = plan_crop(self.box(2.0), self.FRAME_W, self.FRAME_H)
        self.assertAlmostEqual(rect.w, rect.h, places=6)
        self.assertGreaterEqual(rect.x0, 0.0)
        self.assertGreaterEqual(rect.y0, 0.0)
        self.assertLessEqual(rect.x1, self.FRAME_W)
        self.assertLessEqual(rect.y1, self.FRAME_H)

    def test_crop_stays_inside_the_frame_at_the_edges(self):
        for cx, cy in ((0.05, 0.05), (0.95, 0.95), (0.5, 0.02), (0.98, 0.5)):
            rect = plan_crop(self.box(1.0, cx=cx, cy=cy), self.FRAME_W, self.FRAME_H)
            self.assertGreaterEqual(rect.x0, 0.0, (cx, cy))
            self.assertGreaterEqual(rect.y0, 0.0, (cx, cy))
            self.assertLessEqual(rect.x1, self.FRAME_W, (cx, cy))
            self.assertLessEqual(rect.y1, self.FRAME_H, (cx, cy))

    def test_crop_contains_the_hand_with_room_to_spare(self):
        for d in (1.0, 2.0, 3.0):
            for pose in ("point", "palm", "fist", "two"):
                box = self.box(d, pose=pose)
                rect = plan_crop(box, self.FRAME_W, self.FRAME_H)
                self.assertTrue(rect.contains(box), (d, pose))
                self.assertLessEqual(hand_fill(box, rect), 0.62, (d, pose))

    def test_crop_is_held_still_while_the_hand_rests(self):
        """No re-planning for a resting hand: that is what would make the zoom
        shiver and the detector lose the hand."""
        box = self.box(2.0)
        first = plan_crop(box, self.FRAME_W, self.FRAME_H)
        for dx, dy in ((6, 0), (0, -6), (10, 8), (-12, 4)):
            moved = Rect(box.x0 + dx, box.y0 + dy, box.x1 + dx, box.y1 + dy)
            self.assertEqual(plan_crop(moved, self.FRAME_W, self.FRAME_H,
                                       previous=first), first, (dx, dy))

    def test_crop_recentres_when_the_hand_leaves_the_middle(self):
        box = self.box(2.0)
        first = plan_crop(box, self.FRAME_W, self.FRAME_H)
        moved = Rect(box.x0 + 120, box.y0 + 90, box.x1 + 120, box.y1 + 90)
        second = plan_crop(moved, self.FRAME_W, self.FRAME_H, previous=first)
        self.assertNotEqual(second, first)
        self.assertTrue(second.contains(moved))

    def test_crop_resizes_when_the_hand_changes_distance(self):
        near = plan_crop(self.box(1.0), self.FRAME_W, self.FRAME_H)
        far = plan_crop(self.box(3.0), self.FRAME_W, self.FRAME_H)
        self.assertGreater(near.side, far.side * 2.0)
        # ...and a small change of distance does not re-plan
        box = self.box(2.0)
        first = plan_crop(box, self.FRAME_W, self.FRAME_H)
        slightly = Rect(box.x0 - 4, box.y0 - 4, box.x1 + 4, box.y1 + 4)
        self.assertEqual(plan_crop(slightly, self.FRAME_W, self.FRAME_H,
                                   previous=first), first)

    def test_tiny_box_still_gets_a_usable_crop(self):
        rect = plan_crop(Rect(100, 100, 104, 104), self.FRAME_W, self.FRAME_H)
        self.assertGreaterEqual(rect.side, MIN_CROP)

    def test_a_far_hand_is_several_times_bigger_than_a_whole_frame_scan(self):
        box = self.box(3.0)
        rect = plan_crop(box, self.FRAME_W, self.FRAME_H)
        whole_frame = hand_side(box) * upscale_for(self.FRAME_H) / TARGET_SIDE
        self.assertGreater(model_hand_share(box, rect), 3.0 * whole_frame)


class UpscaleTests(unittest.TestCase):
    def test_matches_the_tracker_resize_rule(self):
        self.assertAlmostEqual(upscale_for(512), 1.0)
        self.assertAlmostEqual(upscale_for(1024), TARGET_SIDE / 1024)
        self.assertAlmostEqual(upscale_for(128), 4.0)

    def test_capped_at_max_upscale(self):
        self.assertAlmostEqual(upscale_for(1), MAX_UPSCALE)
        self.assertAlmostEqual(upscale_for(40), MAX_UPSCALE)
        self.assertAlmostEqual(upscale_for(MIN_CROP / 2), MAX_UPSCALE)


class ScanTileTests(unittest.TestCase):
    FRAME_W, FRAME_H = 1280, 720

    def test_tiles_cover_the_whole_frame(self):
        tiles = scan_tiles(self.FRAME_W, self.FRAME_H)
        self.assertEqual(len(tiles), 4)
        for x in range(0, self.FRAME_W + 1, 80):
            for y in range(0, self.FRAME_H + 1, 80):
                self.assertTrue(
                    any(t.x0 <= x <= t.x1 and t.y0 <= y <= t.y1 for t in tiles), (x, y))

    def test_tiles_are_inside_the_frame_and_overlap(self):
        tiles = scan_tiles(self.FRAME_W, self.FRAME_H)
        for t in tiles:
            self.assertGreaterEqual(t.x0, 0.0)
            self.assertGreaterEqual(t.y0, 0.0)
            self.assertLessEqual(t.x1, self.FRAME_W + 1e-6)
            self.assertLessEqual(t.y1, self.FRAME_H + 1e-6)
        left, right = tiles[0], tiles[1]
        horizontal = [t for t in tiles if abs(t.y0 - left.y0) < 1e-6]
        horizontal.sort(key=lambda t: t.x0)
        self.assertGreater(horizontal[0].x1, horizontal[1].x0)   # they overlap

    def test_the_middle_tile_is_scanned_first(self):
        tiles = scan_tiles(self.FRAME_W, self.FRAME_H, cols=3, rows=3)
        middle = Rect(self.FRAME_W / 2 - 5, self.FRAME_H / 2 - 5,
                      self.FRAME_W / 2 + 5, self.FRAME_H / 2 + 5)
        self.assertTrue(tiles[0].contains(middle))

    def test_a_far_hand_is_bigger_in_a_tile_than_in_the_whole_frame(self):
        lm = FakeHand(pose="point").at_distance(3.0).landmarks()
        box = box_of(lm, self.FRAME_W, self.FRAME_H)
        tile = min(scan_tiles(self.FRAME_W, self.FRAME_H), key=lambda t: t.side)
        in_tile = model_hand_share(box, tile)
        in_frame = hand_side(box) * upscale_for(self.FRAME_H) / TARGET_SIDE
        self.assertGreater(in_tile, 1.5 * in_frame)


if __name__ == "__main__":
    unittest.main(verbosity=2)
