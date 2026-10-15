"""Ball tracking: a constant-velocity Kalman filter over noisy detections.

Per-frame ball detection is the weakest part of the pipeline: the ball is
small, blurred and often hidden by a hand. The tracker

* picks the detection that agrees with where the ball should be (gating), so
  a stray "ball" in the background doesn't hijack it,
* keeps predicting through short dropouts ("coasting"),
* jumps to a new spot when a confident detection keeps appearing there
  (e.g. the ball is picked up under the net after a make), and
* tells the detector where to look, so it can re-run on a zoomed crop around
  the prediction (see `YoloDetector.detect_ball_near`).

Only real measurements are fed to the event analyzer; predictions are used
for drawing and for the zoomed re-search, so they can never fake a dribble or
a make.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .structures import Box


@dataclass
class BallState:
    box: Box                 # filtered position, smoothed size
    measured: Box | None     # the detection used this frame (None while coasting)
    velocity: tuple[float, float]  # px / s
    conf: float
    coasting: float          # seconds since the last measurement
    jumped: bool = False     # track (re)started here: don't connect it to the old trail

    @property
    def visible(self) -> bool:
        return self.measured is not None


class BallTracker:
    def __init__(
        self,
        init_conf: float = 0.3,
        max_coast: float = 0.6,
        gate_diameters: float = 5.0,
        gate_speed_factor: float = 0.6,
        process_noise: float = 4000.0,
        measurement_noise: float = 6.0,
        jump_frames: int = 3,
    ):
        self.init_conf = init_conf
        self.max_coast = max_coast
        self.gate_diameters = gate_diameters
        self.gate_speed_factor = gate_speed_factor
        self.q = process_noise         # px/s^2 - balls change direction violently (dribbles)
        self.r = measurement_noise     # px
        self.jump_frames = jump_frames
        self._challenger: tuple[Box, int] | None = None  # confident detection outside the gate
        self._challenger_box: Box | None = None
        self.x: np.ndarray | None = None  # [x, y, vx, vy]
        self.P = np.eye(4)
        self.size = 0.0
        self.t: float | None = None
        self.last_seen: float | None = None
        self.conf = 0.0
        self.frames = 0
        self.visible_frames = 0

    @property
    def active(self) -> bool:
        return self.x is not None

    def reset(self) -> None:
        self.x = None
        self.t = self.last_seen = None

    def predicted(self) -> Box | None:
        if self.x is None:
            return None
        r = self.size / 2
        return Box(self.x[0] - r, self.x[1] - r, self.x[0] + r, self.x[1] + r)

    def search_region(self, t: float) -> Box | None:
        """Where to look for the ball this frame (for zoomed re-detection)."""
        if self.x is None:
            return None
        self._predict(t)
        coast = t - (self.last_seen or t)
        radius = max(self.size * 4, 60.0) + float(np.hypot(*self.x[2:])) * coast * 0.5
        return Box(self.x[0] - radius, self.x[1] - radius, self.x[0] + radius, self.x[1] + radius)

    def _predict(self, t: float) -> None:
        if self.t is None or t <= self.t:
            self.t = t if self.t is None else self.t
            return
        dt = t - self.t
        F = np.eye(4)
        F[0, 2] = F[1, 3] = dt
        g = np.array([[dt ** 2 / 2, 0], [0, dt ** 2 / 2], [dt, 0], [0, dt]])
        self.x = F @ self.x
        self.P = F @ self.P @ F.T + g @ g.T * self.q ** 2
        self.t = t

    def _correct(self, box: Box, conf: float) -> None:
        H = np.zeros((2, 4))
        H[0, 0] = H[1, 1] = 1
        R = np.eye(2) * self.r ** 2
        z = np.array(box.center)
        y = z - H @ self.x
        S = H @ self.P @ H.T + R
        K = self.P @ H.T @ np.linalg.inv(S)
        self.x = self.x + K @ y
        self.P = (np.eye(4) - K @ H) @ self.P
        self.size = 0.7 * self.size + 0.3 * max(box.w, box.h)
        self.conf = conf

    def _init(self, t: float, box: Box, conf: float) -> None:
        self.x = np.array([box.cx, box.cy, 0.0, 0.0])
        self.P = np.diag([self.r ** 2, self.r ** 2, 600.0 ** 2, 600.0 ** 2])
        self.size = max(box.w, box.h)
        self.t = self.last_seen = t
        self.conf = conf

    def update(self, t: float, candidates: list[tuple[Box, float]]) -> BallState | None:
        self.frames += 1
        if self.x is None:
            good = [c for c in candidates if c[1] >= self.init_conf]
            if not good:
                return None
            box, conf = max(good, key=lambda c: c[1])
            self._init(t, box, conf)
            self.visible_frames += 1
            return BallState(box, box, (0.0, 0.0), conf, 0.0, jumped=True)

        self._predict(t)
        coast = t - self.last_seen
        speed = float(np.hypot(self.x[2], self.x[3]))
        gate = max(self.size, 8.0) * self.gate_diameters + speed * max(coast, 1 / 30) * self.gate_speed_factor
        best, best_cost = None, float("inf")
        for box, conf in candidates:
            d = float(np.hypot(box.cx - self.x[0], box.cy - self.x[1]))
            if d > gate:
                continue
            cost = d / gate - 0.3 * conf  # nearer and more confident wins
            if cost < best_cost:
                best, best_cost = (box, conf), cost

        if best is None:
            if self._jump(t, candidates):
                return BallState(self.predicted(), self._challenger_box, (0.0, 0.0), self.conf, 0.0, jumped=True)
            if coast > self.max_coast:
                # Lost it. Re-acquire from scratch on a confident detection anywhere.
                self.reset()
                return self.update(t, candidates) if candidates else None
            return BallState(self.predicted(), None, (self.x[2], self.x[3]), self.conf, coast)

        self._challenger = None
        box, conf = best
        self._correct(box, conf)
        self.last_seen = t
        self.visible_frames += 1
        return BallState(self.predicted(), box, (self.x[2], self.x[3]), conf, 0.0)

    def _jump(self, t: float, candidates: list[tuple[Box, float]]) -> bool:
        """Re-anchor when the same confident detection shows up outside the gate N frames running."""
        good = [c for c in candidates if c[1] >= self.init_conf]
        if not good:
            self._challenger = None
            return False
        box, conf = max(good, key=lambda c: c[1])
        if self._challenger is not None:
            prev, n = self._challenger
            near = np.hypot(box.cx - prev.cx, box.cy - prev.cy) < max(prev.w, prev.h, 8.0) * self.gate_diameters
            self._challenger = (box, n + 1) if near else (box, 1)
        else:
            self._challenger = (box, 1)
        if self._challenger[1] < self.jump_frames:
            return False
        self._init(t, box, conf)
        self._challenger_box = box
        self._challenger = None
        self.visible_frames += 1
        return True

    @property
    def visibility(self) -> float:
        return self.visible_frames / self.frames if self.frames else 0.0
