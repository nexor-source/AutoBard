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
