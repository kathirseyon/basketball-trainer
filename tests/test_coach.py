import copy

from hoopvision.analyzer import GameAnalyzer
from hoopvision.coach import generate_tips
from hoopvision.structures import OPPONENT, YOU


def base_summary():
    s = GameAnalyzer().summary()
    return copy.deepcopy(s)


def titles(tips):
    return [t.title for t in tips]


def test_no_data_gives_info_tip():
    tips = generate_tips(base_summary())
    assert len(tips) == 1 and tips[0].side == "info"


def test_opponent_tendencies():
    s = base_summary()
    o = s["players"][OPPONENT]
    o["drives"] = {"total": 6, "by_direction": {"right": 5, "left": 1},
                   "got_past_by_direction": {"right": 3}}
    o["dribble_hands"] = {"R": 18, "L": 2}
    o["shots"] = {"attempts": 6, "makes": 3,
                  "by_type": {"layup": [3, 4], "jumper": [0, 2]},
                  "by_zone": {"paint": [3, 4], "top perimeter": [0, 3]}}
    o["sequences"] = [["start:top", "dribble:R", "crossover>L", "drive:left", "shot:layup"]] * 2 + \
                     [["start:right", "crossover>L", "drive:left"]]
    o["possessions"] = 6
    tips = generate_tips(s)
    t = titles(tips)
    assert "Force them left" in t
    assert "Give a bigger cushion on their drive" in t
    assert "Take away their right hand" in t
    assert "Their go-to is the layup" in t
    assert "Deny the paint" in t
    assert "Live with shots from the top perimeter" in t
    assert "Don't bite on the crossover" in t
    assert "Their go-to play: R-hand > cross L > drive L > layup" in t
    assert all(tip.evidence for tip in tips)
    assert [x.priority for x in tips] == sorted((x.priority for x in tips), reverse=True)


def test_offense_and_conditioning_tips():
    s = base_summary()
    o, y = s["players"][OPPONENT], s["players"][YOU]
    o["avg_cushion_when_defending"] = 1.5
    o["early_speed_mps"], o["late_speed_mps"] = 3.0, 2.0
    y["possessions"] = 5
    y["drives"] = {"total": 4, "by_direction": {"left": 3, "right": 1}, "got_past_by_direction": {"left": 3}}
    y["shots"]["by_zone"] = {"left mid-range": [3, 4], "right perimeter": [0, 4]}
    t = titles(generate_tips(s))
    assert "Shoot it - they're giving you space" in t
    assert "They're getting tired - push the pace" in t
    assert "Keep attacking left" in t
    assert "Hunt your left mid-range shot" in t
    assert "Fewer shots from the right perimeter" in t
