import random

from hoopvision.identity import IdentityAssigner
from hoopvision.structures import OPPONENT, YOU

from .sim import FPS, lerp, person, render


def test_follows_shirts_through_a_crossing_and_id_switch():
    ida = IdentityAssigner(you_side="left")
    rng = random.Random(0)
    n = 90
    for i in range(n):
        u = i / (n - 1)
        you = person(lerp(-2.0, 2.0, u), 2.0, track_id=1 if i < n // 2 else 2)   # tracker IDs swap mid-way
        opp = person(lerp(2.0, -2.0, u), 2.2, track_id=2 if i < n // 2 else 1)
        frame = render(you, opp, None, seed=i)
        persons = [you, opp]
        rng.shuffle(persons)
        out = ida.update(frame, persons, i / FPS)
        if ida.initialized:
            assert out[YOU] is you, f"frame {i}"
            assert out[OPPONENT] is opp, f"frame {i}"
    assert ida.initialized


def test_click_to_choose_you_and_swap():
    ida = IdentityAssigner(you_side="left")
    left, right = person(-2.0, 2.0, 1), person(2.0, 2.0, 2)
    frame = render(left, right, None)
    ida.select_you_at(right.box.cx, right.box.cy)
    out = ida.update(frame, [left, right], 0.0)
    assert out[YOU] is right and out[OPPONENT] is left
    ida.swap()
    out = ida.update(frame, [left, right], 1 / FPS)
    assert out[YOU] is left and out[OPPONENT] is right


def test_reacquires_after_leaving_frame():
    ida = IdentityAssigner(you_side="left", lost_after=10)
    you, opp = person(-2.0, 2.0, 1), person(2.0, 2.0, 2)
    for i in range(5):
        ida.update(render(you, opp, None, i), [you, opp], i / FPS)
    # Opponent walks off; YOU stays.
    for i in range(5, 40):
        ida.update(render(you, None, None, i), [you], i / FPS)
    # Opponent comes back on the other side with a brand-new tracker ID.
    opp2 = person(-0.5, 3.0, 9)
    out = ida.update(render(you, opp2, None, 40), [opp2, you], 40 / FPS)
    assert out[YOU] is you and out[OPPONENT] is opp2
