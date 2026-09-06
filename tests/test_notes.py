import cv2
import numpy as np
import pytest

from autobard.vision.notes import NoteDetector, _attach_nearby_support


CONFIG = {
    "pixel_quantile": 0.73,
    "column_coverage": 0.18,
    "min_width_ratio": 0.01,
    "max_width_ratio": 0.15,
    "merge_gap_ratio": 0.004,
    "min_confidence": 0.15,
    "min_vertical_coverage": 0.45,
}


def synthetic_bar(brightness: float = 1.0, gamma: float = 1.0) -> np.ndarray:
    image = np.full((32, 520, 3), (18, 18, 22), dtype=np.uint8)
    for center in [70, 180, 305, 440]:
        cv2.rectangle(image, (center - 14, 8), (center + 14, 24), (110, 185, 220), -1)
        cv2.rectangle(image, (center - 5, 6), (center + 5, 26), (25, 185, 245), -1)
    adjusted = np.clip(image.astype(np.float32) * brightness / 255.0, 0, 1) ** gamma
    return np.clip(adjusted * 255.0, 0, 255).astype(np.uint8)


@pytest.mark.parametrize("brightness,gamma", [(0.65, 1.0), (1.0, 1.0), (1.2, 0.85)])
def test_note_detector_survives_brightness_changes(brightness: float, gamma: float) -> None:
    result = NoteDetector(CONFIG).detect(synthetic_bar(brightness, gamma))
    assert len(result.notes) == 4
    targets = [note.target for note in result.notes]
    for actual, expected in zip(targets, [70, 180, 305, 440], strict=True):
        assert abs(actual - expected) < 8


def test_note_detector_rejects_dim_background_texture() -> None:
    image = np.full((32, 520, 3), (3, 5, 8), dtype=np.uint8)
    for center in [70, 180, 305, 440]:
        cv2.rectangle(image, (center - 8, 8), (center + 8, 24), (12, 20, 28), -1)

    result = NoteDetector(CONFIG).detect(image)

    assert result.notes == []


def test_note_detector_ignores_warm_horizontal_rails() -> None:
    image = synthetic_bar()
    cv2.rectangle(image, (95, 14), (150, 19), (80, 155, 215), -1)
    cv2.rectangle(image, (205, 15), (270, 20), (80, 155, 215), -1)

    result = NoteDetector(CONFIG).detect(image)

    assert len(result.notes) == 4


def test_note_detector_expands_dim_shoulders_and_uses_geometric_center() -> None:
    image = np.full((32, 220, 3), (18, 18, 22), dtype=np.uint8)
    cv2.rectangle(image, (80, 9), (119, 23), (75, 120, 175), -1)
    cv2.rectangle(image, (91, 6), (112, 26), (25, 185, 245), -1)

    result = NoteDetector({
        **CONFIG,
        "edge_vertical_coverage": 0.30,
        "min_brightness_p90": 0,
        "max_width_ratio": 0.30,
    }).detect(image)

    assert len(result.notes) == 1
    note = result.notes[0]
    assert note.left < 91
    assert note.right > 113
    assert abs(note.target - (note.left + note.right - 1) / 2.0) < 0.01


def test_fragmented_dim_shoulders_attach_within_a_strict_budget() -> None:
    attached = _attach_nearby_support(
        [(250, 287), (393, 417), (94, 145)],
        [
            (236, 238),
            (244, 247),
            (250, 287),
            (379, 390),
            (393, 416),
            (419, 429),
            (68, 92),
            (94, 145),
        ],
        max_gap=7,
        max_extension=14,
    )

    assert attached == [(94, 145), (236, 287), (379, 429)]
