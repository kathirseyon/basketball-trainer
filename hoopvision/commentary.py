"""Live play-by-play with a session clock.

The commentator narrates three phases:

1. **Calibrating** - finding the hoop, locking onto both players (and their
   shirt colours) and spotting the ball.
2. **Scouting** - recapping every possession while it collects enough of the
   opponent's possessions to trust their tendencies.
3. **Game plan ready** - tendencies are solid; new patterns are still called
   out as they appear and the chat coach has data to work with.

It is deterministic and instant, so it works with no network. An optional
LLM analyst (see `chat.AIAnalyst`) can add colour commentary on top.
"""

from __future__ import annotations

import threading
from dataclasses import asdict, dataclass

from .analyzer import Event, GameAnalyzer
from .coach import Tip
from .patterns import describe_token
from .structures import OPPONENT, ROLES, YOU

PHASE_LABELS = {"calibrating": "Calibrating", "scouting": "Scouting", "ready": "Game plan ready"}


def clock(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


@dataclass
class Line:
    id: int
    t: float
    clock: str
    kind: str  # "system" | "play" | "insight" | "ai"
    text: str
    player: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class Commentator:
    def __init__(self, names: dict[str, str], scout_target: int = 5, hoop_hint_after: float = 3.0,
                 ball_hint_after: float = 10.0):
        self.names = names
        self.scout_target = scout_target
        self.hoop_hint_after = hoop_hint_after
        self.ball_hint_after = ball_hint_after
        self.lines: list[Line] = []
        self.phase = "calibrating"
        self.steps = {"hoop": False, "players": False, "ball": False}
        self.start_t: float | None = None
        self.t = 0.0
        self._hinted: set[str] = set()
        self._seen_tips: set[str] = set()
        self._blow_by: dict[str, bool] = {r: False for r in ROLES}
        self._lock = threading.Lock()

    # ----------------------------------------------------------------- output
    def say(self, kind: str, text: str, player: str | None = None) -> Line:
        with self._lock:
            line = Line(len(self.lines) + 1, self.t, clock(self.elapsed), kind, text, player)
            self.lines.append(line)
        return line

    def since(self, last_id: int) -> list[dict]:
        with self._lock:
            return [l.to_dict() for l in self.lines[last_id:]]

    @property
    def elapsed(self) -> float:
        return 0.0 if self.start_t is None else self.t - self.start_t

    def status(self, analyzer: GameAnalyzer | None = None) -> dict:
        if self.phase == "calibrating":
            done = sum(self.steps.values())
            progress = done / len(self.steps)
            todo = [k for k, v in self.steps.items() if not v]
            detail = "Looking for: " + ", ".join(todo) if todo else "Done"
        else:
            n = self._opp_possessions(analyzer)
            progress = min(1.0, n / self.scout_target)
            detail = (f"{self.names[OPPONENT]} possessions watched: {n}/{self.scout_target}"
                      if self.phase == "scouting" else f"{n} {self.names[OPPONENT]} possessions analysed")
        return {"phase": self.phase, "label": PHASE_LABELS[self.phase], "clock": clock(self.elapsed),
                "progress": round(progress, 2), "detail": detail, "steps": dict(self.steps)}

    @staticmethod
    def _opp_possessions(analyzer: GameAnalyzer | None) -> int:
        if analyzer is None:
            return 0
        st = analyzer.stats[OPPONENT]
        current = analyzer.possession is not None and analyzer.possession.player == OPPONENT
        return len(st.possessions) + int(current)

    # ----------------------------------------------------------------- update
    def update(
        self,
        t: float,
        *,
        hoop_ready: bool,
        players: dict,
        shirts: dict[str, str | None],
        ball_seen: bool,
        events: list[Event],
        analyzer: GameAnalyzer,
        tips: list[Tip] | None = None,
        can_detect_hoop: bool = False,
    ) -> None:
        if self.start_t is None:
            self.start_t = t
            self.t = t
            self.say("system", "Calibrating... looking for the hoop, both players and the ball.")
        self.t = t
        self._calibrate(hoop_ready, players, shirts, ball_seen, can_detect_hoop)
        if self.phase == "calibrating":
            return
        for e in events:
            self._narrate(e, analyzer)
        if tips:
            self._insights(tips)
        if self.phase == "scouting" and self._opp_possessions(analyzer) >= self.scout_target:
            self.phase = "ready"
            self.say("system", f"Game plan ready after {clock(self.elapsed)}. I've got a read on "
                               f"{self.names[OPPONENT]} - ask me anything in the chat, like "
                               f"\"how do I guard {self.names[OPPONENT]}?\"")

    def _calibrate(self, hoop_ready, players, shirts, ball_seen, can_detect_hoop) -> None:
        el = self.elapsed
        if hoop_ready and not self.steps["hoop"]:
            self.steps["hoop"] = True
            self.say("system", "Hoop locked in.")
        elif not hoop_ready and el >= self.hoop_hint_after and "hoop" not in self._hinted and not can_detect_hoop:
            self._hinted.add("hoop")
            self.say("system", "I can't find the hoop on my own - drag a box around the rim so I can "
                               "track makes and drive directions.")
        if not self.steps["players"] and all(players.get(r) is not None for r in ROLES):
            self.steps["players"] = True
            left = min(ROLES, key=lambda r: players[r].box.cx)
            parts = []
            for r in ROLES:
                desc = f"{shirts[r]} shirt, " if shirts.get(r) else ""
                parts.append(f"{self.names[r]} ({desc}{'left' if r == left else 'right'})")
            self.say("system", f"Locked on: {parts[0]} and {parts[1]}. Wrong way round? Click yourself or hit swap.")
        if ball_seen and not self.steps["ball"]:
            self.steps["ball"] = True
            self.say("system", "Ball spotted.")
        elif not ball_seen and el >= self.ball_hint_after and "ball" not in self._hinted:
            self._hinted.add("ball")
            self.say("system", "Still no ball - keep it in frame and in good light. I can track movement "
                               "without it, but not dribbles or shots.")
        ready = self.steps["hoop"] and self.steps["players"] and (self.steps["ball"] or el >= self.ball_hint_after)
        if self.phase == "calibrating" and ready:
            self.phase = "scouting"
            self.say("system", f"Calibration done in {clock(el)}. Now watching how you both play - I need about "
                               f"{self.scout_target} of {self.names[OPPONENT]}'s possessions to call out tendencies.")

    def _narrate(self, e: Event, analyzer: GameAnalyzer) -> None:
        name = self.names.get(e.player, e.player)
        if e.kind == "blow_by":
            self._blow_by[e.player] = True
        elif e.kind == "possession":
            self._blow_by[e.player] = False
        elif e.kind == "shot_result":
            poss = analyzer.stats[e.player].possessions
            moves = [describe_token(t) for t in (poss[-1].tokens if poss else [])
                     if not t.startswith("start:") and not t.startswith("shot:")]
            if self._blow_by[e.player]:
                moves.append(f"gets by {self.names[_other(e.player)]}")
            result = {"make": "and it's GOOD.", "miss": "no good.", "unknown": "couldn't see if it dropped."}
            build = (", ".join(moves) + ", then ") if moves else ""
            score = f" {e.detail['score_text']}" if e.detail.get("score_text") else ""
            self.say("play", f"{name} {build}{e.detail['type']} from the {e.detail['zone']} - "
                             f"{result.get(e.detail['result'], '')}{score}", e.player)
        elif e.kind == "turnover":
            self.say("play", f"{name} loses it - {self.names[_other(e.player)]} comes away with the ball.", e.player)

    def _insights(self, tips: list[Tip]) -> None:
        for tip in tips:
            if tip.side == "info" or tip.title in self._seen_tips:
                continue
            self._seen_tips.add(tip.title)
            self.say("insight", f"{tip.title}: {tip.text} ({tip.evidence})")


def _other(role: str) -> str:
    return OPPONENT if role == YOU else YOU
