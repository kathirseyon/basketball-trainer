"""Ties detector → hoop tracker → identity → analyzer → overlay together."""

from __future__ import annotations

import time
from collections import deque

import numpy as np

from . import overlay
from .analyzer import GameAnalyzer
from .coach import Tip, generate_tips
from .detection import Detector
from .hoop import HoopTracker
from .identity import IdentityAssigner
from .structures import ROLES


class Session:
    def __init__(
        self,
        detector: Detector,
        identity: IdentityAssigner | None = None,
        analyzer: GameAnalyzer | None = None,
        hoop: HoopTracker | None = None,
        tip_interval: float = 4.0,
        show_skeleton: bool = False,
    ):
        self.detector = detector
        self.identity = identity or IdentityAssigner()
        self.analyzer = analyzer or GameAnalyzer()
        self.hoop = hoop or HoopTracker()
        self.tip_interval = tip_interval
        self.show_skeleton = show_skeleton
        self.feed: deque[tuple[str, str]] = deque(maxlen=4)
        self.trail: deque[tuple[float, float]] = deque(maxlen=14)
        self._ball_missing = 0
        self.tip: Tip | None = None
        self._last_tip_t = -1e9
        self.snapshot: np.ndarray | None = None
        self._fps: float | None = None
        self._last_wall: float | None = None

    def tips(self) -> list[Tip]:
        return generate_tips(self.analyzer.summary())

    def process(self, idx: int, t: float, frame: np.ndarray) -> np.ndarray:
        det = self.detector(frame)
        hoop = self.hoop.update(frame, det.hoop)
        players = self.identity.update(frame, det.persons, t)
        events = self.analyzer.update(idx, t, players, det.ball, hoop, frame.shape[1])

        for e in events:
            if e.kind != "dribble":
                self.feed.append((e.player, e.text()))
        if det.ball is not None:
            self.trail.append(det.ball.center)
            self._ball_missing = 0
        else:
            self._ball_missing += 1
            if self._ball_missing > 8:
                self.trail.clear()

        if t - self._last_tip_t >= self.tip_interval:
            tips = self.tips()
            self.tip = tips[0] if tips else None
            self._last_tip_t = t

        if self.snapshot is None and all(players[r] is not None for r in ROLES):
            self.snapshot = frame.copy()

        now = time.monotonic()
        if self._last_wall is not None:
            inst = 1.0 / max(now - self._last_wall, 1e-6)
            self._fps = inst if self._fps is None else 0.9 * self._fps + 0.1 * inst
        self._last_wall = now

        return self.render(frame, players, det.ball, hoop)

    def render(self, frame, players, ball, hoop) -> np.ndarray:
        img = frame.copy()
        if hoop is not None:
            overlay.draw_hitbox(img, hoop, "HOOP", overlay.COLORS["HOOP"])
        holder = self.analyzer.possession.player if self.analyzer.possession else None
        for role in ROLES:
            p = players.get(role)
            if p is None:
                continue
            color = overlay.COLORS[role]
            if self.show_skeleton:
                overlay.draw_skeleton(img, p, color)
            overlay.draw_hitbox(img, p.box, role, color, "BALL" if holder == role else None)
        overlay.draw_ball(img, ball, self.trail)
        overlay.draw_scoreboard(img, self.analyzer.scoreboard(), holder, self._fps)
        overlay.draw_feed(img, list(self.feed))
        if self.tip is not None:
            overlay.draw_coach(img, self.tip.title, self.tip.evidence)
        if not self.identity.initialized:
            overlay.draw_status(img, "Waiting for both players to be in frame...")
        return img
