import json

from hoopvision.app import Session
from hoopvision.hoop import HoopTracker
from hoopvision.report import write_report
from hoopvision.structures import OPPONENT, Detections

from .sim import FPS, HOOP, drive_and_layup, dribble_frames, render


class ReplayDetector:
    """Stands in for YOLO: returns scripted detections for each frame."""

    def __init__(self, frames):
        self.frames = frames
        self.i = 0

    def __call__(self, frame):
        you, opp, ball = self.frames[self.i]
        self.i += 1
        return Detections(persons=[p for p in (opp, you) if p is not None], ball=ball)


def test_full_pipeline_writes_report(tmp_path):
    script = []
    for _ in range(3):
        script += dribble_frames((0.0, 3.0), (0.0, 2.2), ["R", "L"])
        script += drive_and_layup(holder_is_you=False, direction="left", make=True)
    det = ReplayDetector(script)
    session = Session(det, tip_interval=0.5)
    first = render(*script[0])
    session.hoop.set_manual(first, HOOP)
    # Both players start at the same x, so tell it who YOU are (like clicking in the window).
    you0 = script[0][0]
    session.identity.select_you_at(you0.box.cx, you0.box.cy)
    for i, (you, opp, ball) in enumerate(script):
        out = session.process(i, i / FPS, render(you, opp, ball, i))
        assert out.shape[1] == first.shape[1] and out.shape[0] > first.shape[0]  # video + live court
    session.analyzer.finish()

    s = session.analyzer.summary()["players"][OPPONENT]
    assert s["shots"]["attempts"] == 3 and s["shots"]["makes"] == 3
    assert s["drives"]["by_direction"] == {"left": 3}
    tips = session.tips()
    assert any(t.title == "Force them right" for t in tips)

    out = write_report(tmp_path, session.analyzer, tips, session.snapshot)
    data = json.loads((out / "report.json").read_text())
    assert data["patterns"][OPPONENT][0]["possessions"] == 3
    assert (out / "heatmap.png").exists() and (out / "shot_chart.png").exists()
    assert "Force them right" in (out / "report.md").read_text()


def test_hoop_tracker_follows_camera_shake():
    script = drive_and_layup()
    frame = render(*script[0])
    ht = HoopTracker()
    ht.set_manual(frame, HOOP)
    import numpy as np

    shifted = np.roll(frame, (6, -9), axis=(0, 1))
    box = None
    for _ in range(30):
        box = ht.update(shifted)
    assert abs(box.x1 - (HOOP.x1 - 9)) < 1.5 and abs(box.y1 - (HOOP.y1 + 6)) < 1.5
