"""tracker.py  --  webcam + MediaPipe HandLandmarker, tuned for long range.

Why this exists on top of MediaPipe: at ~3 m (10 ft) the hand is only ~30-60 px
tall in a 720p frame and the detector starts missing it. This tracker keeps a box
around the last hand, crops it and upscales it to 512 px before detection, so the
hand looks big to the model again. When the hand is lost it re-scans the whole
frame (downscaled) to reacquire.

Nothing here draws anything and nothing leaves the machine: frames are only ever
held in memory and are never written to disk or sent anywhere.
"""
from __future__ import annotations

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


@dataclass
class Frame:
    image: np.ndarray | None = None      # BGR full frame
    landmarks: list | None = None        # 21 points, normalized to the FULL frame
    box: tuple | None = None             # (x0, y0, x1, y1) in frame pixels
    zoom: float = 1.0                    # crop upscale actually used
    fps: float = 0.0
    width: int = 0
    height: int = 0

    @property
    def detected(self):
        return self.landmarks is not None


class HandTracker:
    """cv2 camera + mediapipe Tasks HandLandmarker in VIDEO mode."""

    def __init__(self, camera=0, width=1280, height=720, model=DEFAULT_MODEL,
                 zoom=True, target_side=512, max_upscale=4.0,
                 min_detection=0.3, min_presence=0.3, min_tracking=0.3):
        model = ensure_model(model)
        self.target_side = target_side
        self.max_upscale = max_upscale
        self.zoom = zoom

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

    @staticmethod
    def _expand(box, margin, frame_w, frame_h):
        x0, y0, x1, y1 = box
        bw, bh = max(x1 - x0, 16.0), max(y1 - y0, 16.0)
        cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
        hw, hh = bw * (0.5 + margin), bh * (0.5 + margin)
        return (int(max(0, cx - hw)), int(max(0, cy - hh)),
                int(min(frame_w, cx + hw)), int(min(frame_h, cy + hh)))

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
        zoom = 1.0
        attempts = []

        # 1) tracking: crop around the last known hand (the long-range win)
        if self.zoom and self._box is not None:
            attempts.append(self._expand(self._box, 0.35, frame_w, frame_h))
        # 2) reacquire: full frame, downscaled so the model still sees a hand
        if self._box is None or self._misses > 0:
            attempts.append((0, 0, frame_w, frame_h))

        for (x0, y0, x1, y1) in attempts:
            if x1 - x0 < 24 or y1 - y0 < 24:
                continue
            sub = frame[y0:y1, x0:x1]
            sub, k = self._resize_for_model(sub)
            h, w = sub.shape[:2]
            found = self._detect(sub)
            if not found:
                continue
            landmarks, box = self._crop_for(found, x0, y0, x0 + w / k, y0 + h / k,
                                            frame_w, frame_h)
            zoom = k
            break

        if landmarks is not None:
            self._misses = 0
            if self._box is None:
                self._box = box
            else:                       # smooth the tracking box
                a = 0.55
                self._box = tuple(a * n + (1 - a) * o for n, o in zip(box, self._box))
        else:
            self._misses += 1
            if self._misses > 6:
                self._box = None

        return Frame(image=frame, landmarks=landmarks, box=box, zoom=zoom,
                     fps=self._fps, width=frame_w, height=frame_h)

    def close(self):
        try:
            self.cap.release()
        finally:
            try:
                self.landmarker.close()
            except Exception:
                pass
