"""Turns per-frame tracking into basketball events and per-player stats.

Event vocabulary
----------------
possession   a player gains control of the ball
dribble      ball bounce (lowest point below the hips) + which hand
crossover    consecutive dribbles switch hands
drive        fast approach to the hoop; direction left/right/straight relative
             to the straight line to the rim, and whether the attacker got past
shot         ball rises above the shooter's head; typed as layup / pull-up /
             stepback / spot-up / jumper / close shot
shot_result  make or miss, from the ball passing through the rim box
blow_by      during a drive the attacker gets closer to the rim than the defender
turnover     the other player takes the ball without a shot

Each possession is also recorded as a token sequence such as
``["start:right", "dribble:R", "crossover>L", "drive:left", "shot:layup"]``,
which `patterns.py` mines for repeated plays.
"""

from __future__ import annotations

import math
from collections import Counter, deque
from dataclasses import dataclass, field

from .court import CourtPos, PLAYER_HEIGHT_M, court_position, side_of, zone_of
from .structures import OPPONENT, ROLES, YOU, Box, Person


def other(role: str) -> str:
    return OPPONENT if role == YOU else YOU


@dataclass
class AnalyzerConfig:
    possession_radius: float = 0.45      # body heights from ball to hand
    possession_confirm_frames: int = 3
    possession_timeout: float = 1.5      # s without control before the ball is loose
    drive_window: float = 0.6            # s
    drive_min_approach: float = 0.6      # body heights closer to the hoop within the window
    drive_min_speed: float = 1.2         # body heights / s toward the hoop
    drive_cooldown: float = 1.2
    drive_straight_sin: float = 0.35     # |sin(angle off the rim line)| below this = straight
    drive_max_duration: float = 1.5      # s to watch a drive for a blow-by
    blow_by_margin: float = 0.15         # body heights closer to the rim than the defender
    dribble_cooldown: float = 0.22
    crossover_window: float = 1.2
    shot_min_rise_speed: float = 0.7     # body heights / s upward
    shot_timeout: float = 3.0
    stepback_min: float = 0.3            # body heights moved away from hoop before the shot
    position_smoothing: float = 0.5
    mirror: bool = False


@dataclass
class Event:
    t: float
    frame: int
    player: str
    kind: str
    detail: dict = field(default_factory=dict)

    def text(self) -> str:
        d, p = self.detail, self.player
        if self.kind == "possession":
            return f"{p} has the ball"
        if self.kind == "dribble":
            return f"{p} dribble ({d.get('hand', '?')})"
        if self.kind == "crossover":
            return f"{p} crossover to {'left' if d['to'] == 'L' else 'right'} hand"
        if self.kind == "drive":
            return f"{p} drives {d['direction']}"
        if self.kind == "blow_by":
            return f"{p} blew by the defender!"
        if self.kind == "shot":
            return f"{p} {d['type']} from {d['zone']}"
        if self.kind == "shot_result":
            return f"{p} {'MAKES IT' if d['result'] == 'make' else d['result'].upper()}"
        if self.kind == "turnover":
            return f"{p} lost the ball"
        return f"{p} {self.kind}"


@dataclass
class Shot:
    player: str
    t: float
    frame: int
    zone: str
    type: str
    pos: CourtPos
    image_xy: tuple[float, float]
    result: str = "pending"
    saw_above: bool = False


@dataclass
class Possession:
    player: str
    start_t: float
    start_zone: str
    tokens: list[str] = field(default_factory=list)
    dribbles: int = 0
    last_drive_t: float = -math.inf
    end_t: float | None = None
    end_reason: str | None = None

    def add(self, token: str) -> None:
        if not self.tokens or self.tokens[-1] != token:
            self.tokens.append(token)


@dataclass
class _Sample:
    t: float
    pos: CourtPos
    person: Person


@dataclass
class PlayerStats:
    frames_seen: int = 0
    distance: float = 0.0                       # body heights
    speed_samples: list[tuple[float, float]] = field(default_factory=list)
    zone_frames: Counter = field(default_factory=Counter)
    foot_points: list[tuple[float, float]] = field(default_factory=list)
    dribble_hands: Counter = field(default_factory=Counter)
    crossovers: int = 0
    drives: list[dict] = field(default_factory=list)
    shots: list[Shot] = field(default_factory=list)
    cushion: list[float] = field(default_factory=list)  # distance to the ball handler while defending
    possessions: list[Possession] = field(default_factory=list)
    turnovers: int = 0


