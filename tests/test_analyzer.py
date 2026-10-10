from hoopvision.analyzer import GameAnalyzer
from hoopvision.structures import OPPONENT, YOU

from .sim import FPS, HOOP, W, drive_and_layup, dribble_frames, hold_frames, move_frames, shot_frames


def play(frames, an=None, hoop=HOOP):
    an = an or GameAnalyzer()
    start = len(an.events) and an.frame + 1
    for i, (you, opp, ball) in enumerate(frames, start=start):
        an.update(i, i / FPS, {YOU: you, OPPONENT: opp}, ball, hoop, W)
    return an


def kinds(an, player=None):
    return [e.kind for e in an.events if e.kind != "dribble" and (player is None or e.player == player)]


def test_drive_right_and_made_layup():
    an = play(drive_and_layup(holder_is_you=False, direction="right", make=True))
    assert kinds(an) == ["possession", "drive", "blow_by", "shot", "shot_result"]
    drive = next(e for e in an.events if e.kind == "drive")
    assert drive.player == OPPONENT
    assert drive.detail == {"direction": "right"}
    assert an.stats[OPPONENT].drives[0]["got_past"] is True
    shot = next(e for e in an.events if e.kind == "shot")
    assert shot.detail == {"type": "layup", "zone": "paint"}
    assert an.events[-1].detail["result"] == "make"
    assert an.sequences(OPPONENT) == [["start:top", "drive:right", "shot:layup"]]


def test_drive_left_missed():
    an = play(drive_and_layup(holder_is_you=True, direction="left", make=False))
    assert next(e for e in an.events if e.kind == "drive").detail["direction"] == "left"
    assert an.events[-1].kind == "shot_result" and an.events[-1].detail["result"] == "miss"
    assert an.events[-1].player == YOU


def test_dribbles_and_crossovers():
    an = play(dribble_frames((0.0, 3.0), (0.0, 2.0), ["R", "R", "L", "R"]))
    st = an.stats[OPPONENT]
    assert st.dribble_hands == {"R": 3, "L": 1}
    assert st.crossovers == 2
    assert an.sequences(OPPONENT) == [["start:top", "dribble:R", "crossover>L", "crossover>R"]]


def test_steal_is_a_turnover():
    frames = hold_frames((0.0, 3.0), (0.5, 2.4), holder_is_you=False, n=6)
    frames += hold_frames((0.5, 2.4), (0.0, 3.0), holder_is_you=True, n=6)
    an = play(frames)
    assert kinds(an) == ["possession", "turnover", "possession"]
    assert an.stats[OPPONENT].turnovers == 1
    assert an.possession.player == YOU


def test_stepback_jumper():
    frames = hold_frames((2.0, 2.0), (1.6, 1.5), holder_is_you=True, n=20)
    frames += move_frames((2.0, 2.0), (2.5, 2.6), (1.6, 1.5), holder_is_you=True, n=10)
    frames += shot_frames((2.5, 2.6), (1.6, 1.5), shooter_is_you=True, make=True)
    an = play(frames)
    shot = next(e for e in an.events if e.kind == "shot")
    assert shot.player == YOU
    assert shot.detail["type"] == "stepback"
    assert shot.detail["zone"] == "right perimeter"
    s = an.summary()["players"][YOU]["shots"]
    assert s["by_type"] == {"stepback": [1, 1]}


def test_no_hoop_still_tracks_possession_and_shots():
    an = play(drive_and_layup(make=True), hoop=None)
    assert "drive" not in kinds(an)  # needs the hoop for direction
    assert an.stats[OPPONENT].shots and an.stats[OPPONENT].shots[0].result in ("unknown", "pending")
    an.finish()
    assert an.stats[OPPONENT].shots[0].result == "unknown"


def test_ball_dropout_keeps_possession():
    frames = hold_frames((0.0, 3.0), (0.0, 2.0), holder_is_you=False, n=6)
    frames += [(y, o, None) for y, o, _ in hold_frames((0.0, 3.0), (0.0, 2.0), False, n=20)]
    frames += hold_frames((0.0, 3.0), (0.0, 2.0), holder_is_you=False, n=3)
    an = play(frames)
    assert kinds(an) == ["possession"]


def test_summary_counts():
    frames = drive_and_layup(False, "right", True) + drive_and_layup(False, "right", False)
    frames += drive_and_layup(False, "right", True)
    an = play(frames)
    an.finish()
    opp = an.summary()["players"][OPPONENT]
    assert opp["shots"]["attempts"] == 3 and opp["shots"]["makes"] == 2
    assert opp["drives"]["by_direction"] == {"right": 3}
    assert opp["possessions"] == 3
    assert opp["avg_cushion_when_defending"] is None
    assert an.summary()["players"][YOU]["avg_cushion_when_defending"] > 0


def test_drive_cut_off_is_not_a_blow_by():
    # Defender stays between the attacker and the rim the whole way.
    frames = hold_frames((0.0, 3.4), (0.0, 2.0), holder_is_you=False, n=10)
    for i in range(1, 25):
        u = i / 24
        att = (u * 0.8, 3.4 - u * 1.6)
        dfd = (u * 0.7, 2.0 - u * 1.0)
        frames += move_frames(att, att, dfd, holder_is_you=False, n=1)
    an = play(frames)
    assert "drive" in kinds(an)
    assert "blow_by" not in kinds(an)
    assert an.stats[OPPONENT].drives[0]["got_past"] is False
