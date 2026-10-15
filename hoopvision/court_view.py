"""Top-down "LIVE COURT" minimap drawn under the camera view.

Player positions come from `court.CourtPos` (body heights from the rim, from
the attacker's point of view), converted to metres on a FIBA half court with
the hoop at the top.
"""

from __future__ import annotations

from collections import deque

import cv2
import numpy as np

from .court import PLAYER_HEIGHT_M, CourtPos
from .structures import ROLES

COURT_W, COURT_D = 15.0, 14.0          # half court, metres
RIM_Y = 1.575                           # rim centre from the baseline
BG = (36, 30, 27)
LINE = (210, 210, 210)
PAINT = (82, 55, 34)
RIM = (0, 150, 255)
BALL = (0, 220, 255)


class CourtView:
    def __init__(self, colors: dict[str, tuple[int, int, int]], names: dict[str, str], trail: int = 45):
        self.colors = colors
        self.names = names
        self.trails: dict[str, deque[tuple[float, float]]] = {r: deque(maxlen=trail) for r in ROLES}

    def push(self, role: str, pos: CourtPos | None) -> None:
        if pos is None:
            return
        x = float(np.clip(pos.lateral * PLAYER_HEIGHT_M, -COURT_W / 2, COURT_W / 2))
        y = float(np.clip(RIM_Y + pos.depth * PLAYER_HEIGHT_M, 0, COURT_D))
        self.trails[role].append((x, y))

    def render(self, width: int, height: int, ball_with: str | None = None, ball_at_rim: bool = False) -> np.ndarray:
        img = np.empty((height, width, 3), np.uint8)
        img[:] = (24, 20, 18)
        s = width / 1280
        top = int(40 * s)
        scale = min((width - 40 * s) / COURT_W, (height - top - 10 * s) / COURT_D)
        ox = width / 2
        oy = top

        def P(x: float, y: float) -> tuple[int, int]:
            return int(ox + x * scale), int(oy + y * scale)

        def R(m: float) -> int:
            return max(1, int(m * scale))

        t = max(1, int(2 * s))
        cv2.rectangle(img, P(-COURT_W / 2, 0), P(COURT_W / 2, COURT_D), BG, -1)
        cv2.rectangle(img, P(-2.45, 0), P(2.45, 5.8), PAINT, -1)
        cv2.rectangle(img, P(-COURT_W / 2, 0), P(COURT_W / 2, COURT_D), LINE, t, cv2.LINE_AA)
        cv2.rectangle(img, P(-2.45, 0), P(2.45, 5.8), LINE, t, cv2.LINE_AA)
        cv2.circle(img, P(0, 5.8), R(1.8), LINE, t, cv2.LINE_AA)
        cv2.ellipse(img, P(0, RIM_Y), (R(1.25), R(1.25)), 0, 0, 180, LINE, max(1, t // 2), cv2.LINE_AA)
        # Three-point line: straight corners then the 6.75 m arc.
        corner_x = COURT_W / 2 - 0.9
        corner_y = RIM_Y + float(np.sqrt(6.75 ** 2 - corner_x ** 2))
        cv2.line(img, P(-corner_x, 0), P(-corner_x, corner_y), LINE, t, cv2.LINE_AA)
        cv2.line(img, P(corner_x, 0), P(corner_x, corner_y), LINE, t, cv2.LINE_AA)
        a0 = float(np.degrees(np.arctan2(corner_y - RIM_Y, corner_x)))
        cv2.ellipse(img, P(0, RIM_Y), (R(6.75), R(6.75)), 0, a0, 180 - a0, LINE, t, cv2.LINE_AA)
        cv2.ellipse(img, P(0, COURT_D), (R(1.8), R(1.8)), 0, 180, 360, LINE, t, cv2.LINE_AA)
        cv2.line(img, P(-0.9, 1.2), P(0.9, 1.2), RIM, max(2, t), cv2.LINE_AA)
        cv2.circle(img, P(0, RIM_Y), R(0.23), RIM, max(2, t), cv2.LINE_AA)

        font = cv2.FONT_HERSHEY_DUPLEX
        cv2.putText(img, "LIVE COURT", (int(16 * s), int(28 * s)), font, 0.65 * s, (235, 235, 235),
                    max(1, int(s)), cv2.LINE_AA)
        lx = width - int(16 * s)
        for role in reversed(ROLES):
            label = self.names[role]
            (tw, _), _ = cv2.getTextSize(label, font, 0.5 * s, max(1, int(s)))
            lx -= tw
            cv2.putText(img, label, (lx, int(28 * s)), font, 0.5 * s, (235, 235, 235), max(1, int(s)), cv2.LINE_AA)
            lx -= int(16 * s)
            cv2.circle(img, (lx + int(6 * s), int(23 * s)), int(6 * s), self.colors[role], -1, cv2.LINE_AA)
            lx -= int(18 * s)

        for role in ROLES:
            pts = list(self.trails[role])
            if not pts:
                continue
            c = self.colors[role]
            for i in range(1, len(pts)):
                a = i / len(pts)
                col = tuple(int(BG[k] * (1 - a) + c[k] * a) for k in range(3))
                cv2.line(img, P(*pts[i - 1]), P(*pts[i]), col, max(1, int(2 * s)), cv2.LINE_AA)
            p = P(*pts[-1])
            cv2.circle(img, p, int(11 * s), (255, 255, 255), -1, cv2.LINE_AA)
            cv2.circle(img, p, int(8 * s), c, -1, cv2.LINE_AA)
            label = self.names[role]
            (tw, th), _ = cv2.getTextSize(label, font, 0.5 * s, max(1, int(s)))
            cv2.putText(img, label, (p[0] - tw // 2, p[1] - int(16 * s)), font, 0.5 * s, (255, 255, 255),
                        max(1, int(s)), cv2.LINE_AA)
            if role == ball_with:
                _ball(img, (p[0] + int(13 * s), p[1] + int(8 * s)), int(6 * s))
        if ball_at_rim:
            _ball(img, P(0, RIM_Y + 0.5), int(6 * s))
        return img


def _ball(img: np.ndarray, center: tuple[int, int], r: int) -> None:
    cv2.circle(img, center, r + 2, (20, 20, 20), -1, cv2.LINE_AA)
    cv2.circle(img, center, r, BALL, -1, cv2.LINE_AA)
