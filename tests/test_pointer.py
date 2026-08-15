import cv2
import numpy as np

from autobard.vision.pointer import PointerDetector


CONFIG = {
    "analysis_y": [0.05, 0.95],
    "excluded_y": [],
    "motion_weight": 0.58,
    "edge_weight": 0.30,
    "color_weight": 0.12,
    "prediction_weight": 0.45,
    "prediction_sigma_ratio": 0.035,
    "prediction_search_ratio": 0.06,
    "min_confidence": 0.12,
    "max_width_ratio": 0.05,
}


def frame(pointer_x: int) -> np.ndarray:
    image = np.full((90, 420, 3), (20, 20, 20), dtype=np.uint8)
    for x in [80, 170, 290, 360]:
        cv2.rectangle(image, (x - 10, 40), (x + 10, 58), (90, 160, 210), -1)
    cv2.line(image, (pointer_x, 10), (pointer_x, 80), (40, 215, 250), 3)
    return image


def test_pointer_detector_tracks_moving_line() -> None:
    detector = PointerDetector(CONFIG)
    first = detector.detect(frame(110), predicted_x=110)
    assert first is not None
    second = detector.detect(frame(120), predicted_x=120)
    assert second is not None
    assert abs(second.x - 120) < 7


def test_pointer_detector_does_not_return_to_a_static_note_behind_prediction() -> None:
    detector = PointerDetector(CONFIG)
    detector.detect(frame(170), predicted_x=170)

    measurement = detector.detect(frame(250), predicted_x=250)

    assert measurement is not None
    assert abs(measurement.x - 250) < 7


def test_pointer_detector_ignores_a_changed_capture_border_during_bootstrap() -> None:
    detector = PointerDetector({**CONFIG, "bootstrap_border_ratio": 0.03})
    first = frame(110)
    assert detector.detect(first) is None

    second = frame(120)
    cv2.rectangle(second, (0, 0), (5, second.shape[0] - 1), (255, 255, 255), -1)
    measurement = detector.detect(second)

    assert measurement is not None
    assert abs(measurement.x - 120) < 7


def test_bootstrap_window_rejects_distant_animated_scenery() -> None:
    detector = PointerDetector({
        **CONFIG,
        "bootstrap_border_ratio": 0.03,
        "bootstrap_search_ratio": 0.10,
    })
    first = frame(110)
    cv2.rectangle(first, (345, 5), (370, 84), (20, 40, 80), -1)
    assert detector.detect(first) is None

    second = frame(120)
    cv2.rectangle(second, (345, 5), (370, 84), (240, 250, 255), -1)
    measurement = detector.detect(second, bootstrap_x=100)

    assert measurement is not None
    assert abs(measurement.x - 120) < 7