class GameAnalyzer:
    def __init__(self, config: AnalyzerConfig | None = None):
        self.cfg = config or AnalyzerConfig()
        self.events: list[Event] = []
        self.stats: dict[str, PlayerStats] = {r: PlayerStats() for r in ROLES}
        self.history: dict[str, deque[_Sample]] = {r: deque(maxlen=120) for r in ROLES}
        self.ball_hist: deque[tuple[float, float, float]] = deque(maxlen=60)
        self.possession: Possession | None = None
        self.pending_shot: Shot | None = None
        self.hoop: Box | None = None
        self.t = 0.0
        self.start_t: float | None = None
        self.frame = 0
        self.frame_w = 1
        self._last_control_t = -math.inf
        self._challenger: str | None = None
        self._challenge_count = 0
        self._last_dribble: tuple[float, str | None] | None = None
        self._active_drive: tuple[str, dict] | None = None
        self._new: list[Event] = []

    # ------------------------------------------------------------------ utils
    def _emit(self, player: str, kind: str, **detail) -> Event:
        ev = Event(self.t, self.frame, player, kind, detail)
        self.events.append(ev)
        self._new.append(ev)
        return ev

    def _sample_ago(self, role: str, seconds: float) -> _Sample | None:
        hist = self.history[role]
        target = self.t - seconds
        best = None
        for s in reversed(hist):
            if s.t <= target:
                return s
            best = s
        # Not enough history yet: only use the oldest sample if it covers most of the window.
        if best is not None and self.t - best.t >= 0.7 * seconds:
            return best
        return None

    def _ball_velocity(self, window: float = 0.2) -> tuple[float, float] | None:
        if len(self.ball_hist) < 2:
            return None
        t1, x1, y1 = self.ball_hist[-1]
        if t1 < self.t - 1e-6:
            return None  # ball not seen this frame
        for t0, x0, y0 in reversed(self.ball_hist):
            if t1 - t0 >= window:
                break
        if t1 - t0 <= 1e-6 or t1 - t0 > 3 * window:
            return None
        return (x1 - x0) / (t1 - t0), (y1 - y0) / (t1 - t0)

    def current_pos(self, role: str) -> CourtPos | None:
        h = self.history[role]
        return h[-1].pos if h and h[-1].t == self.t else None

    # ------------------------------------------------------------------ main
    def update(
        self,
        frame_idx: int,
        t: float,
        players: dict[str, Person | None],
        ball: Box | None,
        hoop: Box | None,
        frame_w: int = 1920,
    ) -> list[Event]:
        self._new = []
        self.frame, self.t, self.hoop, self.frame_w = frame_idx, t, hoop, frame_w
        if self.start_t is None:
            self.start_t = t

        for role, p in players.items():
            if p is not None:
                self._track_player(role, p)

        if ball is not None:
            self.ball_hist.append((t, ball.cx, ball.cy))

        self._update_shot(ball, players)
        self._update_possession(players, ball)

        holder = self.possession.player if self.possession else None
        if holder is not None and players.get(holder) is not None:
            hp = players[holder]
            self._detect_dribble(holder, hp, ball)
            self._follow_drive(holder)
            self._detect_drive(holder)
            if self.possession is not None:
                self._detect_shot(holder, hp, ball)
            defender = other(holder)
            dpos, hpos = self.current_pos(defender), self.current_pos(holder)
            if dpos is not None and hpos is not None:
                self.stats[defender].cushion.append((dpos - hpos).distance)
        return self._new

    def _track_player(self, role: str, p: Person) -> None:
        raw = court_position(p.box, self.hoop, self.frame_w, self.cfg.mirror)
        hist = self.history[role]
        st = self.stats[role]
        if hist and self.t - hist[-1].t < 0.5:
            a = self.cfg.position_smoothing
            prev = hist[-1].pos
            pos = CourtPos(a * prev.lateral + (1 - a) * raw.lateral, a * prev.depth + (1 - a) * raw.depth)
            step = (pos - prev).distance
            dt = self.t - hist[-1].t
            if dt > 0 and step / dt < 6.0:  # ignore teleports from identity swaps
                st.distance += step
        else:
            pos = raw
        hist.append(_Sample(self.t, pos, p))
        st.frames_seen += 1
        st.zone_frames[zone_of(pos)] += 1
        if st.frames_seen % 3 == 0:
            st.foot_points.append(p.box.foot)
        old = self._sample_ago(role, 0.5)
        if old is not None and self.t > old.t:
            st.speed_samples.append((self.t, (pos - old.pos).distance / (self.t - old.t)))

    # ------------------------------------------------------------ possession
    def _control_distance(self, p: Person, ball: Box) -> float:
        scale = max(p.box.h, 1.0)
        bx, by = ball.center
        d = math.inf
        for wx, wy in p.wrists().values():
            d = min(d, math.hypot(bx - wx, by - wy) / scale)
        if p.box.expand(0.3, 0.05).contains(bx, by):
            # Ball inside the player's silhouette (e.g. low dribble) counts as close.
            d = min(d, 0.3 if p.keypoints is not None else 0.0)
        return d

    def _start_possession(self, role: str) -> None:
        pos = self.current_pos(role) or (self.history[role][-1].pos if self.history[role] else CourtPos(0, 0))
        self.possession = Possession(role, self.t, zone_of(pos))
        self.possession.add(f"start:{side_of(pos)}")
        self._last_control_t = self.t
        self._last_dribble = None
        self._emit(role, "possession", zone=self.possession.start_zone)

    def _end_possession(self, reason: str) -> None:
        pos = self.possession
        if pos is None:
            return
        self._active_drive = None
        pos.end_t, pos.end_reason = self.t, reason
        if reason == "turnover":
            pos.add("turnover")
            self.stats[pos.player].turnovers += 1
            self._emit(pos.player, "turnover")
        self.stats[pos.player].possessions.append(pos)
        self.possession = None

    def _update_possession(self, players: dict[str, Person | None], ball: Box | None) -> None:
        cfg = self.cfg
        holder = self.possession.player if self.possession else None
        if self.pending_shot is not None:
            return  # ball is in the air
        if ball is None:
            if holder and self.t - self._last_control_t > 2 * cfg.possession_timeout:
                self._end_possession("lost track")
            return
        dists = {r: self._control_distance(p, ball) for r, p in players.items() if p is not None}
        if not dists:
            return
        if holder and dists.get(holder, math.inf) <= cfg.possession_radius:
            self._last_control_t = self.t
            self._challenger, self._challenge_count = None, 0
            return
        best = min(dists, key=dists.get)
        if dists[best] <= cfg.possession_radius and best != holder:
            if self._challenger == best:
                self._challenge_count += 1
            else:
                self._challenger, self._challenge_count = best, 1
            if self._challenge_count >= cfg.possession_confirm_frames:
                if holder:
                    self._end_possession("turnover")
                self._challenger, self._challenge_count = None, 0
                self._start_possession(best)
        elif holder and self.t - self._last_control_t > cfg.possession_timeout:
            self._end_possession("loose ball")

    # ----------------------------------------------------------- dribbling
    def _detect_dribble(self, role: str, p: Person, ball: Box | None) -> None:
        if ball is None or len(self.ball_hist) < 3:
            return
        (t0, _, y0), (t1, x1, y1), (t2, _, y2) = list(self.ball_hist)[-3:]
        if t2 != self.t or t2 - t0 > 0.3:
            return
        scale = max(p.box.h, 1.0)
        is_bottom = y1 > y0 and y1 >= y2 and (y1 - y0) > 0.02 * scale
        if not is_bottom or y1 < p.hip_y():
            return
        if self._last_dribble and t1 - self._last_dribble[0] < self.cfg.dribble_cooldown:
            return
        wrists = p.wrists()
        hand = min(wrists, key=lambda k: abs(wrists[k][0] - x1)) if wrists else None
        prev = self._last_dribble
        self._last_dribble = (t1, hand)
        poss = self.possession
        poss.dribbles += 1
        if hand:
            self.stats[role].dribble_hands[hand] += 1
        self._emit(role, "dribble", hand=hand or "?")
        if poss.dribbles == 1 and hand:
            poss.add(f"dribble:{hand}")
        if prev and hand and prev[1] and prev[1] != hand and t1 - prev[0] <= self.cfg.crossover_window:
            self.stats[role].crossovers += 1
            poss.add(f"crossover>{hand}")
            self._emit(role, "crossover", to=hand)

    # -------------------------------------------------------------- driving
    def _detect_drive(self, role: str) -> None:
        if self.hoop is None or self.possession is None:
            return
        cfg = self.cfg
        if self.t - self.possession.last_drive_t < cfg.drive_cooldown:
            return
        now = self.current_pos(role)
        old = self._sample_ago(role, cfg.drive_window)
        if now is None or old is None or self.t <= old.t:
            return
        dt = self.t - old.t
        approach = old.pos.distance - now.distance
        if approach < cfg.drive_min_approach or approach / dt < cfg.drive_min_speed:
            return
        # Which way does the move veer off the straight line to the rim, from the attacker's view?
        d0 = old.pos.distance
        if d0 < 1e-6:
            return
        ux, uy = -old.pos.lateral / d0, -old.pos.depth / d0
        mx, my = now.lateral - old.pos.lateral, now.depth - old.pos.depth
        m = math.hypot(mx, my)
        sin = (ux * my - uy * mx) / m if m > 0 else 0.0
        if abs(sin) < cfg.drive_straight_sin:
            direction = "straight"
        else:
            direction = "right" if sin > 0 else "left"
        self.possession.last_drive_t = self.t
        self.possession.add(f"drive:{direction}")
        info = {"direction": direction, "got_past": False, "from": zone_of(old.pos), "t": self.t}
        self.stats[role].drives.append(info)
        self._active_drive = (role, info)
        self._emit(role, "drive", direction=direction)
        self._follow_drive(role)

    def _follow_drive(self, role: str) -> None:
        """Watch an ongoing drive and record whether the attacker beats the defender."""
        if self._active_drive is None:
            return
        drive_role, info = self._active_drive
        if drive_role != role or self.t - info["t"] > self.cfg.drive_max_duration:
            self._active_drive = None
            return
        if info["got_past"]:
            return
        now, dpos = self.current_pos(role), self.current_pos(other(role))
        if now is not None and dpos is not None and dpos.distance > now.distance + self.cfg.blow_by_margin:
            info["got_past"] = True
            self._emit(role, "blow_by", direction=info["direction"])

    # ------------------------------------------------------------- shooting
    def _classify_shot(self, role: str, pos: CourtPos) -> str:
        poss = self.possession
        recent_drive = poss is not None and self.t - poss.last_drive_t < 1.5
        if zone_of(pos) == "paint":
            return "layup" if recent_drive else "close shot"
        old = self._sample_ago(role, 0.6)
        if old is not None and pos.distance - old.pos.distance > self.cfg.stepback_min:
            return "stepback"
        if recent_drive:
            return "pull-up"
        if poss is not None and poss.dribbles <= 1:
            return "spot-up"
        return "jumper"

    def _detect_shot(self, role: str, p: Person, ball: Box | None) -> None:
        if ball is None or self.pending_shot is not None:
            return
        v = self._ball_velocity()
        if v is None:
            return
        scale = max(p.box.h, 1.0)
        above_head = ball.cy < p.head_y()
        near = abs(ball.cx - p.box.cx) < 0.8 * scale
        rising = -v[1] / scale > self.cfg.shot_min_rise_speed
        if not (above_head and near and rising):
            return
        pos = self.current_pos(role) or CourtPos(0, 0)
        zone = zone_of(pos)
        shot_type = self._classify_shot(role, pos)
        shot = Shot(role, self.t, self.frame, zone, shot_type, pos, p.box.foot)
        self.pending_shot = shot
        self.stats[role].shots.append(shot)
        self.possession.add(f"shot:{shot_type}")
        self._emit(role, "shot", type=shot_type, zone=zone)
        self._end_possession("shot")

    def _resolve_shot(self, result: str) -> None:
        s = self.pending_shot
        s.result = result
        self.pending_shot = None
        self._emit(s.player, "shot_result", result=result, type=s.type, zone=s.zone)

    def _update_shot(self, ball: Box | None, players: dict[str, Person | None]) -> None:
        s = self.pending_shot
        if s is None or self.t == s.t:
            return
        hoop = self.hoop
        if self.t - s.t > self.cfg.shot_timeout:
            self._resolve_shot("miss" if hoop is not None and s.saw_above else "unknown")
            return
        if ball is None:
            return
        bx, by = ball.center
        if hoop is None:
            # Without a hoop we can only tell the ball came back down to someone.
            if self.t - s.t > 0.6 and any(
                p is not None and self._control_distance(p, ball) < self.cfg.possession_radius for p in players.values()
            ):
                self._resolve_shot("unknown")
            return
        if by < hoop.y1 + 0.3 * hoop.h and abs(bx - hoop.cx) < 2.0 * hoop.w:
            s.saw_above = True
        if s.saw_above and by > hoop.cy + 0.2 * hoop.h:
            self._resolve_shot("make" if hoop.x1 <= bx <= hoop.x2 else "miss")
            return
        # Airball / block: ball back in someone's hands without reaching the rim.
        if not s.saw_above and self.t - s.t > 0.6 and any(
            p is not None and self._control_distance(p, ball) < self.cfg.possession_radius for p in players.values()
        ):
            self._resolve_shot("miss")

    # -------------------------------------------------------------- summary
    def scoreboard(self) -> dict:
        """Cheap subset of `summary()` for drawing every frame."""
        return {"players": {r: {
            "shots": {"makes": sum(s.result == "make" for s in st.shots), "attempts": len(st.shots)},
            "drives": {"total": len(st.drives)},
            "crossovers": st.crossovers,
        } for r, st in self.stats.items()}}

    def finish(self) -> None:
        if self.pending_shot is not None:
            self._resolve_shot("unknown")
        if self.possession is not None:
            self._end_possession("end of session")

    def sequences(self, role: str) -> list[list[str]]:
        seqs = [p.tokens for p in self.stats[role].possessions]
        if self.possession is not None and self.possession.player == role:
            seqs.append(self.possession.tokens)
        return seqs

    def summary(self) -> dict:
        duration = (self.t - self.start_t) if self.start_t is not None else 0.0
        out: dict = {"duration_s": round(duration, 1), "players": {}}
        for role in ROLES:
            st = self.stats[role]
            shots = [s for s in st.shots if s.result != "pending"]
            by_zone: dict[str, list[int]] = {}
            by_type: dict[str, list[int]] = {}
            for s in st.shots:
                for key, table in ((s.zone, by_zone), (s.type, by_type)):
                    row = table.setdefault(key, [0, 0])
                    row[1] += 1
                    row[0] += s.result == "make"
            makes = sum(s.result == "make" for s in shots)
            drives = Counter(d["direction"] for d in st.drives)
            drives_won = Counter(d["direction"] for d in st.drives if d["got_past"])
            speeds = [v for _, v in st.speed_samples]
            early = late = None
            if duration >= 60 and len(st.speed_samples) >= 30:
                third = self.start_t + duration / 3
                last_third = self.start_t + 2 * duration / 3
                e = [v for t, v in st.speed_samples if t <= third]
                l = [v for t, v in st.speed_samples if t >= last_third]
                if e and l:
                    early, late = sum(e) / len(e), sum(l) / len(l)
            total_zone = sum(st.zone_frames.values()) or 1
            out["players"][role] = {
                "frames_seen": st.frames_seen,
                "possessions": len(st.possessions) + (self.possession is not None and self.possession.player == role),
                "turnovers": st.turnovers,
                "shots": {
                    "attempts": len(st.shots),
                    "makes": makes,
                    "by_zone": by_zone,
                    "by_type": by_type,
                },
                "drives": {
                    "total": len(st.drives),
                    "by_direction": dict(drives),
                    "got_past_by_direction": dict(drives_won),
                },
                "dribble_hands": dict(st.dribble_hands),
                "crossovers": st.crossovers,
                "avg_cushion_when_defending": (sum(st.cushion) / len(st.cushion)) if st.cushion else None,
                "distance_m": round(st.distance * PLAYER_HEIGHT_M, 1),
                "avg_speed_mps": round(sum(speeds) / len(speeds) * PLAYER_HEIGHT_M, 2) if speeds else None,
                "early_speed_mps": round(early * PLAYER_HEIGHT_M, 2) if early is not None else None,
                "late_speed_mps": round(late * PLAYER_HEIGHT_M, 2) if late is not None else None,
                "zone_share": {z: round(n / total_zone, 3) for z, n in st.zone_frames.most_common()},
                "sequences": self.sequences(role),
            }
        return out
