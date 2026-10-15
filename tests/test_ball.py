from hoopvision.ball import BallTracker
from hoopvision.structures import Box

from .sim import ball_at

DT = 1 / 30


def test_follows_ball_and_ignores_far_false_positive():
    bt = BallTracker()
    for i in range(20):
        x = 300 + 10 * i
        decoy = (Box(1100, 600, 1120, 620), 0.9)  # a "ball" in the crowd
        st = bt.update(i * DT, [decoy, (ball_at(x, 400), 0.5)] if i else [(ball_at(x, 400), 0.6)])
        assert st.visible and abs(st.measured.cx - x) < 1e-6
    assert abs(st.velocity[0] - 300) < 40  # px/s


def test_coasts_through_gap_then_reacquires():
    bt = BallTracker(max_coast=0.5)
    for i in range(15):
        bt.update(i * DT, [(ball_at(200 + 12 * i, 300), 0.6)])
    # Hidden for 8 frames: the tracker keeps predicting along the motion.
    for i in range(15, 23):
        st = bt.update(i * DT, [])
        assert not st.visible
        assert abs(st.box.cx - (200 + 12 * i)) < 25
    st = bt.update(23 * DT, [(ball_at(200 + 12 * 23, 300), 0.4)])
    assert st.visible and bt.visibility < 1


def test_gives_up_after_max_coast_and_restarts_on_confident_detection():
    bt = BallTracker(max_coast=0.3)
    bt.update(0, [(ball_at(100, 100), 0.8)])
    assert bt.update(0.2, []) is not None
    assert bt.update(0.5, []) is None and not bt.active
    st = bt.update(0.6, [(ball_at(900, 500), 0.7)])
    assert st.visible and st.box.cx == 900
    # A low-confidence blip alone can't start a track.
    bt2 = BallTracker()
    assert bt2.update(0, [(ball_at(10, 10), 0.1)]) is None


def test_jumps_to_a_consistent_detection_elsewhere():
    bt = BallTracker(jump_frames=3)
    for i in range(10):
        bt.update(i * DT, [(ball_at(640, 140), 0.6)])  # ball at the rim
    far = ball_at(640, 700)                              # picked up under the basket, far below
    assert not bt.update(10 * DT, [(far, 0.6)]).visible
    assert not bt.update(11 * DT, [(far, 0.6)]).visible
    st = bt.update(12 * DT, [(far, 0.6)])
    assert st.visible and st.box.cy == 700 and st.jumped
    # A one-off false positive doesn't move it.
    st = bt.update(13 * DT, [(ball_at(100, 100), 0.9), (ball_at(642, 700), 0.5)])
    assert st.visible and abs(st.measured.cy - 700) < 1
