"""Hoop-relative court coordinates from a single uncalibrated camera.

We don't know the camera's intrinsics or the court lines, so distances are
expressed in *body heights* using each player's own bounding-box height as a
ruler (1 body height ≈ 1.8 m). Coordinates are from the attacker's point of
view facing the hoop:

* ``lateral`` > 0 means to the right of the hoop,
* ``depth``  > 0 means out from the hoop toward half court.

The camera is assumed to face the hoop from behind the players (phone at half
court). Pass ``mirror=True`` when the phone is behind the hoop looking at the
players instead.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .structures import Box

PLAYER_HEIGHT_M = 1.8
HOOP_HEIGHT_M = 3.05
# Floor distances toward/away from the camera are squashed by perspective.
DEPTH_FORESHORTENING = 1.6

PAINT_RADIUS = 1.4   # ≈ 2.5 m
MID_RADIUS = 6.75 / PLAYER_HEIGHT_M   # the three-point arc: "perimeter" means behind it
THREE_POINT_RADIUS = MID_RADIUS
SIDE_RATIO = 0.45    # |lateral| / distance above this counts as a side, not the top


@dataclass(frozen=True)
class CourtPos:
    lateral: float
    depth: float

    @property
    def distance(self) -> float:
        return math.hypot(self.lateral, self.depth)

    def __sub__(self, other: "CourtPos") -> "CourtPos":
        return CourtPos(self.lateral - other.lateral, self.depth - other.depth)


def court_position(box: Box, hoop: Box | None, frame_w: int, mirror: bool = False) -> CourtPos:
    scale = max(box.h, 1.0)
    fx, fy = box.foot
    if hoop is not None:
        # Where the floor directly under the rim would be, at this player's scale.
        floor_y = hoop.cy + (HOOP_HEIGHT_M / PLAYER_HEIGHT_M) * scale
        lateral = (fx - hoop.cx) / scale
        depth = (fy - floor_y) / scale * DEPTH_FORESHORTENING
    else:
        lateral = (fx - frame_w / 2) / scale
        depth = 0.0
    if mirror:
        lateral, depth = -lateral, -depth
    return CourtPos(lateral, depth)


def side_of(pos: CourtPos) -> str:
    d = pos.distance
    if d < PAINT_RADIUS:
        return "paint"
    ratio = pos.lateral / d if d > 0 else 0.0
    if ratio < -SIDE_RATIO:
        return "left"
    if ratio > SIDE_RATIO:
        return "right"
    return "top"


def zone_of(pos: CourtPos) -> str:
    side = side_of(pos)
    if side == "paint":
        return "paint"
    depth = "mid-range" if pos.distance < MID_RADIUS else "perimeter"
    return f"{side} {depth}"
