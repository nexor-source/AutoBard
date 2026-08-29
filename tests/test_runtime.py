import numpy as np

from autobard.runtime import _capture_has_signal


def test_capture_signal_rejects_black_frame() -> None:
    assert not _capture_has_signal(np.zeros((120, 581, 3), dtype=np.uint8))


def test_capture_signal_accepts_dark_scene_with_visible_rhythm_bar() -> None:
    image = np.full((120, 581, 3), 4, dtype=np.uint8)
    image[50:70, 20:560] = 180

    assert _capture_has_signal(image)
