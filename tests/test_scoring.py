import pytest

from hoopvision.scoring import Scoreboard
from hoopvision.structures import OPPONENT, YOU


def test_values_by_system():
    assert Scoreboard("1s2s").value_of_make(False) == 1 and Scoreboard("1s2s").value_of_make(True) == 2
    assert Scoreboard("2s3s").value_of_make(False) == 2 and Scoreboard("2s3s").value_of_make(True) == 3
    with pytest.raises(ValueError):
        Scoreboard("4s")


def test_game_point_game_over_and_series():
    sb = Scoreboard(game_to=3)
    assert sb.make(0, YOU, False) == (1, [])
    pts, ann = sb.make(1, YOU, False)
    assert ann == [{"type": "game_point", "player": YOU}]
    assert sb.make(2, OPPONENT, False) == (1, [])  # still game point YOU, no repeat call
    pts, ann = sb.make(3, YOU, True)
    assert pts == 2
    assert ann == [{"type": "game_over", "winner": YOU, "final": {YOU: 4, OPPONENT: 1}, "game": 1}]
    assert sb.points == {YOU: 0, OPPONENT: 0} and sb.game == 2 and sb.games_won[YOU] == 1


def test_win_by_two():
    sb = Scoreboard(game_to=3, win_by=2)
    for who in (YOU, OPPONENT, YOU, OPPONENT, YOU):
        sb.make(0, who, False)
    assert sb.points == {YOU: 3, OPPONENT: 2} and sb.game == 1  # 3-2 isn't enough
    _, ann = sb.make(0, YOU, False)
    assert ann[0]["type"] == "game_over" and ann[0]["final"] == {YOU: 4, OPPONENT: 2}


def test_manual_and_undo():
    sb = Scoreboard()
    sb.add(0, OPPONENT, -1, "manual")
    assert sb.points[OPPONENT] == 0 and sb.history == []  # never below zero, no-op not recorded
    sb.make(1, YOU, True)
    sb.add(2, OPPONENT, 1, "manual")
    assert sb.undo(3) == OPPONENT and sb.points == {YOU: 2, OPPONENT: 0}
    assert sb.undo(4) == YOU and sb.points == {YOU: 0, OPPONENT: 0}
    assert sb.undo(5) is None


def test_undo_stops_at_finished_game():
    sb = Scoreboard(game_to=1)
    sb.make(0, YOU, False)
    assert sb.game == 2 and sb.undo(1) is None
