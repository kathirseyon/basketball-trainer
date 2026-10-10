"""Tiny synthetic 1v1 scene generator for tests (no camera or model needed)."""

from __future__ import annotations

import numpy as np

from hoopvision.court import DEPTH_FORESHORTENING, HOOP_HEIGHT_M, PLAYER_HEIGHT_M
from hoopvision.structures import Box, Person

FPS = 30.0
W, H_IMG = 1280, 720
HOOP = Box(610, 120, 670, 160)
PH = 150  # player height in pixels


def foot_at(lateral: float, depth: float, h: float = PH) -> tuple[float, float]:
    floor_y = HOOP.cy + (HOOP_HEIGHT_M / PLAYER_HEIGHT_M) * h
    return HOOP.cx + lateral * h, floor_y + depth / DEPTH_FORESHORTENING * h


def person(lateral: float, depth: float, track_id: int | None = None, h: float = PH,
           wrist_l=None, wrist_r=None) -> Person:
    fx, fy = foot_at(lateral, depth, h)
    kps = np.zeros((17, 3), np.float32)

    def put(i, x, y):
        kps[i] = (x, y, 0.9)

    put(0, fx, fy - 0.93 * h)                       # nose
    put(5, fx - 0.12 * h, fy - 0.8 * h)              # shoulders (player faces the hoop,
    put(6, fx + 0.12 * h, fy - 0.8 * h)              # so their left is screen-left)
    put(9, *(wrist_l or (fx - 0.2 * h, fy - 0.5 * h)))
    put(10, *(wrist_r or (fx + 0.2 * h, fy - 0.5 * h)))
    put(11, fx - 0.1 * h, fy - 0.5 * h)              # hips
    put(12, fx + 0.1 * h, fy - 0.5 * h)
    put(15, fx - 0.08 * h, fy)
    put(16, fx + 0.08 * h, fy)
    box = Box(fx - 0.22 * h, fy - h, fx + 0.22 * h, fy)
    return Person(box, 0.9, kps, track_id)


def ball_at(x: float, y: float, r: float = 9) -> Box:
    return Box(x - r, y - r, x + r, y + r)


def right_hand(p: Person) -> tuple[float, float]:
    return p.kp(10)


def lerp(a, b, u):
    return a + (b - a) * u


# --------------------------------------------------------------------------
# Scripted plays. Each returns a list of frames: (you, opponent, ball).
# Positions are (lateral, depth) in body heights from the attacker's view.

def _ball_flight(start, peak, end, n):
    """Quadratic Bezier from start through `peak` (control point) to end."""
    pts = []
    for i in range(1, n + 1):
        u = i / n
        x = (1 - u) ** 2 * start[0] + 2 * (1 - u) * u * peak[0] + u ** 2 * end[0]
        y = (1 - u) ** 2 * start[1] + 2 * (1 - u) * u * peak[1] + u ** 2 * end[1]
        pts.append((x, y))
    return pts


def shot_frames(shooter_pos, defender_pos, shooter_is_you: bool, make: bool, ids=(1, 2)):
    """Ball goes from the shooter's hand over their head, up over the rim, then down."""
    frames = []
    s = person(*shooter_pos, track_id=ids[0] if shooter_is_you else ids[1])
    d = person(*defender_pos, track_id=ids[1] if shooter_is_you else ids[0])
    hx, hy = right_hand(s)
    release = (s.box.cx, s.box.y1 - 0.3 * PH)
    # Rise from hand to above the head quickly.
    for i in range(1, 7):
        frames.append((s, d, (lerp(hx, release[0], i / 6), lerp(hy, release[1], i / 6))))
    end_x = HOOP.cx if make else HOOP.x2 + 25
    above = (end_x, HOOP.y1 - 40)
    for p in _ball_flight(release, (lerp(release[0], above[0], 0.5), HOOP.y1 - 220), above, 20):
        frames.append((s, d, p))
    for i in range(1, 9):
        frames.append((s, d, (end_x, HOOP.y1 - 40 + i * 15)))
    out = []
    for a, b, ball in frames:
        you, opp = (a, b) if shooter_is_you else (b, a)
        out.append((you, opp, ball_at(*ball)))
    return out


