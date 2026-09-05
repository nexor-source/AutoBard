import numpy as np

from autobard.models import Note
from autobard.runtime import (
    _capture_has_signal,
    _pointer_bootstrap_search_bounds,
    _remaining_pointer_start_delay_s,
)


def test_capture_signal_rejects_black_frame() -> None:
    assert not _capture_has_signal(np.zeros((120, 581, 3), dtype=np.uint8))


def test_capture_signal_accepts_dark_scene_with_visible_rhythm_bar() -> None:
    image = np.full((120, 581, 3), 4, dtype=np.uint8)
    image[50:70, 20:560] = 180

    assert _capture_has_signal(image)


def test_pointer_start_delay_counts_initial_note_processing_time() -> None:
    remaining = _remaining_pointer_start_delay_s(
        session_started_at=10.0,
        delay_ms=500,
        now=10.12,
    )

    assert abs(remaining - 0.38) < 1e-9


def test_pointer_start_delay_never_waits_past_configured_deadline() -> None:
    assert _remaining_pointer_start_delay_s(10.0, 500, 10.8) == 0.0
    assert _remaining_pointer_start_delay_s(10.0, 0, 10.0) == 0.0


def test_pointer_bootstrap_search_expands_from_second_to_last_note() -> None:
    notes = [
        Note(0, 100.0, 150.0, 125.0, 1.0),
        Note(1, 250.0, 300.0, 275.0, 1.0),
        Note(2, 500.0, 550.0, 525.0, 1.0),
    ]

    initial = _pointer_bootstrap_search_bounds(notes, 581, 0.0, 150)
    halfway = _pointer_bootstrap_search_bounds(notes, 581, 0.075, 150)
    expanded = _pointer_bootstrap_search_bounds(notes, 581, 0.150, 150)

    assert initial[0] < notes[0].left
    assert initial[1] > notes[1].right
    assert initial[1] < halfway[1] < expanded[1]
    assert expanded[1] > notes[-1].right
