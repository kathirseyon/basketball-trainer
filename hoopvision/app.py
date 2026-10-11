"""Ties detector → hoop tracker → identity → analyzer → commentary → overlay together."""

from __future__ import annotations

import threading
import time
from collections import deque

import cv2
import numpy as np

from . import overlay
from .analyzer import GameAnalyzer
from .chat import AIAnalyst, CoachChat
from .coach import Tip, generate_tips
from .commentary import Commentator
from .court_view import CourtView
from .detection import Detector
from .hoop import HoopTracker
from .identity import IdentityAssigner
from .patterns import describe, frequent_sequences
from .structures import OPPONENT, ROLES, YOU, Box


class Session:
    def __init__(
        self,
        detector: Detector,
        identity: IdentityAssigner | None = None,
        analyzer: GameAnalyzer | None = None,
        hoop: HoopTracker | None = None,
        names: dict[str, str] | None = None,
        tip_interval: float = 4.0,
        show_skeleton: bool = False,
        show_court: bool = True,
        scout_target: int = 5,
        can_detect_hoop: bool = False,
    ):
        self.detector = detector
        self.identity = identity or IdentityAssigner()
        self.analyzer = analyzer or GameAnalyzer()
        self.hoop = hoop or HoopTracker()
        self.names = {YOU: YOU, OPPONENT: OPPONENT, **(names or {})}
        self.tip_interval = tip_interval
        self.show_skeleton = show_skeleton
        self.show_court = show_court
        self.can_detect_hoop = can_detect_hoop
        self.commentator = Commentator(self.names, scout_target=scout_target)
        self.court = CourtView(overlay.COLORS, self.names)
        self.feed: deque[tuple[str, str]] = deque(maxlen=4)
        self.trail: deque[tuple[float, float]] = deque(maxlen=14)
        self._ball_missing = 0
        self.ball_seen = False
        self.tip: Tip | None = None
        self.latest_tips: list[Tip] = []
        self._last_tip_t = -1e9
        self.snapshot: np.ndarray | None = None
        self.frame_size: tuple[int, int] | None = None  # (w, h) of the camera view
        self._fps: float | None = None
        self._last_wall: float | None = None
        self.lock = threading.RLock()  # the web server reads state from other threads
        self.analyst: AIAnalyst | None = None

    # ------------------------------------------------------------- chat hooks
    def enable_ai(self, chat: CoachChat, commentary: bool = True) -> None:
        if commentary:
            self.analyst = AIAnalyst(chat, lambda text: self.commentator.say("ai", text))

    def tips(self) -> list[Tip]:
        with self.lock:
            return generate_tips(self.analyzer.summary())

    def context(self) -> dict:
        """Everything the chat coach gets to see about the game so far."""
        with self.lock:
            summary = self.analyzer.summary()
            for p in summary["players"].values():
                p["sequences"] = p["sequences"][-12:]
            return {
                "names": dict(self.names),
                "clock": self.commentator.status(self.analyzer)["clock"],
                "phase": self.commentator.phase,
                "summary": summary,
                "patterns": {
                    r: [{"description": describe(p), "possessions": n}
                        for p, n in frequent_sequences(self.analyzer.sequences(r))]
                    for r in ROLES
                },
                "tips": [t.to_dict() for t in generate_tips(summary)],
                "commentary": [l.text for l in self.commentator.lines[-15:]],
            }

    def state(self) -> dict:
        """Small JSON for the dashboard's polling loop."""
        with self.lock:
            board = self.analyzer.scoreboard()["players"]
            holder = self.analyzer.possession.player if self.analyzer.possession else None
            return {
                "status": self.commentator.status(self.analyzer),
                "names": dict(self.names),
                "holder": holder,
                "score": {r: board[r] for r in ROLES},
                "tip": self.tip.to_dict() if self.tip else None,
                "frame": {"w": self.frame_size[0], "h": self.frame_size[1]} if self.frame_size else None,
                "fps": round(self._fps or 0, 1),
            }

    def set_hoop(self, frame: np.ndarray, box: Box) -> None:
        with self.lock:
            self.hoop.set_manual(frame, box)

    # ---------------------------------------------------------------- per frame
    def process(self, idx: int, t: float, frame: np.ndarray) -> np.ndarray:
        det = self.detector(frame)
        with self.lock:
            self.frame_size = (frame.shape[1], frame.shape[0])
            hoop = self.hoop.update(frame, det.hoop)
            players = self.identity.update(frame, det.persons, t)
            events = self.analyzer.update(idx, t, players, det.ball, hoop, frame.shape[1])
            self.ball_seen |= det.ball is not None

            for e in events:
                if e.kind != "dribble":
                    self.feed.append((e.player, e.text().replace(e.player, self.names[e.player], 1)))
            if det.ball is not None:
                self.trail.append(det.ball.center)
                self._ball_missing = 0
            else:
                self._ball_missing += 1
                if self._ball_missing > 8:
                    self.trail.clear()

            new_tips = None
            if t - self._last_tip_t >= self.tip_interval:
                self.latest_tips = generate_tips(self.analyzer.summary())
                self.tip = self.latest_tips[0] if self.latest_tips else None
                self._last_tip_t = t
                new_tips = self.latest_tips

            shirts = {r: self.identity.shirt(r) for r in ROLES}
            self.commentator.update(
                t, hoop_ready=hoop is not None, players=players, shirts=shirts, ball_seen=self.ball_seen,
                events=events, analyzer=self.analyzer, tips=new_tips, can_detect_hoop=self.can_detect_hoop,
            )
            if self.analyst is not None and self.commentator.phase != "calibrating":
                done = sum(len(self.analyzer.stats[r].possessions) for r in ROLES)
                self.analyst.maybe_run(t, done)

            for r in ROLES:
                self.court.push(r, self.analyzer.current_pos(r))

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
            overlay.draw_hitbox(img, p.box, self.names[role], color, "BALL" if holder == role else None)
        overlay.draw_ball(img, ball, self.trail)
        overlay.draw_scoreboard(img, self.analyzer.scoreboard(), holder, self._fps, self.names)
        overlay.draw_feed(img, list(self.feed))
        overlay.draw_phase(img, self.commentator.status(self.analyzer))
        if self.tip is not None and self.commentator.phase != "calibrating":
            overlay.draw_coach(img, self.tip.title, self.tip.evidence)
        if not self.identity.initialized:
            overlay.draw_status(img, "Waiting for both players to be in frame...")
        if self.show_court:
            h, w = img.shape[:2]
            img = np.vstack([img, self.court.render(w, int(w * 0.56))])
        return img


def encode_jpeg(img: np.ndarray, quality: int = 80) -> bytes:
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return buf.tobytes() if ok else b""
