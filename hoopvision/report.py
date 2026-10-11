"""End-of-session scouting report: JSON, Markdown and two images."""

from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np

from .analyzer import GameAnalyzer
from .coach import Tip
from .overlay import COLORS
from .patterns import describe, frequent_sequences
from .structures import OPPONENT, ROLES, YOU


def _heatmap(snapshot: np.ndarray, analyzer: GameAnalyzer) -> np.ndarray:
    img = snapshot.copy()
    h, w = img.shape[:2]
    sigma = max(w, h) / 60
    for role in ROLES:
        pts = analyzer.stats[role].foot_points
        if not pts:
            continue
        acc = np.zeros((h, w), np.float32)
        for x, y in pts:
            xi, yi = int(np.clip(x, 0, w - 1)), int(np.clip(y, 0, h - 1))
            acc[yi, xi] += 1
        acc = cv2.GaussianBlur(acc, (0, 0), sigma)
        if acc.max() <= 0:
            continue
        alpha = (acc / acc.max() * 0.65)[..., None]
        color = np.array(COLORS[role], np.float32)[None, None, :]
        img = (img * (1 - alpha) + color * alpha).astype(np.uint8)
    return img


def _shot_chart(snapshot: np.ndarray, analyzer: GameAnalyzer) -> np.ndarray:
    img = (snapshot * 0.6).astype(np.uint8)
    r = max(6, img.shape[1] // 120)
    for role in ROLES:
        for s in analyzer.stats[role].shots:
            x, y = map(int, s.image_xy)
            c = COLORS[role]
            if s.result == "make":
                cv2.circle(img, (x, y), r, c, 3, cv2.LINE_AA)
            else:
                cv2.line(img, (x - r, y - r), (x + r, y + r), c, 3, cv2.LINE_AA)
                cv2.line(img, (x - r, y + r), (x + r, y - r), c, 3, cv2.LINE_AA)
    cv2.putText(img, "O = make   X = miss   green = YOU   red = OPPONENT", (12, img.shape[0] - 14),
                cv2.FONT_HERSHEY_DUPLEX, 0.6, (255, 255, 255), 1, cv2.LINE_AA)
    return img


def _table(rows: dict[str, list[int]]) -> list[str]:
    if not rows:
        return ["_none recorded_", ""]
    out = ["| | Made | Att | % |", "|---|---:|---:|---:|"]
    for k, (m, a) in sorted(rows.items(), key=lambda kv: -kv[1][1]):
        out.append(f"| {k} | {m} | {a} | {round(100 * m / a) if a else 0}% |")
    return out + [""]


def write_report(out_dir: str | Path, analyzer: GameAnalyzer, tips: list[Tip], snapshot: np.ndarray | None,
                 names: dict[str, str] | None = None, commentary: list[str] | None = None) -> Path:
    names = {YOU: YOU, OPPONENT: OPPONENT, **(names or {})}
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    summary = analyzer.summary()
    patterns = {
        role: [{"moves": list(p), "description": describe(p), "possessions": n}
               for p, n in frequent_sequences(analyzer.sequences(role))]
        for role in ROLES
    }
    data = {"names": names, "summary": summary, "commentary": commentary or [], "patterns": patterns, "tips": [t.to_dict() for t in tips],
            "events": [{"t": round(e.t, 2), "player": e.player, "kind": e.kind, **e.detail}
                       for e in analyzer.events if e.kind != "dribble"]}
    (out / "report.json").write_text(json.dumps(data, indent=2, default=str))

    images = []
    if snapshot is not None:
        cv2.imwrite(str(out / "heatmap.png"), _heatmap(snapshot, analyzer))
        cv2.imwrite(str(out / "shot_chart.png"), _shot_chart(snapshot, analyzer))
        images = ["heatmap.png", "shot_chart.png"]

    md = ["# HoopVision scouting report", "", f"Session length: {summary['duration_s']} s", ""]
    md += ["## Coaching tips", ""]
    for t in tips:
        md.append(f"- **[{t.side}] {t.title}** - {t.text} _(evidence: {t.evidence})_")
    md.append("")
    for role in (OPPONENT, YOU):
        p = summary["players"][role]
        md += [f"## {names[role]}" + (f" ({role})" if names[role] != role else ""), ""]
        md.append(f"- Possessions: {p['possessions']}, turnovers: {p['turnovers']}")
        md.append(f"- Drives: {p['drives']['total']} {p['drives']['by_direction']} "
                  f"(got past defender: {p['drives']['got_past_by_direction']})")
        md.append(f"- Dribble hand: {p['dribble_hands']}, crossovers: {p['crossovers']}")
        if p["avg_cushion_when_defending"] is not None:
            md.append(f"- Average gap when defending: {p['avg_cushion_when_defending'] * 1.8:.1f} m")
        md.append(f"- Distance covered: ~{p['distance_m']} m, average speed: {p['avg_speed_mps']} m/s")
        md += ["", "**Shots by zone**", ""] + _table(p["shots"]["by_zone"])
        md += ["**Shots by type**", ""] + _table(p["shots"]["by_type"])
        if patterns[role]:
            md += ["**Repeated plays**", ""]
            md += [f"- {pt['description']} ({pt['possessions']} possessions)" for pt in patterns[role]]
            md.append("")
    for img in images:
        md += [f"![{img}]({img})", ""]
    if commentary:
        md += ["## Commentary log", ""] + [f"- {line}" for line in commentary] + [""]
    (out / "report.md").write_text("\n".join(md))
    return out
