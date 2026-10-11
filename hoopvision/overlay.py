"""Draws the HUD: game-style hitboxes, name tags, ball trail, live stats and coaching banner."""

from __future__ import annotations

from collections import deque

import cv2
import numpy as np

from .structures import OPPONENT, YOU, Box, Person

# BGR
COLORS = {
    YOU: (90, 220, 60),
    OPPONENT: (60, 60, 235),
    "HOOP": (0, 150, 255),
    "BALL": (0, 220, 255),
}
FONT = cv2.FONT_HERSHEY_DUPLEX
SKELETON = [(5, 7), (7, 9), (6, 8), (8, 10), (5, 6), (5, 11), (6, 12), (11, 12), (11, 13), (13, 15), (12, 14), (14, 16)]


def _scale(img: np.ndarray) -> float:
    return max(img.shape[1] / 1280, 0.5)


def _blend_rect(img: np.ndarray, x1: int, y1: int, x2: int, y2: int, color, alpha: float) -> None:
    h, w = img.shape[:2]
    x1, y1, x2, y2 = max(x1, 0), max(y1, 0), min(x2, w), min(y2, h)
    if x2 <= x1 or y2 <= y1:
        return
    roi = img[y1:y2, x1:x2]
    overlay = np.empty_like(roi)
    overlay[:] = color
    cv2.addWeighted(overlay, alpha, roi, 1 - alpha, 0, dst=roi)


def draw_tag(img: np.ndarray, text: str, x: int, y: int, color, s: float, above: bool = True) -> None:
    """Filled name tag anchored at (x, y) = left edge, top of the box."""
    fs, th = 0.6 * s, max(1, int(round(1.5 * s)))
    (tw, tht), base = cv2.getTextSize(text, FONT, fs, th)
    pad = int(6 * s)
    y2 = y if above else y + tht + base + 2 * pad
    y1 = y2 - tht - base - 2 * pad
    if y1 < 0:  # flip inside the box when there is no room above
        y1, y2 = y, y + tht + base + 2 * pad
    cv2.rectangle(img, (x, y1), (x + tw + 2 * pad, y2), color, -1)
    cv2.putText(img, text, (x + pad, y2 - pad - base), FONT, fs, (255, 255, 255), th, cv2.LINE_AA)


def draw_hitbox(img: np.ndarray, box: Box, label: str, color, sublabel: str | None = None) -> None:
    s = _scale(img)
    x1, y1, x2, y2 = box.as_int()
    _blend_rect(img, x1, y1, x2, y2, color, 0.12)
    cv2.rectangle(img, (x1, y1), (x2, y2), color, 1, cv2.LINE_AA)
    # Thick corner brackets give the "video game" hitbox look.
    L = int(min(x2 - x1, y2 - y1) * 0.22) + 2
    t = max(2, int(3 * s))
    for (cx, cy, dx, dy) in ((x1, y1, 1, 1), (x2, y1, -1, 1), (x1, y2, 1, -1), (x2, y2, -1, -1)):
        cv2.line(img, (cx, cy), (cx + dx * L, cy), color, t, cv2.LINE_AA)
        cv2.line(img, (cx, cy), (cx, cy + dy * L), color, t, cv2.LINE_AA)
    draw_tag(img, label if not sublabel else f"{label}  {sublabel}", x1, y1, color, s)


def draw_skeleton(img: np.ndarray, person: Person, color) -> None:
    if person.keypoints is None:
        return
    for a, b in SKELETON:
        pa, pb = person.kp(a, 0.4), person.kp(b, 0.4)
        if pa and pb:
            cv2.line(img, tuple(map(int, pa)), tuple(map(int, pb)), color, 2, cv2.LINE_AA)


def draw_ball(img: np.ndarray, ball: Box | None, trail: deque) -> None:
    pts = [tuple(map(int, p)) for p in trail]
    for i in range(1, len(pts)):
        cv2.line(img, pts[i - 1], pts[i], COLORS["BALL"], max(1, int(4 * i / len(pts))), cv2.LINE_AA)
    if ball is not None:
        r = int(max(ball.w, ball.h) / 2) + 3
        cv2.circle(img, (int(ball.cx), int(ball.cy)), r, COLORS["BALL"], 2, cv2.LINE_AA)


