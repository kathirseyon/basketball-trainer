from hoopvision.court import CourtPos, court_position, side_of, zone_of
from hoopvision.patterns import describe, follow_ups, frequent_sequences
from hoopvision.structures import Box

from .sim import HOOP, foot_at


def test_court_position_round_trip():
    fx, fy = foot_at(1.0, 2.0)
    box = Box(fx - 30, fy - 150, fx + 30, fy)
    pos = court_position(box, HOOP, 1280)
    assert abs(pos.lateral - 1.0) < 1e-6 and abs(pos.depth - 2.0) < 1e-6
    mirrored = court_position(box, HOOP, 1280, mirror=True)
    assert mirrored.lateral < 0 and mirrored.depth < 0


def test_zones():
    assert zone_of(CourtPos(0.2, 0.5)) == "paint"
    assert zone_of(CourtPos(0.0, 2.5)) == "top mid-range"
    assert zone_of(CourtPos(-3.0, 1.0)) == "left mid-range"
    assert zone_of(CourtPos(0.0, 3.6)) == "top mid-range"   # just inside the arc (6.5 m)
    assert zone_of(CourtPos(0.0, 3.9)) == "top perimeter"   # behind it (7.0 m)
    assert zone_of(CourtPos(3.5, 2.0)) == "right perimeter"
    assert side_of(CourtPos(2.0, 0.5)) == "right"


def test_frequent_sequences_prefers_maximal_patterns():
    seqs = [
        ["start:right", "dribble:R", "crossover>L", "drive:left", "shot:layup"],
        ["start:top", "dribble:R", "crossover>L", "drive:left", "shot:layup"],
        ["start:right", "dribble:R", "crossover>L", "drive:left", "turnover"],
        ["start:left", "dribble:L", "shot:spot-up"],
    ]
    pats = frequent_sequences(seqs)
    assert pats[0] == (("dribble:R", "crossover>L", "drive:left"), 3)
    assert (("dribble:R", "crossover>L", "drive:left", "shot:layup"), 2) in pats
    # Sub-pattern with the same support is not reported separately.
    assert all(p != ("crossover>L", "drive:left") for p, _ in pats)
    assert follow_ups(seqs, "crossover>")["drive:left"] == 3
    assert describe(("crossover>L", "drive:left")) == "crossover to the left hand -> drives left"
