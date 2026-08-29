from autobard.models import PointerMeasurement
from autobard.tracking import PointerTracker


CONFIG = {
    "history_size": 18,
    "min_fit_samples": 4,
    "min_speed_px_s": 20.0,
    "max_speed_px_s": 3000.0,
    "backward_tolerance_ratio": 0.025,
    "max_prediction_error_ratio": 0.05,
    "speed_hold_ms": 1200,
}


def measurement(x: float) -> PointerMeasurement:
    return PointerMeasurement(x, 1.0, 3.0)


def test_reanchor_preserves_motion_prediction_across_pointer_reset() -> None:
    tracker = PointerTracker(CONFIG, 500)
    for index in range(4):
        timestamp = index * 0.02
        assert tracker.update(timestamp, measurement(100.0 + 200.0 * timestamp))
    assert tracker.speed is not None
    assert abs(tracker.speed - 200.0) < 1.0

    tracker.reanchor_after_hit(0.06, 112.0)
    # Static note-center detections must not reset the projected trajectory.
    assert tracker.update(0.08, measurement(112.0))
    assert tracker.update(0.10, measurement(112.0))
    assert tracker.update(0.12, measurement(112.0))

    assert tracker.speed is not None
    assert abs(tracker.speed - 200.0) < 1.0
    assert abs(tracker.predict(0.14) - 128.0) < 1.0


def test_reanchor_keeps_one_speed_for_the_whole_session() -> None:
    tracker = PointerTracker(CONFIG, 500)
    for index in range(4):
        timestamp = index * 0.02
        assert tracker.update(timestamp, measurement(50.0 + 180.0 * timestamp))

    tracker.reanchor_after_hit(0.06, 100.0)
    for index in range(1, 4):
        timestamp = 0.06 + index * 0.02
        assert tracker.update(timestamp, measurement(100.0 + 270.0 * (timestamp - 0.06)))

    assert tracker.speed is not None
    assert abs(tracker.speed - 180.0) < 1.0


def test_note_center_jitter_cannot_replace_reliable_segment_speed() -> None:
    tracker = PointerTracker(CONFIG, 500)
    for index in range(4):
        timestamp = index * 0.02
        assert tracker.update(timestamp, measurement(80.0 + 220.0 * timestamp))

    tracker.reanchor_after_hit(0.06, 100.0)
    for index, x in enumerate([101.0, 102.0, 103.0], start=1):
        assert tracker.update(0.06 + index * 0.02, measurement(x))

    assert tracker.speed is not None
    assert abs(tracker.speed - 220.0) < 1.0
    assert tracker.predict(0.20) > 128.0


def test_post_hit_false_slow_fit_cannot_take_over() -> None:
    tracker = PointerTracker(CONFIG, 500)
    for index in range(4):
        timestamp = index * 0.02
        assert tracker.update(timestamp, measurement(60.0 + 230.0 * timestamp))

    tracker.reanchor_after_hit(0.06, 100.0)
    for index in range(1, 4):
        timestamp = 0.06 + index * 0.02
        assert tracker.update(timestamp, measurement(100.0 + 150.0 * (timestamp - 0.06)))

    assert tracker.speed is not None
    assert abs(tracker.speed - 230.0) < 1.0


def test_locked_trajectory_ignores_an_upcoming_note_measurement_jump() -> None:
    tracker = PointerTracker(CONFIG, 500)
    for index in range(4):
        timestamp = index * 0.02
        assert tracker.update(timestamp, measurement(100.0 + 200.0 * timestamp))

    tracker.reanchor_after_hit(0.10, 150.0)
    assert tracker.update(0.20, measurement(185.0))

    # The raw detector jumped 15 px ahead of the constant-speed trajectory.
    assert tracker.last_x == 185.0
    assert abs((tracker.predict(0.20) or 0.0) - 170.0) < 1.0




def test_reset_allows_a_different_speed_in_the_next_session() -> None:
    tracker = PointerTracker(CONFIG, 500)
    for index in range(4):
        timestamp = index * 0.02
        assert tracker.update(timestamp, measurement(50.0 + 180.0 * timestamp))
    tracker.reanchor_after_hit(0.06, 100.0)
    assert abs((tracker.speed or 0.0) - 180.0) < 1.0

    tracker.reset()
    for index in range(4):
        timestamp = index * 0.02
        assert tracker.update(timestamp, measurement(50.0 + 270.0 * timestamp))

    assert tracker.speed is not None
    assert abs(tracker.speed - 270.0) < 1.0
