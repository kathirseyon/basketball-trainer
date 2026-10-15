"""Ties detector → hoop tracker → identity → analyzer → commentary → overlay together."""

from __future__ import annotations

import threading
import time
from collections import deque

import cv2
import numpy as np

from . import overlay
from .analyzer import GameAnalyzer
from .ball import BallState, BallTracker
from .chat import AIAnalyst, CoachChat
from .coach import Tip, generate_tips
from .commentary import Commentator
from .court_view import CourtView
from .detection import Detector
from .hoop import HoopTracker
from .identity import IdentityAssigner
from .patterns import describe, frequent_sequences
from .scoring import Scoreboard
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
        scoreboard: Scoreboard | None = None,
        ball_tracker: BallTracker | None = None,
    ):
        self.detector = detector
        self.identity = identity or IdentityAssigner()
        self.analyzer = analyzer or GameAnalyzer()
        self.hoop = hoop or HoopTracker()
        self.scoreboard = scoreboard or Scoreboard()
        self.ball = ball_tracker or BallTracker()
        self.ball_state: BallState | None = None
        self.names = {YOU: YOU, OPPONENT: OPPONENT, **(names or {})}
        self.tip_interval = tip_interval
        self.show_skeleton = show_skeleton
        self.show_court = show_court
        self.can_detect_hoop = can_detect_hoop
        self.commentator = Commentator(self.names, scout_target=scout_target)
        self.court = CourtView(overlay.COLORS, self.names)
        self.feed: deque[tuple[str, str]] = deque(maxlen=4)
        self.trail: deque[tuple[float, float]] = deque(maxlen=14)
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
                "score": self.scoreboard.to_dict(),
                "ball_visible_share": round(self.ball.visibility, 2),
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
                "game": self.scoreboard.to_dict(),
                "ball": {
                    "tracking": self.ball.active,
                    "visible": bool(self.ball_state and self.ball_state.visible),
                    "visible_share": round(self.ball.visibility, 2),
                },
                "tip": self.tip.to_dict() if self.tip else None,
                "frame": {"w": self.frame_size[0], "h": self.frame_size[1]} if self.frame_size else None,
                "fps": round(self._fps or 0, 1),
            }

    def set_hoop(self, frame: np.ndarray, box: Box) -> None:
        with self.lock:
            self.hoop.set_manual(frame, box)

    # ------------------------------------------------------------------ score
    def score_text(self) -> str:
        p = self.scoreboard.points
        return f"{self.names[YOU]} {p[YOU]} - {self.names[OPPONENT]} {p[OPPONENT]}"

    def _announce(self, announcements: list[dict]) -> None:
        sb = self.scoreboard
        for a in announcements:
            if a["type"] == "game_point":
                self.commentator.say("score", f"Game point {self.names[a['player']]}! ({self.score_text()})",
                                     a["player"])
            elif a["type"] == "game_over":
                w = a["winner"]
                lose = OPPONENT if w == YOU else YOU
                series = f"{self.names[YOU]} {sb.games_won[YOU]} - {self.names[OPPONENT]} {sb.games_won[OPPONENT]}"
                self.commentator.say("score", f"GAME OVER - {self.names[w]} wins game {a['game']}, "
                                              f"{a['final'][w]}-{a['final'][lose]}. Games: {series}. "
                                              f"Game {sb.game} starts at 0-0.", w)

    def adjust_score(self, role: str, delta: int) -> None:
        """Manual correction from the dashboard / keyboard (e.g. a make the camera missed)."""
        with self.lock:
            before = dict(self.scoreboard.points)
            ann = self.scoreboard.add(self.commentator.t, role, delta, "manual")
            if ann or self.scoreboard.points != before:
                sign = "+" if delta > 0 else ""
                self.commentator.say("score", f"Score corrected: {sign}{delta} {self.names[role]} "
                                              f"({self.score_text()})", role)
            self._announce(ann)

    def undo_score(self) -> None:
        with self.lock:
            role = self.scoreboard.undo(self.commentator.t)
            if role is not None:
                self.commentator.say("score", f"Last score undone ({self.score_text()})", role)

    def _track_ball(self, frame: np.ndarray, t: float, det) -> BallState | None:
        cands = det.ball_candidates()
        near = getattr(self.detector, "detect_ball_near", None)
        region = self.ball.search_region(t)
        if near is not None and region is not None and not any(region.contains(*b.center) for b, _ in cands):
            # Full-frame detector missed it: look again, zoomed in, where it should be.
            cands = cands + near(frame, region)
        return self.ball.update(t, cands)

    # ---------------------------------------------------------------- per frame
    def process(self, idx: int, t: float, frame: np.ndarray) -> np.ndarray:
        det = self.detector(frame)
        with self.lock:
            self.frame_size = (frame.shape[1], frame.shape[0])
            hoop = self.hoop.update(frame, det.hoop)
            players = self.identity.update(frame, det.persons, t)
            ball = self.ball_state = self._track_ball(frame, t, det)
            # Only real measurements reach the analyzer; predictions can't fake a dribble or a make.
            events = self.analyzer.update(idx, t, players, ball.measured if ball else None, hoop, frame.shape[1])
            self.ball_seen |= self.ball.active

            announcements = []
            for e in events:
                if e.kind == "shot_result" and e.detail["result"] == "make":
                    pts, ann = self.scoreboard.make(t, e.player, e.detail["three"])
                    e.detail["points"] = pts
                    over = next((a for a in ann if a["type"] == "game_over"), None)
                    e.detail["score_text"] = (f"+{pts}, that's the game!" if over
                                              else f"+{pts} ({self.score_text()})")
                    announcements += ann

            for e in events:
                if e.kind != "dribble":
                    self.feed.append((e.player, e.text().replace(e.player, self.names[e.player], 1)))
            if ball is not None and ball.visible:
                if ball.jumped:
                    self.trail.clear()
                self.trail.append(ball.box.center)
            elif ball is None:
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
            self._announce(announcements)
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

            return self.render(frame, players, ball, hoop)

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
        overlay.draw_ball(img, ball.box if ball else None, self.trail, predicted=bool(ball and not ball.visible))
        board = self.analyzer.scoreboard()
        board["points"] = self.scoreboard.points
        overlay.draw_scoreboard(img, board, holder, self._fps, self.names)
        overlay.draw_feed(img, list(self.feed))
        overlay.draw_phase(img, self.commentator.status(self.analyzer))
        if self.tip is not None and self.commentator.phase != "calibrating":
            overlay.draw_coach(img, self.tip.title, self.tip.evidence)
        if not self.identity.initialized:
            overlay.draw_status(img, "Waiting for both players to be in frame...")
        if self.show_court:
            h, w = img.shape[:2]
            court = self.court.render(w, int(w * 0.56), ball_with=holder,
                                      ball_at_rim=self.analyzer.pending_shot is not None)
            img = np.vstack([img, court])
        return img


def encode_jpeg(img: np.ndarray, quality: int = 80) -> bytes:
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return buf.tobytes() if ok else b""
