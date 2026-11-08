"""zoom.py  --  where to crop the camera frame, and how far to upscale it.

The detector resizes whatever image it is handed to its own fixed input, so the
only thing that decides whether a hand is findable is how much of that input the
hand fills. Handed a whole 720p frame, a hand at 3 m fills ~13% of it and a hand
at 1 m fills ~40%: the same gesture gets harder the further you stand. Handed a
crop that is just big enough to hold the hand plus a margin, the hand fills the
same ~55% at every distance, so the detector sees the same hand at 1 m and at 4 m.

This is the "auto focus" of the camera: the crop is sized from the hand, not from
the frame, and it follows the hand around.

Two jobs, two entry points:

  * `plan_crop()`  -- follow. A square crop around the hand, recomputed only when
                      the hand leaves the comfortable middle of the current crop,
                      so the crop does not shiver with every landmark twitch (and
                      so the detector keeps seeing the hand in the same place,
                      which is what its own tracking step needs), and re-sized only
                      when the hand changes distance appreciably.
  * `scan_tiles()` -- acquire. While nothing is tracked there is no hand to crop
                      around, so the frame is cut into overlapping tiles and one
                      tile is tried per frame: a tile is upscaled much harder than
                      a whole frame, so a hand too small for a full-frame detection
                      is found inside a tile.

Everything here is pure arithmetic -- no cv2, no numpy, no camera -- so the crop
behaviour is unit tested (tests/test_zoom.py) and measured on synthetic hands
(`python simulate.py focus`). tracker.py only slices the frame.
"""
from __future__ import annotations

from dataclasses import dataclass

TARGET_SIDE = 512.0     # tracker feeds the model ~this many px on the short side
MAX_UPSCALE = 6.0       # ...and never stretches a crop further (no signal left)
MIN_CROP = 96.0         # a crop smaller than this has nothing in it
FILL = 0.55             # wanted hand side / crop side
DEADBAND = 0.40         # hold the crop while the hand stays in this middle share


@dataclass(frozen=True)
class Rect:
    """Axis-aligned box in frame pixels. Frozen so a plan can be reused safely."""

    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def w(self):
        return self.x1 - self.x0

    @property
    def h(self):
        return self.y1 - self.y0

    @property
    def side(self):
        return max(self.w, self.h)

    @property
    def short(self):
        """Short side: what the model resize normalises on (min(w, h))."""
        return min(self.w, self.h)

    @property
    def center(self):
        return ((self.x0 + self.x1) / 2.0, (self.y0 + self.y1) / 2.0)

    def ints(self):
        """Pixel slice indices (frame[y0:y1, x0:x1])."""
        return int(self.x0), int(self.y0), int(round(self.x1)), int(round(self.y1))

    def contains(self, box):
        return (box.x0 >= self.x0 and box.y0 >= self.y0
                and box.x1 <= self.x1 and box.y1 <= self.y1)


def box_of(landmarks, frame_w, frame_h):
    """Landmarks -> pixel box, the same box tracker.py reports in Frame.box."""
    xs = [p.x * frame_w for p in landmarks]
    ys = [p.y * frame_h for p in landmarks]
    return Rect(min(xs), min(ys), max(xs), max(ys))


def hand_side(box):
    """The hand's size in pixels, as one number: its longer side."""
    return max(box.w, box.h)


def crop_side_for(box, fill=FILL, min_side=MIN_CROP):
    """Crop side that puts the hand at `fill` of the crop."""
    return max(hand_side(box) / max(fill, 0.05), min_side)


