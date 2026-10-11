import json

from hoopvision.app import Session
from hoopvision.chat import CoachChat
from hoopvision.server import Runner, create_app

from .sim import FPS, HOOP, drive_and_layup, render
from .test_session import ReplayDetector


class ListSource:
    """FrameSource stand-in that replays rendered frames."""

    live = False
    fps = FPS

    def __init__(self, script):
        self.script = script

    def __iter__(self):
        for i, f in enumerate(self.script):
            yield i, i / FPS, render(*f, seed=i)

    def release(self):
        pass


def test_dashboard_api(tmp_path):
    script = drive_and_layup() * 2
    session = Session(ReplayDetector(script), names={"OPPONENT": "WEMBY"}, scout_target=1)
    you0 = script[0][0]
    session.identity.select_you_at(you0.box.cx, you0.box.cy)
    runner = Runner(session, ListSource(script), tmp_path, realtime=False, hoop=HOOP)
    chat = CoachChat(session.context, offline=True)
    client = create_app(session, runner, chat).test_client()

    assert b"Coach chat" in client.get("/").data
    runner.start()
    runner.join(timeout=60)
    assert runner.done

    s = client.get("/api/state").get_json()
    assert s["names"]["OPPONENT"] == "WEMBY"
    assert s["status"]["phase"] == "ready"
    assert s["coach"] == "offline" and s["done"] is True
    assert s["score"]["OPPONENT"]["shots"]["attempts"] == 2
    texts = [l["text"] for l in s["lines"]]
    assert any(t.startswith("WEMBY drives") for t in texts)
    assert texts[-1].startswith("Session over")
    later = client.get(f"/api/state?since={len(s['lines'])}").get_json()
    assert later["lines"] == []

    r = client.post("/api/chat", json={"message": "how do I guard WEMBY?"})
    assert r.status_code == 200 and "data says" in r.get_data(as_text=True)
    assert client.post("/api/chat", json={"message": " "}).status_code == 400
    assert client.post("/api/hoop", json={"x": 1, "y": 1, "w": 1, "h": 1}).status_code == 400
    assert client.post("/api/swap").get_json() == {"ok": True}

    report = json.loads((tmp_path / "report.json").read_text())
    assert report["names"]["OPPONENT"] == "WEMBY"
    assert any(line.startswith("Calibrating") for line in report["commentary"])


def test_mjpeg_stream_yields_frames(tmp_path):
    script = drive_and_layup()[:5]
    session = Session(ReplayDetector(script))
    runner = Runner(session, ListSource(script), tmp_path, realtime=False)
    client = create_app(session, runner, CoachChat(session.context, offline=True)).test_client()
    runner.start()
    runner.join(timeout=30)
    body = client.get("/stream.mjpg").get_data()
    assert body.startswith(b"--frame\r\nContent-Type: image/jpeg") and b"\xff\xd8" in body
