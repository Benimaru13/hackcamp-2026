"""tracker.py  --  webcam + MediaPipe HandLandmarker, tuned for long range.

Why this exists on top of MediaPipe: the detector resizes whatever image it is
given to its own fixed input, so the only thing that decides whether a hand is
findable is how much of that input the hand fills. In a whole 720p frame a hand at
3 m fills ~13% of it, and a hand at 1 m fills ~40% -- the same gesture gets harder
the further away you stand.

So the tracker auto-zooms, like a camera focusing on the hand (the planning is in
zoom.py, which is pure arithmetic and unit tested without a camera):

  * focus -- the last hand is cropped to a square just big enough to hold it, and
    that crop is what the model sees, so the hand fills the same ~55% of the input
    at 1 m and at 4 m. The crop follows the hand and holds still while the hand
    rests in its middle.
  * scan -- while nothing is tracked the frame is cut into overlapping tiles and
    one tile is tried per frame, each upscaled hard, so a hand too small for a
    full-frame detection is still found. The whole frame stays as the last resort.

Nothing here draws anything and nothing leaves the machine: frames are only ever
held in memory and are never written to disk or sent anywhere.
"""
from __future__ import annotations

import math
import os
import time
import urllib.request
from dataclasses import dataclass
from types import SimpleNamespace

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision

from zoom import (DEADBAND, FILL, Rect, hand_fill, plan_crop, scan_tiles)

MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
             "hand_landmarker/float16/1/hand_landmarker.task")
DEFAULT_MODEL = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "models", "hand_landmarker.task")


def ensure_model(path=DEFAULT_MODEL, url=MODEL_URL, quiet=False):
    """Download the 7.8 MB hand landmarker once, if it is not there yet."""
    if os.path.exists(path) and os.path.getsize(path) > 1_000_000:
        return path
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    if not quiet:
        print(f"[tracker] downloading hand model once -> {path}")
    tmp = path + ".part"
    urllib.request.urlretrieve(url, tmp)
    os.replace(tmp, path)
    return path


def boost_low_light(img, threshold=85.0, target=105.0):
    """Night lighting: in a dim room the frame goes dark and flat, and the landmark
    model finds the hand on one frame and misses it on the next -- exactly the
    "sometimes it works up close, sometimes it ignores me" behaviour. This maps a
    dark frame back toward a usable mid-grey with a gamma curve.

    Only the crop handed to the model is touched, so the preview keeps the real
    picture. No-op in normal light, and it cannot wash out a bright frame.
    """
    mean = float(img.mean())
    if mean >= threshold or mean <= 1.0:
        return img
    gamma = math.log(target / 255.0) / math.log(mean / 255.0)
    gamma = min(max(gamma, 0.35), 1.0)
    if gamma >= 0.99:
        return img
    lut = np.array([min(255, int(((i / 255.0) ** gamma) * 255.0)) for i in range(256)],
                   dtype=np.uint8)
    return cv2.LUT(img, lut)


@dataclass
class Frame:
    image: np.ndarray | None = None      # BGR full frame
    landmarks: list | None = None        # 21 points, normalized to the FULL frame
    box: tuple | None = None             # (x0, y0, x1, y1) in frame pixels
    zoom: float = 1.0                    # crop upscale actually used
    crop: Rect | None = None             # the crop the model was given, frame px
    fill: float = 0.0                    # hand side / crop side (0 = not cropped)
    focused: bool = False                # True when the detection used a crop
    fps: float = 0.0
    width: int = 0
    height: int = 0

    @property
    def detected(self):
        return self.landmarks is not None


