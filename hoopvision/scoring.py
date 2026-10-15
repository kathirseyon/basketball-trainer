"""Keeps the score of a 1v1 game (and a series of games).

Points come from detected makes: a make from beyond the arc is worth the
"long" value, anything else the "short" value. Streetball 1s-and-2s is the
default; ``--scoring 2s3s`` gives standard 2s and 3s. Automatic make
detection isn't perfect, so manual corrections (+/- and undo) are first-class.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .structures import OPPONENT, ROLES, YOU

SCORING_SYSTEMS = {"1s2s": (1, 2), "2s3s": (2, 3)}


@dataclass
class ScoreChange:
    t: float
    player: str
    points: int
    reason: str  # "make" | "manual" | "undo"
    game: int


@dataclass
class Scoreboard:
    scoring: str = "1s2s"
    game_to: int = 11
    win_by: int = 1
    points: dict[str, int] = field(default_factory=lambda: {r: 0 for r in ROLES})
    games_won: dict[str, int] = field(default_factory=lambda: {r: 0 for r in ROLES})
    game: int = 1
    history: list[ScoreChange] = field(default_factory=list)
    final_scores: list[dict[str, int]] = field(default_factory=list)
    _undone: set[int] = field(default_factory=set, repr=False)

    def __post_init__(self) -> None:
        if self.scoring not in SCORING_SYSTEMS:
            raise ValueError(f"scoring must be one of {sorted(SCORING_SYSTEMS)}")

    @property
    def values(self) -> tuple[int, int]:
        return SCORING_SYSTEMS[self.scoring]

    def value_of_make(self, three: bool) -> int:
        short, long = self.values
        return long if three else short

    def _winner(self) -> str | None:
        for r in ROLES:
            other = OPPONENT if r == YOU else YOU
            if self.points[r] >= self.game_to and self.points[r] - self.points[other] >= self.win_by:
                return r
        return None

    def add(self, t: float, player: str, points: int, reason: str) -> list[dict]:
        """Apply a score change. Returns announcements: ``{"type": "game_point", "player": r}``
        or ``{"type": "game_over", "winner": r, "final": {...}, "game": n}``."""
        if points < 0:
            points = -min(-points, self.points[player])  # never below zero
        if points == 0:
            return []
        before = self._game_point()
        self.points[player] += points
        self.history.append(ScoreChange(t, player, points, reason, self.game))
        winner = self._winner()
        if winner is not None:
            return self._end_game(winner)
        after = self._game_point()
        if after and after != before and points > 0:
            return [{"type": "game_point", "player": after}]
        return []

    def make(self, t: float, player: str, three: bool) -> tuple[int, list[dict]]:
        pts = self.value_of_make(three)
        return pts, self.add(t, player, pts, "make")

    def undo(self, t: float) -> str | None:
        """Reverse the most recent not-yet-undone change in the current game.
        (A finished game is final; fix it before the winning basket, or adjust manually.)"""
        for i in range(len(self.history) - 1, -1, -1):
            change = self.history[i]
            if change.game != self.game:
                return None
            if change.reason == "undo" or i in self._undone:
                continue
            self._undone.add(i)
            self.points[change.player] = max(0, self.points[change.player] - change.points)
            self.history.append(ScoreChange(t, change.player, -change.points, "undo", self.game))
            return change.player
        return None

    def _game_point(self) -> str | None:
        """Role that is one make away from winning, if any (key used for 'game point' calls)."""
        short, _ = self.values
        for r in ROLES:
            other = OPPONENT if r == YOU else YOU
            p = self.points[r] + short
            if p >= self.game_to and p - self.points[other] >= self.win_by:
                return r
        return None

    def _end_game(self, winner: str) -> list[dict]:
        final = dict(self.points)
        self.final_scores.append(final)
        self.games_won[winner] += 1
        game = self.game
        self.game += 1
        self.points = {r: 0 for r in ROLES}
        return [{"type": "game_over", "winner": winner, "final": final, "game": game}]

    def to_dict(self) -> dict:
        return {
            "scoring": self.scoring,
            "game_to": self.game_to,
            "win_by": self.win_by,
            "game": self.game,
            "points": dict(self.points),
            "games_won": dict(self.games_won),
            "final_scores": list(self.final_scores),
        }
