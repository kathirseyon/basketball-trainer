"""Plain data structures shared across the pipeline.

Everything downstream of the detector works on these types, so the analytics
can be unit-tested without a camera or a neural network.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

# COCO-17 keypoint indices produced by YOLO pose models.
NOSE = 0
L_SHOULDER, R_SHOULDER = 5, 6
L_WRIST, R_WRIST = 9, 10
L_HIP, R_HIP = 11, 12
L_ANKLE, R_ANKLE = 15, 16

YOU = "YOU"
OPPONENT = "OPPONENT"
ROLES = (YOU, OPPONENT)


@dataclass(frozen=True)
class Box:
    """Axis-aligned box in pixel coordinates (x1, y1) top-left, (x2, y2) bottom-right."""

    x1: float
    y1: float
    x2: float
    y2: float

    @classmethod
    def from_xywh(cls, x: float, y: float, w: float, h: float) -> "Box":
        return cls(x, y, x + w, y + h)

    @property
    def w(self) -> float:
        return max(0.0, self.x2 - self.x1)

    @property
    def h(self) -> float:
        return max(0.0, self.y2 - self.y1)

    @property
    def cx(self) -> float:
        return (self.x1 + self.x2) / 2

    @property
    def cy(self) -> float:
        return (self.y1 + self.y2) / 2

    @property
    def center(self) -> tuple[float, float]:
        return self.cx, self.cy

    @property
    def foot(self) -> tuple[float, float]:
        """Bottom-centre of the box: where a standing player touches the floor."""
        return self.cx, self.y2

    @property
    def area(self) -> float:
        return self.w * self.h

    def iou(self, other: "Box") -> float:
        ix = max(0.0, min(self.x2, other.x2) - max(self.x1, other.x1))
        iy = max(0.0, min(self.y2, other.y2) - max(self.y1, other.y1))
        inter = ix * iy
        union = self.area + other.area - inter
        return inter / union if union > 0 else 0.0

    def expand(self, sx: float, sy: float | None = None) -> "Box":
        sy = sx if sy is None else sy
        dw, dh = self.w * sx / 2, self.h * sy / 2
        return Box(self.x1 - dw, self.y1 - dh, self.x2 + dw, self.y2 + dh)

    def shift(self, dx: float, dy: float) -> "Box":
        return Box(self.x1 + dx, self.y1 + dy, self.x2 + dx, self.y2 + dy)

    def contains(self, x: float, y: float) -> bool:
        return self.x1 <= x <= self.x2 and self.y1 <= y <= self.y2

    def clip(self, width: int, height: int) -> "Box":
        return Box(
            min(max(self.x1, 0), width - 1),
            min(max(self.y1, 0), height - 1),
            min(max(self.x2, 0), width - 1),
            min(max(self.y2, 0), height - 1),
        )

    def as_int(self) -> tuple[int, int, int, int]:
        return int(round(self.x1)), int(round(self.y1)), int(round(self.x2)), int(round(self.y2))


@dataclass
class Person:
    box: Box
    conf: float = 1.0
    keypoints: np.ndarray | None = None  # (17, 3): x, y, confidence
    track_id: int | None = None

    def kp(self, idx: int, min_conf: float = 0.3) -> tuple[float, float] | None:
        if self.keypoints is None or idx >= len(self.keypoints):
            return None
        x, y, c = self.keypoints[idx]
        return (float(x), float(y)) if c >= min_conf else None

    def head_y(self) -> float:
        nose = self.kp(NOSE)
        return nose[1] if nose else self.box.y1 + 0.08 * self.box.h

    def wrists(self) -> dict[str, tuple[float, float]]:
        """Anatomical left/right wrists that were detected with enough confidence."""
        out = {}
        for side, idx in (("L", L_WRIST), ("R", R_WRIST)):
            p = self.kp(idx)
            if p is not None:
                out[side] = p
        return out

    def hip_y(self) -> float:
        hips = [p for p in (self.kp(L_HIP), self.kp(R_HIP)) if p]
        if hips:
            return sum(p[1] for p in hips) / len(hips)
        return self.box.y1 + 0.55 * self.box.h


@dataclass
class Detections:
    persons: list[Person] = field(default_factory=list)
    ball: Box | None = None          # most confident ball detection
    ball_conf: float = 0.0
    balls: list[tuple[Box, float]] = field(default_factory=list)  # every ball candidate
    hoop: Box | None = None

    def ball_candidates(self) -> list[tuple[Box, float]]:
        if self.balls:
            return self.balls
        return [(self.ball, self.ball_conf or 1.0)] if self.ball is not None else []
