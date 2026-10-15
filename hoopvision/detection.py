"""Neural-network front end: turns a BGR frame into `Detections`.

Players come from a YOLO *pose* model (boxes + 17 body keypoints + ByteTrack
IDs). The ball comes from the COCO "sports ball" class of a regular YOLO
detector. Stock COCO has no hoop class, so the hoop either comes from an
optional custom model (see scripts/train_hoop_detector.py) or from the
`HoopTracker` after a one-time manual selection.
"""

from __future__ import annotations

from typing import Protocol

import cv2
import numpy as np

from .structures import Box, Detections, Person

COCO_PERSON = 0
COCO_SPORTS_BALL = 32
HOOP_NAMES = ("hoop", "rim", "basket", "net")
BALL_NAMES = ("ball", "basketball")


class Detector(Protocol):
    def __call__(self, frame: np.ndarray) -> Detections: ...


def _class_ids(names: dict[int, str], keywords: tuple[str, ...]) -> list[int]:
    return [i for i, n in names.items() if any(k in n.lower() for k in keywords)]


def _all_boxes(result, class_ids: list[int] | None, dx: float = 0.0, dy: float = 0.0,
               scale: float = 1.0) -> list[tuple[Box, float]]:
    boxes = result.boxes
    if boxes is None or len(boxes) == 0:
        return []
    out = []
    for b, c, k in zip(boxes.xyxy.cpu().numpy(), boxes.conf.cpu().numpy(), boxes.cls.cpu().numpy().astype(int)):
        if class_ids is not None and k not in class_ids:
            continue
        x1, y1, x2, y2 = (float(v) / scale for v in b)
        out.append((Box(x1 + dx, y1 + dy, x2 + dx, y2 + dy), float(c)))
    return out


def _best_box(result, class_ids: list[int] | None) -> tuple[Box | None, float]:
    boxes = result.boxes
    if boxes is None or len(boxes) == 0:
        return None, 0.0
    xyxy = boxes.xyxy.cpu().numpy()
    conf = boxes.conf.cpu().numpy()
    cls = boxes.cls.cpu().numpy().astype(int)
    best, best_conf = None, 0.0
    for b, c, k in zip(xyxy, conf, cls):
        if class_ids is not None and k not in class_ids:
            continue
        if c > best_conf:
            best, best_conf = Box(*map(float, b)), float(c)
    return best, best_conf


class YoloDetector:
    def __init__(
        self,
        pose_weights: str = "yolo11n-pose.pt",
        ball_weights: str | None = "yolo11n.pt",
        hoop_weights: str | None = None,
        device: str | None = None,
        imgsz: int = 640,
        ball_imgsz: int = 960,
        person_conf: float = 0.4,
        ball_conf: float = 0.15,
        hoop_conf: float = 0.3,
        track: bool = True,
    ):
        from ultralytics import YOLO  # imported lazily so tests don't need torch

        self.pose = YOLO(pose_weights)
        self.ball_model = YOLO(ball_weights) if ball_weights else None
        self.hoop_model = YOLO(hoop_weights) if hoop_weights else None
        self.device = device
        self.imgsz = imgsz
        self.ball_imgsz = ball_imgsz
        self.person_conf = person_conf
        self.ball_conf = ball_conf
        self.hoop_conf = hoop_conf
        self.track = track

        self.hoop_classes: list[int] = []
        self.custom_ball_classes: list[int] = []
        if self.hoop_model is not None:
            names = self.hoop_model.names
            self.hoop_classes = _class_ids(names, HOOP_NAMES)
            # Many community basketball models also detect the ball; use it if so.
            self.custom_ball_classes = [i for i in _class_ids(names, BALL_NAMES) if i not in self.hoop_classes]

    def _common(self) -> dict:
        kw = {"verbose": False}
        if self.device:
            kw["device"] = self.device
        return kw

    def __call__(self, frame: np.ndarray) -> Detections:
        kw = self._common()
        pose_args = dict(classes=[COCO_PERSON], conf=self.person_conf, imgsz=self.imgsz, **kw)
        if self.track:
            res = self.pose.track(frame, persist=True, tracker="bytetrack.yaml", **pose_args)[0]
        else:
            res = self.pose.predict(frame, **pose_args)[0]

        persons: list[Person] = []
        if res.boxes is not None and len(res.boxes):
            xyxy = res.boxes.xyxy.cpu().numpy()
            confs = res.boxes.conf.cpu().numpy()
            ids = res.boxes.id.int().cpu().numpy() if res.boxes.id is not None else [None] * len(xyxy)
            kps = res.keypoints.data.cpu().numpy() if res.keypoints is not None else None
            for i, (b, c, tid) in enumerate(zip(xyxy, confs, ids)):
                persons.append(
                    Person(
                        box=Box(*map(float, b)),
                        conf=float(c),
                        keypoints=kps[i] if kps is not None else None,
                        track_id=int(tid) if tid is not None else None,
                    )
                )

        det = Detections(persons=persons)

        if self.ball_model is not None:
            r = self.ball_model.predict(
                frame, classes=[COCO_SPORTS_BALL], conf=self.ball_conf, imgsz=self.ball_imgsz, **kw
            )[0]
            det.balls += _all_boxes(r, None)

        if self.hoop_model is not None:
            r = self.hoop_model.predict(frame, conf=self.hoop_conf, imgsz=self.imgsz, **kw)[0]
            det.hoop, _ = _best_box(r, self.hoop_classes or None)
            if self.custom_ball_classes:
                det.balls += _all_boxes(r, self.custom_ball_classes)

        if det.balls:
            det.ball, det.ball_conf = max(det.balls, key=lambda bc: bc[1])
        return det

    def detect_ball_near(self, frame: np.ndarray, region: Box) -> list[tuple[Box, float]]:
        """Re-run ball detection on a zoomed crop: a small, blurry ball is far easier to
        find at 3-4x magnification than in the full frame."""
        model = self.hoop_model if self.custom_ball_classes else self.ball_model
        if model is None:
            return []
        h, w = frame.shape[:2]
        x1, y1, x2, y2 = region.clip(w, h).as_int()
        if x2 - x1 < 16 or y2 - y1 < 16:
            return []
        crop = frame[y1:y2, x1:x2]
        side = 320
        scale = side / max(crop.shape[:2])
        crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_LINEAR)
        classes = self.custom_ball_classes if self.custom_ball_classes else [COCO_SPORTS_BALL]
        r = model.predict(crop, classes=classes, conf=self.ball_conf, imgsz=side, **self._common())[0]
        return _all_boxes(r, None, x1, y1, scale)