def square_at(center, side, frame_w, frame_h):
    """Square crop of `side` px around `center`, slid (not shrunk) inside the
    frame. Near an edge the crop slides until it fits, so the hand stays in it."""
    cx, cy = center
    half = max(side, 1.0) / 2.0
    x0, y0, x1, y1 = cx - half, cy - half, cx + half, cy + half
    if x0 < 0.0:
        x1 -= x0
        x0 = 0.0
    if y0 < 0.0:
        y1 -= y0
        y0 = 0.0
    if x1 > frame_w:
        x0 -= x1 - frame_w
        x1 = float(frame_w)
    if y1 > frame_h:
        y0 -= y1 - frame_h
        y1 = float(frame_h)
    return Rect(max(x0, 0.0), max(y0, 0.0),
                min(x1, float(frame_w)), min(y1, float(frame_h)))


def _comfortable(box, rect, deadband):
    """Is the hand still sitting comfortably inside this crop?

    It has to fit with room to spare, and its center has to be within the middle
    (1 - deadband) of the crop, so the crop is not recomputed for a hand that is
    moving gently -- that recomputation is what would make the zoom shiver.
    """
    if not rect.contains(box):
        return False
    cx, cy = box.center
    rx, ry = rect.center
    lim = (1.0 - max(0.0, min(deadband, 0.9))) / 2.0 * rect.side
    return abs(cx - rx) <= lim and abs(cy - ry) <= lim


def plan_crop(box, frame_w, frame_h, *, fill=FILL, deadband=DEADBAND,
              previous=None, min_side=MIN_CROP):
    """The crop to feed the model next: square, around the hand, inside the frame.

    `previous` is the crop used last frame. While the hand is still comfortable
    inside it (and has not moved much nearer or further), that crop is kept
    unchanged -- the zoom follows the hand, it does not chase it.
    """
    wanted = crop_side_for(box, fill, min_side)
    if previous is not None and _comfortable(box, previous, deadband):
        if 0.70 * previous.side <= wanted <= 1.45 * previous.side:
            return previous
    return square_at(box.center, wanted, frame_w, frame_h)


def upscale_for(side, target_side=TARGET_SIDE, max_upscale=MAX_UPSCALE):
    """How far tracker.py will scale a crop of `side` px before detection.
    Matches HandTracker._resize_for_model for a square crop: big crops are
    downscaled freely, small ones are upscaled only up to `max_upscale`."""
    side = max(float(side), 1.0)
    k = target_side / side
    return min(k, max_upscale) if k >= 1.0 else k


def hand_fill(box, crop):
    """Share of the crop the hand covers (0..1): 0.55 is the plan, 0.13 is a
    whole-frame scan of a hand at 3 m."""
    return min(max(hand_side(box) / max(crop.side, 1.0), 0.0), 1.0)


def model_hand_share(box, crop, target_side=TARGET_SIDE, max_upscale=MAX_UPSCALE):
    """Share of the model's input the hand ends up covering, after the upscale.
    This is the number that decides how findable the hand is. Uses the SHORT side
    of the crop, because that is what tracker._resize_for_model normalises on."""
    return hand_side(box) * upscale_for(crop.short, target_side, max_upscale) / target_side


def scan_tiles(frame_w, frame_h, cols=2, rows=2, overlap=0.25):
    """Overlapping tiles covering the frame, the middle one first.

    Used only while there is no hand to crop around. A tile is the same cost to
    detect as the whole frame (the model input is fixed), but the frame's pixels
    are shared between fewer of them, so the same hand is much larger in the
    model's input. Rotating through them one per frame keeps the cost at one
    extra detection per frame and stops as soon as a hand is found.
    """
    cols, rows = max(int(cols), 1), max(int(rows), 1)
    overlap = max(0.0, min(float(overlap), 0.9))
    tw = frame_w / (cols - (cols - 1) * overlap)
    th = frame_h / (rows - (rows - 1) * overlap)
    sx, sy = tw * (1.0 - overlap), th * (1.0 - overlap)
    tiles = [Rect(i * sx, j * sy, i * sx + tw, j * sy + th)
             for j in range(rows) for i in range(cols)]
    mx, my = frame_w / 2.0, frame_h / 2.0
    tiles.sort(key=lambda t: (t.center[0] - mx) ** 2 + (t.center[1] - my) ** 2)
    return tiles
