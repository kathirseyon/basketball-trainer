import json

from hoopvision.app import Session
from hoopvision.hoop import HoopTracker
from hoopvision.report import write_report
from hoopvision.structures import OPPONENT, YOU, Detections

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


class ZoomDetector(ReplayDetector):
    """Full-frame detection loses the ball for a few frames; the zoomed re-search finds it."""

    def __init__(self, frames, blind):
        super().__init__(frames)
        self.blind = blind
        self.zoom_calls = 0

    def __call__(self, frame):
        det = super().__call__(frame)
        self._last = det.ball
        if self.i - 1 in self.blind:
            det.ball = None
        return det

    def detect_ball_near(self, frame, region):
        self.zoom_calls += 1
        b = self._last
        return [(b, 0.5)] if b is not None and region.contains(*b.center) else []


def test_zoomed_ball_research_fills_detector_gaps():
    script = drive_and_layup()
    blind = set(range(12, 20))
    det = ZoomDetector(script, blind)
    session = Session(det, show_court=False)
    session.hoop.set_manual(render(*script[0]), HOOP)
    for i, f in enumerate(script):
        session.process(i, i / FPS, render(*f, seed=i))
        if i in blind:
            assert session.ball_state is not None and session.ball_state.visible
    assert det.zoom_calls >= len(blind)


def test_makes_update_score_and_commentary():
    from .sim import hold_frames, shot_frames

    script = []
    for _ in range(2):
        script += drive_and_layup(holder_is_you=False, direction="right", make=True)  # 1 point each
    script += hold_frames((0.0, 4.3), (0.0, 3.0), holder_is_you=True, n=10)
    script += shot_frames((0.0, 4.3), (0.0, 3.0), shooter_is_you=True, make=True)  # behind the arc: 2
    session = Session(ReplayDetector(script), names={"OPPONENT": "WEMBY"}, scout_target=1)
    session.hoop.set_manual(render(*script[0]), HOOP)
    you0 = script[0][0]
    session.identity.select_you_at(you0.box.cx, you0.box.cy)
    for i, f in enumerate(script):
        session.process(i, i / FPS, render(*f, seed=i))
    assert session.scoreboard.points == {YOU: 2, OPPONENT: 2}
    plays = [l.text for l in session.commentator.lines if l.kind == "play"]
    assert plays[0].endswith("+1 (YOU 0 - WEMBY 1)")
    assert plays[-1].endswith("+2 (YOU 2 - WEMBY 2)")
    assert "perimeter" in plays[-1]

    session.adjust_score(YOU, 1)
    session.undo_score()
    texts = [l.text for l in session.commentator.lines if l.kind == "score"]
    assert texts == ["Score corrected: +1 YOU (YOU 3 - WEMBY 2)", "Last score undone (YOU 2 - WEMBY 2)"]
    assert session.state()["game"]["points"] == {YOU: 2, OPPONENT: 2}
    assert session.context()["score"]["points"] == {YOU: 2, OPPONENT: 2}
