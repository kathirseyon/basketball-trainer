"""Frame sources: laptop webcam, phone camera stream, or a recorded video file."""

from __future__ import annotations

import threading
import time
from typing import Iterator

import cv2
import numpy as np

STREAM_PREFIXES = ("http://", "https://", "rtsp://", "rtmp://", "udp://", "tcp://")


def parse_source(src: str | int) -> str | int:
    if isinstance(src, int):
        return src
    return int(src) if src.strip().isdigit() else src


def is_live(src: str | int) -> bool:
    src = parse_source(src)
    return isinstance(src, int) or src.lower().startswith(STREAM_PREFIXES)


class FrameSource:
    """Iterates ``(frame_index, timestamp_seconds, frame)``.

    Video files are read frame by frame and timestamped from their FPS, so the
    analysis is identical no matter how fast your computer is. Live sources
    are read on a background thread that always keeps only the newest frame;
    otherwise a slow model makes a phone stream fall further and further behind.
    """

    def __init__(self, src: str | int, width: int | None = None):
        self.src = parse_source(src)
        self.live = is_live(self.src)
        self.width = width
        self.cap = cv2.VideoCapture(self.src)
        if not self.cap.isOpened():
            hint = (
                "Check the camera index (try 0 or 1)." if isinstance(self.src, int)
                else "Check the path, or that the phone stream URL opens in a browser on this network."
            )
            raise RuntimeError(f"Could not open video source {self.src!r}. {hint}")
        fps = self.cap.get(cv2.CAP_PROP_FPS)
        self.fps = fps if fps and 1 < fps < 240 else 30.0
        self.frame_count = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT)) if not self.live else 0
        self._latest: np.ndarray | None = None
        self._seq = 0
        self._stop = False
        self._cond = threading.Condition()
        self._thread: threading.Thread | None = None
        if self.live:
            self._thread = threading.Thread(target=self._reader, daemon=True)
            self._thread.start()

    def _reader(self) -> None:
        while not self._stop:
            ok, frame = self.cap.read()
            with self._cond:
                if not ok:
                    self._stop = True
                else:
                    self._latest = frame
                    self._seq += 1
                self._cond.notify_all()

    def _resize(self, frame: np.ndarray) -> np.ndarray:
        if self.width and frame.shape[1] != self.width:
            h = int(frame.shape[0] * self.width / frame.shape[1])
            frame = cv2.resize(frame, (self.width, h), interpolation=cv2.INTER_AREA)
        return frame

    def __iter__(self) -> Iterator[tuple[int, float, np.ndarray]]:
        idx = 0
        if not self.live:
            while True:
                ok, frame = self.cap.read()
                if not ok:
                    return
                yield idx, idx / self.fps, self._resize(frame)
                idx += 1
        start = time.monotonic()
        seen = 0
        while True:
            with self._cond:
                self._cond.wait_for(lambda: self._seq != seen or self._stop, timeout=5.0)
                if self._seq == seen:
                    return  # stream ended or stalled
                seen, frame = self._seq, self._latest
            yield idx, time.monotonic() - start, self._resize(frame)
            idx += 1

    def release(self) -> None:
        self._stop = True
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        self.cap.release()
