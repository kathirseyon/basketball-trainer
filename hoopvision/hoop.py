"""Keeps a stable estimate of where the hoop is.

The hoop barely moves when the phone is on a tripod, so once we know where it
is (from a detector or a one-time manual selection) we smooth detections and
fall back to template matching to follow small camera shake.
"""

from __future__ import annotations

import cv2
import numpy as np

from .structures import Box


class HoopTracker:
    def __init__(self, smoothing: float = 0.85, search_scale: float = 3.0, match_threshold: float = 0.55):
        self.box: Box | None = None
        self.template: np.ndarray | None = None
        self.smoothing = smoothing
        self.search_scale = search_scale
        self.match_threshold = match_threshold
        self.manual = False

    def set_manual(self, frame: np.ndarray, box: Box) -> None:
        self.manual = True
        self.box = box
        self._grab_template(frame)

    def _grab_template(self, frame: np.ndarray) -> None:
        if self.box is None:
            return
        h, w = frame.shape[:2]
        x1, y1, x2, y2 = self.box.clip(w, h).as_int()
        if x2 - x1 >= 4 and y2 - y1 >= 4:
            self.template = cv2.cvtColor(frame[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)

    def _blend(self, new: Box) -> Box:
        if self.box is None:
            return new
        a = self.smoothing
        return Box(*(a * o + (1 - a) * n for o, n in zip(
            (self.box.x1, self.box.y1, self.box.x2, self.box.y2), (new.x1, new.y1, new.x2, new.y2))))

    def _match(self, frame: np.ndarray) -> Box | None:
        if self.template is None or self.box is None:
            return None
        h, w = frame.shape[:2]
        th, tw = self.template.shape
        sx1, sy1, sx2, sy2 = self.box.expand(self.search_scale - 1).clip(w, h).as_int()
        if sx2 - sx1 <= tw or sy2 - sy1 <= th:
            return None
        region = cv2.cvtColor(frame[sy1:sy2, sx1:sx2], cv2.COLOR_BGR2GRAY)
        res = cv2.matchTemplate(region, self.template, cv2.TM_CCOEFF_NORMED)
        _, score, _, loc = cv2.minMaxLoc(res)
        if score < self.match_threshold:
            return None
        return Box.from_xywh(sx1 + loc[0], sy1 + loc[1], tw, th)

    def update(self, frame: np.ndarray, detected: Box | None = None) -> Box | None:
        if detected is not None:
            first = self.box is None
            self.box = self._blend(detected)
            if first or self.template is None:
                self._grab_template(frame)
        else:
            matched = self._match(frame)
            if matched is not None:
                self.box = self._blend(matched)
        return self.box