class HandTracker:
    """cv2 camera + mediapipe Tasks HandLandmarker in VIDEO mode."""

    def __init__(self, camera=0, width=1280, height=720, model=DEFAULT_MODEL,
                 zoom=True, target_side=512, max_upscale=6.0, fill=FILL,
                 deadband=DEADBAND, min_detection=0.3, min_presence=0.3,
                 min_tracking=0.3):
        model = ensure_model(model)
        self.target_side = target_side
        self.max_upscale = max_upscale
        self.zoom = zoom
        self.fill = fill              # wanted hand side / crop side
        self.deadband = deadband      # keep the crop while the hand is this central

        self.cap = cv2.VideoCapture(camera)
        if not self.cap.isOpened():
            raise RuntimeError(
                f"could not open camera {camera}. Close other apps using it, or "
                f"pick another index with --camera 1.")
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)   # low latency: drop stale frames
        self.width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH) or width)
        self.height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or height)

        options = vision.HandLandmarkerOptions(
            base_options=mp_python.BaseOptions(model_asset_path=model),
            running_mode=vision.RunningMode.VIDEO,
            num_hands=1,
            min_hand_detection_confidence=min_detection,
            min_hand_presence_confidence=min_presence,
            min_tracking_confidence=min_tracking,
        )
        self.landmarker = vision.HandLandmarker.create_from_options(options)

        self._box = None          # float box in frame px, smoothed
        self._crop = None         # Rect of the focus crop that last worked
        self._tiles = None        # acquire scan tiles, built once per frame size
        self._tiles_for = None
        self._tile_i = 0
        self._misses = 0          # consecutive frames without a hand
        self._last_scan = 0.0
        self._t0 = time.monotonic()
        self._ts = 0
        self._fps = 0.0

    # ------------------------------------------------ helpers
    def _stamp(self):
        """Strictly increasing millisecond timestamps for detect_for_video."""
        ts = int((time.monotonic() - self._t0) * 1000)
        self._ts = max(self._ts + 1, ts)
        return self._ts

    def _detect(self, bgr):
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        img = mp.Image(image_format=mp.ImageFormat.SRGB,
                       data=np.ascontiguousarray(rgb))
        res = self.landmarker.detect_for_video(img, self._stamp())
        return res.hand_landmarks[0] if res.hand_landmarks else None

    def _crop_for(self, lm, x0, y0, x1, y1, frame_w, frame_h):
        """Landmarks inside a crop -> full-frame normalized points + pixel box."""
        w, h = x1 - x0, y1 - y0
        pts = [SimpleNamespace(x=(x0 + p.x * w) / frame_w,
                               y=(y0 + p.y * h) / frame_h,
                               z=p.z) for p in lm]
        xs = [p.x * frame_w for p in pts]
        ys = [p.y * frame_h for p in pts]
        box = (min(xs), min(ys), max(xs), max(ys))
        return pts, box

    def _resize_for_model(self, sub):
        """Up-scale a hand-sized crop (long range) and down-scale a full frame
        (reacquire) so the detector always sees roughly `target_side` pixels."""
        h, w = sub.shape[:2]
        side = min(w, h)
        if side >= self.target_side * 1.25:      # full frame: detect smaller = faster
            k = self.target_side / side
            return cv2.resize(sub, (int(w * k), int(h * k)),
                              interpolation=cv2.INTER_AREA), k
        if side >= self.target_side:
            return sub, 1.0
        k = min(self.target_side / max(side, 1), self.max_upscale)
        if k <= 1.05:
            return sub, 1.0
        return cv2.resize(sub, (int(w * k), int(h * k)), interpolation=cv2.INTER_LINEAR), k

    # ------------------------------------------------ main call
    def read(self) -> Frame:
        ok, frame = self.cap.read()
        if not ok or frame is None:
            return Frame(None, width=self.width, height=self.height)
        frame_h, frame_w = frame.shape[:2]
        t = time.monotonic()
        if self._fps:
            dt = max(t - self._last_scan, 1e-6)
            self._fps = 0.9 * self._fps + 0.1 * (1.0 / dt)
        else:
            self._fps = 1.0 / max(t - self._last_scan, 1e-6)
        self._last_scan = t

        landmarks = box = None
        zoom, fill = 1.0, 0.0
        focused, crop, used = False, None, None
        attempts = []            # (rect, kind): "focus", "scan" or "full"

        # 1) focus: crop around the last hand, sized so the hand fills ~55% of the
        #    model input at ANY distance. This is the range win -- the crop is
        #    planned from the hand, so the detector sees the same hand size at 1 m
        #    and at 4 m instead of one that shrinks with distance.
        if self.zoom and self._box is not None:
            attempts.append((plan_crop(Rect(*self._box), frame_w, frame_h,
                                       fill=self.fill, deadband=self.deadband,
                                       previous=self._crop), "focus"))
        # 2) scan: while nothing is tracked, one tile per frame. A far hand is too
        #    small to survive the downscale that a whole-frame scan applies, while
        #    in a tile it is upscaled instead. Rotation keeps this to one extra
        #    detection per frame, and it stops the moment a hand is found.
        if self.zoom:
            if self._tiles is None or self._tiles_for != (frame_w, frame_h):
                self._tiles = scan_tiles(frame_w, frame_h)
                self._tiles_for = (frame_w, frame_h)
                self._tile_i = 0
            if self._box is None and self._tiles:
                attempts.append((self._tiles[self._tile_i % len(self._tiles)], "scan"))
                self._tile_i += 1
        # 3) last resort: the whole frame (downscaled), so a hand anywhere is still
        #    found when every crop misses. Always present, not just after a miss:
        #    when the hand leaves the box the focus crop misses, and waiting a frame
        #    to notice turned one stale box into a dropped frame.
        attempts.append((Rect(0, 0, frame_w, frame_h), "full"))

        for rect, kind in attempts:
            x0, y0, x1, y1 = rect.ints()
            if x1 - x0 < 24 or y1 - y0 < 24:
                continue
            sub = frame[y0:y1, x0:x1]
            sub, k = self._resize_for_model(sub)
            sub = boost_low_light(sub)
            h, w = sub.shape[:2]
            found = self._detect(sub)
            if not found:
                continue
            landmarks, box = self._crop_for(found, x0, y0, x0 + w / k, y0 + h / k,
                                            frame_w, frame_h)
            used = kind
            focused = kind != "full"
            crop = rect if focused else None
            zoom = k if focused else 1.0
            fill = hand_fill(Rect(*box), rect) if focused else 0.0
            break

        if landmarks is not None:
            self._misses = 0
            # Only a focus crop is worth reusing next frame: a scan tile is just a
            # place the hand happened to be found, not a crop built around it.
            self._crop = crop if used == "focus" else None
            if self._box is None:
                self._box = box
            else:                       # smooth the tracking box
                a = 0.55
                self._box = tuple(a * n + (1 - a) * o for n, o in zip(box, self._box))
        else:
            self._misses += 1
            self._crop = None           # re-plan from scratch when it comes back
            if self._misses > 6:
                self._box = None

        return Frame(image=frame, landmarks=landmarks, box=box, zoom=zoom,
                     fps=self._fps, width=frame_w, height=frame_h,
                     crop=crop, fill=fill, focused=focused)

    def close(self):
        try:
            self.cap.release()
        finally:
            try:
                self.landmarker.close()
            except Exception:
                pass
