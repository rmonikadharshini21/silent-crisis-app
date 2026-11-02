"""Simulated pose data only. This shows the rules work as written, not real accuracy."""
from detection.rules import FallDetector, Sample

FPS = 15


def run(segments, length=0.25):
    """Each segment is (seconds, start_cy, end_cy, start_angle, end_angle)."""
    detector = FallDetector()
    t = 0.0
    results = []
    for seconds, cy0, cy1, a0, a1 in segments:
        frames = int(seconds * FPS)
        for i in range(frames):
            p = (i + 1) / frames
            sample = Sample(t, cy0 + (cy1 - cy0) * p, a0 + (a1 - a0) * p, length)
            score = detector.update(sample, t)
            if score is not None:
                results.append(score)
            t += 1 / FPS
    return results


def test_fast_fall_then_still_is_detected():
    assert run([(2, 0.4, 0.4, 5, 5), (0.5, 0.4, 0.8, 5, 85), (4, 0.8, 0.8, 85, 85)])


def test_slow_lie_down_is_ignored():
    assert not run([(2, 0.4, 0.4, 5, 5), (5, 0.4, 0.8, 5, 85), (4, 0.8, 0.8, 85, 85)])


def test_quick_sit_stays_upright_and_is_ignored():
    assert not run([(2, 0.4, 0.4, 5, 5), (0.7, 0.4, 0.62, 5, 12), (6, 0.62, 0.62, 12, 12)])


def test_quick_bend_and_return_is_ignored():
    assert not run([(2, 0.4, 0.4, 5, 5), (0.6, 0.4, 0.6, 5, 70), (0.8, 0.6, 0.4, 70, 5), (5, 0.4, 0.4, 5, 5)])


def test_fall_then_getting_up_is_ignored():
    assert not run([(2, 0.4, 0.4, 5, 5), (0.5, 0.4, 0.8, 5, 85), (0.8, 0.8, 0.8, 85, 85), (1, 0.8, 0.4, 85, 5), (4, 0.4, 0.4, 5, 5)])


def test_falling_and_moving_is_not_confirmed_while_moving():
    detector = FallDetector()
    t = 0.0
    results = []
    for i in range(30):
        results.append(detector.update(Sample(t, 0.4, 5, 0.25), t))
        t += 1 / FPS
    for i in range(8):
        results.append(detector.update(Sample(t, 0.4 + 0.05 * i, 5 + 10 * i, 0.25), t))
        t += 1 / FPS
    for i in range(60):
        cy = 0.75 + (0.1 if i % 2 else 0)
        results.append(detector.update(Sample(t, cy, 85, 0.25), t))
        t += 1 / FPS
    assert not [r for r in results if r is not None]


def test_drop_out_of_frame_is_detected():
    detector = FallDetector()
    t = 0.0
    for _ in range(30):
        assert detector.update(Sample(t, 0.5, 5, 0.25), t) is None
        t += 1 / FPS
    for i in range(5):
        assert detector.update(Sample(t, 0.5 + 0.03 * i, 20, 0.25), t) is None
        t += 1 / FPS
    score = None
    for _ in range(60):
        score = score or detector.update(None, t)
        t += 1 / FPS
    assert score == 0.65


def test_no_person_never_triggers():
    detector = FallDetector()
    assert all(detector.update(None, i / FPS) is None for i in range(100))