def draw_scoreboard(img: np.ndarray, summary: dict, holder: str | None, fps: float | None,
                    names: dict[str, str] | None = None) -> None:
    s = _scale(img)
    fs, th = 0.55 * s, max(1, int(s))
    rows = []
    for role in (YOU, OPPONENT):
        p = summary["players"][role]
        sh = p["shots"]
        rows.append((role, f"FG {sh['makes']}/{sh['attempts']}   DRIVES {p['drives']['total']}   XOVER {p['crossovers']}"))
    lh = int(28 * s)
    w, h = int(430 * s), lh * len(rows) + int(14 * s)
    x0, y0 = int(12 * s), int(12 * s)
    _blend_rect(img, x0, y0, x0 + w, y0 + h, (20, 20, 20), 0.6)
    for i, (role, txt) in enumerate(rows):
        y = y0 + int(8 * s) + lh * (i + 1) - int(8 * s)
        cv2.circle(img, (x0 + int(12 * s), y - int(6 * s)), int(6 * s), COLORS[role], -1)
        name = (names or {}).get(role, role) + (" *" if holder == role else "")
        cv2.putText(img, name, (x0 + int(24 * s), y), FONT, fs, COLORS[role], th, cv2.LINE_AA)
        cv2.putText(img, txt, (x0 + int(150 * s), y), FONT, fs * 0.9, (235, 235, 235), th, cv2.LINE_AA)
    if fps:
        cv2.putText(img, f"{fps:.0f} FPS", (img.shape[1] - int(90 * s), int(28 * s)), FONT, 0.5 * s,
                    (200, 200, 200), th, cv2.LINE_AA)


def draw_feed(img: np.ndarray, lines: list[tuple[str, str]]) -> None:
    """Recent events, newest at the bottom-left."""
    s = _scale(img)
    fs, th = 0.55 * s, max(1, int(s))
    lh = int(26 * s)
    y = img.shape[0] - int(16 * s)
    for role, text in reversed(lines):
        (tw, tht), _ = cv2.getTextSize(text, FONT, fs, th)
        _blend_rect(img, int(10 * s), y - tht - int(8 * s), int(26 * s) + tw, y + int(6 * s), (20, 20, 20), 0.55)
        cv2.rectangle(img, (int(10 * s), y - tht - int(8 * s)), (int(14 * s), y + int(6 * s)),
                      COLORS.get(role, (200, 200, 200)), -1)
        cv2.putText(img, text, (int(20 * s), y), FONT, fs, (255, 255, 255), th, cv2.LINE_AA)
        y -= lh


def draw_coach(img: np.ndarray, title: str | None, detail: str | None = None) -> None:
    if not title:
        return
    s = _scale(img)
    fs, th = 0.6 * s, max(1, int(round(1.5 * s)))
    text = f"COACH: {title}"
    (tw, tht), _ = cv2.getTextSize(text, FONT, fs, th)
    w = img.shape[1]
    x2 = w - int(12 * s)
    x1 = x2 - tw - int(24 * s)
    y1, y2 = int(44 * s), int(44 * s) + tht + int(20 * s)
    _blend_rect(img, x1, y1, x2, y2, (40, 25, 10), 0.7)
    cv2.rectangle(img, (x1, y1), (x2, y2), COLORS["HOOP"], max(1, int(2 * s)), cv2.LINE_AA)
    cv2.putText(img, text, (x1 + int(12 * s), y2 - int(10 * s)), FONT, fs, (255, 255, 255), th, cv2.LINE_AA)
    if detail:
        cv2.putText(img, detail, (x1 + int(12 * s), y2 + int(20 * s)), FONT, 0.45 * s, (230, 230, 230),
                    max(1, int(s)), cv2.LINE_AA)


def draw_status(img: np.ndarray, text: str) -> None:
    s = _scale(img)
    fs, th = 0.7 * s, max(1, int(round(1.5 * s)))
    (tw, tht), _ = cv2.getTextSize(text, FONT, fs, th)
    x = (img.shape[1] - tw) // 2
    y = img.shape[0] // 2
    _blend_rect(img, x - 16, y - tht - 16, x + tw + 16, y + 16, (20, 20, 20), 0.7)
    cv2.putText(img, text, (x, y), FONT, fs, (255, 255, 255), th, cv2.LINE_AA)


def draw_phase(img: np.ndarray, status: dict) -> None:
    """Session clock + phase progress bar under the scoreboard."""
    s = _scale(img)
    x0, y0 = int(12 * s), int(84 * s)
    w, h = int(430 * s), int(34 * s)
    _blend_rect(img, x0, y0, x0 + w, y0 + h, (20, 20, 20), 0.6)
    fs, th = 0.5 * s, max(1, int(s))
    text = f"{status['clock']}  {status['label'].upper()}"
    cv2.putText(img, text, (x0 + int(10 * s), y0 + int(22 * s)), FONT, fs, (255, 255, 255), th, cv2.LINE_AA)
    bx1, bx2 = x0 + int(230 * s), x0 + w - int(12 * s)
    by1, by2 = y0 + int(13 * s), y0 + int(21 * s)
    cv2.rectangle(img, (bx1, by1), (bx2, by2), (70, 70, 70), -1)
    fill = bx1 + int((bx2 - bx1) * status["progress"])
    color = COLORS["HOOP"] if status["phase"] != "ready" else COLORS[YOU]
    cv2.rectangle(img, (bx1, by1), (fill, by2), color, -1)
