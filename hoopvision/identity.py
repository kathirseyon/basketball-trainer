"""Decides which detected person is YOU and which is the OPPONENT.

Detector track IDs are not enough on their own: they swap when players
overlap or leave the frame. Each role therefore keeps

* an appearance signature (HSV colour histogram of the torso — i.e. the shirt),
* a motion model (last position + velocity),
* the last tracker ID it was matched to,

and every frame the roles are matched to detections with the Hungarian
algorithm on a cost that blends all three.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
from scipy.optimize import linear_sum_assignment

from .structures import L_HIP, L_SHOULDER, OPPONENT, R_HIP, R_SHOULDER, ROLES, YOU, Box, Person

HIST_BINS = (16, 8)  # hue, saturation


def torso_box(person: Person) -> Box:
    """Shirt region: shoulders→hips from keypoints if available, else a box heuristic."""
    pts = [person.kp(i, 0.4) for i in (L_SHOULDER, R_SHOULDER, L_HIP, R_HIP)]
    pts = [p for p in pts if p is not None]
    if len(pts) == 4:
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        b = Box(min(xs), min(ys), max(xs), max(ys))
        if b.w > 4 and b.h > 4:
            return b
    bb = person.box
    return Box(bb.x1 + 0.25 * bb.w, bb.y1 + 0.2 * bb.h, bb.x2 - 0.25 * bb.w, bb.y1 + 0.55 * bb.h)


def appearance(frame: np.ndarray, person: Person) -> np.ndarray | None:
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = torso_box(person).clip(w, h).as_int()
    if x2 - x1 < 3 or y2 - y1 < 3:
        return None
    hsv = cv2.cvtColor(frame[y1:y2, x1:x2], cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0, 1], None, list(HIST_BINS), [0, 180, 0, 256])
    cv2.normalize(hist, hist, 1.0, 0.0, cv2.NORM_L1)
    return hist.astype(np.float32)


def hist_distance(a: np.ndarray | None, b: np.ndarray | None) -> float:
    """Bhattacharyya distance in [0, 1]; 0.5 (uninformative) if either is missing."""
    if a is None or b is None:
        return 0.5
    return float(np.clip(cv2.compareHist(a, b, cv2.HISTCMP_BHATTACHARYYA), 0.0, 1.0))


HUE_NAMES = [(10, "red"), (22, "orange"), (35, "yellow"), (85, "green"), (130, "blue"), (165, "purple"), (180, "red")]


def color_name(hist: np.ndarray | None) -> str | None:
    """Rough shirt colour name from a torso hue/saturation histogram."""
    if hist is None:
        return None
    h = np.asarray(hist, np.float32)
    sat_bins = h.shape[1]
    colourful = h[:, sat_bins // 3:]  # ignore washed-out pixels
    if colourful.sum() < 0.35 * max(h.sum(), 1e-6):
        return "white/grey"
    hue_bin = int(np.argmax(colourful.sum(axis=1)))
    hue = (hue_bin + 0.5) * 180 / h.shape[0]
    return next(name for limit, name in HUE_NAMES if hue <= limit)


@dataclass
class RoleTrack:
    role: str
    hist: np.ndarray | None
    pos: tuple[float, float]
    vel: tuple[float, float]
    height: float
    track_id: int | None
    last_t: float
    missing: int = 0

    def predict(self, t: float) -> tuple[float, float]:
        dt = min(t - self.last_t, 1.0)
        return self.pos[0] + self.vel[0] * dt, self.pos[1] + self.vel[1] * dt


class IdentityAssigner:
    def __init__(
        self,
        you_side: str = "left",
        max_people: int = 4,
        appearance_weight: float = 0.55,
        position_weight: float = 0.45,
        track_id_bonus: float = 0.15,
        max_cost: float = 0.8,
        lost_after: int = 45,
        hist_lr: float = 0.05,
        init_frames: int = 3,
    ):
        if you_side not in ("left", "right"):
            raise ValueError("you_side must be 'left' or 'right'")
        self.you_side = you_side
        self.max_people = max_people
        self.wa = appearance_weight
        self.wp = position_weight
        self.id_bonus = track_id_bonus
        self.max_cost = max_cost
        self.lost_after = lost_after
        self.hist_lr = hist_lr
        self.init_frames = init_frames
        self.tracks: dict[str, RoleTrack] = {}
        self.you_point: tuple[float, float] | None = None
        self._init_streak = 0

    @property
    def initialized(self) -> bool:
        return len(self.tracks) == len(ROLES)

    def select_you_at(self, x: float, y: float) -> None:
        """Click-to-identify: the person nearest this point becomes YOU (re-initialises)."""
        self.you_point = (x, y)
        self.tracks.clear()
        self._init_streak = self.init_frames  # don't wait, use the next frame

    def swap(self) -> None:
        if self.initialized:
            a, b = self.tracks[YOU], self.tracks[OPPONENT]
            a.role, b.role = OPPONENT, YOU
            self.tracks = {YOU: b, OPPONENT: a}

    def shirt(self, role: str) -> str | None:
        tr = self.tracks.get(role)
        return color_name(tr.hist) if tr else None

    def reset(self) -> None:
        self.tracks.clear()
        self._init_streak = 0

    def _candidates(self, persons: list[Person]) -> list[Person]:
        # The two players are normally the biggest, most confident people in shot.
        return sorted(persons, key=lambda p: p.box.area * p.conf, reverse=True)[: self.max_people]

    def _new_track(self, role: str, frame: np.ndarray, p: Person, t: float) -> RoleTrack:
        return RoleTrack(role, appearance(frame, p), p.box.center, (0.0, 0.0), p.box.h, p.track_id, t)

    def _initialize(self, frame: np.ndarray, persons: list[Person], t: float) -> None:
        cands = self._candidates(persons)
        if len(cands) < 2:
            self._init_streak = 0
            return
        self._init_streak += 1
        # Wait a few frames so we don't lock onto a spurious detection.
        if self._init_streak < self.init_frames:
            return
        two = cands[:2]
        if self.you_point is not None:
            px, py = self.you_point
            inside = [p for p in cands if p.box.contains(px, py)]
            pool = inside or cands
            you = min(pool, key=lambda p: (p.box.cx - px) ** 2 + (p.box.cy - py) ** 2)
            opp = next(p for p in cands if p is not you)
            self.you_point = None
        else:
            two.sort(key=lambda p: p.box.cx)
            you, opp = (two[0], two[1]) if self.you_side == "left" else (two[1], two[0])
        self.tracks = {YOU: self._new_track(YOU, frame, you, t), OPPONENT: self._new_track(OPPONENT, frame, opp, t)}

    def update(self, frame: np.ndarray, persons: list[Person], t: float) -> dict[str, Person | None]:
        out: dict[str, Person | None] = {r: None for r in ROLES}
        if not self.initialized:
            self._initialize(frame, persons, t)
            if not self.initialized:
                return out
            # Fall through and match on this same frame.

        cands = self._candidates(persons)
        if not cands:
            for tr in self.tracks.values():
                tr.missing += 1
            return out

        hists = [appearance(frame, p) for p in cands]
        roles = list(ROLES)
        cost = np.zeros((len(roles), len(cands)))
        for i, r in enumerate(roles):
            tr = self.tracks[r]
            px, py = tr.predict(t)
            lost = tr.missing > self.lost_after
            for j, p in enumerate(cands):
                app = hist_distance(tr.hist, hists[j])
                dist = np.hypot(p.box.cx - px, p.box.cy - py) / max(tr.height * 1.5, 1.0)
                pos = min(dist, 1.0)
                c = app if lost else self.wa * app + self.wp * pos
                if tr.track_id is not None and p.track_id == tr.track_id:
                    c -= self.id_bonus
                cost[i, j] = c

        rows, cols = linear_sum_assignment(cost)
        assigned: dict[str, int] = {}
        for i, j in zip(rows, cols):
            if cost[i, j] <= self.max_cost:
                assigned[roles[i]] = j

        overlap = False
        if len(assigned) == 2:
            a, b = (cands[assigned[r]] for r in roles)
            overlap = a.box.iou(b.box) > 0.05

        for r in roles:
            tr = self.tracks[r]
            if r not in assigned:
                tr.missing += 1
                continue
            j = assigned[r]
            p = cands[j]
            dt = max(t - tr.last_t, 1e-3)
            nx, ny = p.box.center
            vx, vy = (nx - tr.pos[0]) / dt, (ny - tr.pos[1]) / dt
            if tr.missing > 0:  # velocity across a gap is unreliable
                vx, vy = 0.0, 0.0
            tr.vel = (0.6 * tr.vel[0] + 0.4 * vx, 0.6 * tr.vel[1] + 0.4 * vy)
            tr.pos, tr.height, tr.last_t, tr.missing = (nx, ny), p.box.h, t, 0
            tr.track_id = p.track_id
            # Only learn appearance when the match is unambiguous; overlapping
            # players would otherwise contaminate each other's signature.
            if hists[j] is not None and not overlap:
                tr.hist = hists[j] if tr.hist is None else (1 - self.hist_lr) * tr.hist + self.hist_lr * hists[j]
            out[r] = p
        return out