def hold_frames(holder_pos, other_pos, holder_is_you: bool, n=8, ids=(1, 2)):
    out = []
    for _ in range(n):
        h = person(*holder_pos, track_id=ids[0] if holder_is_you else ids[1])
        o = person(*other_pos, track_id=ids[1] if holder_is_you else ids[0])
        ball = ball_at(*right_hand(h))
        out.append((h, o, ball) if holder_is_you else (o, h, ball))
    return out


def move_frames(holder_from, holder_to, other_pos, holder_is_you: bool, n: int, ids=(1, 2)):
    out = []
    for i in range(1, n + 1):
        u = i / n
        pos = (lerp(holder_from[0], holder_to[0], u), lerp(holder_from[1], holder_to[1], u))
        h = person(*pos, track_id=ids[0] if holder_is_you else ids[1])
        o = person(*other_pos, track_id=ids[1] if holder_is_you else ids[0])
        ball = ball_at(*right_hand(h))
        out.append((h, o, ball) if holder_is_you else (o, h, ball))
    return out


def drive_and_layup(holder_is_you: bool = False, direction: str = "right", make: bool = True):
    side = 1.0 if direction == "right" else -1.0
    start, end, defender = (0.0, 3.0), (side * 1.0, 0.8), (0.0, 2.2)
    frames = hold_frames(start, defender, holder_is_you, n=10)
    frames += move_frames(start, end, defender, holder_is_you, n=24)
    frames += shot_frames(end, defender, holder_is_you, make)
    return frames


def dribble_frames(holder_pos, other_pos, hands: list[str], holder_is_you: bool = False, ids=(1, 2)):
    """Ball bounces once per entry in `hands` ("L"/"R")."""
    out = hold_frames(holder_pos, other_pos, holder_is_you, n=4, ids=ids)
    h = person(*holder_pos, track_id=ids[0] if holder_is_you else ids[1])
    o = person(*other_pos, track_id=ids[1] if holder_is_you else ids[0])
    for hand in hands:
        wx, wy = h.kp(9 if hand == "L" else 10)
        floor = h.box.y2 - 8
        for i in list(range(1, 7)) + list(range(5, -1, -1)):
            ball = ball_at(wx, lerp(wy, floor, i / 6))
            out.append((h, o, ball) if holder_is_you else (o, h, ball))
    return out


SHIRTS = {"YOU": (40, 40, 220), "OPPONENT": (220, 120, 30)}  # BGR: red vs blue shirts


_BG: dict[int, np.ndarray] = {}


def _background(seed: int) -> np.ndarray:
    if seed not in _BG:
        rng = np.random.default_rng(seed)
        _BG[seed] = (110 + rng.integers(-8, 8, (H_IMG, W, 3))).astype(np.uint8)
    return _BG[seed]


def render(you: Person | None, opp: Person | None, ball: Box | None, seed: int = 0) -> np.ndarray:
    """Draw a crude scene so appearance-based identity has real pixels to look at."""
    import cv2

    img = _background(seed % 4).copy()
    cv2.rectangle(img, HOOP.as_int()[:2], HOOP.as_int()[2:], (0, 90, 230), 3)
    for p, role in ((you, "YOU"), (opp, "OPPONENT")):
        if p is None:
            continue
        x1, y1, x2, y2 = p.box.as_int()
        cv2.rectangle(img, (x1, y1), (x2, y2), (60, 60, 60), -1)  # skin/shorts
        sx1, sy1 = p.kp(5)
        sx2, sy2 = p.kp(12)
        cv2.rectangle(img, (int(sx1), int(sy1)), (int(sx2), int(sy2)), SHIRTS[role], -1)
    if ball is not None:
        cv2.circle(img, (int(ball.cx), int(ball.cy)), int(ball.w / 2), (0, 120, 255), -1)
    return img
