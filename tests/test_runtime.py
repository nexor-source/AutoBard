import numpy as np
import pytest

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


@pytest.mark.parametrize("limit,click_count,remaining,reason", [
    (8.0, 6, 1, "timeout"),
    (12.0, 7, 0, "all_notes_processed"),
])
def test_slow_performance_runs_past_eight_seconds_when_allowed(
    monkeypatch, tmp_path, limit, click_count, remaining, reason,
) -> None:
    """Exercise the session loop with a known trajectory, without any OS input."""
    import json
    from types import SimpleNamespace
    import autobard.runtime as runtime
    from autobard.config import load_config
    from autobard.models import CaptureFrame, PointerMeasurement, Rect

    cfg = load_config(tmp_path / "absent.json")
    cfg["session"].update(max_duration_s=limit, initial_frame_spacing_ms=0)
    cfg["debug"].update(enabled=True, output_dir=str(tmp_path / "debug"))
    image = np.full((124, 574, 3), 100, dtype=np.uint8)

    class Source:
        timestamp = 1000.0

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self):
            self.timestamp += 1 / 70
            rendered = image.copy()
            x = min(573, int(20 + 60 * (self.timestamp - 1000)))
            rendered[:, x] = (40, 215, 250)
            return CaptureFrame(rendered, self.timestamp)

    source = Source()
    monkeypatch.setattr(runtime, "create_capture", lambda *args: source)
    monkeypatch.setattr(runtime.time, "perf_counter", lambda: source.timestamp)

    class Notes:
        def __init__(self, *args):
            pass

        def detect(self, *args):
            centers = [15, 139, 209, 280, 351, 422, 493, 563]
            return SimpleNamespace(notes=[Note(i, x - 7, x + 7, x, 1.0)
                                          for i, x in enumerate(centers)],
                                   mask=np.zeros((17, 574), dtype=np.uint8))

    class Pointer:
        def __init__(self, *args):
            pass

        def detect(self, *args, **kwargs):
            return PointerMeasurement(20 + 60 * (source.timestamp - 1000), 1.0, 3.0)

    class Action:
        clicks = []

        def hit_note(self, note, timestamp):
            self.clicks.append(note.index)

    monkeypatch.setattr(runtime, "NoteDetector", Notes)
    monkeypatch.setattr(runtime, "PointerDetector", Pointer)
    action = Action()
    result = runtime.AutoBardSession(cfg, Rect(0, 0, 574, 124), action).run()
    assert result.hit_count == click_count
    assert len(action.clicks) == click_count
    summary_path = next((tmp_path / "debug").glob("*/session_result.json"))
    summary = json.loads(summary_path.read_text())
    assert summary["pending_count"] == remaining
    assert summary["end_reason"] == reason
    metadata = json.loads((summary_path.parent / "session_meta.json").read_text())
    assert metadata["config"]["session"]["max_duration_s"] == limit
    assert list(summary_path.parent.glob("event_*_raw.png"))
