from types import SimpleNamespace

from hoopvision.analyzer import GameAnalyzer
from hoopvision.chat import CoachChat, offline_answer
from hoopvision.coach import Tip
from hoopvision.commentary import Commentator, clock
from hoopvision.structures import OPPONENT, YOU

from .sim import FPS, HOOP, W, drive_and_layup

NAMES = {YOU: "YOU", OPPONENT: "WEMBY"}


def run_commentary(frames, hoop_from=0, ball=True, scout_target=2):
    an = GameAnalyzer()
    c = Commentator(NAMES, scout_target=scout_target)
    for i, (you, opp, b) in enumerate(frames):
        t = 100 + i / FPS  # clock should be relative to the first frame
        hoop = HOOP if i >= hoop_from else None
        events = an.update(i, t, {YOU: you, OPPONENT: opp}, b, hoop, W)
        c.update(t, hoop_ready=hoop is not None, players={YOU: you, OPPONENT: opp},
                 shirts={YOU: "red", OPPONENT: "blue"}, ball_seen=ball, events=events, analyzer=an)
    return an, c


def test_clock_format():
    assert clock(0) == "0:00" and clock(75.9) == "1:15" and clock(-3) == "0:00"


def test_calibration_then_scouting_then_ready():
    frames = drive_and_layup(False, "right", True) + drive_and_layup(False, "left", False)
    an, c = run_commentary(frames, hoop_from=5)
    texts = [l.text for l in c.lines]
    assert texts[0].startswith("Calibrating")
    assert any(t.startswith("Locked on: YOU (red shirt, ") and "WEMBY (blue shirt," in t for t in texts)
    assert "Hoop locked in." in texts
    plays = [l for l in c.lines if l.kind == "play"]
    assert len(plays) == 2
    assert plays[0].player == OPPONENT
    assert plays[0].text == "WEMBY drives right, gets by YOU, then layup from the paint - and it's GOOD."
    assert plays[1].text.endswith("no good.")
    assert c.phase == "ready"
    assert any(t.startswith("Game plan ready") for t in texts)
    assert c.status(an)["progress"] == 1.0
    assert c.lines[-1].clock.startswith("0:0")  # relative clock, not t=100s


def test_hints_when_hoop_and_ball_missing():
    frames = drive_and_layup()
    frames = frames + frames + frames + frames + frames  # ~11 s
    _, c = run_commentary(frames, hoop_from=10_000, ball=False)
    texts = " ".join(l.text for l in c.lines)
    assert "drag a box around the rim" in texts
    assert "Still no ball" in texts
    assert c.phase == "calibrating"
    assert c.status()["detail"] == "Looking for: hoop, ball"


def test_new_tips_become_insights_once():
    c = Commentator(NAMES)
    c.phase = "scouting"
    c.start_t = 0
    tip = Tip(5, "defense", "Force them left", "They drive right.", "drives right: 4/5")
    c._insights([tip, Tip(0, "info", "Still learning", "", "")])
    c._insights([tip])
    insights = [l for l in c.lines if l.kind == "insight"]
    assert [l.text for l in insights] == ["Force them left: They drive right. (drives right: 4/5)"]


# ------------------------------------------------------------------ chat
DATA = {
    "names": NAMES,
    "tips": [
        {"side": "defense", "title": "Force them left", "text": "Shade right.", "evidence": "4/5"},
        {"side": "offense", "title": "Shoot it", "text": "They sag.", "evidence": "2.4 m"},
    ],
    "patterns": {OPPONENT: [{"description": "drives right -> layup", "possessions": 3}]},
}


def test_offline_answers_route_by_topic():
    assert "Force them left" in offline_answer("how do I guard him?", DATA)
    assert "Shoot it" in offline_answer("how do I score on them", DATA)
    assert "drives right -> layup" in offline_answer("what's his go-to pattern?", DATA)
    assert "enough data" in offline_answer("hi", {"tips": []})


class FakeStream:
    def __init__(self, chunks, stop_reason="end_turn"):
        self.chunks, self.stop_reason = chunks, stop_reason

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    @property
    def text_stream(self):
        yield from self.chunks

    def get_final_message(self):
        return SimpleNamespace(stop_reason=self.stop_reason,
                               content=[SimpleNamespace(type="text", text="".join(self.chunks))])


class FakeClient:
    def __init__(self, *streams, error=None):
        self.streams = list(streams)
        self.error = error
        self.calls = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=self._stream))

    def _stream(self, **kw):
        self.calls.append(kw)
        if self.error:
            raise self.error
        return self.streams.pop(0)


def test_claude_chat_streams_and_keeps_history():
    client = FakeClient(FakeStream(["Shade ", "right."]), FakeStream(["Yes."]))
    chat = CoachChat(lambda: DATA, client=client)
    assert "".join(chat.ask("How do I guard WEMBY?")) == "Shade right."
    assert "".join(chat.ask("Really?")) == "Yes."
    first, second = client.calls
    assert first["model"] == "claude-opus-5-5"
    assert first["fallbacks"] == "default" and first["betas"] == ["server-side-fallback-2026-07-01"]
    assert first["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert first["messages"][0]["content"].startswith("<game_data>")
    assert first["messages"][0]["content"].endswith("How do I guard WEMBY?")
    # Second request = first turn + assistant reply + new question (append-only history).
    assert [m["role"] for m in second["messages"]] == ["user", "assistant", "user"]
    assert second["messages"][0] == first["messages"][0]


def test_claude_refusal_and_errors_fall_back():
    chat = CoachChat(lambda: DATA, client=FakeClient(FakeStream([], stop_reason="refusal")))
    assert "can't help" in "".join(chat.ask("?"))
    assert chat.messages == []  # refused turn not kept

    chat = CoachChat(lambda: DATA, client=FakeClient(error=ConnectionError("down")))
    out = "".join(chat.ask("how do I guard him"))
    assert "Couldn't reach Claude" in out and "Force them left" in out
    assert chat.online  # transient error: keep trying Claude next time


def test_offline_flag_never_calls_claude():
    chat = CoachChat(lambda: DATA, offline=True)
    assert not chat.online
    assert "Force them left" in "".join(chat.ask("defend"))


def test_missing_credentials_switch_to_offline():
    chat = CoachChat(lambda: DATA, client=FakeClient(error=TypeError("Could not resolve authentication method")))
    out = "".join(chat.ask("defend"))
    assert "no valid API key" in out and "Force them left" in out
    assert not chat.online
